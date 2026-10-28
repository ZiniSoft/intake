"""One row per person for a day: hours planned across every project's plan against the hours they have (FR-PLAN-28).

The project boards show a project at a time; a person who works in two projects can be over hours without either
board noticing. The CTO sees everyone; a Project Owner sees the people on their teams, with the names and hours of
the other projects those people are in (the work itself stays with that project).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db import get_session
from app.models import PlanningAssignment, PlanningRun, Project, WorkforceMember
from app.modules.planning.cto import cto_member_ids
from app.modules.planning.overview import _hours_on

TOLERANCE = 0.01


def people_day(plan_date: date, allowed_project_ids: frozenset[str] | None = None) -> dict[str, object]:
    from app.modules.planning.scope import team_member_ids

    team = team_member_ids(allowed_project_ids) if allowed_project_ids is not None else None
    with get_session() as session:
        members = [
            member for member in session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE").order_by(WorkforceMember.display_name)).all()
            if team is None or str(member.id) in team
        ]
        cto_ids = cto_member_ids(session)
        assignments = session.execute(
            select(PlanningAssignment.member_id, PlanningAssignment.project_id, PlanningAssignment.planned_hours, PlanningRun.status)
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(PlanningRun.plan_date == plan_date, PlanningRun.status != "SUPERSEDED")
        ).all()
        project_names = {str(row.id): row.name for row in session.scalars(select(Project)).all()}
        by_member: dict[str, dict[str, dict[str, object]]] = {}
        for member_id, project_id, planned_hours, run_status in assignments:
            slot = by_member.setdefault(str(member_id), {}).setdefault(str(project_id), {"hours": 0.0, "run_status": run_status})
            slot["hours"] = float(slot["hours"]) + float(planned_hours or 0)
        people = []
        for member in members:
            available = _hours_on(session, member, plan_date)
            projects = [
                {"id": project_id, "name": project_names.get(project_id, project_id), "hours": round(float(slot["hours"]), 2), "run_status": slot["run_status"]}
                for project_id, slot in sorted(by_member.get(str(member.id), {}).items(), key=lambda pair: project_names.get(pair[0], pair[0]).casefold())
            ]
            planned = round(sum(float(row["hours"]) for row in projects), 2)
            if available <= 0 and not projects and str(member.id) in cto_ids:
                continue  # the CTO is not off duty on a day they took no work (FR-PLAN-37)
            if available <= 0:
                state = "OFF" if not projects else "OVER"
            elif planned > available + TOLERANCE:
                state = "OVER"
            elif planned < available - TOLERANCE:
                state = "FREE"
            else:
                state = "OK"
            people.append({
                "member_id": str(member.id), "display_name": member.display_name,
                "available_hours": round(available, 2), "planned_hours": planned, "free_hours": round(max(available - planned, 0.0), 2),
                "state": state, "projects": projects,
            })
        order = {"OVER": 0, "FREE": 1, "OK": 2, "OFF": 3}
        people.sort(key=lambda row: (order[str(row["state"])], str(row["display_name"]).casefold()))
        return {
            "plan_date": plan_date, "people": people,
            "over": sum(1 for row in people if row["state"] == "OVER"), "free": sum(1 for row in people if row["state"] == "FREE"),
        }
