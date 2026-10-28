from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import case, delete as sql_delete, exists, false, func, or_, select, tuple_, update as sql_update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import get_session, init_db
from app.models import (
    ApprovalAction,
    ApprovalSnapshot,
    Attachment,
    AuditEvent,
    DuplicateCandidate,
    EvidenceFragment,
    ExternalLink,
    GitLabIssueSnapshot,
    GlossaryTerm,
    IdeaTrack,
    IntakeCounter,
    IssueVerification,
    PlanSlot,
    WatchSignal,
    IntakeItem,
    MeetingNoteItem,
    OutboxEvent,
    PlanningAssignment,
    PlanningCandidate,
    PlanningRun,
    PostDraft,
    ProcessingRun,
    Project,
    ProjectIntegration,
    ReportItem,
    SourceMessage,
    SyncJob,
    WorkItem,
)
from app.schemas import IntakeCreate, IntakeDecision, IntakeLifecycleStage, IntakeListSummary, IntakeOut, IntakePage, IntakeReview
from app.models import AIExtraction as StoredExtraction
from app.services.ai_processor import AIExtraction
from app.modules.integrations.description import clarified, has_details, proposed_details
from app.modules.private_space.service import private_project_ids
from app.services.object_storage import get_object_storage
from app.modules.intake.decisions import latest_reopen_at, taken_back
from app.modules.intake.readiness import agent_readiness
from app.services.raw_crypto import decrypt, encrypt
from app.modules.work.service import work_service


