from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import IntakeItem, OutboxEvent, ProcessingRun
from app.schemas import IntakeCreate
from app.services.intake_service import intake_store
from app.services.outbox_dispatcher import outbox_dispatcher
from app.services.processing_repository import NORMALIZE_EVENT, processing_repository


def enqueue(text: str) -> tuple[str, str, str]:
    item = intake_store.create(IntakeCreate(project_id="orbit", channel="MANUAL", raw_text=text))
    result = processing_repository.enqueue_normalization(item.id)
    assert result is not None
    with get_session() as session:
        event = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == item.id,
                OutboxEvent.event_type == NORMALIZE_EVENT,
            )
        )
        assert event is not None
        return item.id, result.run_id, event.id


def test_broker_publish_failure_is_redacted_and_retry_is_bounded() -> None:
    _, _, event_id = enqueue("SYNTHETIC TEST DATA: broker failure")
    settings = get_settings()

    with get_session() as session:
        event = session.get(OutboxEvent, event_id)
        event.status = "PUBLISHING"
        event.attempt = 1
        session.commit()
    outbox_dispatcher.mark_failed(event_id, "BROKER_UNAVAILABLE")
    with get_session() as session:
        event = session.get(OutboxEvent, event_id)
        assert event.status == "RETRY"
        assert event.next_attempt_at is not None
        assert event.error_detail_redacted == "BROKER_UNAVAILABLE"

        event.status = "PUBLISHING"
        event.attempt = settings.outbox_max_attempts
        session.commit()
    outbox_dispatcher.mark_failed(event_id, "BROKER_UNAVAILABLE")
    with get_session() as session:
        event = session.get(OutboxEvent, event_id)
        assert event.status == "DEAD"
        assert event.next_attempt_at is None
        assert event.lease_expires_at is None
        assert event.error_detail_redacted == "BROKER_UNAVAILABLE"

    assert all(claim.id != event_id for claim in outbox_dispatcher.claim())


def test_invalid_outbox_payload_fails_terminal_without_publish() -> None:
    _, _, event_id = enqueue("SYNTHETIC TEST DATA: invalid event payload")
    with get_session() as session:
        event = session.get(OutboxEvent, event_id)
        event.payload = "not-json"
        event.status = "NEW"
        session.commit()

    claimed = outbox_dispatcher.claim()
    assert all(event.id != event_id for event in claimed)
    with get_session() as session:
        event = session.get(OutboxEvent, event_id)
        assert event.status == "DEAD"
        assert event.error_detail_redacted == "INVALID_EVENT_PAYLOAD"
        assert event.next_attempt_at is None


def test_expired_worker_lease_is_requeued_once() -> None:
    _, run_id, event_id = enqueue("SYNTHETIC TEST DATA: recover expired worker lease")
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    with get_session() as session:
        run = session.get(ProcessingRun, run_id)
        event = session.get(OutboxEvent, event_id)
        run.status = "RUNNING"
        run.attempt = 1
        run.max_attempts = 3
        run.lease_expires_at = expired
        event.status = "PUBLISHING"
        event.lease_expires_at = expired
        session.commit()

    assert processing_repository.recover_stale_runs() >= 1
    with get_session() as session:
        run = session.get(ProcessingRun, run_id)
        event = session.get(OutboxEvent, event_id)
        assert run.status == "RETRY"
        assert run.error_code == "WORKER_LEASE_EXPIRED"
        assert event.status == "RETRY"
        assert event.published_at is None


def test_expired_worker_lease_stops_at_max_attempts() -> None:
    intake_id, run_id, event_id = enqueue("SYNTHETIC TEST DATA: exhaust worker lease")
    expired = datetime.now(timezone.utc) - timedelta(seconds=1)
    with get_session() as session:
        run = session.get(ProcessingRun, run_id)
        event = session.get(OutboxEvent, event_id)
        run.status = "RUNNING"
        run.attempt = run.max_attempts
        run.lease_expires_at = expired
        event.status = "PUBLISHING"
        event.lease_expires_at = expired
        session.commit()

    assert processing_repository.recover_stale_runs() >= 1
    with get_session() as session:
        run = session.get(ProcessingRun, run_id)
        event = session.get(OutboxEvent, event_id)
        item = session.get(IntakeItem, intake_id)
        assert run.status == "FAILED"
        assert run.retryable is False
        assert run.error_code == "WORKER_LEASE_EXHAUSTED"
        assert item.status == "PROCESSING_FAILED"
        assert event.status == "DEAD"
        assert event.error_detail_redacted == "WORKER_LEASE_EXHAUSTED"
        assert event.next_attempt_at is None
