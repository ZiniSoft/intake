from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select

from app.modules.integrations.description import proposed_details
from app.config import get_settings
from app.db import get_session, init_db
from app.models import AIExtraction, IntakeItem, OutboxEvent, ProcessingRun
from app.services.ai_processor import INTAKE_PROMPT_VERSION, AIExtraction as ExtractionResult


NORMALIZE_EVENT = "intake.normalization.requested.v1"
NORMALIZE_RUN_TYPE = "AI_NORMALIZE"
NORMALIZE_STAGE = "NORMALIZE"
NORMALIZE_SCHEMA_VERSION = "intake-normalized-v1"


@dataclass(frozen=True)
class EnqueueResult:
    run_id: str
    created: bool


class ProcessingRepository:
    def enqueue_normalization(self, intake_id: str) -> EnqueueResult | None:
        """Create a queued run and its dispatch event in the same DB transaction."""
        init_db()
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id).with_for_update())
            if item is None:
                return None
            if item.status in ("SYNC_PENDING", "SYNCED"):
                raise RuntimeError("SYNC_LOCKED")

            active = session.scalar(
                select(ProcessingRun)
                .where(
                    ProcessingRun.intake_id == intake_id,
                    ProcessingRun.run_type == NORMALIZE_RUN_TYPE,
                    ProcessingRun.status.in_(("QUEUED", "RUNNING")),
                )
                .order_by(ProcessingRun.created_at.desc())
            )
            if active is not None:
                return EnqueueResult(run_id=active.id, created=False)

            input_material = f"{intake_id}:{item.version}:{item.normalized_summary or ''}"
            input_hash = hashlib.sha256(input_material.encode("utf-8")).hexdigest()
            job_key = f"normalize:{intake_id}:{input_hash}:{NORMALIZE_SCHEMA_VERSION}"
            existing = session.scalar(select(ProcessingRun).where(ProcessingRun.job_key == job_key))
            if existing is not None:
                return EnqueueResult(run_id=existing.id, created=False)

            run_id = str(uuid4())
            session.add(
                ProcessingRun(
                    id=run_id,
                    intake_id=intake_id,
                    run_type=NORMALIZE_RUN_TYPE,
                    stage=NORMALIZE_STAGE,
                    job_key=job_key,
                    input_hash=input_hash,
                    status="QUEUED",
                    attempt=0,
                    max_attempts=get_settings().ai_task_max_retries,
                    retryable=True,
                    run_metadata={"schema_version": NORMALIZE_SCHEMA_VERSION},
                    created_at=now,
                )
            )
            session.add(
                OutboxEvent(
                    id=str(uuid4()),
                    aggregate_type="intake",
                    aggregate_id=intake_id,
                    project_id=item.project_id,
                    event_type=NORMALIZE_EVENT,
                    payload={"run_id": run_id, "intake_id": intake_id},
                    status="NEW",
                    dedupe_key=f"dispatch:{job_key}",
                    attempt=0,
                    created_at=now,
                )
            )
            item.status = "PROCESSING"
            item.version += 1
            item.updated_at = now
            session.commit()
            return EnqueueResult(run_id=run_id, created=True)

    def mark_running(self, run_id: str, worker_id: str) -> bool:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update())
            if run is None or run.status not in ("QUEUED", "RETRY"):
                return False
            if run.next_attempt_at is not None and run.next_attempt_at > now:
                return False
            run.status = "RUNNING"
            run.attempt += 1
            run.worker_id = worker_id
            run.started_at = now
            run.finished_at = None
            run.error_code = None
            run.error_detail_redacted = None
            run.next_attempt_at = None
            run.lease_expires_at = now + timedelta(seconds=settings.pipeline_run_lease_seconds)
            session.commit()
            return True

    def requeue(self, run_id: str, error_code: str, delay_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.get(ProcessingRun, run_id)
            if run is None or run.status == "SUCCEEDED":
                return
            run.status = "RETRY"
            run.error_code = error_code
            run.next_attempt_at = now + timedelta(seconds=delay_seconds)
            run.lease_expires_at = None
            session.commit()

    def complete(
        self,
        run_id: str,
        intake_id: str,
        extraction: ExtractionResult,
        model_provider: str,
        model_name: str,
        latency_ms: int,
        provider_metadata: dict[str, object] | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        result = extraction.model_dump()
        output_hash = hashlib.sha256(str(sorted(result.items())).encode("utf-8")).hexdigest()
        extraction_id = str(uuid4())
        with get_session() as session:
            run = session.scalar(select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update())
            if run is None or run.status == "SUCCEEDED":
                return
            run.status = "SUCCEEDED"
            run.output_hash = output_hash
            run.finished_at = now
            run.next_attempt_at = None
            run.lease_expires_at = None
            run.run_metadata = {
                **(run.run_metadata or {}),
                "provider": model_provider,
                "model": model_name,
                **(provider_metadata or {}),
            }
            input_policy = {
                "OPENROUTER": "ZDR_DENY_COLLECTION",
                "UMODELVERSE": "PILOT_APPROVED_EXTERNAL",
            }.get(model_provider, "LOCAL_ONLY")
            session.add(
                AIExtraction(
                    id=extraction_id,
                    processing_run_id=run_id,
                    intake_id=intake_id,
                    schema_version=NORMALIZE_SCHEMA_VERSION,
                    prompt_version=INTAKE_PROMPT_VERSION,
                    model_provider=model_provider,
                    model_name=model_name,
                    input_policy=input_policy,
                    result=result,
                    confidence=None,
                    token_usage=(provider_metadata or {}).get("token_usage") if provider_metadata else None,
                    fallback_reason=(provider_metadata or {}).get("fallback_reason") if provider_metadata else None,
                    latency_ms=latency_ms,
                )
            )
            item = session.get(IntakeItem, intake_id)
            if item is not None:
                item.current_extraction_id = extraction_id
                item.item_type = extraction.item_type
                item.suggested_priority = extraction.suggested_priority
                item.proposed_route = extraction.proposed_route
                item.normalized_title = extraction.normalized_title
                item.normalized_summary = extraction.normalized_summary
                item.normalized_details = proposed_details(session, item.project_id, extraction, item.normalized_details)
                item.status = "NEEDS_INFORMATION" if extraction.item_type == "UNCLEAR" else "PENDING_APPROVAL"
                item.version += 1
                item.updated_at = now
            session.commit()

    def fail(self, run_id: str, error_code: str, retryable: bool = False) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(ProcessingRun).where(ProcessingRun.id == run_id).with_for_update())
            if run is None or run.status == "SUCCEEDED":
                return
            run.status = "FAILED"
            run.error_code = error_code
            run.retryable = retryable
            run.finished_at = now
            run.next_attempt_at = None
            run.lease_expires_at = None
            item = session.get(IntakeItem, run.intake_id)
            if item is not None:
                item.status = "PROCESSING_FAILED"
                item.version += 1
                item.updated_at = now
            session.commit()

    def recover_stale_runs(self) -> int:
        """Re-publish work whose worker lease expired after a crash."""
        now = datetime.now(timezone.utc)
        recovered = 0
        with get_session() as session:
            runs = session.scalars(
                select(ProcessingRun)
                .where(
                    ProcessingRun.status == "RUNNING",
                    ProcessingRun.retryable.is_(True),
                    ProcessingRun.lease_expires_at.is_not(None),
                    ProcessingRun.lease_expires_at <= now,
                )
                .with_for_update(skip_locked=True)
            ).all()
            for run in runs:
                event = session.scalar(select(OutboxEvent).where(OutboxEvent.dedupe_key == f"dispatch:{run.job_key}"))
                if run.attempt >= run.max_attempts:
                    run.status = "FAILED"
                    run.retryable = False
                    run.error_code = "WORKER_LEASE_EXHAUSTED"
                    run.finished_at = now
                    run.next_attempt_at = None
                    run.lease_expires_at = None
                    item = session.get(IntakeItem, run.intake_id)
                    if item is not None:
                        item.status = "PROCESSING_FAILED"
                        item.version += 1
                        item.updated_at = now
                    if event is not None:
                        event.status = "DEAD"
                        event.next_attempt_at = None
                        event.lease_expires_at = None
                        event.error_detail_redacted = "WORKER_LEASE_EXHAUSTED"
                else:
                    run.status = "RETRY"
                    run.error_code = "WORKER_LEASE_EXPIRED"
                    run.next_attempt_at = now
                    run.lease_expires_at = None
                    if event is not None:
                        event.status = "RETRY"
                        event.next_attempt_at = now
                        event.lease_expires_at = None
                        event.published_at = None
                recovered += 1
            session.commit()
        return recovered

    def list_runs(self, intake_id: str) -> list[ProcessingRun]:
        with get_session() as session:
            return list(
                session.scalars(
                    select(ProcessingRun)
                    .where(ProcessingRun.intake_id == intake_id)
                    .order_by(ProcessingRun.created_at, ProcessingRun.id)
                ).all()
            )


processing_repository = ProcessingRepository()
