from __future__ import annotations

from datetime import datetime
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import select

from app.api.errors import api_exception
from app.modules.identity.service import identity_service
from app.schemas import IntakeAction, IntakeCreate, IntakeDecision, IntakeJourneyOut, IntakeLifecycleStage, IntakeOut, IntakePage, IntakeReopenRequest, IntakeReview, PipelineStageOut, PipelineStatusOut, IntakeSplit, IntakeSplitOut, IntakeClarify, IntakeReady, IntakeDeleted, IntakeDuplicate, IntakeDuplicateIssue, IntakeFixHints, IntakeHardFlag, IntakeWorkLogCreate, IntakeWorkLogOut, IntakeWorkLogReview
from app.modules.intake.worklog import WorkLogError, work_log_service
from app.services.intake_service import intake_store
from app.services.processing_repository import processing_repository
from app.services.attachment_service import save_attachment
from app.api.security import AuthContext, ensure_project, get_current_user_strict, require_member
from app.modules.intake.journey import intake_journey
from app.modules.projects.service import project_catalog_service

router = APIRouter(prefix="/intakes", tags=["intakes"])


def intake_member(intake_id: str, context: AuthContext = Depends(require_member)) -> AuthContext:
    """The CTO, or a Project Owner of the project this Intake belongs to. Anything else is "not found"."""
    project_id = intake_store.project_of(intake_id)
    if project_id is not None:
        ensure_project(context, project_id, "Intake")
    return context


def require_roles(*allowed_roles: str):
    def dependency(context: AuthContext = Depends(get_current_user_strict)) -> AuthContext:
        if context.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this action",
            )
        return context

    return dependency


@router.post(
    "",
    response_model=IntakeOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-INT-01", "FR-INT-02", "FR-PRJ-05"]},
)
async def create_intake(
    payload: IntakeCreate,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", min_length=8, max_length=200),
    context: AuthContext = Depends(require_member),
) -> IntakeOut:
    project = project_catalog_service.get_project(payload.project_id) if payload.project_id else None
    if project is None or not context.allows(project.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found or inactive")
    if not payload.raw_text and not payload.sender_reference:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="raw_text or sender_reference is required",
        )
    if payload.needs_cto_acceptance and context.role != "CTO":
        payload = payload.model_copy(update={"needs_cto_acceptance": False})
    try:
        return intake_store.create(payload, idempotency_key=idempotency_key)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found or inactive") from exc
    except RuntimeError as exc:
        if str(exc) == "IDEMPOTENCY_KEY_REUSED":
            raise api_exception(
                status.HTTP_409_CONFLICT,
                "IDEMPOTENCY_KEY_REUSED",
                "Idempotency-Key was already used with a different request",
            ) from exc
        raise


