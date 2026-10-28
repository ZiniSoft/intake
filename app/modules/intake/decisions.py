"""Which decision a sync belongs to, and whether that decision was taken back (FR-APR-10).

An approval snapshot is invalidated both when the approver edits the request after approving (FR-APR-06) and when the
decision is taken back (FR-APR-08). Only the second makes the item outside "the item of a decision that was taken
back": a reopen recorded after the snapshot was made.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from app.models import ApprovalAction, ApprovalSnapshot, IntakeItem, Project, User

# What each recorded action reads as on the decision history (FR-APR-15).
DECISION_KINDS = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "DEFER": "DEFERRED", "NEEDS_INFORMATION": "NEEDS_INFORMATION", "REOPEN": "REOPENED"}


def list_decisions(session, allowed_project_ids, project_id: str | None, since: datetime | None, before: datetime | None, limit: int) -> list[dict[str, object]]:
    """Decisions taken on requests, newest first: who, when, what, why, and what the request is now. A decision
    leaves the queue, not the record. Scope is the caller's projects, like the queue itself (FR-APR-15)."""
    query = (
        select(ApprovalAction, IntakeItem, Project)
        .join(IntakeItem, IntakeItem.id == ApprovalAction.intake_id)
        .join(Project, Project.id == IntakeItem.project_id)
        .where(ApprovalAction.action.in_(sorted(DECISION_KINDS)))
    )
    if allowed_project_ids is not None:
        query = query.where(IntakeItem.project_id.in_(sorted(str(value) for value in allowed_project_ids)))
    if project_id:
        query = query.where((IntakeItem.project_id == project_id) | (Project.code == project_id))
    if since is not None:
        query = query.where(ApprovalAction.created_at >= since)
    if before is not None:
        query = query.where(ApprovalAction.created_at < before)
    rows = session.execute(query.order_by(ApprovalAction.created_at.desc()).limit(limit)).all()
    action_ids = [str(action.id) for action, _, _ in rows]
    snapshots = {str(row.approval_action_id): row for row in session.scalars(select(ApprovalSnapshot).where(ApprovalSnapshot.approval_action_id.in_(action_ids))).all()} if action_ids else {}
    actor_ids = sorted({str(action.actor_id) for action, _, _ in rows if action.actor_id})
    users = {str(user.id): (user.display_name or user.auth_subject) for user in session.scalars(select(User).where(User.id.in_(actor_ids))).all()} if actor_ids else {}
    out: list[dict[str, object]] = []
    for action, item, project in rows:
        snapshot = snapshots.get(str(action.id))
        payload = snapshot.payload if snapshot is not None and isinstance(snapshot.payload, dict) else {}
        out.append({
            "id": str(action.id), "at": action.created_at, "action": DECISION_KINDS[action.action], "source": action.source or "QUEUE",
            "actor_id": str(action.actor_id) if action.actor_id else None, "actor_name": users.get(str(action.actor_id)) if action.actor_id else None,
            "reason": action.reason, "intake_id": str(item.id), "public_id": item.public_id,
            "title": item.normalized_title or (item.normalized_summary or "")[:120] or item.public_id, "status": item.status,
            "project_id": str(project.id), "project_code": project.code, "project_name": project.name,
            "approved_route": snapshot.approved_route if snapshot is not None else None,
            "approved_priority": str(payload.get("approved_priority")) if payload.get("approved_priority") else None,
        })
    return out


def latest_reopen_at(session, intake_ids: list[str]) -> dict[str, datetime]:
    """When each request was last taken back; requests never taken back are absent."""
    out: dict[str, datetime] = {}
    if not intake_ids:
        return out
    for action in session.scalars(select(ApprovalAction).where(
        ApprovalAction.action == "REOPEN", ApprovalAction.intake_id.in_(intake_ids),
    )).all():
        key = str(action.intake_id)
        if key not in out or action.created_at > out[key]:
            out[key] = action.created_at
    return out


def taken_back(snapshot_created_at: datetime | None, invalidated_at: datetime | None, reopened_at: datetime | None) -> bool:
    """The decision behind this snapshot was taken back: invalidated, and a reopen came after it was made."""
    if invalidated_at is None or reopened_at is None or snapshot_created_at is None:
        return False
    return reopened_at >= snapshot_created_at
