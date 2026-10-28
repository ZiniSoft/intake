"""Who decides a request that waits for approval (FR-APR-14), and how long things may wait before they count as
overdue on the morning board (FR-PLAN-27).

A project with an active Project Owner decides its own requests. The CTO takes what the owner should not carry
alone: P0 and P1, requests of projects without an owner, and anything nobody decided within a day.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models import User, UserProjectAccess

ESCALATE_AFTER = timedelta(hours=24)
CTO_PRIORITIES = ("P0", "P1")
# How long each kind of waiting may last before the board marks it overdue (ADR-0052). All in one place on purpose.
OVERDUE = {
    "approvals": ESCALATE_AFTER,          # a request nobody decided
    "waiting": timedelta(days=2),         # a candidate nobody assigned
    "work_log": timedelta(days=1),        # a work log the CTO has not confirmed
    "p0_open": timedelta(days=1),         # a P0 Issue still open, counted from the first time the Issue list showed it
}


def projects_with_owner(session) -> set[str]:
    rows = session.execute(
        select(UserProjectAccess.project_id).join(User, User.id == UserProjectAccess.user_id)
        .where(User.role == "PROJECT_OWNER", User.is_active.is_(True))
    ).all()
    return {str(project_id) for (project_id,) in rows}


def approval_owner(*, project_has_owner: bool, priority: str | None, waiting_since: datetime, now: datetime | None = None) -> tuple[str, bool]:
    """("CTO" | "PO", overdue): who should decide, and whether the request has waited longer than a day."""
    current = now or datetime.now(timezone.utc)
    since = waiting_since if waiting_since.tzinfo else waiting_since.replace(tzinfo=timezone.utc)
    overdue = current - since > ESCALATE_AFTER
    if not project_has_owner or (priority or "") in CTO_PRIORITIES or overdue:
        return "CTO", overdue
    return "PO", overdue


def route_approvals(session, items: list, now: datetime | None = None) -> list:
    """Set approval_owner and approval_overdue on IntakeOut rows that wait for approval."""
    owned = projects_with_owner(session)
    for item in items:
        owner, overdue = approval_owner(
            project_has_owner=str(item.project_id) in owned, priority=item.suggested_priority, waiting_since=item.updated_at, now=now,
        )
        item.approval_owner = owner
        item.approval_overdue = overdue
    return items
