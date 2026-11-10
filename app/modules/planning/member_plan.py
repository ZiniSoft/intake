"""One person's plan over a stretch of days, read only (FR-PLAN-40, ADR-0081).

The project boards show a project at a time and the people board shows a day at a time; this puts one person's
days side by side, past ones included: the work placed for them in every project's plan, the internal work and
posts in their name, the hours they had and the days they were off.

Who sees whom:
- the CTO sees everyone, every piece of work;
- anyone else sees themselves, and the people who share a project with them: the projects a Project Owner holds and
  the projects the viewer is an active member of. In those projects they see the work; in the person's other
  projects only the project's name and hours (as ADR-0062 has it for the people board);
- a person's own tasks (FR-PER-01) stay theirs: anyone else sees only how many hours they took.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.db import get_session
from app.models import DailyCapacity, PersonalTask, PlanningAssignment, PlanningCandidate, PlanningRun, Project, WorkforceMember, WorkforceProjectMembership, WorkItem
from app.modules.planning.overview import LOCAL_TZ
from app.modules.planning.personal import member_for_user

MAX_DAYS = 62
WORK_STATUSES = ("PLANNED", "IN_PROGRESS", "DONE", "BLOCKED")
CLOSED_WORK = ("DONE", "CANCELLED")


class MemberPlanError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Viewer:
    """What a login may see of other people's plans."""

    def __init__(self, member_id: str | None, projects: frozenset[str] | None) -> None:
        self.member_id = member_id
        # None means every project (the CTO).
        self.projects = projects

    def sees_project(self, project_id: object, member_id: str) -> bool:
        return self.projects is None or member_id == self.member_id or str(project_id) in self.projects


def viewer_for(session, user_id: str, role: str, granted: frozenset[str] | None) -> Viewer:
    member = member_for_user(session, user_id)
    member_id = str(member.id) if member is not None else None
    if role == "CTO":
        return Viewer(member_id, None)
    projects = {str(project_id) for project_id in granted or ()}
    if member_id:
        projects.update(str(project_id) for project_id in session.scalars(select(WorkforceProjectMembership.project_id).where(
            WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.active.is_(True),
        )))
    return Viewer(member_id, frozenset(projects))


def _visible_ids(session, viewer: Viewer) -> set[str] | None:
    """The people a viewer may look at; None means everyone."""
    if viewer.projects is None:
        return None
    from app.modules.planning.scope import team_member_ids

    seen = team_member_ids(viewer.projects) if viewer.projects else set()
    if viewer.member_id:
        seen.add(viewer.member_id)
    return seen


def visible_members(user_id: str, role: str, granted: frozenset[str] | None) -> dict[str, object]:
    """The people a viewer may pick, active staff only, the viewer first."""
    with get_session() as session:
        viewer = viewer_for(session, user_id, role, granted)
        allowed = _visible_ids(session, viewer)
        members = session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE").order_by(WorkforceMember.display_name)).all()
        rows = [
            {"member_id": str(member.id), "display_name": member.display_name, "is_me": str(member.id) == viewer.member_id}
            for member in members if allowed is None or str(member.id) in allowed
        ]
        rows.sort(key=lambda row: (not row["is_me"], str(row["display_name"]).casefold()))
        return {"me": viewer.member_id, "members": rows}


def _local_day(stamp: datetime | None) -> date | None:
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(LOCAL_TZ).date()


