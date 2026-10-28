"""What a Project Owner may touch in Daily Planning and Daily Reports (ADR-0026).

An owner works with the teams of their own projects and with plans whose whole scope is their projects.
"""
from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from app.db import get_session
from app.models import EmailMessage, IntakeItem, PlanningRun, Project, WorkforceProjectMembership


def team_member_ids(project_ids: Iterable[str]) -> set[str]:
    """Everyone on the team of at least one of the projects, the owner included."""
    wanted = [str(project_id) for project_id in project_ids]
    if not wanted:
        return set()
    with get_session() as session:
        members = {str(member_id) for member_id in session.scalars(select(WorkforceProjectMembership.member_id).where(
            WorkforceProjectMembership.project_id.in_(wanted), WorkforceProjectMembership.active.is_(True),
        ))}
        members.update(str(owner) for owner in session.scalars(
            select(Project.owner_member_id).where(Project.id.in_(wanted), Project.owner_member_id.is_not(None))
        ))
        return members


def project_ids(references: Iterable[str]) -> list[str | None]:
    """Project ids for ids or codes; None for a reference that names no project."""
    wanted = [str(reference) for reference in references]
    with get_session() as session:
        known = {key: str(project.id) for project in session.scalars(select(Project)) for key in (str(project.id), project.code)}
    return [known.get(reference) for reference in wanted]


def run_projects(run_id: str) -> list[str] | None:
    with get_session() as session:
        run = session.get(PlanningRun, run_id)
        return None if run is None else [str(project_id) for project_id in run.project_scope]


def report_member(report_id: str) -> str | None:
    """The staff member a Daily Report came from; None when the report is unknown or its sender is not on the staff list."""
    with get_session() as session:
        report = session.get(EmailMessage, report_id)
        return str(report.member_id) if report is not None and report.member_id else None


def intake_awaits_approval(intake_id: str | None) -> bool:
    if not intake_id:
        return False
    with get_session() as session:
        item = session.get(IntakeItem, intake_id)
        return item is not None and item.status == "PENDING_APPROVAL"
