from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import or_, select

from app.config import get_settings
from app.db import get_session
from app.models import OutboxEvent
from app.services.processing_repository import NORMALIZE_EVENT
from app.modules.integrations.service import SYNC_EVENT
from app.modules.planning.service import PLANNING_SYNC_EVENT


logger = logging.getLogger("intake.outbox.publisher")


@dataclass(frozen=True)
class ClaimedEvent:
    id: str
    event_type: str
    payload: dict


TASK_ROUTES = {
    NORMALIZE_EVENT: ("intake.normalize", "ai.normalize"),
    SYNC_EVENT: ("intake.sync.external", "integration.sync"),
    PLANNING_SYNC_EVENT: ("intake.sync.planning-gitlab", "integration.sync"),
}


def decode_event_payload(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("Outbox payload must be a JSON object")


class OutboxDispatcher:
    def claim(self) -> list[ClaimedEvent]:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        lease_until = now + timedelta(seconds=settings.outbox_lease_seconds)
        with get_session() as session:
            events = session.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type.in_(tuple(TASK_ROUTES)),
                    or_(
                        OutboxEvent.status.in_(("NEW", "RETRY")),
                        (OutboxEvent.status == "PUBLISHING") & (OutboxEvent.lease_expires_at <= now),
                    ),
                    or_(OutboxEvent.next_attempt_at.is_(None), OutboxEvent.next_attempt_at <= now),
                )
                .order_by(OutboxEvent.created_at)
                .limit(settings.outbox_batch_size)
                .with_for_update(skip_locked=True)
            ).all()
            claimed: list[ClaimedEvent] = []
            for event in events:
                try:
                    payload = decode_event_payload(event.payload or {})
                except (TypeError, ValueError, json.JSONDecodeError):
                    event.status = "DEAD"
                    event.next_attempt_at = None
                    event.lease_expires_at = None
                    event.error_detail_redacted = "INVALID_EVENT_PAYLOAD"
                    continue
                event.status = "PUBLISHING"
                event.attempt += 1
                event.lease_expires_at = lease_until
                event.error_detail_redacted = None
                claimed.append(ClaimedEvent(event.id, event.event_type, payload))
            session.commit()
            return claimed

    def mark_published(self, event_id: str) -> None:
        with get_session() as session:
            event = session.get(OutboxEvent, event_id)
            if event is None:
                return
            event.status = "PUBLISHED"
            event.published_at = datetime.now(timezone.utc)
            event.next_attempt_at = None
            event.lease_expires_at = None
            event.error_detail_redacted = None
            session.commit()

    def mark_failed(self, event_id: str, error_code: str = "BROKER_UNAVAILABLE") -> None:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        with get_session() as session:
            event = session.get(OutboxEvent, event_id)
            if event is None:
                return
            if event.attempt >= settings.outbox_max_attempts:
                event.status = "DEAD"
                event.next_attempt_at = None
                event.lease_expires_at = None
                event.error_detail_redacted = error_code
                session.commit()
                return
            delay = min(300, 2 ** min(event.attempt, 8))
            event.status = "RETRY"
            event.next_attempt_at = now + timedelta(seconds=delay)
            event.lease_expires_at = None
            event.error_detail_redacted = error_code
            session.commit()

    def dispatch_once(self, publisher: Callable[..., object]) -> int:
        published = 0
        for event in self.claim():
            task_name, queue = TASK_ROUTES[event.event_type]
            try:
                publisher(task_name, kwargs=event.payload, queue=queue, task_id=event.id)
            except Exception as exc:
                logger.exception(
                    "Outbox publish failed event_id=%s event_type=%s exception=%s",
                    event.id,
                    event.event_type,
                    type(exc).__name__,
                )
                self.mark_failed(event.id)
                continue
            self.mark_published(event.id)
            published += 1
        return published


outbox_dispatcher = OutboxDispatcher()
