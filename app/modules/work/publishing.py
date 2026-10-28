"""Approved channel versions of marketing posts on the posting flow's queue (FR-MKT-14, ADR-0038, ADR-0068): a
version goes out through the flow only when its channel is switched to auto-publish by the CTO, the post is
approved, the version is ready and its hour has come; the flow calls back with the link and the version is out.
One switch pauses everything."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import AppSetting, AuditEvent, ChannelRule, Project, WorkChannel, WorkItem
from app.modules.work.links import links_of
from app.modules.work.service import WorkError, work_service
from app.services.raw_crypto import decrypt

QUEUE_PREFIX = "work_channel:"
PAUSE_KEY = "publish.paused"
# How early before its hour a version is handed to the flow, so the flow's own rhythm does not make it late.
LEAD_MINUTES = 15
# A version whose hour is this far gone is not handed out any more: someone should look at it instead.
STALE_HOURS = 48


class PublishingError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_paused() -> bool:
    with get_session() as session:
        row = session.get(AppSetting, PAUSE_KEY)
        return bool(row.value) if row is not None else False


def set_paused(value: bool, *, actor_id: str) -> bool:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(AppSetting, PAUSE_KEY)
        if row is None:
            row = AppSetting(key=PAUSE_KEY)
            session.add(row)
        if bool(row.value) != bool(value):
            row.value, row.updated_by, row.updated_at = bool(value), actor_id, now
            session.add(AuditEvent(id=str(uuid4()), project_id=None, actor_type="USER", actor_id=actor_id, event_type="publish.paused" if value else "publish.resumed",
                                   entity_type="app_setting", entity_id=str(uuid4()), details={"key": PAUSE_KEY}, created_at=now))
            session.commit()
        return bool(row.value)


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def queue(channel: str | None = None, now: datetime | None = None) -> list[dict[str, object]]:
    """What the flow may post now: approved posts' ready versions on auto-publish channels, due within the lead, soonest first."""
    if is_paused():
        return []
    now = now or datetime.now(timezone.utc)
    horizon, floor = now + timedelta(minutes=LEAD_MINUTES), now - timedelta(hours=STALE_HOURS)
    with get_session() as session:
        auto = {row.code for row in session.scalars(select(ChannelRule).where(ChannelRule.enabled.is_(True), ChannelRule.auto_publish.is_(True))).all()}
        if not auto or (channel and channel.upper() not in auto):
            return []
        rows = session.execute(
            select(WorkChannel, WorkItem, Project).join(WorkItem, WorkItem.id == WorkChannel.work_id).join(Project, Project.id == WorkItem.project_id)
            .where(WorkChannel.status == "READY", WorkItem.status == "APPROVED", WorkChannel.publish_at.is_not(None), WorkChannel.channel.in_(list(auto)))
        ).all()
        kept = []
        for version, work, project in rows:
            when = _aware(version.publish_at)
            if when is None or when > horizon or when < floor or (channel and version.channel != channel.upper()):
                continue
            kept.append((version, work, project, when))
        kept.sort(key=lambda row: row[3])
        links = links_of(session, [str(version.id) for version, _, _, _ in kept]) if kept else {}
        return [{
            "draft_id": f"{QUEUE_PREFIX}{version.id}", "kind": "post_version", "track": None, "channel": version.channel, "group_context": None, "pillar": None,
            "title": work.title, "text": version.text or decrypt(work.description_ciphertext) or work.title, "scheduled_for": when, "approved_at": _aware(work.updated_at) or now,
            "project": project.intake_key, "work": work.code, "language": version.language, "short_link": (links.get(str(version.id)) or {}).get("url"),
        } for version, work, project, when in kept]


def record(draft_id: str, *, posted: bool, posted_at: datetime | None, url: str | None, platform: str | None, error: str | None) -> dict[str, object]:
    """The flow says a version went out (with its link) or failed. Said twice, the first record stands."""
    version_id = draft_id[len(QUEUE_PREFIX):]
    now = datetime.now(timezone.utc)
    with get_session() as session:
        try:
            version = session.get(WorkChannel, version_id)
        except Exception:
            session.rollback()
            version = None
        work = session.get(WorkItem, version.work_id) if version is not None else None
        if version is None or work is None:
            raise PublishingError("DRAFT_NOT_FOUND", "Version not found")
        if work.status not in ("APPROVED", "DONE"):
            raise PublishingError("DRAFT_NOT_APPROVED", "The post is not approved")
        if version.status == "PUBLISHED":
            return {"draft_id": draft_id, "posted_at": _aware(version.updated_at), "posted_url": version.published_url, "posted_via": "WEBHOOK", "publish_error": None}
        work_id, project_id, channel = str(work.id), str(work.project_id), version.channel
    if posted:
        try:
            work_service.update_channel(work_id, version_id, actor_id="publish-flow", status="PUBLISHED", published_url=(url or "").strip()[:1000] or None, actor_type="INTEGRATION")
        except WorkError as exc:
            raise PublishingError(exc.code, str(exc)) from exc
        return {"draft_id": draft_id, "posted_at": posted_at or now, "posted_url": (url or "").strip()[:1000] or None, "posted_via": "WEBHOOK", "publish_error": None}
    reason = " ".join((error or "POST_FAILED").split())[:200]
    with get_session() as session:
        session.add(AuditEvent(id=str(uuid4()), project_id=project_id, actor_type="INTEGRATION", actor_id="publish-flow", event_type="work.publish_failed",
                               entity_type="work", entity_id=work_id, details={"channel": channel, "error": reason, "platform": (platform or "")[:40] or None}, created_at=now))
        session.commit()
    return {"draft_id": draft_id, "posted_at": None, "posted_url": None, "posted_via": None, "publish_error": reason}
