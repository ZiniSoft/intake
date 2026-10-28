"""Suggestions from members who are not Project Owners (FR-FBK-01..03, ADR-0064).

A Developer, a linked person on Telegram or their agent says "this should be a request" for a project they belong
to. It waits here as a suggestion: no Intake code, no AI call, no place in the Intake lists. The Project Owner (or the
CTO) reads the words and the pictures and accepts it, which creates the Intake on channel FEEDBACK with the files
attached and the AI reading it, or rejects it with a line that goes back to the person. Nothing here talks to an AI
or to a tracker.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from app.db import get_session
from app.models import AuditEvent, FeedbackFile, FeedbackItem, IntakeItem, Project, User, WorkforceMember, WorkforceProjectMembership
from app.services.attachment_reader import AttachmentCheckError, check_file
from app.services.attachment_service import ALLOWED_MIME_TYPES, MAX_ATTACHMENT_SIZE, store_attachment
from app.services.object_storage import get_object_storage
from app.services.raw_crypto import decrypt, encrypt

TRANSPORTS = ("WEB", "TELEGRAM", "AGENT")
STATES = ("PENDING", "ACCEPTED", "REJECTED")
MAX_FILES = 3
MIN_TEXT = 5
MAX_TEXT = 20000


class FeedbackError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def member_of_user(session, user_id: str | None) -> WorkforceMember | None:
    if not user_id:
        return None
    user = session.get(User, user_id)
    if user is None or not user.member_id:
        return None
    return session.get(WorkforceMember, user.member_id)


def projects_of_member(session, member_id: str) -> list[Project]:
    """The active software projects the person is on: the only ones they may suggest for."""
    return session.scalars(
        select(Project).join(WorkforceProjectMembership, WorkforceProjectMembership.project_id == Project.id)
        .where(WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.active.is_(True),
               Project.status == "ACTIVE", Project.kind == "SOFTWARE")
        .order_by(Project.code)
    ).all()


class FeedbackService:
    def create(self, *, project_id: str, text: str, transport: str, user_id: str | None, member_id: str | None,
               files: list[tuple[str, str, bytes]] | None = None, idempotency_key: str | None = None) -> dict[str, object]:
        """A new suggestion with its files checked at the door; the same idempotency key gives the same suggestion back."""
        if transport not in TRANSPORTS:
            raise FeedbackError("TRANSPORT_UNKNOWN", "Transport must be WEB, TELEGRAM or AGENT")
        body = text.strip()
        if len(body) < MIN_TEXT:
            raise FeedbackError("TEXT_REQUIRED", "Say in a few words what should be done")
        body = body[:MAX_TEXT]
        files = files or []
        if len(files) > MAX_FILES:
            raise FeedbackError("TOO_MANY_FILES", f"At most {MAX_FILES} files")
        checked: list[tuple[str, str, bytes, str]] = []
        for name, mime, content in files:
            if mime not in ALLOWED_MIME_TYPES:
                raise AttachmentCheckError("ATTACHMENT_TYPE_UNSUPPORTED", "Unsupported attachment type")
            if len(content) > MAX_ATTACHMENT_SIZE:
                raise AttachmentCheckError("ATTACHMENT_TOO_LARGE", "Attachment exceeds 5 MB")
            checked.append((name, mime, content, check_file(content, mime) or mime))
        now = datetime.now(timezone.utc)
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest() if idempotency_key else None
        with get_session() as session:
            if key_hash:
                existing = session.scalar(select(FeedbackItem).where(FeedbackItem.idempotency_key_hash == key_hash))
                if existing is not None:
                    return {**self._dict(session, existing), "created": False}
            project = session.get(Project, project_id)
            if project is None or project.status != "ACTIVE":
                raise KeyError(project_id)
            row = FeedbackItem(
                id=str(uuid4()), project_id=project.id, member_id=member_id, user_id=user_id, transport=transport,
                text_ciphertext=encrypt(body), status="PENDING", idempotency_key_hash=key_hash, created_at=now,
            )
            session.add(row)
            storage = get_object_storage()
            keys: list[str] = []
            try:
                for name, mime, content, detected in checked:
                    key = f"feedback/{row.id}/{uuid4().hex}"
                    storage.put(key, content, mime)
                    keys.append(key)
                    session.add(FeedbackFile(
                        id=str(uuid4()), feedback_id=row.id, object_key=key, name_ciphertext=encrypt(name), mime_type=detected,
                        size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), created_at=now,
                    ))
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=project.id, actor_type="AGENT" if transport == "AGENT" else "USER",
                    actor_id=user_id or member_id or "telegram", event_type="feedback.created", entity_type="feedback", entity_id=row.id,
                    details={"transport": transport, "files": len(checked)}, created_at=now,
                ))
                session.commit()
            except Exception:
                for key in keys:
                    storage.delete(key)
                raise
            return {**self._dict(session, row), "created": True}

    def add_file(self, feedback_id: str, *, name: str, mime: str, content: bytes, actor_user_id: str | None) -> dict[str, object]:
        """One more picture on a suggestion still waiting, by the person who wrote it."""
        if mime not in ALLOWED_MIME_TYPES:
            raise AttachmentCheckError("ATTACHMENT_TYPE_UNSUPPORTED", "Unsupported attachment type")
        if len(content) > MAX_ATTACHMENT_SIZE:
            raise AttachmentCheckError("ATTACHMENT_TOO_LARGE", "Attachment exceeds 5 MB")
        detected = check_file(content, mime) or mime
        with get_session() as session:
            row = session.get(FeedbackItem, feedback_id)
            if row is None:
                raise KeyError(feedback_id)
            if row.status != "PENDING":
                raise FeedbackError("ALREADY_DECIDED", "This suggestion was already decided")
            if actor_user_id and row.user_id and str(row.user_id) != str(actor_user_id):
                raise FeedbackError("NOT_YOURS", "Only the person who wrote the suggestion adds files to it")
            count = int(session.scalar(select(func.count()).select_from(FeedbackFile).where(FeedbackFile.feedback_id == row.id)) or 0)
            if count >= MAX_FILES:
                raise FeedbackError("TOO_MANY_FILES", f"At most {MAX_FILES} files")
            key = f"feedback/{row.id}/{uuid4().hex}"
            get_object_storage().put(key, content, mime)
            session.add(FeedbackFile(
                id=str(uuid4()), feedback_id=row.id, object_key=key, name_ciphertext=encrypt(name), mime_type=detected,
                size_bytes=len(content), sha256=hashlib.sha256(content).hexdigest(), created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            return self._dict(session, row)

    def list(self, *, allowed_project_ids: frozenset[str] | None, project_id: str | None = None, status: str | None = None,
             user_id: str | None = None, member_id: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        with get_session() as session:
            query = select(FeedbackItem)
            if allowed_project_ids is not None:
                query = query.where(FeedbackItem.project_id.in_(list(allowed_project_ids)))
            if project_id:
                query = query.where(FeedbackItem.project_id == project_id)
            if status:
                query = query.where(FeedbackItem.status == status)
            if user_id or member_id:
                mine = []
                if user_id:
                    mine.append(FeedbackItem.user_id == user_id)
                if member_id:
                    mine.append(FeedbackItem.member_id == member_id)
                from sqlalchemy import or_
                query = query.where(or_(*mine))
            rows = session.scalars(query.order_by(FeedbackItem.created_at.desc()).limit(limit)).all()
            return [self._dict(session, row) for row in rows]

    def get(self, feedback_id: str) -> dict[str, object] | None:
        with get_session() as session:
            row = session.get(FeedbackItem, feedback_id)
            return self._dict(session, row) if row is not None else None

    def pending_count(self, allowed_project_ids: frozenset[str] | None) -> int:
        with get_session() as session:
            query = select(func.count()).select_from(FeedbackItem).where(FeedbackItem.status == "PENDING")
            if allowed_project_ids is not None:
                query = query.where(FeedbackItem.project_id.in_(list(allowed_project_ids)))
            return int(session.scalar(query) or 0)

    def file_bytes(self, feedback_id: str, file_id: str) -> tuple[str, str, bytes]:
        with get_session() as session:
            row = session.get(FeedbackFile, file_id)
            if row is None or str(row.feedback_id) != str(feedback_id):
                raise KeyError(file_id)
            name, mime, key = decrypt(row.name_ciphertext) or "tep", row.mime_type, row.object_key
        return name, mime, get_object_storage().get(key)

    def accept(self, feedback_id: str, *, actor_id: str, note: str | None = None) -> dict[str, object]:
        """The owner's yes: the suggestion becomes a request on channel FEEDBACK, files attached, AI reading it."""
        from app.schemas import IntakeCreate
        from app.services.intake_service import intake_store
        from app.services.processing_repository import processing_repository

        with get_session() as session:
            row = session.get(FeedbackItem, feedback_id)
            if row is None:
                raise KeyError(feedback_id)
            if row.status != "PENDING":
                raise FeedbackError("ALREADY_DECIDED", "This suggestion was already decided")
            project = session.get(Project, row.project_id)
            member = session.get(WorkforceMember, row.member_id) if row.member_id else None
            user = session.get(User, row.user_id) if row.user_id else None
            who = (member.display_name if member else None) or (user.display_name if user else None) or "nhân sự"
            text = decrypt(row.text_ciphertext) or ""
            files = [(decrypt(f.name_ciphertext) or "tep", f.mime_type, f.object_key) for f in session.scalars(select(FeedbackFile).where(FeedbackFile.feedback_id == row.id)).all()]
            code = project.code
        payload = IntakeCreate(project_id=code, channel="FEEDBACK", raw_text=text, sender_reference=f"Góp ý của {who}")
        item = intake_store.create(payload, idempotency_key=f"feedback:{feedback_id}")
        if not processing_repository.list_runs(item.id):
            storage = get_object_storage()
            for name, mime, key in files:
                try:
                    store_attachment(item.id, name, mime, storage.get(key), read_now=False)
                except AttachmentCheckError:
                    continue
            processing_repository.enqueue_normalization(item.id)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.get(FeedbackItem, feedback_id)
            row.status, row.intake_id, row.decided_by, row.decided_at = "ACCEPTED", item.id, actor_id, now
            row.decision_note = " ".join((note or "").split())[:500] or None
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id, event_type="feedback.accepted",
                entity_type="feedback", entity_id=row.id, details={"intake_id": item.id, "public_id": item.public_id}, created_at=now,
            ))
            session.commit()
            return self._dict(session, row)

    def reject(self, feedback_id: str, *, actor_id: str, note: str | None) -> dict[str, object]:
        text = " ".join((note or "").split())
        if len(text) < 3:
            raise FeedbackError("NOTE_REQUIRED", "Say why, in a line the person will read")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.get(FeedbackItem, feedback_id)
            if row is None:
                raise KeyError(feedback_id)
            if row.status != "PENDING":
                raise FeedbackError("ALREADY_DECIDED", "This suggestion was already decided")
            row.status, row.decided_by, row.decided_at, row.decision_note = "REJECTED", actor_id, now, text[:500]
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id, event_type="feedback.rejected",
                entity_type="feedback", entity_id=row.id, details={"note": text[:500]}, created_at=now,
            ))
            session.commit()
            return self._dict(session, row)

    def decided_recently(self, session, since: datetime) -> list[dict[str, object]]:
        """Decisions the Telegram bot still has to tell: decided after `since`, by a person with a chat."""
        rows = session.scalars(
            select(FeedbackItem).join(WorkforceMember, WorkforceMember.id == FeedbackItem.member_id)
            .where(FeedbackItem.status.in_(("ACCEPTED", "REJECTED")), FeedbackItem.decided_at >= since, WorkforceMember.telegram_chat_id.is_not(None))
            .order_by(FeedbackItem.decided_at)
        ).all()
        return [self._dict(session, row) for row in rows]

    @staticmethod
    def _dict(session, row: FeedbackItem) -> dict[str, object]:
        project = session.get(Project, row.project_id)
        member = session.get(WorkforceMember, row.member_id) if row.member_id else None
        user = session.get(User, row.user_id) if row.user_id else None
        decided = session.get(User, row.decided_by) if row.decided_by else None
        intake = session.get(IntakeItem, row.intake_id) if row.intake_id else None
        files = session.scalars(select(FeedbackFile).where(FeedbackFile.feedback_id == row.id).order_by(FeedbackFile.created_at)).all()
        return {
            "id": str(row.id), "project_id": str(row.project_id), "project_code": project.code if project else None,
            "project_name": project.name if project else None, "member_id": str(row.member_id) if row.member_id else None,
            "member_name": (member.display_name if member else None) or (user.display_name if user else None),
            "member_chat_id": member.telegram_chat_id if member else None,
            "user_id": str(row.user_id) if row.user_id else None, "transport": row.transport, "text": decrypt(row.text_ciphertext) or "",
            "status": row.status, "intake_id": str(row.intake_id) if row.intake_id else None, "intake_public_id": intake.public_id if intake else None,
            "decided_by": str(row.decided_by) if row.decided_by else None, "decided_by_name": decided.display_name if decided else None,
            "decided_at": row.decided_at, "decision_note": row.decision_note,
            "files": [{"id": str(f.id), "name": decrypt(f.name_ciphertext), "mime_type": f.mime_type, "size_bytes": f.size_bytes} for f in files],
            "created_at": row.created_at,
        }


feedback_service = FeedbackService()
