"""The CTO's own staff record (FR-PLAN-37).

The CTO logs in as a user; planning, reports and Telegram know people as staff records. When the CTO takes work
themself, their login is linked to a staff record (`users.member_id`) that keeps the CTO's two differences: no hours
unless the CTO sets them for a day, and no Daily Report expected. A staff record carrying the CTO's email counts as
the CTO's even before the link is made, as the reminders always assumed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models import AuditEvent, User, WorkforceMember


class CtoStaffError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def cto_user(session) -> User | None:
    return session.scalar(select(User).where(User.role == "CTO", User.is_active.is_(True)).order_by(User.created_at))


def cto_member(session) -> WorkforceMember | None:
    """The staff record behind the CTO's login: the linked one, else the one with the CTO's email."""
    user = cto_user(session)
    if user is None:
        return None
    if user.member_id:
        return session.get(WorkforceMember, user.member_id)
    return session.scalar(select(WorkforceMember).where(WorkforceMember.email_reference == user.email))


def cto_member_ids(session) -> set[str]:
    """Ids of the staff records that are a CTO: linked to a CTO login, or carrying a CTO login's email."""
    ids: set[str] = set()
    for user in session.scalars(select(User).where(User.role == "CTO", User.is_active.is_(True))).all():
        if user.member_id:
            ids.add(str(user.member_id))
            continue
        found = session.scalar(select(WorkforceMember.id).where(WorkforceMember.email_reference == user.email))
        if found:
            ids.add(str(found))
    return ids


def is_cto_member(session, member: WorkforceMember) -> bool:
    return str(member.id) in cto_member_ids(session)


def link_cto_login(session, member: WorkforceMember, now: datetime) -> bool:
    """A staff record made with the CTO's email is the CTO's: link the login to it when it has none yet."""
    if not member.email_reference:
        return False
    user = session.scalar(select(User).where(
        User.role == "CTO", User.is_active.is_(True), User.email == member.email_reference, User.member_id.is_(None),
    ))
    if user is None:
        return False
    user.member_id, user.updated_at = member.id, now
    return True


def ensure_cto_member(session, user_id: str, actor_id: str) -> WorkforceMember:
    """The CTO's staff record, made or linked in one click. Idempotent: a second click returns the same record.

    Made fresh, it has no daily hours: the CTO sets hours on the days they take work. The caller commits."""
    now = datetime.now(timezone.utc)
    user = session.get(User, user_id)
    if user is None or user.role != "CTO":
        raise CtoStaffError("CTO_ONLY", "Only the CTO adds themself to the staff list")
    email = (user.email or "").strip().lower()
    member = session.get(WorkforceMember, user.member_id) if user.member_id else None
    if member is None and email:
        member = session.scalar(select(WorkforceMember).where(WorkforceMember.email_reference == email))
        if member is not None and session.scalar(select(User.id).where(User.member_id == member.id, User.id != user.id)):
            raise CtoStaffError("MEMBER_HAS_ACCOUNT", "The staff record with this email belongs to another login")
    if member is None:
        member = WorkforceMember(
            id=str(uuid4()), display_name=" ".join((user.display_name or "").split())[:255] or "CTO",
            email_reference=email or None, status="ACTIVE", timezone="Asia/Ho_Chi_Minh", default_weekday_hours=0,
            created_at=now, updated_at=now,
        )
        session.add(member)
        session.flush()
        session.add(AuditEvent(
            id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="planning.member.created",
            entity_type="workforce_member", entity_id=member.id, details={"cto": True, "project_ids": []}, created_at=now,
        ))
    if member.status != "ACTIVE":
        member.status, member.updated_at = "ACTIVE", now
    if str(user.member_id or "") != str(member.id):
        user.member_id, user.updated_at = member.id, now
    return member