class IntakeStore:
    def __init__(self) -> None:
        init_db()
        from app.modules.projects.service import project_catalog_service

        project_catalog_service.ensure_database_projects()

    @staticmethod
    def _to_output(item: IntakeItem, sync_targets: list[dict[str, object]] | None = None, project_context: dict | None = None,
                   work_item: dict[str, object] | None = None, duplicate_issue: dict[str, object] | None = None,
                   lifecycle_stage: IntakeLifecycleStage | None = None) -> IntakeOut:
        def as_datetime(value: datetime | str) -> datetime:
            if isinstance(value, datetime):
                return value
            return datetime.fromisoformat(value.replace(" ", "T"))

        if lifecycle_stage is None:
            if item.status in ("REJECTED", "DEFERRED", "CLOSED"):
                lifecycle_stage = "STOPPED"
            elif item.status == "NEEDS_INFORMATION":
                lifecycle_stage = "NEEDS_INFORMATION"
            elif item.status == "PENDING_APPROVAL":
                lifecycle_stage = "PENDING_APPROVAL"
            elif item.status in ("NEW", "PROCESSING", "PROCESSING_FAILED"):
                lifecycle_stage = "RECEIVED"
            elif item.approved_route == "RESPONSE":
                lifecycle_stage = "ACCEPTED"
            elif item.approved_route == "WORK" and work_item:
                lifecycle_stage = {
                    "DONE": "ACCEPTED", "CANCELLED": "STOPPED", "ACCEPTANCE": "PENDING_ACCEPTANCE",
                    "IN_PROGRESS": "IN_PROGRESS", "APPROVED": "IN_PROGRESS",
                }.get(str(work_item.get("status")), "WAITING_PLANNING")
            else:
                lifecycle_stage = "WAITING_PLANNING" if item.status in ("APPROVED", "SYNC_PENDING", "SYNCED") else "RECEIVED"

        return IntakeOut(
            id=item.id,
            public_id=item.public_id,
            project_id=item.project_id,
            channel=item.channel,
            item_type=item.item_type,
            status=item.status,
            lifecycle_stage=lifecycle_stage,
            normalized_title=item.normalized_title,
            normalized_summary=item.normalized_summary,
            details=item.normalized_details if isinstance(item.normalized_details, dict) else None,
            duplicate_of_id=str(item.duplicate_of_id) if item.duplicate_of_id else None,
            duplicate_issue=duplicate_issue,
            suggested_priority=item.suggested_priority,
            proposed_route=item.proposed_route,
            approved_priority=item.approved_priority,
            approved_route=item.approved_route,
            sync_targets=sync_targets or [],
            work_item=work_item,
            fix_hints=item.fix_hints,
            needs_cto_acceptance=bool(item.needs_cto_acceptance),
            agent_readiness=agent_readiness(
                item_type=item.item_type, title=item.normalized_title, summary=item.normalized_summary,
                details=item.normalized_details if isinstance(item.normalized_details, dict) else None,
                fix_hints=item.fix_hints, project_context=project_context,
            ),
            version=item.version,
            created_at=as_datetime(item.created_at),
            updated_at=as_datetime(item.updated_at),
        )

    @staticmethod
    def _lifecycle_stage_expression():
        """One shared lifecycle for managers, independent of each subsystem's technical status names."""
        current_link = (
            select(ExternalLink.project_id, ExternalLink.external_id)
            .join(SyncJob, SyncJob.id == ExternalLink.sync_job_id)
            .join(ApprovalSnapshot, ApprovalSnapshot.id == SyncJob.approval_snapshot_id)
            .where(
                ExternalLink.intake_id == IntakeItem.id,
                ExternalLink.target_system.in_(("GITLAB", "GITHUB")),
                ApprovalSnapshot.invalidated_at.is_(None),
            )
            .correlate(IntakeItem)
        )
        accepted_issue = exists(
            select(1).select_from(IssueVerification).where(
                IssueVerification.decision == "ACCEPTED",
                tuple_(IssueVerification.project_id, IssueVerification.issue_external_id).in_(current_link),
            )
        ).correlate(IntakeItem)
        pending_issue = exists(
            select(1).select_from(IssueVerification).where(
                IssueVerification.decision == "PENDING",
                tuple_(IssueVerification.project_id, IssueVerification.issue_external_id).in_(current_link),
            )
        ).correlate(IntakeItem)
        assignment = exists(
            select(1)
            .select_from(PlanningAssignment)
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(
                PlanningRun.status != "SUPERSEDED",
                tuple_(PlanningAssignment.project_id, PlanningAssignment.gitlab_issue_external_id).in_(current_link),
            )
        ).correlate(IntakeItem)
        assignment_done = exists(
            select(1)
            .select_from(PlanningAssignment)
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(
                PlanningRun.status != "SUPERSEDED",
                PlanningAssignment.work_status == "DONE",
                tuple_(PlanningAssignment.project_id, PlanningAssignment.gitlab_issue_external_id).in_(current_link),
            )
        ).correlate(IntakeItem)
        work_status = lambda *statuses: exists(
            select(1).select_from(WorkItem).where(
                WorkItem.intake_id == IntakeItem.id,
                WorkItem.parent_id.is_(None),
                WorkItem.status.in_(statuses),
            )
        ).correlate(IntakeItem)

        return case(
            (IntakeItem.status.in_(("REJECTED", "DEFERRED", "CLOSED")), "STOPPED"),
            (IntakeItem.status == "NEEDS_INFORMATION", "NEEDS_INFORMATION"),
            (IntakeItem.status == "PENDING_APPROVAL", "PENDING_APPROVAL"),
            (IntakeItem.status.in_(("NEW", "PROCESSING", "PROCESSING_FAILED")), "RECEIVED"),
            ((IntakeItem.approved_route == "RESPONSE") & IntakeItem.status.in_(("APPROVED", "SYNCED")), "ACCEPTED"),
            ((IntakeItem.approved_route == "WORK") & work_status("DONE"), "ACCEPTED"),
            (IntakeItem.approved_route.in_(("GITLAB", "GITHUB")) & accepted_issue, "ACCEPTED"),
            ((IntakeItem.approved_route == "WORK") & work_status("CANCELLED"), "STOPPED"),
            ((IntakeItem.approved_route == "WORK") & work_status("ACCEPTANCE"), "PENDING_ACCEPTANCE"),
            (IntakeItem.approved_route.in_(("GITLAB", "GITHUB")) & (pending_issue | assignment_done), "PENDING_ACCEPTANCE"),
            ((IntakeItem.approved_route == "WORK") & work_status("IN_PROGRESS", "APPROVED"), "IN_PROGRESS"),
            (IntakeItem.approved_route.in_(("GITLAB", "GITHUB")) & assignment, "IN_PROGRESS"),
            (IntakeItem.status.in_(("APPROVED", "SYNC_PENDING", "SYNCED")), "WAITING_PLANNING"),
            else_="RECEIVED",
        )

    @staticmethod
    def _resolve_project(session, project_id_or_code: str) -> Project | None:
        project = session.scalar(select(Project).where(Project.code == project_id_or_code))
        if project is None:
            try:
                project = session.get(Project, project_id_or_code)
            except (ValueError, TypeError):
                project = None
        return project

    @staticmethod
    def _next_public_id(session, project: Project, now: datetime) -> str:
        local_now = now.astimezone(ZoneInfo("Asia/Ho_Chi_Minh"))
        iso_year, iso_week, _ = local_now.isocalendar()
        if session.bind.dialect.name == "postgresql":
            statement = (
                postgresql_insert(IntakeCounter)
                .values(
                    project_id=project.id,
                    iso_year=iso_year,
                    iso_week=iso_week,
                    last_value=1,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["project_id", "iso_year", "iso_week"],
                    set_={"last_value": IntakeCounter.last_value + 1, "updated_at": now},
                    where=IntakeCounter.last_value < 999,
                )
                .returning(IntakeCounter.last_value)
            )
            sequence = session.scalar(statement)
        else:
            counter = session.get(IntakeCounter, (project.id, iso_year, iso_week))
            if counter is None:
                counter = IntakeCounter(
                    project_id=project.id,
                    iso_year=iso_year,
                    iso_week=iso_week,
                    last_value=1,
                    updated_at=now,
                )
                session.add(counter)
                sequence = 1
            elif counter.last_value < 999:
                counter.last_value += 1
                counter.updated_at = now
                sequence = counter.last_value
            else:
                sequence = None
        if sequence is None:
            raise RuntimeError("INTAKE_WEEKLY_LIMIT")
        return f"{project.intake_key}-{iso_year % 100:02d}W{iso_week:02d}-{int(sequence):03d}"

    @staticmethod
    def _sync_summaries(session, intake_ids: list[str]) -> dict[str, list[dict[str, object]]]:
        summaries: dict[str, list[dict[str, object]]] = {str(intake_id): [] for intake_id in intake_ids}
        if not intake_ids:
            return summaries
        rows = session.execute(
            select(SyncJob, ExternalLink, ApprovalSnapshot.created_at, ApprovalSnapshot.invalidated_at)
            .outerjoin(ExternalLink, ExternalLink.sync_job_id == SyncJob.id)
            .outerjoin(ApprovalSnapshot, ApprovalSnapshot.id == SyncJob.approval_snapshot_id)
            .where(SyncJob.intake_id.in_(intake_ids))
            .order_by(SyncJob.created_at.desc())
        ).all()
        reopened = latest_reopen_at(session, intake_ids)
        seen: set[tuple[str, str]] = set()
        for job, link, decided_at, invalidated_at in rows:
            key = (str(job.intake_id), str(job.target_system))
            if key in seen:
                continue
            seen.add(key)
            metadata = job.response_metadata if isinstance(job.response_metadata, dict) else {}
            summaries[str(job.intake_id)].append(
                {
                    "system": job.target_system,
                    "status": job.status,
                    "external_id": str(link.external_id) if link else None,
                    "sequence_id": str(metadata.get("sequence_id")) if metadata.get("sequence_id") is not None else None,
                    "external_url": link.url if link else None,
                    "error_code": job.error_code,
                    "updated_at": job.updated_at,
                    "superseded": taken_back(decided_at, invalidated_at, reopened.get(str(job.intake_id))),
                }
            )
        return summaries

    @staticmethod
    def _list_summary(
        session, total_items: int, project_id: str | None = None, allowed_project_ids: frozenset[str] | None = None,
        private: bool = False,
    ) -> IntakeListSummary:
        priority = func.coalesce(IntakeItem.approved_priority, IntakeItem.suggested_priority)
        lifecycle_stage = IntakeStore._lifecycle_stage_expression()
        intake_scope = [IntakeItem.project_id == project_id] if project_id else []
        if allowed_project_ids is not None:
            intake_scope.append(IntakeItem.project_id.in_(sorted(allowed_project_ids)))
        hidden = private_project_ids(session)
        if private or hidden:
            intake_scope.append((IntakeItem.project_id.in_(hidden) if hidden else false()) if private else IntakeItem.project_id.not_in(hidden))
        count_for = lambda value: int(
            session.scalar(
                select(func.count()).select_from(IntakeItem).where(
                    *intake_scope,
                    lifecycle_stage.not_in(("ACCEPTED", "STOPPED")),
                    priority == value,
                )
            )
            or 0
        )
        return IntakeListSummary(
            total_items=total_items,
            p0_attention=count_for("P0"),
            p1_attention=count_for("P1"),
            pending_approval=int(
                session.scalar(
                    select(func.count()).select_from(IntakeItem).where(
                        *intake_scope,
                        IntakeItem.status == "PENDING_APPROVAL",
                    )
                )
                or 0
            ),
            sync_failed=int(
                session.scalar(
                    select(func.count(func.distinct(SyncJob.intake_id)))
                    .join(IntakeItem, IntakeItem.id == SyncJob.intake_id)
                    .where(*intake_scope, SyncJob.status == "FAILED")
                )
                or 0
            ),
        )

    @staticmethod
    def _request_hash(payload: IntakeCreate) -> str:
        fields = payload.model_dump(mode="json")
        if not fields.get("needs_cto_acceptance"):
            # Keeps the hash of requests stored before the flag existed.
            fields.pop("needs_cto_acceptance", None)
        canonical = json.dumps(
            fields,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def create(self, payload: IntakeCreate, idempotency_key: str | None = None) -> IntakeOut:
        now = datetime.now(timezone.utc)
        intake_id = str(uuid4())
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest() if idempotency_key else None
        request_hash = self._request_hash(payload) if key_hash else None
        with get_session() as session:
            if key_hash:
                existing = session.scalar(
                    select(IntakeItem).where(IntakeItem.create_idempotency_key_hash == key_hash)
                )
                if existing is not None:
                    if existing.create_request_hash != request_hash:
                        raise RuntimeError("IDEMPOTENCY_KEY_REUSED")
                    return self._to_output(existing)
            project = self._resolve_project(session, payload.project_id)
            if project is None or project.status != "ACTIVE":
                raise KeyError("PROJECT_NOT_FOUND")
            public_id = self._next_public_id(session, project, now)
            item = IntakeItem(
                id=intake_id,
                public_id=public_id,
                create_idempotency_key_hash=key_hash,
                create_request_hash=request_hash,
                project_id=project.id,
                channel=payload.channel,
                item_type="UNCLEAR",
                status="NEW",
                needs_cto_acceptance=payload.needs_cto_acceptance,
                normalized_title=payload.raw_text[:80].strip() if payload.raw_text else None,
                normalized_summary=payload.raw_text.strip() if payload.raw_text else None,
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(item)
            session.add(
                SourceMessage(
                    id=str(uuid4()),
                    intake_id=intake_id,
                    channel=payload.channel,
                    sender_reference_ciphertext=encrypt(payload.sender_reference),
                    raw_content_ciphertext=encrypt(payload.raw_text),
                    received_at=payload.received_at or now,
                    purge_after=now + timedelta(days=90),
                    created_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                if key_hash:
                    existing = session.scalar(
                        select(IntakeItem).where(IntakeItem.create_idempotency_key_hash == key_hash)
                    )
                    if existing is not None:
                        if existing.create_request_hash != request_hash:
                            raise RuntimeError("IDEMPOTENCY_KEY_REUSED")
                        return self._to_output(existing)
                raise
            session.refresh(item)
            return self._to_output(item)

    def list(self, project_id: str | None = None) -> list[IntakeOut]:
        with get_session() as session:
            lifecycle_stage = self._lifecycle_stage_expression()
            query = select(IntakeItem, lifecycle_stage)
            if project_id:
                project = self._resolve_project(session, project_id)
                if project is None:
                    return []
                query = query.where(IntakeItem.project_id == project.id)
            rows = session.execute(query.order_by(IntakeItem.created_at, IntakeItem.id)).all()
            return [self._to_output(item, lifecycle_stage=stage) for item, stage in rows]

    def list_page(
        self,
        *,
        project_id: str | None = None,
        search: str | None = None,
        item_status: str | None = None,
        lifecycle_stage: IntakeLifecycleStage | None = None,
        priority: str | None = None,
        target_system: str | None = None,
        channel: str | None = None,
        from_at: datetime | None = None,
        to_at: datetime | None = None,
        limit: int = 20,
        cursor: str | None = None,
        sort_by: str = "updated_at",
        sort_order: str = "desc",
        allowed_project_ids: frozenset[str] | None = None,
        private: bool = False,
    ) -> IntakePage:
        if sort_by not in {"created_at", "updated_at"} or sort_order not in {"asc", "desc"}:
            raise ValueError("INVALID_SORT")
        with get_session() as session:
            query = select(IntakeItem)
            conditions = []
            summary_project_id: str | None = None
            if allowed_project_ids is not None:
                # A Project Owner only ever sees the granted projects, whatever filter was asked for.
                conditions.append(IntakeItem.project_id.in_(sorted(allowed_project_ids)))
            # Company lists and counts never include the private space (ADR-0031); it is read only when asked for by name.
            hidden = private_project_ids(session)
            if private or hidden:
                conditions.append((IntakeItem.project_id.in_(hidden) if hidden else false()) if private else IntakeItem.project_id.not_in(hidden))
            if project_id:
                project = self._resolve_project(session, project_id)
                if project is None:
                    return IntakePage(
                        items=[],
                        next_cursor=None,
                        limit=limit,
                        summary=IntakeListSummary(),
                    )
                summary_project_id = str(project.id)
                conditions.append(IntakeItem.project_id == project.id)
            if search:
                pattern = f"%{search.strip()}%"
                conditions.append(
                    or_(IntakeItem.public_id.ilike(pattern), IntakeItem.normalized_title.ilike(pattern))
                )
            if item_status:
                conditions.append(IntakeItem.status == item_status)
            stage_expression = self._lifecycle_stage_expression()
            if lifecycle_stage:
                conditions.append(stage_expression == lifecycle_stage)
            if priority:
                conditions.append(func.coalesce(IntakeItem.approved_priority, IntakeItem.suggested_priority) == priority)
            if target_system in ("GITLAB", "GITHUB", "PLANE"):
                conditions.append(
                    or_(
                        IntakeItem.approved_route == target_system,
                        exists(
                            select(1).where(
                                SyncJob.intake_id == IntakeItem.id,
                                SyncJob.target_system == target_system,
                            )
                        ),
                    )
                )
            elif target_system == "UNSYNCED":
                conditions.append(~exists(select(1).where(SyncJob.intake_id == IntakeItem.id)))
            elif target_system == "FAILED":
                conditions.append(
                    exists(
                        select(1).where(
                            SyncJob.intake_id == IntakeItem.id,
                            SyncJob.status == "FAILED",
                        )
                    )
                )
            if channel:
                conditions.append(IntakeItem.channel == channel)
            sort_column = getattr(IntakeItem, sort_by)
            if from_at:
                conditions.append(sort_column >= from_at)
            if to_at:
                conditions.append(sort_column <= to_at)
            if conditions:
                query = query.where(*conditions)
            total_items = int(
                session.scalar(select(func.count()).select_from(IntakeItem).where(*conditions)) or 0
            )
            if cursor:
                cursor_data = _decode_cursor(cursor)
                if cursor_data.get("sort_by") != sort_by or cursor_data.get("sort_order") != sort_order:
                    raise ValueError("INVALID_CURSOR")
                try:
                    cursor_time = datetime.fromisoformat(str(cursor_data["value"]))
                    cursor_id = str(cursor_data["id"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError("INVALID_CURSOR") from exc
                if sort_order == "desc":
                    query = query.where(
                        or_(sort_column < cursor_time, (sort_column == cursor_time) & (IntakeItem.id < cursor_id))
                    )
                else:
                    query = query.where(
                        or_(sort_column > cursor_time, (sort_column == cursor_time) & (IntakeItem.id > cursor_id))
                    )
            ordering = (sort_column.desc(), IntakeItem.id.desc()) if sort_order == "desc" else (
                sort_column.asc(),
                IntakeItem.id.asc(),
            )
            rows = list(session.scalars(query.order_by(*ordering).limit(limit + 1)).all())
            has_more = len(rows) > limit
            rows = rows[:limit]
            next_cursor = None
            if has_more and rows:
                last = rows[-1]
                next_cursor = _encode_cursor(
                    {
                        "sort_by": sort_by,
                        "sort_order": sort_order,
                        "value": getattr(last, sort_by).isoformat(),
                        "id": str(last.id),
                    }
                )
            sync_summaries = self._sync_summaries(session, [str(item.id) for item in rows])
            bands = self._context_bands(session)
            work_refs = work_service.ref_for_intakes(session, [str(item.id) for item in rows])
            issue_duplicates = self._duplicate_issues(session, [str(item.id) for item in rows])
            stages = dict(session.execute(
                select(IntakeItem.id, stage_expression).where(IntakeItem.id.in_([item.id for item in rows]))
            ).all()) if rows else {}
            return IntakePage(
                items=[self._to_output(item, sync_summaries.get(str(item.id), []), bands.get(str(item.project_id)), work_refs.get(str(item.id)),
                                       issue_duplicates.get(str(item.id)), stages.get(item.id, "RECEIVED")) for item in rows],
                next_cursor=next_cursor,
                limit=limit,
                summary=self._list_summary(session, total_items, summary_project_id, allowed_project_ids, private),
            )

    @staticmethod
    def _context_bands(session) -> dict[str, dict[str, object]]:
        """The context pack of every project as scored (FR-CTX-02): the readiness score of a request counts its band."""
        from app.models import ProjectContextSnapshot

        return {
            str(row.project_id): {"band": row.band, "score": row.score, "missing": list(row.missing or [])}
            for row in session.scalars(select(ProjectContextSnapshot)).all()
        }

    def get(self, intake_id: str) -> IntakeOut | None:
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                return None
            summaries = self._sync_summaries(session, [str(item.id)])
            lifecycle_stage = session.scalar(select(self._lifecycle_stage_expression()).where(IntakeItem.id == item.id)) or "RECEIVED"
            output = self._to_output(item, summaries.get(str(item.id), []), self._context_bands(session).get(str(item.project_id)),
                                     work_service.ref_for_intakes(session, [str(item.id)]).get(str(item.id)),
                                     self._duplicate_issues(session, [str(item.id)]).get(str(item.id)), lifecycle_stage)
            if item.duplicate_of_id:
                kept = session.get(IntakeItem, item.duplicate_of_id)
                if kept is not None:
                    output.duplicate_of = {"id": str(kept.id), "public_id": kept.public_id, "title": kept.normalized_title}
            return output

    def raw_text(self, intake_id: str) -> str | None:
        with get_session() as session:
            source = session.scalar(
                select(SourceMessage).where(SourceMessage.intake_id == intake_id).order_by(SourceMessage.created_at)
            )
            return decrypt(source.raw_content_ciphertext) if source is not None else None

    def project_of(self, intake_id: str) -> str | None:
        with get_session() as session:
            try:
                value = session.scalar(select(IntakeItem.project_id).where(IntakeItem.id == intake_id))
            except Exception:  # a malformed ID is simply not an Intake
                session.rollback()
                return None
            return str(value) if value else None

    def normalization_source(self, intake_id: str) -> dict[str, object] | None:
        """What the AI reads for an Intake: always the original text, never a previous summary.

        Re-running the analysis on its own output loses detail each time. The stored summary is only
        used once the original has been purged by retention.
        """
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                return None
            source = session.scalar(
                select(SourceMessage).where(SourceMessage.intake_id == intake_id).order_by(SourceMessage.created_at)
            )
            raw = decrypt(source.raw_content_ciphertext) if source is not None and source.raw_content_ciphertext else None
            project = session.get(Project, item.project_id)
            systems = set(session.scalars(select(ProjectIntegration.system).where(
                ProjectIntegration.project_id == item.project_id, ProjectIntegration.project_external_id.is_not(None),
            )).all())
            # Reference material from the project team (ADR-0032): what the product is, and what is already tracked.
            brief = (project.project_settings or {}).get("brief") if project and isinstance(project.project_settings, dict) else None
            brief = brief if isinstance(brief, str) and brief.strip() else None
            # An approved context pack wins (FR-CTX-05): its sections 1 and 2 stand in for the free brief.
            from app.modules.projects.context import project_context_service

            pack = project_context_service.prompt_context(str(item.project_id))
            brief_source = "PACK" if pack is not None else ("BRIEF" if brief else None)
            if pack is not None:
                brief = str(pack["text"])
            terms = sorted(set(session.scalars(select(GlossaryTerm.term).where(GlossaryTerm.project_id == item.project_id)).all()))
            issues = session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == item.project_id, GitLabIssueSnapshot.is_current.is_(True),
                GitLabIssueSnapshot.state == "opened",
            ).order_by(GitLabIssueSnapshot.external_updated_at.desc()).limit(40)).all()
            own_links = session.scalars(
                select(ExternalLink).where(ExternalLink.intake_id == item.id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")))
                .order_by(ExternalLink.created_at.desc())
            ).all()
            issue_link = own_links[0] if own_links else None
            # The Issue made from this very request is not "an issue it may duplicate".
            own_issue_ids = {str(link.external_id) for link in own_links}
            issues = [row for row in issues if str(row.issue_external_id) not in own_issue_ids]
            # What the pictures said (FR-AI-14): each transcript follows the text under a heading naming the file.
            from app.services.attachment_reader import transcripts

            notes = [
                f"[Ảnh đính kèm {row['index']}{' - ' + str(row['name']) if row.get('name') else ''}]\n{str(row['text']).strip()}"
                for row in transcripts(session, intake_id) if row.get("text") and str(row["text"]).strip()
            ]
            text = (raw or "").strip()
            if notes:
                text = "\n\n".join([text] + notes) if text else "\n\n".join(notes)
            return {
                "existing_issue": {"system": issue_link.target_system, "external_id": issue_link.external_id} if issue_link is not None else None,
                "clarifications": clarified(item.normalized_details),
                "brief": brief,
                "brief_source": brief_source,
                "terms": terms,
                "open_issues": [{"id": row.issue_external_id, "title": row.title, "labels": list(row.labels or [])} for row in issues],
                "text": text or (item.normalized_summary or ""),
                "origin": "RAW" if text else "SUMMARY",
                "project_name": project.name if project else None,
                "project_kind": project.kind if project else None,
                "channel": item.channel,
                "has_delivery": bool(systems & {"GITLAB", "GITHUB"}),
            }

    def approve(self, intake_id: str, decision: IntakeDecision, actor_id: str | None = None, source: str = "QUEUE") -> IntakeOut:
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            if item.status in ("SYNC_PENDING", "SYNCED"):
                raise RuntimeError("SYNC_LOCKED")
            if item.version != decision.expected_version:
                raise RuntimeError("STALE_VERSION")
            if item.status != "PENDING_APPROVAL" or not item.normalized_title or not item.normalized_summary:
                raise RuntimeError("REVIEW_REQUIRED")
            # "GITLAB" from the AI or an older client means "the delivery system"; a project whose
            # delivery lives in the customer's GitHub is approved for GitHub, and the other way round.
            approved_route = decision.approved_route
            if approved_route == "PLANE":
                raise RuntimeError("ROUTE_RETIRED")
            if approved_route in ("GITLAB", "GITHUB"):
                has_github = session.scalar(select(ProjectIntegration.id).where(
                    ProjectIntegration.project_id == item.project_id, ProjectIntegration.system == "GITHUB",
                    ProjectIntegration.project_external_id.is_not(None),
                )) is not None
                approved_route = "GITHUB" if has_github else "GITLAB"
            # A tracker that already holds this request's item may be approved again: the sync finds that item by
            # its marker and brings it up to date (reopened when closed) instead of making a second one (FR-APR-10).
            item.version += 1
            item.status = "APPROVED"
            item.approved_route = approved_route
            item.approved_priority = decision.approved_priority
            if decision.needs_cto_acceptance is not None and decision.needs_cto_acceptance != bool(item.needs_cto_acceptance):
                item.needs_cto_acceptance = decision.needs_cto_acceptance
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id,
                    event_type="intake.hard_flag_changed", entity_type="intake", entity_id=item.id,
                    details={"needs_cto_acceptance": item.needs_cto_acceptance, "at": "approval"}, created_at=datetime.now(timezone.utc),
                ))
            item.normalized_title = item.normalized_title or "Approved intake"
            item.updated_at = datetime.now(timezone.utc)
            approval_action_id = str(uuid4())
            snapshot_id = str(uuid4())
            snapshot_payload = {
                "intake_id": str(item.id),
                "public_id": item.public_id,
                "project_id": str(item.project_id),
                "approved_route": approved_route,
                "approved_priority": decision.approved_priority,
                "item_type": item.item_type,
                "item_version": item.version,
                "title": item.normalized_title,
                "summary": item.normalized_summary,
            }
            if has_details(item.normalized_details):
                snapshot_payload["details"] = item.normalized_details
            payload_hash = hashlib.sha256(
                json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            session.add(
                ApprovalAction(
                    id=approval_action_id,
                    intake_id=item.id,
                    actor_id=actor_id,
                    action="APPROVE",
                    reason=decision.reason,
                    item_version=item.version,
                    source=source,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                ApprovalSnapshot(
                    id=snapshot_id,
                    approval_action_id=approval_action_id,
                    intake_id=item.id,
                    project_id=item.project_id,
                    item_version=item.version,
                    approved_route=approved_route,
                    payload=snapshot_payload,
                    payload_hash=payload_hash,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                OutboxEvent(
                    id=str(uuid4()),
                    aggregate_type="intake",
                    aggregate_id=item.id,
                    project_id=item.project_id,
                    event_type="intake.approved",
                    payload={"approval_action_id": approval_action_id, "snapshot_id": snapshot_id},
                    status="NEW",
                    dedupe_key=f"approval:{snapshot_id}",
                    created_at=datetime.now(timezone.utc),
                )
            )
            # The WORK route has no tracker to sync to: the request becomes a work item on the board here and now
            # (FR-WRK-06, ADR-0066), in the same transaction as the decision.
            work_ref = None
            if approved_route == "WORK":
                work = work_service.from_intake(session, item, priority=decision.approved_priority, actor_id=actor_id)
                work_ref = {"id": str(work.id), "code": work.code, "status": work.status, "project_id": str(work.project_id)}
            session.commit()
            session.refresh(item)
            return self._to_output(item, work_item=work_ref)

    def redirect_to_delivery(self, intake_id: str, *, priority: str, reason: str, actor_id: str | None, source: str = "WORK") -> IntakeOut:
        """A request standing as approved for WORK is decided again for the delivery tracker in one step (FR-WRK-05):
        the open snapshot is invalidated and a fresh APPROVE with its own snapshot takes its place, ready to sync."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            if item.status != "APPROVED" or item.approved_route != "WORK":
                raise RuntimeError("NOT_WORK_ROUTE")
            has_github = session.scalar(select(ProjectIntegration.id).where(
                ProjectIntegration.project_id == item.project_id, ProjectIntegration.system == "GITHUB",
                ProjectIntegration.project_external_id.is_not(None),
            )) is not None
            approved_route = "GITHUB" if has_github else "GITLAB"
            for snapshot in session.scalars(select(ApprovalSnapshot).where(
                ApprovalSnapshot.intake_id == item.id, ApprovalSnapshot.invalidated_at.is_(None),
            )):
                snapshot.invalidated_at = now
            item.version += 1
            item.approved_route = approved_route
            item.approved_priority = priority
            item.updated_at = now
            approval_action_id = str(uuid4())
            snapshot_payload = {
                "intake_id": str(item.id), "public_id": item.public_id, "project_id": str(item.project_id),
                "approved_route": approved_route, "approved_priority": priority, "item_type": item.item_type,
                "item_version": item.version, "title": item.normalized_title, "summary": item.normalized_summary,
            }
            if has_details(item.normalized_details):
                snapshot_payload["details"] = item.normalized_details
            payload_hash = hashlib.sha256(
                json.dumps(snapshot_payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            session.add(ApprovalAction(
                id=approval_action_id, intake_id=item.id, actor_id=actor_id, action="APPROVE", reason=reason,
                item_version=item.version, source=source, created_at=now,
            ))
            session.add(ApprovalSnapshot(
                id=str(uuid4()), approval_action_id=approval_action_id, intake_id=item.id, project_id=item.project_id,
                item_version=item.version, approved_route=approved_route, payload=snapshot_payload, payload_hash=payload_hash, created_at=now,
            ))
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id or "unknown",
                event_type="intake.redirected", entity_type="intake", entity_id=item.id,
                details={"from": "WORK", "to": approved_route, "reason": reason}, created_at=now,
            ))
            session.commit()
            session.refresh(item)
            return self._to_output(item)

    def process(self, intake_id: str, extraction: AIExtraction | None = None) -> IntakeOut | None:
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                return None
            source_text = self.raw_text(intake_id) or ""
            normalized_text = " ".join(source_text.split())
            if extraction is not None:
                item.item_type = extraction.item_type
                item.suggested_priority = extraction.suggested_priority
                item.proposed_route = extraction.proposed_route
                item.normalized_title = extraction.normalized_title
                item.normalized_summary = extraction.normalized_summary
                item.normalized_details = proposed_details(session, item.project_id, extraction, item.normalized_details)
                item.status = "NEEDS_INFORMATION" if extraction.item_type == "UNCLEAR" else "PENDING_APPROVAL"
            else:
                lowered_text = normalized_text.lower()
                if any(keyword in lowered_text for keyword in ("bug", "lỗi", "error", "không hiển thị", "not working")):
                    item.item_type, item.suggested_priority = "BUG", "P1"
                elif any(keyword in lowered_text for keyword in ("scope", "thay đổi", "change", "thêm mới")):
                    item.item_type, item.suggested_priority = "SCOPE_CHANGE", "P1"
                elif any(keyword in lowered_text for keyword in ("cần", "need", "task", "việc")):
                    item.item_type, item.suggested_priority = "TASK", "P2"
                else:
                    item.item_type, item.suggested_priority = "UNCLEAR", "P3"
                item.proposed_route = "NEEDS_INFO" if item.item_type == "UNCLEAR" else "GITLAB"
                item.normalized_title = normalized_text[:80] or "Unclear intake"
                item.normalized_summary = normalized_text or None
                item.normalized_details = None
                item.status = "NEEDS_INFORMATION" if item.item_type == "UNCLEAR" else "PENDING_APPROVAL"
            item.version += 1
            item.updated_at = datetime.now(timezone.utc)
            session.commit()
            session.refresh(item)
            return self._to_output(item)

    # States in which a request has produced nothing outside Intake that would be orphaned by removing it.
    REMOVABLE = ("NEW", "PENDING_APPROVAL", "NEEDS_INFORMATION", "PROCESSING_FAILED", "REJECTED", "DEFERRED")

    def remove(self, intake_id: str, actor_id: str | None = None) -> dict[str, object]:
        """Delete a request for good: its source, attachments, AI results, decisions and drafts (FR-APR-11).

        Only a request with no consequence can go: not approved, never created outside, not in a plan. What stays is
        one audit line saying which request was deleted, by whom and when, without any of its content.
        """
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id).with_for_update())
            if item is None:
                raise KeyError(intake_id)
            if item.status not in self.REMOVABLE:
                raise RuntimeError("INTAKE_PROCESSING" if item.status == "PROCESSING" else "INTAKE_DECIDED")
            if session.scalar(select(func.count()).select_from(ExternalLink).where(ExternalLink.intake_id == item.id)):
                # An external work item still exists: deleting the Intake would leave it untraceable.
                raise RuntimeError("INTAKE_HAS_EXTERNAL")
            candidates = session.scalars(select(PlanningCandidate).where(PlanningCandidate.intake_id == item.id)).all()
            if any(candidate.status == "ASSIGNED" for candidate in candidates):
                raise RuntimeError("INTAKE_PLANNED")
            attachments = session.scalars(select(Attachment).where(Attachment.intake_id == item.id)).all()
            keys = [row.object_key for row in attachments if row.object_key]
            # Things that pointed at it are let go, not deleted with it.
            for row in session.scalars(select(MeetingNoteItem).where(MeetingNoteItem.intake_id == item.id)).all():
                row.intake_id = None
            for row in session.scalars(select(ReportItem).where(ReportItem.intake_id == item.id)).all():
                row.intake_id = None
            for row in session.scalars(select(IntakeItem).where(IntakeItem.duplicate_of_id == item.id)).all():
                row.duplicate_of_id = None
            for candidate in candidates:
                session.delete(candidate)
            item.current_extraction_id = None
            session.flush()
            # Children first, in an order the foreign keys accept on any database.
            # Work still queued for it (an analysis, an approval notice) must not run against a request that is gone.
            session.execute(sql_delete(OutboxEvent).where(OutboxEvent.aggregate_type == "intake", OutboxEvent.aggregate_id == item.id))
            runs = select(ProcessingRun.id).where(ProcessingRun.intake_id == item.id)
            session.execute(sql_delete(EvidenceFragment).where(EvidenceFragment.processing_run_id.in_(runs)))
            # A slot of the week plan outlives the idea that filled it.
            session.execute(sql_update(PlanSlot).where(PlanSlot.intake_id == item.id).values(intake_id=None, draft_id=None))
            session.execute(sql_update(WatchSignal).where(WatchSignal.intake_id == item.id).values(intake_id=None))
            for model in (IdeaTrack, PostDraft, ExternalLink, SyncJob, ApprovalSnapshot, ApprovalAction, DuplicateCandidate, StoredExtraction, ProcessingRun, Attachment, SourceMessage):
                session.execute(sql_delete(model).where(model.intake_id == item.id))
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id, event_type="intake.deleted",
                entity_type="intake", entity_id=item.id,
                details={"public_id": item.public_id, "status": item.status, "attachments": len(keys)}, created_at=now,
            ))
            public_id = item.public_id
            session.delete(item)
            session.commit()
        # The database no longer knows these files; remove them from storage. A file that cannot be removed now
        # is unreachable anyway and is reported in the result.
        left = 0
        if keys:
            storage = get_object_storage()
            for key in keys:
                try:
                    storage.delete(key)
                except Exception:  # noqa: BLE001 - storage being down must not undo the deletion
                    left += 1
        return {"deleted": True, "public_id": public_id, "attachments_left": left}

    def mark_duplicate(self, intake_id: str, of_ref: str, expected_version: int, actor_id: str | None = None) -> IntakeOut:
        """Close a request as a repeat of another one in the same project, keeping it so the repeat can be traced (FR-APR-12)."""
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            kept = session.scalar(select(IntakeItem).where(IntakeItem.public_id == of_ref.strip()))
            if kept is None:
                try:
                    kept = session.get(IntakeItem, of_ref.strip())
                except Exception:  # a malformed ID is simply not a request
                    session.rollback()
                    kept = None
            if kept is None or str(kept.project_id) != str(item.project_id):
                raise RuntimeError("DUPLICATE_TARGET_NOT_FOUND")
            if str(kept.id) == str(item.id) or kept.duplicate_of_id is not None:
                raise RuntimeError("DUPLICATE_TARGET_INVALID")
            if item.status in ("APPROVED", "SYNC_PENDING", "SYNCED"):
                raise RuntimeError("DECISION_LOCKED")
            kept_id, kept_public = str(kept.id), kept.public_id
        self.transition(intake_id, "REJECT", expected_version, actor_id=actor_id, reason=f"Trùng với {kept_public}")
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            item.duplicate_of_id = kept_id
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id, event_type="intake.marked_duplicate",
                entity_type="intake", entity_id=item.id, details={"of": kept_id}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
        return self.get(intake_id)

    # A confirmed duplicate_candidates row of this type closes the request as a repeat of an Issue at GitLab (FR-APR-12).
    ISSUE_DUPLICATE_TYPE = "GITLAB_ISSUE"

    @staticmethod
    def _duplicate_issues(session, intake_ids: list[str]) -> dict[str, dict[str, object]]:
        """The Issue each request was closed as a repeat of, with what the last GitLab snapshot knows about it."""
        if not intake_ids:
            return {}
        rows = session.execute(
            select(DuplicateCandidate.intake_id, DuplicateCandidate.candidate_reference, IntakeItem.project_id)
            .join(IntakeItem, IntakeItem.id == DuplicateCandidate.intake_id)
            .where(DuplicateCandidate.intake_id.in_(intake_ids), DuplicateCandidate.candidate_type == IntakeStore.ISSUE_DUPLICATE_TYPE,
                   DuplicateCandidate.decision == "CONFIRMED")
        ).all()
        if not rows:
            return {}
        snapshots = {
            (str(row.project_id), str(row.issue_external_id)): row
            for row in session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.project_id.in_({row.project_id for row in rows}),
                GitLabIssueSnapshot.issue_external_id.in_({row.candidate_reference for row in rows}),
            )).all()
        }
        output: dict[str, dict[str, object]] = {}
        for intake_id, reference, project_id in rows:
            snapshot = snapshots.get((str(project_id), str(reference)))
            output[str(intake_id)] = {
                "system": "GITLAB", "external_id": str(reference),
                "title": snapshot.title if snapshot is not None else None, "url": snapshot.web_url if snapshot is not None else None,
            }
        return output

    def mark_duplicate_issue(self, intake_id: str, issue_ref: str, expected_version: int, actor_id: str | None = None) -> IntakeOut:
        """Close a request as a repeat of an Issue that already exists at GitLab, usually one the AI pointed at (FR-APR-12).

        Nothing is written to GitLab: the Issue keeps the work, the request keeps the trace.
        """
        reference = issue_ref.strip().lstrip("#").strip()
        if not reference:
            raise RuntimeError("DUPLICATE_TARGET_NOT_FOUND")
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            snapshot = session.scalar(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == item.project_id, GitLabIssueSnapshot.issue_external_id == reference,
                GitLabIssueSnapshot.is_current.is_(True),
            ))
            if snapshot is None:
                raise RuntimeError("DUPLICATE_TARGET_NOT_FOUND")
            own = session.scalar(select(ExternalLink.id).where(
                ExternalLink.intake_id == item.id, ExternalLink.target_system == "GITLAB", ExternalLink.external_id == reference,
            ))
            if own is not None:
                raise RuntimeError("DUPLICATE_TARGET_INVALID")
            if item.status in ("APPROVED", "SYNC_PENDING", "SYNCED"):
                raise RuntimeError("DECISION_LOCKED")
            details = item.normalized_details if isinstance(item.normalized_details, dict) else {}
            suggested = any(str(row.get("id")) == reference for row in (details.get("related") or []) if isinstance(row, dict))
        self.transition(intake_id, "REJECT", expected_version, actor_id=actor_id, reason=f"Trùng với GitLab #{reference}")
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            candidate = session.scalar(select(DuplicateCandidate).where(
                DuplicateCandidate.intake_id == item.id, DuplicateCandidate.candidate_type == self.ISSUE_DUPLICATE_TYPE,
                DuplicateCandidate.candidate_reference == reference,
            ))
            if candidate is None:
                candidate = DuplicateCandidate(
                    id=str(uuid4()), intake_id=item.id, candidate_type=self.ISSUE_DUPLICATE_TYPE, candidate_reference=reference,
                    match_method="AI_SUGGESTED" if suggested else "MANUAL", score=None, created_at=datetime.now(timezone.utc),
                )
                session.add(candidate)
            candidate.decision = "CONFIRMED"
            candidate.decided_by = actor_id
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id, event_type="intake.marked_duplicate",
                entity_type="intake", entity_id=item.id, details={"issue": {"system": "GITLAB", "external_id": reference}},
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()
        return self.get(intake_id)

    def unmark_duplicate(self, intake_id: str, expected_version: int, actor_id: str | None = None) -> IntakeOut:
        with get_session() as session:
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id).with_for_update())
            if item is None:
                raise KeyError(intake_id)
            confirmed = session.scalars(select(DuplicateCandidate).where(
                DuplicateCandidate.intake_id == item.id, DuplicateCandidate.candidate_type == self.ISSUE_DUPLICATE_TYPE,
                DuplicateCandidate.decision == "CONFIRMED",
            )).all()
            if item.duplicate_of_id is None and not confirmed:
                raise RuntimeError("NOT_A_DUPLICATE")
            if item.version != expected_version:
                raise RuntimeError("STALE_VERSION")
            for candidate in confirmed:
                candidate.decision = "REVERTED"
                candidate.decided_by = actor_id
            item.duplicate_of_id = None
            item.status = "PENDING_APPROVAL" if item.normalized_title and item.normalized_summary else "NEEDS_INFORMATION"
            item.version += 1
            item.updated_at = datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id, event_type="intake.unmarked_duplicate",
                entity_type="intake", entity_id=item.id, details=None, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
        return self.get(intake_id)

    def clarify(self, intake_id: str, answers: list[dict], expected_version: int, actor_id: str | None = None) -> IntakeOut:
        """Record what the team learned about the questions AI raised. The answers reach the next analysis and the work item."""
        with get_session() as session:
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id).with_for_update())
            if item is None:
                raise KeyError(intake_id)
            if item.status in ("APPROVED", "SYNC_PENDING", "SYNCED"):
                raise RuntimeError("DECISION_LOCKED")
            if item.version != expected_version:
                raise RuntimeError("STALE_VERSION")
            details = dict(item.normalized_details) if isinstance(item.normalized_details, dict) else {}
            rows = []
            for answer in answers:
                question = " ".join(str(answer.get("question") or "").split())
                text = str(answer.get("answer") or "").strip()
                skipped = bool(answer.get("skipped")) and not text
                if question and (text or skipped):
                    rows.append({"question": question, "answer": text or None, "skipped": skipped})
            details["clarifications"] = rows
            item.normalized_details = details if has_details(details) else None
            item.version += 1
            item.updated_at = datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id, event_type="intake.clarified",
                entity_type="intake", entity_id=item.id,
                details={"answered": sum(1 for row in rows if row["answer"]), "skipped": sum(1 for row in rows if row["skipped"])},
                created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            session.refresh(item)
            return self._to_output(item)

    def ready(self, intake_id: str, expected_version: int, actor_id: str | None = None) -> IntakeOut:
        """A request that was waiting for information, or deferred, goes back to the approval queue."""
        with get_session() as session:
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id).with_for_update())
            if item is None:
                raise KeyError(intake_id)
            if item.status not in ("NEEDS_INFORMATION", "DEFERRED"):
                raise RuntimeError("NOT_WAITING")
            if item.version != expected_version:
                raise RuntimeError("STALE_VERSION")
            if not item.normalized_title or not item.normalized_summary:
                raise RuntimeError("REVIEW_REQUIRED")
            previous = item.status
            item.status = "PENDING_APPROVAL"
            item.defer_until = None
            item.version += 1
            item.updated_at = datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id, event_type="intake.ready_for_approval",
                entity_type="intake", entity_id=item.id, details={"from": previous}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            session.refresh(item)
            return self._to_output(item)

    def split(self, intake_id: str, items: list[str], expected_version: int, actor_id: str | None = None) -> tuple[IntakeOut, list[IntakeOut]]:
        """One request per ask, in the same project. The original is closed with a note naming the new ones.

        Each new request carries the ask it is about, then the original words as background, so its analysis keeps
        the details the sender gave. Nothing has been created outside yet: only undecided requests can be split.
        """
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            if item.status not in ("PENDING_APPROVAL", "NEEDS_INFORMATION"):
                raise RuntimeError("NOT_SPLITTABLE")
            if item.version != expected_version:
                raise RuntimeError("STALE_VERSION")
            project_id, channel, public_id = str(item.project_id), item.channel, item.public_id
        original_text = (self.raw_text(intake_id) or "").strip()
        children = []
        for ask in items:
            background = (
                f"\n\nNguyên văn yêu cầu gốc {public_id}, chỉ để lấy chi tiết của ý trên "
                f"(các ý khác đã được tách thành yêu cầu riêng):\n{original_text}" if original_text else ""
            )
            children.append(self.create(IntakeCreate(
                project_id=project_id, channel=channel, raw_text=f"Ý cần xử lý: {ask}{background}",
                sender_reference=f"Tách từ {public_id}",
            )))
        closed = self.transition(
            intake_id, "REJECT", expected_version, actor_id=actor_id,
            reason=f"Đã tách thành {len(children)} yêu cầu riêng: {', '.join(child.public_id for child in children)}",
        )
        with get_session() as session:
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="USER", actor_id=actor_id, event_type="intake.split",
                entity_type="intake", entity_id=intake_id,
                details={"children": [str(child.id) for child in children]}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
        return closed, children

    def reopen(self, intake_id: str, reason: str, expected_version: int, actor_id: str | None = None) -> IntakeOut:
        """Take back an approval so the request can be decided again, for example after it went to the wrong system.

        Nothing is removed outside Intake: a work item already created stays where it is and is shown as no longer
        in use. A request whose Issue is in a day plan has to leave the plan first.
        """
        reason = (reason or "").strip()
        if len(reason) < 5:
            raise ValueError("A reason is required to reopen a decision")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id).with_for_update())
            if item is None:
                raise KeyError(intake_id)
            if item.status == "SYNC_PENDING":
                raise RuntimeError("SYNC_LOCKED")
            if item.status not in ("APPROVED", "SYNCED"):
                raise RuntimeError("NOT_DECIDED")
            if item.version != expected_version:
                raise RuntimeError("STALE_VERSION")
            planned = session.scalar(
                select(PlanningAssignment.id)
                .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
                .join(ExternalLink, (ExternalLink.external_id == PlanningAssignment.gitlab_issue_external_id) & (ExternalLink.project_id == PlanningAssignment.project_id))
                .where(ExternalLink.intake_id == item.id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")), PlanningRun.status != "SUPERSEDED")
            )
            if planned is not None:
                raise RuntimeError("INTAKE_PLANNED")
            # Waiting in an open day plan: a request without a decision has no place there (FR-APR-11).
            withdrawn: list[str] = []
            for candidate, run in session.execute(
                select(PlanningCandidate, PlanningRun).join(PlanningRun, PlanningRun.id == PlanningCandidate.planning_run_id)
                .where(
                    PlanningCandidate.intake_id == item.id, PlanningCandidate.status.in_(("PENDING_TRIAGE", "READY")),
                    PlanningRun.status.in_(("DRAFT", "REVIEW_REQUIRED")),
                )
            ).all():
                candidate.status = "REJECTED"
                candidate.summary = f"Rút khỏi kế hoạch: quyết định phê duyệt được rút lại ({reason})"[:2000]
                candidate.updated_at = now
                run.status = "REVIEW_REQUIRED"
                run.version += 1
                run.updated_at = now
                withdrawn.append(str(run.id))
            for snapshot in session.scalars(select(ApprovalSnapshot).where(
                ApprovalSnapshot.intake_id == intake_id, ApprovalSnapshot.invalidated_at.is_(None),
            )):
                snapshot.invalidated_at = now
            previous = {"route": item.approved_route, "priority": item.approved_priority, "status": item.status}
            dropped_work = work_service.cancel_for_intake(session, str(item.id), reason=reason, actor_id=actor_id)
            item.approved_priority = None
            item.approved_route = None
            item.status = "PENDING_APPROVAL"
            item.version += 1
            item.updated_at = now
            session.add(ApprovalAction(
                id=str(uuid4()), intake_id=item.id, actor_id=actor_id, action="REOPEN", reason=reason,
                item_version=item.version, created_at=now,
            ))
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id or "unknown",
                event_type="intake.reopen", entity_type="intake", entity_id=item.id,
                details={"reason": reason, "previous": previous, "withdrawn_from_runs": withdrawn, "dropped_work": dropped_work}, created_at=now,
            ))
            session.commit()
            session.refresh(item)
            return self._to_output(item)

    def review(self, intake_id: str, review: IntakeReview, actor_id: str | None = None) -> IntakeOut:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id).with_for_update())
            if item is None:
                raise KeyError(intake_id)
            if item.status == "SYNC_PENDING":
                raise RuntimeError("SYNC_LOCKED")
            if item.version != review.expected_version:
                raise RuntimeError("STALE_VERSION")
            snapshots = session.scalars(
                select(ApprovalSnapshot).where(
                    ApprovalSnapshot.intake_id == intake_id,
                    ApprovalSnapshot.invalidated_at.is_(None),
                )
            ).all()
            for snapshot in snapshots:
                snapshot.invalidated_at = now
            item.normalized_title = review.normalized_title.strip()
            item.normalized_summary = review.normalized_summary.strip()
            if review.details is not None:
                # The reviewer edits where, sub-tasks and acceptance; the rest of what AI proposed stays as it was.
                kept = dict(item.normalized_details) if isinstance(item.normalized_details, dict) else {}
                merged = {**kept, **review.details.model_dump()}
                item.normalized_details = merged if has_details(merged) else None
            item.suggested_priority = review.suggested_priority
            item.proposed_route = review.proposed_route
            item.approved_priority = None
            item.approved_route = None
            item.status = "PENDING_APPROVAL"
            item.version += 1
            item.updated_at = now
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    project_id=item.project_id,
                    actor_type="USER",
                    actor_id=actor_id or "unknown",
                    event_type="intake.reviewed",
                    entity_type="intake",
                    entity_id=item.id,
                    details={"invalidated_snapshot_count": len(snapshots)},
                    created_at=now,
                )
            )
            session.commit()
            session.refresh(item)
            return self._to_output(item)

    def build_local_extraction(self, intake_id: str) -> AIExtraction | None:
        if self.get(intake_id) is None:
            return None
        normalized_text = " ".join((self.raw_text(intake_id) or "").split())
        lowered_text = normalized_text.lower()
        if any(keyword in lowered_text for keyword in ("bug", "lỗi", "error", "không hiển thị", "not working")):
            item_type, priority = "BUG", "P1"
        elif any(keyword in lowered_text for keyword in ("scope", "thay đổi", "change", "thêm mới")):
            item_type, priority = "SCOPE_CHANGE", "P1"
        elif any(keyword in lowered_text for keyword in ("cần", "need", "task", "việc")):
            item_type, priority = "TASK", "P2"
        else:
            item_type, priority = "UNCLEAR", "P3"
        return AIExtraction(
            item_type=item_type,
            suggested_priority=priority,
            proposed_route="NEEDS_INFO" if item_type == "UNCLEAR" else "GITLAB",
            normalized_title=normalized_text[:80] or "Unclear intake",
            normalized_summary=normalized_text or "No normalized content",
        )

    def transition(
        self,
        intake_id: str,
        action: str,
        expected_version: int,
        actor_id: str | None = None,
        reason: str | None = None,
        defer_until: datetime | None = None,
    ) -> IntakeOut:
        status_by_action = {
            "REJECT": "REJECTED",
            "DEFER": "DEFERRED",
            "NEEDS_INFORMATION": "NEEDS_INFORMATION",
        }
        if action not in status_by_action:
            raise ValueError(action)
        if action == "REJECT" and not reason:
            raise ValueError("A rejection reason is required")
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            if item.status in ("SYNC_PENDING", "SYNCED"):
                raise RuntimeError("SYNC_LOCKED")
            if item.version != expected_version:
                raise RuntimeError("STALE_VERSION")
            item.version += 1
            item.status = status_by_action[action]
            item.defer_until = defer_until if action == "DEFER" else None
            item.updated_at = datetime.now(timezone.utc)
            action_id = str(uuid4())
            session.add(
                ApprovalAction(
                    id=action_id,
                    intake_id=item.id,
                    actor_id=actor_id,
                    action=action,
                    reason=reason,
                    item_version=item.version,
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    project_id=item.project_id,
                    actor_type="USER",
                    actor_id=actor_id or "unknown",
                    event_type=f"intake.{action.lower()}",
                    entity_type="intake",
                    entity_id=item.id,
                    details={"reason": reason} if reason else {},
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.add(
                OutboxEvent(
                    id=str(uuid4()),
                    aggregate_type="intake",
                    aggregate_id=item.id,
                    project_id=item.project_id,
                    event_type=f"intake.{action.lower()}",
                    payload={"approval_action_id": action_id},
                    status="NEW",
                    dedupe_key=f"decision:{action_id}",
                    created_at=datetime.now(timezone.utc),
                )
            )
            session.commit()
            session.refresh(item)
            return self._to_output(item)


intake_store = IntakeStore()


def _encode_cursor(payload: dict[str, str]) -> str:
    encoded = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=")
    signature = hmac.new(get_settings().secret_key.encode("utf-8"), encoded, hashlib.sha256).digest()
    return f"{encoded.decode('ascii')}.{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def _decode_cursor(cursor: str) -> dict[str, str]:
    try:
        encoded_text, signature_text = cursor.split(".", 1)
        encoded = encoded_text.encode("ascii")
        expected = hmac.new(get_settings().secret_key.encode("utf-8"), encoded, hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature_text + "=" * (-len(signature_text) % 4))
        if not hmac.compare_digest(expected, actual):
            raise ValueError("INVALID_CURSOR")
        decoded = base64.urlsafe_b64decode(encoded_text + "=" * (-len(encoded_text) % 4))
        value = json.loads(decoded)
        if not isinstance(value, dict):
            raise ValueError("INVALID_CURSOR")
        return value
    except (UnicodeError, ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("INVALID_CURSOR") from exc
