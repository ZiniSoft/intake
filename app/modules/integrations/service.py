from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import get_session, init_db
from app.models import (
    ApprovalSnapshot,
    AuditEvent,
    ExternalLink,
    IntakeItem,
    OutboxEvent,
    ProjectIntegration,
    SyncJob,
)


SYNC_EVENT = "integration.sync.requested.v1"
SYNC_TARGETS = ("GITLAB", "GITHUB")
HISTORICAL_TARGETS = ("PLANE",)


class SyncValidationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ExternalSyncContext:
    job_id: str
    intake_id: str
    intake_public_id: str
    target_system: str
    workspace_slug: str | None
    project_external_id: str
    project_base_url: str
    project_config: dict[str, object]
    idempotency_key: str
    approved: dict[str, object]
    attempt: int
    max_attempts: int


class IntegrationService:
    def __init__(self) -> None:
        init_db()

    @staticmethod
    def _mapping(session, project_id: str, target_system: str) -> ProjectIntegration | None:
        return session.scalar(
            select(ProjectIntegration).where(
                ProjectIntegration.project_id == project_id,
                ProjectIntegration.system == target_system,
            )
        )

    @staticmethod
    def _validate_snapshot(
        snapshot: ApprovalSnapshot,
        item: IntakeItem,
        mapping: ProjectIntegration | None,
        target_system: str,
    ) -> None:
        if target_system not in SYNC_TARGETS:
            raise SyncValidationError("ROUTE_NOT_SYNCABLE", "Approved route is not an external sync target")
        if snapshot.invalidated_at is not None or item.version != snapshot.item_version:
            raise SyncValidationError("SNAPSHOT_INVALIDATED", "Approval snapshot is no longer current")
        if snapshot.approved_route != target_system or item.approved_route != target_system:
            raise SyncValidationError("ROUTE_MISMATCH", "Approved route does not match the sync target")
        if mapping is None or not mapping.enabled:
            raise SyncValidationError(f"{target_system}_MAPPING_DISABLED", f"{target_system} project mapping is not enabled")
        if not mapping.project_external_id:
            raise SyncValidationError(f"{target_system}_MAPPING_INCOMPLETE", "External project ID is missing")

    def snapshot_project(self, snapshot_id: str) -> str | None:
        with get_session() as session:
            try:
                value = session.scalar(select(ApprovalSnapshot.project_id).where(ApprovalSnapshot.id == snapshot_id))
            except Exception:  # a malformed ID is simply not a snapshot
                session.rollback()
                return None
            return str(value) if value else None

    def queue_snapshot(self, snapshot_id: str, actor_id: str) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        settings = get_settings()
        with get_session() as session:
            snapshot = session.scalar(
                select(ApprovalSnapshot).where(ApprovalSnapshot.id == snapshot_id).with_for_update()
            )
            if snapshot is None:
                raise KeyError(snapshot_id)
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == snapshot.intake_id).with_for_update())
            if item is None:
                raise KeyError(snapshot.intake_id)
            target_system = str(snapshot.approved_route or "").upper()
            mapping = self._mapping(session, str(snapshot.project_id), target_system)
            self._validate_snapshot(snapshot, item, mapping, target_system)

            idempotency_key = f"{target_system.lower()}:{snapshot.id}"
            job = session.scalar(select(SyncJob).where(SyncJob.idempotency_key == idempotency_key))
            created = False
            if job is None:
                job = SyncJob(
                    id=str(uuid4()),
                    approval_snapshot_id=snapshot.id,
                    intake_id=item.id,
                    project_id=item.project_id,
                    target_system=target_system,
                    status="PENDING",
                    idempotency_key=idempotency_key,
                    attempt=0,
                    max_attempts=settings.sync_job_max_attempts,
                    request_payload_hash=snapshot.payload_hash,
                    created_at=now,
                    updated_at=now,
                )
                session.add(job)
                created = True
            elif job.status == "FAILED":
                job.status = "PENDING"
                job.attempt = 0
                job.next_attempt_at = None
                job.lease_expires_at = None
                job.error_code = None
                job.error_detail_redacted = None
                job.updated_at = now
                created = True

            if created:
                session.add(
                    OutboxEvent(
                        id=str(uuid4()),
                        aggregate_type="sync_job",
                        aggregate_id=job.id,
                        project_id=item.project_id,
                        event_type=SYNC_EVENT,
                        payload={"sync_job_id": job.id},
                        status="NEW",
                        dedupe_key=f"sync-dispatch:{job.id}:{uuid4()}",
                        attempt=0,
                        created_at=now,
                    )
                )
                session.add(
                    AuditEvent(
                        id=str(uuid4()),
                        project_id=item.project_id,
                        actor_type="USER",
                        actor_id=actor_id,
                        event_type="integration.sync.queued",
                        entity_type="sync_job",
                        entity_id=job.id,
                        details={"target": target_system, "snapshot_id": snapshot.id},
                        created_at=now,
                    )
                )
            item.status = "SYNCED" if job.status == "SUCCEEDED" else "SYNC_PENDING"
            item.updated_at = now
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                with get_session() as retry_session:
                    existing = retry_session.scalar(
                        select(SyncJob).where(SyncJob.idempotency_key == idempotency_key)
                    )
                    if existing is None:
                        raise
                    return self._job_dict(existing, None)
            session.refresh(job)
            link = session.scalar(select(ExternalLink).where(ExternalLink.sync_job_id == job.id))
            return self._job_dict(job, link)

    def status_for_intake(self, intake_id: str) -> dict[str, object]:
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            snapshot = session.scalar(
                select(ApprovalSnapshot)
                .where(
                    ApprovalSnapshot.intake_id == intake_id,
                    ApprovalSnapshot.invalidated_at.is_(None),
                )
                .order_by(ApprovalSnapshot.created_at.desc())
            )
            target_system = str(snapshot.approved_route).upper() if snapshot and snapshot.approved_route else None
            mapping = self._mapping(session, str(item.project_id), target_system) if target_system in SYNC_TARGETS else None
            job = None
            link = None
            reason = None
            available = False
            if snapshot is None:
                reason = "NOT_APPROVED"
            elif target_system in HISTORICAL_TARGETS:
                job = session.scalar(
                    select(SyncJob)
                    .where(SyncJob.approval_snapshot_id == snapshot.id, SyncJob.target_system == target_system)
                    .order_by(SyncJob.created_at.desc())
                )
                if job is not None:
                    link = session.scalar(select(ExternalLink).where(ExternalLink.sync_job_id == job.id))
                reason = "ROUTE_RETIRED"
            else:
                job = session.scalar(
                    select(SyncJob)
                    .where(
                        SyncJob.approval_snapshot_id == snapshot.id,
                        SyncJob.target_system == target_system,
                    )
                    .order_by(SyncJob.created_at.desc())
                )
                if job is not None:
                    link = session.scalar(select(ExternalLink).where(ExternalLink.sync_job_id == job.id))
                try:
                    assert target_system is not None
                    self._validate_snapshot(snapshot, item, mapping, target_system)
                    available = job is None or job.status == "FAILED"
                    if not available:
                        reason = "ALREADY_QUEUED" if job.status != "SUCCEEDED" else "ALREADY_SYNCED"
                except SyncValidationError as exc:
                    reason = exc.code
            return {
                "intake_id": str(item.id),
                "snapshot_id": str(snapshot.id) if snapshot else None,
                # A decision with no tracker (RESPONSE, WORK) has no target to report.
                "target_system": target_system if target_system in (*SYNC_TARGETS, *HISTORICAL_TARGETS) else None,
                "sync_available": available,
                "reason": reason,
                "job": self._job_dict(job, link) if job else None,
            }

    def claim_sync_job(self, job_id: str, worker_id: str) -> ExternalSyncContext | None:
        now = datetime.now(timezone.utc)
        settings = get_settings()
        with get_session() as session:
            job = session.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update())
            if job is None or job.status in ("SUCCEEDED", "FAILED"):
                return None
            if job.status == "RUNNING" and job.lease_expires_at and job.lease_expires_at > now:
                return None
            if job.status not in ("PENDING", "RETRY", "RUNNING"):
                return None
            if job.next_attempt_at is not None and job.next_attempt_at > now:
                return None
            if job.attempt >= job.max_attempts:
                job.status = "FAILED"
                job.error_code = "SYNC_ATTEMPTS_EXHAUSTED"
                job.lease_expires_at = None
                job.updated_at = now
                item = session.get(IntakeItem, job.intake_id)
                if item is not None and item.status != "SYNCED":
                    item.status = "APPROVED"
                    item.updated_at = now
                session.commit()
                return None

            snapshot = session.get(ApprovalSnapshot, job.approval_snapshot_id)
            item = session.get(IntakeItem, job.intake_id)
            mapping = self._mapping(session, str(job.project_id), str(job.target_system))
            if snapshot is None or item is None:
                raise SyncValidationError("SYNC_SOURCE_MISSING", "Sync source data is missing")
            self._validate_snapshot(snapshot, item, mapping, str(job.target_system))
            assert mapping is not None and mapping.project_external_id
            payload = snapshot.payload if isinstance(snapshot.payload, dict) else {}
            approved = {
                "approved": True,
                "title": payload.get("title") or "Approved Intake",
                "description": payload.get("summary") or "",
                "approved_priority": payload.get("approved_priority"),
                "intake_public_id": payload.get("public_id") or item.public_id,
                "item_type": payload.get("item_type"),
                "details": payload.get("details"),
            }
            job.status = "RUNNING"
            job.attempt += 1
            job.next_attempt_at = None
            job.lease_expires_at = now + timedelta(seconds=settings.sync_job_lease_seconds)
            job.error_code = None
            job.error_detail_redacted = None
            job.updated_at = now
            session.commit()
            return ExternalSyncContext(
                job_id=str(job.id),
                intake_id=str(item.id),
                intake_public_id=item.public_id,
                target_system=str(job.target_system),
                workspace_slug=mapping.workspace_external_id,
                project_external_id=mapping.project_external_id,
                project_base_url=mapping.base_url,
                project_config=mapping.config if isinstance(mapping.config, dict) else {},
                idempotency_key=job.idempotency_key,
                approved=approved,
                attempt=job.attempt,
                max_attempts=job.max_attempts,
            )

    def mark_retry(self, job_id: str, error_code: str, delay_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = session.get(SyncJob, job_id)
            if job is None or job.status == "SUCCEEDED":
                return
            job.status = "RETRY"
            job.error_code = error_code[:128]
            job.error_detail_redacted = error_code[:255]
            job.next_attempt_at = now + timedelta(seconds=delay_seconds)
            job.lease_expires_at = None
            job.updated_at = now
            session.commit()

    def fail(self, job_id: str, error_code: str) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = session.get(SyncJob, job_id)
            if job is None or job.status == "SUCCEEDED":
                return
            job.status = "FAILED"
            job.error_code = error_code[:128]
            job.error_detail_redacted = error_code[:255]
            job.next_attempt_at = None
            job.lease_expires_at = None
            job.updated_at = now
            item = session.get(IntakeItem, job.intake_id)
            if item is not None and item.status != "SYNCED":
                item.status = "APPROVED"
                item.updated_at = now
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    project_id=job.project_id,
                    actor_type="SYSTEM",
                    actor_id="integration-worker",
                    event_type="integration.sync.failed",
                    entity_type="sync_job",
                    entity_id=job.id,
                    details={"target": job.target_system, "error_code": error_code[:128]},
                    created_at=now,
                )
            )
            session.commit()

    def complete(self, job_id: str, result: dict[str, object], found_existing: bool) -> None:
        now = datetime.now(timezone.utc)
        external_id = str(result.get("id") or "").strip()
        if not external_id:
            raise SyncValidationError("EXTERNAL_INVALID_RESPONSE", "External response has no work item ID")
        with get_session() as session:
            job = session.scalar(select(SyncJob).where(SyncJob.id == job_id).with_for_update())
            if job is None or job.status == "SUCCEEDED":
                return
            snapshot = session.get(ApprovalSnapshot, job.approval_snapshot_id)
            mapping = self._mapping(session, str(job.project_id), str(job.target_system))
            if snapshot is None or mapping is None or not mapping.project_external_id:
                raise SyncValidationError("SYNC_SOURCE_MISSING", "Cannot record external response")
            url = str(result.get("url") or result.get("web_url") or "").strip()
            if not url and job.target_system == "GITLAB":
                project_url = str((mapping.config or {}).get("project_url") or "").rstrip("/")
                url = f"{project_url}/-/issues/{external_id}" if project_url else None
            link = session.scalar(select(ExternalLink).where(ExternalLink.sync_job_id == job.id))
            if link is None:
                # One row per item outside. The item of a decision that was taken back, taken over again by this
                # decision, keeps its row and the row now belongs to this sync (FR-APR-10).
                link = session.scalar(select(ExternalLink).where(
                    ExternalLink.project_id == job.project_id, ExternalLink.target_system == job.target_system,
                    ExternalLink.external_id == external_id,
                ))
                if link is not None and str(link.intake_id) != str(job.intake_id):
                    raise SyncValidationError("EXTERNAL_ID_IN_USE", "The external item belongs to another request")
                if link is not None:
                    link.sync_job_id = job.id
                    link.url = url or link.url
                    link.payload_hash = snapshot.payload_hash
                    link.created_at = now
            if link is None:
                session.add(
                    ExternalLink(
                        id=str(uuid4()),
                        sync_job_id=job.id,
                        intake_id=job.intake_id,
                        project_id=job.project_id,
                        target_system=job.target_system,
                        external_id=external_id,
                        url=url,
                        payload_hash=snapshot.payload_hash,
                        created_at=now,
                    )
                )
            job.status = "SUCCEEDED"
            job.next_attempt_at = None
            job.lease_expires_at = None
            job.error_code = None
            job.error_detail_redacted = None
            job.response_metadata = {
                "external_id": external_id,
                "sequence_id": result.get("sequence_id"),
                "global_id": result.get("global_id"),
                "found_existing": found_existing,
                "reopened": bool(result.get("reopened")),
            }
            job.updated_at = now
            item = session.get(IntakeItem, job.intake_id)
            if item is not None:
                item.status = "SYNCED"
                item.updated_at = now
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    project_id=job.project_id,
                    actor_type="SYSTEM",
                    actor_id="integration-worker",
                    event_type="integration.sync.succeeded",
                    entity_type="sync_job",
                    entity_id=job.id,
                    details={"target": job.target_system, "external_id": external_id, "found_existing": found_existing},
                    created_at=now,
                )
            )
            session.commit()
            created_issue = (
                (str(job.intake_id), str(job.project_id), external_id, url, job.target_system) if job.target_system in ("GITLAB", "GITHUB") else None
            )
        if created_issue is not None:
            # A new Issue is plannable at once instead of waiting for the next morning's refresh.
            from app.modules.planning.add_work import add_work_service
            from app.modules.work.service import work_service

            add_work_service.issue_created(*created_issue[:4])
            # The work item that asked for this Issue (ADR-0066) closes as one.
            work_service.issue_created(created_issue[0], system=created_issue[4], external_id=created_issue[2], url=created_issue[3])

    @staticmethod
    def _job_dict(job: SyncJob, link: ExternalLink | None) -> dict[str, object]:
        return {
            "id": str(job.id),
            "approval_snapshot_id": str(job.approval_snapshot_id),
            "target_system": job.target_system,
            "status": job.status,
            "attempt": job.attempt,
            "max_attempts": job.max_attempts,
            "error_code": job.error_code,
            "external_id": str(link.external_id) if link else None,
            "external_url": link.url if link else None,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }


integration_service = IntegrationService()