@router.get(
    "",
    response_model=IntakePage,
    openapi_extra={"x-requirement-ids": ["FR-UI-02", "FR-PRJ-02", "FR-PRJ-05"]},
)
async def list_intakes(
    project_id: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=255),
    item_status: str | None = Query(default=None, alias="status"),
    lifecycle_stage: IntakeLifecycleStage | None = Query(default=None, alias="stage"),
    priority: Literal["P0", "P1", "P2", "P3"] | None = Query(default=None),
    target_system: Literal["GITLAB", "GITHUB", "PLANE", "UNSYNCED", "FAILED"] | None = Query(default=None),
    channel: str | None = Query(default=None),
    from_at: datetime | None = Query(default=None, alias="from"),
    to_at: datetime | None = Query(default=None, alias="to"),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
    sort_by: Literal["created_at", "updated_at"] = Query(default="updated_at"),
    sort_order: Literal["asc", "desc"] = Query(default="desc"),
    context: AuthContext = Depends(require_member),
) -> IntakePage:
    try:
        return intake_store.list_page(
            allowed_project_ids=context.project_ids,
            project_id=project_id,
            search=search,
            item_status=item_status,
            lifecycle_stage=lifecycle_stage,
            priority=priority,
            target_system=target_system,
            channel=channel,
            from_at=from_at,
            to_at=to_at,
            limit=limit,
            cursor=cursor,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except ValueError as exc:
        raise api_exception(status.HTTP_400_BAD_REQUEST, "INVALID_CURSOR", "Cursor is invalid or does not match sorting") from exc


@router.get("/{intake_id}", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-INT-02", "FR-APR-01"]})
async def get_intake(intake_id: str, _: AuthContext = Depends(intake_member)) -> IntakeOut:
    item = intake_store.get(intake_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    return item


@router.get("/{intake_id}/github-issue-link", openapi_extra={"x-requirement-ids": ["FR-INTG-20"]})
async def github_issue_link(intake_id: str, _: AuthContext = Depends(intake_member)) -> dict:
    """A pre-filled GitHub "new issue" page built from normalized content only (FR-INTG-20)."""
    from app.modules.integrations.issue_link import IssueLinkError, new_issue_link

    try:
        return new_issue_link(intake_id)
    except IssueLinkError as error:
        code = status.HTTP_404_NOT_FOUND if error.code == "NOT_FOUND" else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise api_exception(code, error.code, error.message) from error


@router.get(
    "/{intake_id}/journey", response_model=IntakeJourneyOut,
    openapi_extra={"x-requirement-ids": ["FR-UI-09", "FR-ID-07"]},
)
async def get_intake_journey(intake_id: str, _: AuthContext = Depends(intake_member)) -> IntakeJourneyOut:
    journey = intake_journey(intake_id)
    if journey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    return IntakeJourneyOut.model_validate(journey)


@router.get("/{intake_id}/runs", openapi_extra={"x-requirement-ids": ["FR-AI-03", "FR-APR-01"]})
async def list_processing_runs(
    intake_id: str,
    _: AuthContext = Depends(intake_member),
) -> list[dict[str, object]]:
    if intake_store.get(intake_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    return [
        {
            "id": run.id,
            "run_type": run.run_type,
            "status": run.status,
            "attempt": run.attempt,
            "worker_id": run.worker_id,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "error_code": run.error_code,
        }
        for run in processing_repository.list_runs(intake_id)
    ]


@router.get("/{intake_id}/pipeline", response_model=PipelineStatusOut, openapi_extra={"x-requirement-ids": ["FR-AI-03", "FR-UI-01"]})
async def get_pipeline_status(
    intake_id: str,
    _: AuthContext = Depends(intake_member),
) -> PipelineStatusOut:
    item = intake_store.get(intake_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    runs = processing_repository.list_runs(intake_id)
    stages = [
        PipelineStageOut(
            run_id=run.id,
            stage=run.stage or run.run_type,
            run_type=run.run_type,
            status=run.status,
            attempt=run.attempt,
            worker_id=run.worker_id,
            retryable=run.retryable,
            queued_at=run.created_at,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error_code=run.error_code,
        )
        for run in runs
    ]
    if not stages:
        overall_state = "NOT_STARTED"
    elif any(stage.status == "FAILED" for stage in stages):
        overall_state = "FAILED"
    elif all(stage.status == "SUCCEEDED" for stage in stages):
        overall_state = "SUCCEEDED"
    elif any(stage.status == "RUNNING" for stage in stages):
        overall_state = "RUNNING"
    else:
        overall_state = "QUEUED"
    return PipelineStatusOut(
        intake_id=item.id,
        public_id=item.public_id,
        intake_status=item.status,
        overall_state=overall_state,
        stages=stages,
    )


@router.get("/{intake_id}/raw", openapi_extra={"x-requirement-ids": ["FR-ID-04", "NFR-SEC-03"]})
async def get_raw_intake(
    intake_id: str,
    context: AuthContext = Depends(intake_member),
) -> dict:
    item = intake_store.get(intake_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    if not identity_service.can_access_raw(context.subject):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Raw access is not granted")
    from app.db import get_session
    from app.services.attachment_reader import transcripts

    with get_session() as session:
        files = transcripts(session, intake_id)
    return {"id": item.id, "raw_text": intake_store.raw_text(intake_id), "subject": context.subject, "attachments": files}


@router.get("/{intake_id}/attachments", openapi_extra={"x-requirement-ids": ["FR-INT-03", "FR-AI-14"]})
async def list_attachments(intake_id: str, _: AuthContext = Depends(intake_member)) -> list[dict]:
    """The files on a request and whether each was read; the transcript itself is in the raw view (CTO)."""
    from app.db import get_session
    from app.services.attachment_reader import transcripts

    with get_session() as session:
        rows = transcripts(session, intake_id)
    return [{key: value for key, value in row.items() if key != "text"} for row in rows]


@router.get(
    "/{intake_id}/attachments/{attachment_id}/file",
    openapi_extra={"x-requirement-ids": ["FR-INT-03", "FR-AI-14"]},
)
async def get_attachment_file(
    intake_id: str,
    attachment_id: str,
    _: AuthContext = Depends(intake_member),
) -> Response:
    """Return an authorized attachment as a download-safe response for UI preview or download."""
    from app.db import get_session
    from app.models import Attachment
    from app.services.object_storage import get_object_storage
    from app.services.raw_crypto import decrypt

    with get_session() as session:
        row = session.scalar(
            select(Attachment).where(
                Attachment.id == attachment_id,
                Attachment.intake_id == intake_id,
                Attachment.purged_at.is_(None),
            )
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
        object_key = row.object_key
        mime_type = row.mime_type or "application/octet-stream"
        original_name = decrypt(row.original_name_ciphertext) or "attachment"

    try:
        content = get_object_storage().get(object_key)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found") from exc

    ascii_name = "".join(character if 32 <= ord(character) < 127 and character not in {'"', "/", "\\"} else "_" for character in original_name)
    disposition = f'attachment; filename="{ascii_name or "attachment"}"'
    if not original_name.isascii():
        disposition += f"; filename*=UTF-8''{quote(original_name, safe='')}"
    return Response(
        content=content,
        media_type=mime_type,
        headers={
            "Content-Disposition": disposition,
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{intake_id}/attachments/{attachment_id}/read", status_code=status.HTTP_202_ACCEPTED, openapi_extra={"x-requirement-ids": ["FR-AI-14"]})
async def reread_attachment(intake_id: str, attachment_id: str, _: AuthContext = Depends(intake_member)) -> dict:
    """Read a file again: after a model outage, a rejected check that was fixed on the server, or just to be sure."""
    from app.db import get_session
    from app.models import Attachment
    from app.services.attachment_service import queue_read

    with get_session() as session:
        row = session.scalar(select(Attachment).where(Attachment.id == attachment_id, Attachment.intake_id == intake_id))
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attachment not found")
        row.ocr_status, row.ocr_error = "NONE", None
        session.commit()
    return {"id": attachment_id, "queued": queue_read(attachment_id, intake_id)}


@router.post("/{intake_id}/attachments", status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-INT-03", "FR-INT-04", "FR-AI-09"]})
async def upload_attachment(
    intake_id: str,
    file: UploadFile = File(...),
    _: AuthContext = Depends(intake_member),
) -> dict[str, object]:
    return await save_attachment(intake_id, file)


@router.patch(
    "/{intake_id}/review",
    response_model=IntakeOut,
    openapi_extra={"x-requirement-ids": ["FR-APR-02", "FR-APR-03", "FR-APR-06"]},
)
async def review_intake(
    intake_id: str,
    review: IntakeReview,
    context: AuthContext = Depends(intake_member),
) -> IntakeOut:
    try:
        return intake_store.review(intake_id, review, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        if str(exc) == "SYNC_LOCKED":
            raise api_exception(
                status.HTTP_409_CONFLICT,
                "SYNC_LOCKED",
                "A queued or completed external sync locks the approved snapshot",
            ) from exc
        raise api_exception(
            status.HTTP_409_CONFLICT,
            "STALE_VERSION",
            "Intake changed; reload it before saving the review",
        ) from exc


@router.post("/{intake_id}/process", response_model=IntakeOut, status_code=status.HTTP_202_ACCEPTED, openapi_extra={"x-requirement-ids": ["FR-AI-01", "FR-AI-02", "FR-AI-03"]})
async def process_intake(
    intake_id: str,
    _: AuthContext = Depends(intake_member),
) -> IntakeOut:
    try:
        result = processing_repository.enqueue_normalization(intake_id)
    except RuntimeError as exc:
        if str(exc) == "SYNC_LOCKED":
            raise api_exception(
                status.HTTP_409_CONFLICT,
                "SYNC_LOCKED",
                "A queued or completed external sync cannot be reprocessed",
            ) from exc
        raise
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    item = intake_store.get(intake_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    return item


@router.post("/{intake_id}/approve", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-03", "FR-APR-04", "FR-SYNC-01"]})
async def approve_intake(
    intake_id: str,
    decision: IntakeDecision,
    context: AuthContext = Depends(intake_member),
) -> IntakeOut:
    item = intake_store.get(intake_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    if decision.expected_version != item.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stale version; reload intake before approving",
        )
    if not context.can_approve:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval is not granted")
    if decision.needs_cto_acceptance is not None and context.role != "CTO":
        decision = decision.model_copy(update={"needs_cto_acceptance": None})
    try:
        return intake_store.approve(intake_id, decision, actor_id=context.user_id)
    except RuntimeError as exc:
        if str(exc) == "SYNC_LOCKED":
            raise api_exception(
                status.HTTP_409_CONFLICT,
                "SYNC_LOCKED",
                "A queued or completed external sync cannot be approved again",
            ) from exc
        if str(exc) == "REVIEW_REQUIRED":
            raise api_exception(
                status.HTTP_409_CONFLICT,
                "REVIEW_REQUIRED",
                "Save a normalized review before approving external sync",
            ) from exc
        if str(exc) == "ROUTE_RETIRED":
            raise api_exception(
                status.HTTP_409_CONFLICT,
                "ROUTE_RETIRED",
                "Plane is historical and cannot receive new work",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stale version; reload intake before approving",
        ) from exc


async def _transition_intake(intake_id: str, action: str, payload: IntakeAction, context: AuthContext) -> IntakeOut:
    try:
        return intake_store.transition(
            intake_id,
            action,
            payload.expected_version,
            actor_id=context.user_id,
            reason=payload.reason,
            defer_until=payload.defer_until,
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        if str(exc) == "SYNC_LOCKED":
            raise api_exception(
                status.HTTP_409_CONFLICT,
                "SYNC_LOCKED",
                "A queued or completed external sync locks this decision",
            ) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stale version; reload intake before acting") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.post("/{intake_id}/reopen", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-08", "FR-ID-07"]})
async def reopen_intake(intake_id: str, payload: IntakeReopenRequest, context: AuthContext = Depends(intake_member)) -> IntakeOut:
    try:
        return intake_store.reopen(intake_id, payload.reason, payload.expected_version, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        messages = {
            "SYNC_LOCKED": "A sync is in progress; wait for it to finish before reopening",
            "NOT_DECIDED": "Only an approved or synced Intake can be reopened",
            "INTAKE_PLANNED": "The Issue of this Intake is in a day plan; remove it from the plan first",
        }
        code = str(exc)
        if code in messages:
            raise api_exception(status.HTTP_409_CONFLICT, code, messages[code]) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Stale version; reload intake before acting") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _decision_error(exc: RuntimeError) -> HTTPException:
    codes = {
        "INTAKE_PROCESSING": "AI is still reading this request; try again when it is done",
        "INTAKE_DECIDED": "An approved request cannot be deleted; take the approval back first",
        "INTAKE_HAS_EXTERNAL": "A work item made from this request exists outside Intake, so it cannot be deleted",
        "INTAKE_PLANNED": "This request is in a day plan; remove it from the plan first",
        "DUPLICATE_TARGET_NOT_FOUND": "The request to keep was not found in this project",
        "DUPLICATE_TARGET_INVALID": "Choose another request: not this one, and not one that is itself a duplicate",
        "NOT_A_DUPLICATE": "This request is not marked as a duplicate",
        "SYNC_LOCKED": "A queued or completed external sync cannot be changed",
        "STALE_VERSION": "Stale version; reload intake first",
        "DECISION_LOCKED": "The request is already approved; take the approval back before changing it",
        "NOT_WAITING": "Only a request that is waiting for information or deferred can go back to the queue",
        "REVIEW_REQUIRED": "The request needs a title and a summary first",
    }
    code = str(exc)
    if code in codes:
        return api_exception(status.HTTP_409_CONFLICT, code, codes[code])
    raise exc


@router.delete("/{intake_id}", response_model=IntakeDeleted, openapi_extra={"x-requirement-ids": ["FR-APR-11", "NFR-SEC-03"]})
async def delete_intake(intake_id: str, context: AuthContext = Depends(intake_member)) -> IntakeDeleted:
    """Delete a request that has had no consequence. Its content is gone for good; one audit line remains."""
    if not context.can_approve:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval is not granted")
    try:
        return IntakeDeleted.model_validate(intake_store.remove(intake_id, actor_id=context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        raise _decision_error(exc) from exc


@router.post("/{intake_id}/duplicate", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-12"]})
async def mark_intake_duplicate(intake_id: str, payload: IntakeDuplicate, context: AuthContext = Depends(intake_member)) -> IntakeOut:
    if not context.can_approve:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval is not granted")
    try:
        return intake_store.mark_duplicate(intake_id, payload.of, payload.expected_version, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        raise _decision_error(exc) from exc


@router.post("/{intake_id}/duplicate-issue", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-12"]})
async def mark_intake_duplicate_of_issue(intake_id: str, payload: IntakeDuplicateIssue, context: AuthContext = Depends(intake_member)) -> IntakeOut:
    """Close the request as a repeat of an Issue that already exists at GitLab; DELETE /duplicate takes it back."""
    if not context.can_approve:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval is not granted")
    try:
        return intake_store.mark_duplicate_issue(intake_id, payload.issue, payload.expected_version, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        raise _decision_error(exc) from exc


@router.delete("/{intake_id}/duplicate", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-12"]})
async def unmark_intake_duplicate(intake_id: str, expected_version: int = Query(..., ge=1), context: AuthContext = Depends(intake_member)) -> IntakeOut:
    if not context.can_approve:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval is not granted")
    try:
        return intake_store.unmark_duplicate(intake_id, expected_version, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        raise _decision_error(exc) from exc


@router.put("/{intake_id}/clarifications", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-10", "FR-AI-12", "NFR-SEC-03"]})
async def clarify_intake(intake_id: str, payload: IntakeClarify, context: AuthContext = Depends(intake_member)) -> IntakeOut:
    """Save the answers to the questions AI raised; optionally have AI read the request again with them."""
    try:
        saved = intake_store.clarify(intake_id, [row.model_dump() for row in payload.answers], payload.expected_version, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        raise _decision_error(exc) from exc
    if payload.reanalyse:
        processing_repository.enqueue_normalization(intake_id)
        return intake_store.get(intake_id) or saved
    return saved


@router.post("/{intake_id}/ready", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-10", "FR-APR-05"]})
async def ready_intake(intake_id: str, payload: IntakeReady, context: AuthContext = Depends(intake_member)) -> IntakeOut:
    if not context.can_approve:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval is not granted")
    try:
        return intake_store.ready(intake_id, payload.expected_version, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        raise _decision_error(exc) from exc


@router.post("/{intake_id}/split", response_model=IntakeSplitOut, openapi_extra={"x-requirement-ids": ["FR-APR-09", "FR-AI-12"]})
async def split_intake(intake_id: str, payload: IntakeSplit, context: AuthContext = Depends(intake_member)) -> IntakeSplitOut:
    """Make one request per ask and close the original. The new requests are analysed like any other."""
    if not context.can_approve:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Approval is not granted")
    try:
        original, children = intake_store.split(intake_id, payload.items, payload.expected_version, actor_id=context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except RuntimeError as exc:
        if str(exc) == "NOT_SPLITTABLE":
            raise api_exception(status.HTTP_409_CONFLICT, "NOT_SPLITTABLE", "Only a request that is still waiting for a decision can be split") from exc
        if str(exc) == "STALE_VERSION":
            raise api_exception(status.HTTP_409_CONFLICT, "STALE_VERSION", "Stale version; reload intake before splitting") from exc
        raise
    for child in children:
        processing_repository.enqueue_normalization(str(child.id))
    return IntakeSplitOut(original=original, children=[intake_store.get(str(child.id)) or child for child in children])


@router.post("/{intake_id}/reject", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-05"]})
async def reject_intake(
    intake_id: str,
    payload: IntakeAction,
    context: AuthContext = Depends(intake_member),
) -> IntakeOut:
    return await _transition_intake(intake_id, "REJECT", payload, context)


@router.post("/{intake_id}/defer", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-05"]})
async def defer_intake(
    intake_id: str,
    payload: IntakeAction,
    context: AuthContext = Depends(intake_member),
) -> IntakeOut:
    return await _transition_intake(intake_id, "DEFER", payload, context)


@router.post("/{intake_id}/needs-information", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-APR-05"]})
async def request_information(
    intake_id: str,
    payload: IntakeAction,
    context: AuthContext = Depends(intake_member),
) -> IntakeOut:
    return await _transition_intake(intake_id, "NEEDS_INFORMATION", payload, context)


# ---- What was done about the request, and the hints for whoever does it (FR-MCP-03) -----------------------------

def _work_log_error(error: WorkLogError) -> None:
    conflict = error.code == "ALREADY_REVIEWED"
    raise api_exception(status.HTTP_409_CONFLICT if conflict else status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error))


@router.get("/{intake_id}/work-log", response_model=list[IntakeWorkLogOut], openapi_extra={"x-requirement-ids": ["FR-MCP-03", "FR-ID-08"]})
async def list_work_log(intake_id: str, context: AuthContext = Depends(intake_member)) -> list[IntakeWorkLogOut]:
    if intake_store.get(intake_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found")
    return [IntakeWorkLogOut.model_validate(row) for row in work_log_service.list(intake_id)]


@router.post("/{intake_id}/work-log", response_model=IntakeWorkLogOut, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-MCP-03", "FR-ID-08"]})
async def add_work_log(intake_id: str, payload: IntakeWorkLogCreate, context: AuthContext = Depends(intake_member)) -> IntakeWorkLogOut:
    """A person logs by hand what they did; an agent uses the MCP tool log_work, which lands here too."""
    try:
        return IntakeWorkLogOut.model_validate(work_log_service.add(
            intake_id, summary=payload.summary, details=payload.details.model_dump(), actor_id=context.user_id, agent_name=payload.agent_name,
        ))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    except WorkLogError as error:
        _work_log_error(error)


@router.post("/{intake_id}/work-log/{log_id}/review", response_model=IntakeWorkLogOut, openapi_extra={"x-requirement-ids": ["FR-MCP-03", "FR-ID-08"]})
async def review_work_log(intake_id: str, log_id: str, payload: IntakeWorkLogReview, context: AuthContext = Depends(intake_member)) -> IntakeWorkLogOut:
    """The CTO checked the work and deployed it, or sends it back with a note."""
    if context.role != "CTO":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the CTO reviews work")
    try:
        return IntakeWorkLogOut.model_validate(work_log_service.review(intake_id, log_id, decision=payload.decision, note=payload.note, actor_id=context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work log entry not found") from exc
    except WorkLogError as error:
        _work_log_error(error)


@router.patch("/{intake_id}/hard-flag", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-PLAN-39"]})
async def set_hard_flag(intake_id: str, payload: IntakeHardFlag, context: AuthContext = Depends(intake_member)) -> IntakeOut:
    if context.role != "CTO":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the CTO marks a request as hard")
    try:
        work_log_service.set_hard_flag(intake_id, payload.needs_cto_acceptance, context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    return intake_store.get(intake_id)


@router.patch("/{intake_id}/fix-hints", response_model=IntakeOut, openapi_extra={"x-requirement-ids": ["FR-MCP-03", "FR-ID-08"]})
async def set_fix_hints(intake_id: str, payload: IntakeFixHints, context: AuthContext = Depends(intake_member)) -> IntakeOut:
    try:
        work_log_service.set_fix_hints(intake_id, payload.fix_hints, context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc
    return intake_store.get(intake_id)