def member_plan(member_id: str, start: date, end: date, *, user_id: str, role: str, granted: frozenset[str] | None) -> dict[str, object]:
    if end < start:
        raise MemberPlanError("RANGE_INVALID", "'to' must not be before 'from'")
    if (end - start).days + 1 > MAX_DAYS:
        raise MemberPlanError("RANGE_TOO_LONG", f"At most {MAX_DAYS} days at a time")
    from app.modules.planning.service import planning_service

    with get_session() as session:
        viewer = viewer_for(session, user_id, role, granted)
        allowed = _visible_ids(session, viewer)
        member = session.get(WorkforceMember, member_id)
        if member is None or (allowed is not None and str(member.id) not in allowed):
            raise MemberPlanError("MEMBER_NOT_FOUND", "Member was not found")
        member_id = str(member.id)
        is_self = member_id == viewer.member_id
        projects = {str(row.id): row for row in session.scalars(select(Project)).all()}
        days = [start + timedelta(days=offset) for offset in range((end - start).days + 1)]

        capacity = {
            row.work_date: float(row.available_hours)
            for row in session.scalars(select(DailyCapacity).where(
                DailyCapacity.member_id == member_id, DailyCapacity.work_date >= start, DailyCapacity.work_date <= end,
            ))
        }
        personal_rows = session.scalars(select(PersonalTask).where(
            PersonalTask.member_id == member_id, PersonalTask.task_date >= start, PersonalTask.task_date <= end,
            PersonalTask.archived_at.is_(None), PersonalTask.status != "DELEGATED",
        ).order_by(PersonalTask.task_date, PersonalTask.start_time, PersonalTask.title)).all()
        personal_hours: dict[date, float] = defaultdict(float)
        personal_items: dict[date, list[dict[str, object]]] = defaultdict(list)
        for task in personal_rows:
            if task.status in ("PLANNED", "DONE"):
                personal_hours[task.task_date] += float(task.hours or 0)
            if is_self:
                personal_items[task.task_date].append({
                    "kind": "PERSONAL", "id": str(task.id), "title": task.title, "hours": float(task.hours or 0),
                    "status": task.status, "start_time": task.start_time,
                })

        placed = session.execute(
            select(PlanningAssignment, PlanningRun)
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(PlanningAssignment.member_id == member_id, PlanningRun.plan_date >= start, PlanningRun.plan_date <= end, PlanningRun.status != "SUPERSEDED")
        ).all()
        shown = [assignment for assignment, _ in placed if viewer.sees_project(assignment.project_id, member_id)]
        views = {row["id"]: row for row in planning_service._with_intakes(session, shown)} if shown else {}
        candidate_titles = {
            str(row.assignment_id): row.title for row in session.scalars(select(PlanningCandidate).where(
                PlanningCandidate.assignment_id.in_([assignment.id for assignment in shown]),
            ))
        } if shown else {}

        items: dict[date, list[dict[str, object]]] = defaultdict(list)
        hidden: dict[date, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        planned_hours: dict[date, float] = defaultdict(float)
        by_project: dict[str, float] = defaultdict(float)
        statuses = {key: 0 for key in WORK_STATUSES}
        accepted = 0
        for assignment, run in placed:
            day, hours, project_id = run.plan_date, float(assignment.planned_hours), str(assignment.project_id)
            planned_hours[day] += hours
            by_project[project_id] += hours
            if not viewer.sees_project(project_id, member_id):
                hidden[day][project_id] += hours
                continue
            view = views[str(assignment.id)]
            project = projects.get(project_id)
            status = assignment.work_status or "PLANNED"
            statuses[status] = statuses.get(status, 0) + 1
            if view.get("accepted_at"):
                accepted += 1
            items[day].append({
                "kind": "ASSIGNMENT", "id": str(assignment.id), "run_id": str(run.id), "run_status": run.status,
                "project_id": project_id, "project": project.code if project else None, "project_name": project.name if project else project_id,
                "title": view.get("title") or candidate_titles.get(str(assignment.id)) or assignment.source_reference,
                "issue": assignment.gitlab_issue_external_id, "issue_url": view.get("issue_url"), "intake": view.get("intake_public_id"),
                "priority": assignment.approved_priority or assignment.proposed_priority, "slot": assignment.slot, "hours": hours,
                "work_type": assignment.work_type, "status": status,
                "accepted_at": view["accepted_at"].isoformat() if view.get("accepted_at") else None,
            })

        work_counts: dict[str, int] = defaultdict(int)
        for work in session.scalars(select(WorkItem).where(WorkItem.member_id == member_id)).all():
            day = _local_day(work.closed_at) if work.status in CLOSED_WORK else work.due_date
            if day is None or day < start or day > end or not viewer.sees_project(work.project_id, member_id):
                continue
            project = projects.get(str(work.project_id))
            work_counts[work.status] += 1
            items[day].append({
                "kind": "WORK_ITEM", "id": str(work.id), "code": work.code, "title": work.title, "status": work.status,
                "priority": work.priority, "project_id": str(work.project_id), "project": project.code if project else None,
                "project_name": project.name if project else str(work.project_id), "channel": work.channel, "urgent": bool(work.urgent),
                "due_date": work.due_date.isoformat() if work.due_date else None, "closed": work.status in CLOSED_WORK,
            })

        slot_order = {"MORNING": 0, "AFTERNOON": 1}
        out_days = []
        for day in days:
            base = capacity.get(day, float(member.default_weekday_hours) if day.weekday() < 5 else 0.0)
            available = max(base - personal_hours.get(day, 0.0), 0.0)
            day_items = sorted(items.get(day, []), key=lambda row: (
                {"ASSIGNMENT": 0, "WORK_ITEM": 1}.get(str(row["kind"]), 2), str(row.get("project_name") or "").casefold(),
                slot_order.get(str(row.get("slot")), 2), str(row.get("priority") or "P9"), str(row["title"]).casefold(),
            )) + personal_items.get(day, [])
            out_days.append({
                "date": day.isoformat(), "capacity_hours": round(base, 2), "personal_hours": round(personal_hours.get(day, 0.0), 2),
                "available_hours": round(available, 2), "planned_hours": round(planned_hours.get(day, 0.0), 2), "off": base <= 0,
                "items": day_items,
                "hidden_projects": [
                    {"name": projects[project_id].name if project_id in projects else project_id, "hours": round(hours, 2)}
                    for project_id, hours in sorted(hidden.get(day, {}).items(), key=lambda pair: pair[0])
                ],
            })

        return {
            "member": {"member_id": member_id, "display_name": member.display_name, "is_me": is_self},
            "from": start.isoformat(), "to": end.isoformat(), "days": out_days,
            "totals": {
                "planned_hours": round(sum(planned_hours.values()), 2),
                "available_hours": round(sum(row["available_hours"] for row in out_days), 2),
                "personal_hours": round(sum(personal_hours.values()), 2),
                "off_days": sum(1 for row in out_days if row["off"] and day_is_workday(date.fromisoformat(str(row["date"])))),
                "by_project": [
                    {"name": projects[project_id].name if project_id in projects else project_id, "hours": round(hours, 2),
                     "visible": viewer.sees_project(project_id, member_id)}
                    for project_id, hours in sorted(by_project.items(), key=lambda pair: -pair[1])
                ],
                "work_status": statuses, "accepted": accepted, "work_items": dict(work_counts),
            },
        }


def day_is_workday(day: date) -> bool:
    return day.weekday() < 5
