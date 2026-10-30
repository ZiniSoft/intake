"""The day across projects, read-only (FR-PLAN-33): one block per software project with its plan as it stands,
the people with work, the people still free, and the work waiting to be placed. Nothing here opens or edits a plan;
the CTO reads this, then opens the project that needs a hand."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.db import get_session
from app.models import (
    ExternalLink,
    IntakeItem,
    IntakeWorkLog,
    IssueVerification,
    PlanningAssignment,
    PlanningCandidate,
    PlanningRun,
    PlanningWarning,
    Project,
    User,
    UserPlanningProjectOrder,
    WorkforceMember,
    WorkforceProjectMembership,
)
from app.modules.planning.cto import cto_member_ids
from app.modules.planning.overview import LOCAL_TZ, _hours_on
from app.modules.planning.service import MUTABLE_RUN_STATES, _canonical_hash, planning_service

WAITING = ("PENDING_TRIAGE", "READY")


class ProjectOrderError(ValueError):
    pass


def _project_order(session, user_id: str | None, visible_project_ids: list[str]) -> dict[str, object]:
    if not user_id:
        return {"mode": "PRIORITY", "project_ids": []}
    preference = session.get(UserPlanningProjectOrder, user_id)
    if preference is None:
        return {"mode": "PRIORITY", "project_ids": []}
    visible = set(visible_project_ids)
    ordered = [str(project_id) for project_id in (preference.project_ids or []) if str(project_id) in visible]
    return {"mode": preference.sort_mode, "project_ids": ordered}


def save_project_order(user_id: str, allowed_project_ids: frozenset[str] | None, mode: str, project_ids: list[str]) -> dict[str, object]:
    """Persist only projects the caller can currently see; new projects can be appended by the UI later."""
    with get_session() as session:
        query = select(Project.id).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE")
        if allowed_project_ids is not None:
            query = query.where(Project.id.in_(sorted(allowed_project_ids)))
        visible = {str(project_id) for project_id in session.scalars(query).all()}
        normalized = [str(project_id) for project_id in project_ids]
        if len(normalized) != len(set(normalized)):
            raise ProjectOrderError("PROJECT_ORDER_DUPLICATE")
        if any(project_id not in visible for project_id in normalized):
            raise ProjectOrderError("PROJECT_ORDER_PROJECT_NOT_VISIBLE")
        if mode == "PRIORITY":
            normalized = []
        preference = session.get(UserPlanningProjectOrder, user_id)
        if preference is None:
            preference = UserPlanningProjectOrder(user_id=user_id, sort_mode=mode, project_ids=normalized)
            session.add(preference)
        else:
            preference.sort_mode = mode
            preference.project_ids = normalized
            preference.updated_at = datetime.now(timezone.utc)
        session.commit()
        return {"mode": preference.sort_mode, "project_ids": list(preference.project_ids or [])}


def _off_plan_work(session, project: Project, plan_date: date) -> list[dict[str, object]]:
    """Actual work logged without an assignment on that day. It is history, never a retroactive plan."""
    end = datetime.combine(plan_date + timedelta(days=1), time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    lookback = end - timedelta(days=31)
    rows = session.execute(
        select(IntakeWorkLog, IntakeItem, User)
        .join(IntakeItem, IntakeItem.id == IntakeWorkLog.intake_id)
        .outerjoin(User, User.id == IntakeWorkLog.actor_id)
        .where(IntakeWorkLog.project_id == project.id, IntakeWorkLog.created_at >= lookback, IntakeWorkLog.created_at < end)
        .order_by(IntakeWorkLog.created_at.desc())
    ).all()
    result: list[dict[str, object]] = []
    seen: set[str] = set()
    for log, item, actor in rows:
        details = log.details or {}
        created_at = log.created_at if log.created_at.tzinfo is not None else log.created_at.replace(tzinfo=timezone.utc)
        try:
            worked_on = date.fromisoformat(str(details.get("worked_on"))) if details.get("worked_on") else created_at.astimezone(LOCAL_TZ).date()
        except ValueError:
            worked_on = created_at.astimezone(LOCAL_TZ).date()
        if worked_on != plan_date or str(item.id) in seen:
            continue
        seen.add(str(item.id))
        link = session.scalar(select(ExternalLink).where(
            ExternalLink.intake_id == item.id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")),
        ).order_by(ExternalLink.created_at.desc()))
        if link is None:
            continue
        planned = session.scalar(select(PlanningAssignment.id).join(
            PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id,
        ).where(
            PlanningRun.plan_date == plan_date, PlanningRun.status != "SUPERSEDED",
            PlanningAssignment.project_id == project.id,
            PlanningAssignment.gitlab_issue_external_id == link.external_id,
        ))
        if planned is not None:
            continue
        accepted = session.scalar(select(IssueVerification).where(
            IssueVerification.project_id == project.id,
            IssueVerification.issue_external_id == link.external_id,
            IssueVerification.decision == "ACCEPTED",
        ).order_by(IssueVerification.decided_at.desc()))
        actual_minutes = details.get("actual_minutes")
        minutes = actual_minutes if isinstance(actual_minutes, int) and not isinstance(actual_minutes, bool) else None
        result.append({
            "id": str(log.id), "intake_id": str(item.id), "intake_public_id": item.public_id,
            "title": item.normalized_title or log.summary, "issue": link.external_id, "issue_url": link.url,
            "executor": log.agent_name or (actor.display_name if actor else None) or "Không rõ",
            "review_decision": log.review_decision, "worked_on": worked_on,
            "actual_minutes": minutes, "deployed": details.get("deployed") if isinstance(details.get("deployed"), bool) else None,
            "accepted_at": accepted.decided_at if accepted is not None else None,
        })
    return result


def _run_of(session, project: Project, plan_date: date) -> PlanningRun | None:
    return session.scalar(select(PlanningRun).where(
        PlanningRun.plan_date == plan_date, PlanningRun.scope_hash == _canonical_hash([str(project.id)]), PlanningRun.status != "SUPERSEDED",
    ).order_by(PlanningRun.revision.desc()))


def day_plans(plan_date: date, allowed_project_ids: frozenset[str] | None, user_id: str | None = None) -> dict[str, object]:
    with get_session() as session:
        query = select(Project).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE")
        if allowed_project_ids is not None:
            query = query.where(Project.id.in_(sorted(allowed_project_ids)))
        projects = session.scalars(query.order_by(Project.name)).all()
        cto_ids = cto_member_ids(session)
        blocks = []
        free_hours_total = 0.0
        waiting_total = 0
        off_plan_total = 0
        off_plan_minutes_total = 0
        for project in projects:
            owner = session.get(WorkforceMember, project.owner_member_id) if project.owner_member_id else None
            members = session.scalars(
                select(WorkforceMember).join(WorkforceProjectMembership, WorkforceProjectMembership.member_id == WorkforceMember.id)
                .where(WorkforceProjectMembership.project_id == project.id, WorkforceProjectMembership.active.is_(True), WorkforceMember.status == "ACTIVE")
                .order_by(WorkforceMember.display_name)
            ).all()
            run = _run_of(session, project, plan_date)
            assignments = session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id).order_by(PlanningAssignment.slot)).all() if run else []
            views = {row["id"]: row for row in planning_service._with_intakes(session, assignments)} if assignments else {}
            candidate_titles = {str(row.assignment_id): row.title for row in session.scalars(select(PlanningCandidate).where(
                PlanningCandidate.planning_run_id == run.id, PlanningCandidate.assignment_id.is_not(None),
            )).all()} if run else {}
            names = {str(m.id): m.display_name for m in members}
            for assignment in assignments:
                if str(assignment.member_id) not in names:
                    extra = session.get(WorkforceMember, assignment.member_id)
                    names[str(assignment.member_id)] = extra.display_name if extra else "Nhân sự"
            by_member: dict[str, list[dict[str, object]]] = {}
            for assignment in assignments:
                view = views[str(assignment.id)]
                by_member.setdefault(str(assignment.member_id), []).append({
                    "id": str(assignment.id), "slot": assignment.slot, "hours": float(assignment.planned_hours), "issue": assignment.gitlab_issue_external_id,
                    "title": view.get("title") or candidate_titles.get(str(assignment.id)) or assignment.source_reference,
                    "intake_id": view.get("intake_id"), "intake_public_id": view.get("intake_public_id"), "issue_url": view.get("issue_url"),
                    "priority": assignment.approved_priority or assignment.proposed_priority, "work_status": assignment.work_status or "PLANNED",
                    "accepted": assignment.approved_assignee_external_id is not None, "accepted_at": view.get("accepted_at"),
                })
            people = []
            free = []
            off = []
            for member in members:
                hours = _hours_on(session, member, plan_date)
                planned = sum(float(a.planned_hours) for a in assignments if str(a.member_id) == str(member.id))
                elsewhere = planning_service._hours_elsewhere_by_project(session, str(member.id), plan_date, [str(project.id)])
                taken = sum(float(row["hours"]) for row in elsewhere)
                if str(member.id) in by_member:
                    people.append({"member_id": str(member.id), "name": member.display_name, "hours": hours, "planned": planned, "elsewhere": elsewhere, "assignments": by_member[str(member.id)]})
                elif hours - taken > 0:
                    free.append({"member_id": str(member.id), "name": member.display_name, "hours": round(hours - taken, 2), "elsewhere": elsewhere})
                    free_hours_total += hours - taken
                elif hours > 0:
                    # Their whole day is in other projects' plans: not free, not off.
                    people.append({"member_id": str(member.id), "name": member.display_name, "hours": hours, "planned": 0.0, "elsewhere": elsewhere, "assignments": []})
                elif str(member.id) not in cto_ids:
                    # The CTO with no hours that day is not off duty; they are simply not planned here (FR-PLAN-37).
                    off.append(member.display_name)
            for member_id, items in by_member.items():
                if member_id not in {str(m.id) for m in members}:
                    people.append({"member_id": member_id, "name": names.get(member_id, "Nhân sự"), "hours": 0.0, "planned": sum(float(i["hours"]) for i in items), "elsewhere": [], "assignments": items})
            waiting = []
            warnings_total = unseen = 0
            if run:
                rows = session.scalars(select(PlanningCandidate).where(PlanningCandidate.planning_run_id == run.id, PlanningCandidate.status.in_(WAITING)).order_by(PlanningCandidate.created_at)).all()
                for candidate in planning_service._with_candidate_links(session, rows):
                    waiting.append({
                        "id": candidate["id"], "title": candidate["title"], "summary": candidate["summary"], "source_type": candidate["source_type"],
                        "issue": candidate["gitlab_issue_external_id"], "issue_url": candidate["issue_url"],
                        "intake_id": candidate["intake_id"], "intake_public_id": candidate["intake_public_id"],
                        "priority": candidate["proposed_priority"], "member_name": names.get(str(candidate["member_id"])) if candidate["member_id"] else None,
                        "origin_at": candidate.get("origin_at"),
                    })
                rows = session.scalars(select(PlanningWarning).where(PlanningWarning.planning_run_id == run.id)).all()
                warnings_total = len(rows)
                unseen = sum(1 for row in rows if row.acknowledged_at is None)
            waiting_total += len(waiting)
            off_plan = _off_plan_work(session, project, plan_date)
            off_plan_total += len(off_plan)
            off_plan_minutes_total += sum(int(row["actual_minutes"] or 0) for row in off_plan)
            blocks.append({
                "id": str(project.id), "code": project.code, "name": project.name, "owner_name": owner.display_name if owner else None,
                "run": {
                    "id": str(run.id), "status": run.status, "version": run.version, "revision": run.revision, "open": run.status in MUTABLE_RUN_STATES,
                    "assigned_hours": round(sum(float(a.planned_hours) for a in assignments), 2), "assignments": len(assignments),
                    "warnings": warnings_total, "unseen_warnings": unseen,
                } if run else None,
                "people": people, "free": free, "off": off, "waiting": waiting, "off_plan": off_plan,
            })
        return {
            "plan_date": plan_date, "projects": blocks,
            "project_order": _project_order(session, user_id, [str(project.id) for project in projects]),
            "totals": {
                "projects": len(blocks), "unclosed": sum(1 for b in blocks if b["run"] is None or b["run"]["open"]),
                "free_hours": round(free_hours_total, 2), "free_people": sum(len(b["free"]) for b in blocks), "waiting": waiting_total,
                "off_plan": off_plan_total, "off_plan_actual_minutes": off_plan_minutes_total,
            },
        }
