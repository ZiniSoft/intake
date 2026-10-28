from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response

from app.api.security import AuthContext, ensure_project, require_member
from app.modules.projects.service import project_catalog_service
from app.modules.meetings.service import MAX_AUDIO_CHUNK_BYTES, MeetingError, meeting_service
from app.schemas import (
    GlossaryTermCreate,
    GlossaryTermOut,
    IntakeCreate,
    MeetingCreate,
    MeetingDeleted,
    MeetingDetailOut,
    MeetingNoteWorkCreate,
    MeetingNoteWorkOut,
    MeetingNoteBulkIntake,
    MeetingNoteBulkIntakeOut,
    MeetingNoteItemUpdate,
    MeetingOut,
    MeetingProjectUpdate,
    MeetingFinish,
    MeetingRename,
    MeetingSpeakersUpdate,
    MeetingSummaryUpdate,
)
from sqlalchemy import select

from app.services.intake_service import intake_store
from app.services.processing_repository import processing_repository
from app.services.speech_provider import EXTENSIONS


router = APIRouter(prefix="/meetings", tags=["meetings"])

ERROR_STATUS = {
    "MEETING_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "NOTE_ITEM_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "AUDIO_NOT_AVAILABLE": status.HTTP_404_NOT_FOUND,
    "MEETING_CAPTURE_DISABLED": status.HTTP_409_CONFLICT,
    "MEETING_NOT_RECORDING": status.HTTP_409_CONFLICT,
    "AUDIO_CHUNK_OUT_OF_ORDER": status.HTTP_409_CONFLICT,
    "GLOSSARY_TERM_EXISTS": status.HTTP_409_CONFLICT,
    "NOTE_ITEM_HAS_INTAKE": status.HTTP_409_CONFLICT,
    "MEETING_HAS_NO_TRANSCRIPT": status.HTTP_409_CONFLICT,
    "MEETING_BUSY": status.HTTP_409_CONFLICT,
    "TRANSCRIPT_RETRY_NOT_ALLOWED": status.HTTP_409_CONFLICT,
    "AUDIO_CHUNK_SIZE_INVALID": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
    "AUDIO_TOO_LARGE": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
}


def meeting_member(meeting_id: str, context: AuthContext = Depends(require_member)) -> AuthContext:
    """The CTO, or a Project Owner of the meeting's project. A meeting without a project is the CTO's only."""
    exists, project_id = meeting_service.project_of(meeting_id)
    if exists and context.project_ids is not None:
        ensure_project(context, project_id, "Meeting")
    return context


def _project_in_scope(context: AuthContext, project_ref: str | None) -> None:
    """A Project Owner may only name a granted project; naming none is not allowed for them either."""
    if context.project_ids is None:
        return
    project = project_catalog_service.get_project(project_ref) if project_ref else None
    ensure_project(context, project.id if project else None, "Project")


def _raise(error: MeetingError) -> None:
    raise HTTPException(
        status_code=ERROR_STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_ENTITY),
        detail={"code": error.code, "message": error.message},
    ) from error


@router.get("/glossary", response_model=list[GlossaryTermOut], openapi_extra={"x-requirement-ids": ["FR-REC-07"]})
async def list_glossary(project_id: str | None = Query(default=None), context: AuthContext = Depends(require_member)) -> list[GlossaryTermOut]:
    if project_id:
        _project_in_scope(context, project_id)
    try:
        return [GlossaryTermOut.model_validate(row) for row in meeting_service.glossary(project_id)]
    except MeetingError as error:
        _raise(error)


@router.post(
    "/glossary", response_model=GlossaryTermOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-REC-07"]},
)
async def add_glossary_term(payload: GlossaryTermCreate, context: AuthContext = Depends(require_member)) -> GlossaryTermOut:
    # Shared terms affect every project's transcription, so only the CTO manages them.
    if payload.project_id is None and context.project_ids is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only CTO may change shared terms")
    _project_in_scope(context, payload.project_id)
    try:
        return GlossaryTermOut.model_validate(meeting_service.add_term(payload.term, payload.project_id))
    except MeetingError as error:
        _raise(error)


@router.delete("/glossary/{term_id}", openapi_extra={"x-requirement-ids": ["FR-REC-07"]})
async def remove_glossary_term(term_id: str, context: AuthContext = Depends(require_member)) -> dict[str, bool]:
    exists, term_project = meeting_service.term_project(term_id)
    if exists and context.project_ids is not None:
        if term_project is None:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only CTO may change shared terms")
        ensure_project(context, term_project, "Term")
    if not meeting_service.remove_term(term_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Glossary term not found")
    return {"removed": True}


@router.post(
    "", response_model=MeetingOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-REC-01", "FR-REC-02", "FR-REC-11", "NFR-SEC-03"]},
)
async def start_meeting(payload: MeetingCreate, context: AuthContext = Depends(require_member)) -> MeetingOut:
    _project_in_scope(context, payload.project_id)
    try:
        if payload.continues_meeting_id:
            exists, previous_project = meeting_service.project_of(payload.continues_meeting_id)
            if not exists or (context.project_ids is not None and previous_project not in context.project_ids):
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Meeting not found")
        return MeetingOut.model_validate(meeting_service.create(
            project_ref=payload.project_id, title=payload.title, source=payload.source, actor_id=context.user_id, kind=payload.kind,
            continues_meeting_id=payload.continues_meeting_id,
        ))
    except MeetingError as error:
        _raise(error)


@router.get("", response_model=list[MeetingOut], openapi_extra={"x-requirement-ids": ["FR-REC-06", "FR-REC-11"]})
async def list_meetings(
    include_dictation: bool = Query(default=False), context: AuthContext = Depends(require_member),
) -> list[MeetingOut]:
    # Recordings spoken to fill an Intake are sources, not meetings: listed only when asked for.
    return [MeetingOut.model_validate(row) for row in meeting_service.list(context.project_ids, include_dictation)]


@router.get(
    "/{meeting_id}", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-04", "FR-REC-06", "FR-ID-04", "NFR-SEC-03"]},
)
async def get_meeting(meeting_id: str, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.detail(meeting_id, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.post(
    "/{meeting_id}/audio", response_model=MeetingOut,  # FR-REC-14: retried and resumed uploads land here
    openapi_extra={"x-requirement-ids": ["FR-REC-02", "FR-REC-03"]},
)
async def upload_meeting_audio(
    meeting_id: str,
    sequence: int = Query(..., ge=0, le=100_000),
    file: UploadFile = File(...),
    _: AuthContext = Depends(meeting_member),
) -> MeetingOut:
    content = await file.read(MAX_AUDIO_CHUNK_BYTES + 1)
    try:
        return MeetingOut.model_validate(meeting_service.append_audio(
            meeting_id, sequence, content, file.content_type or "application/octet-stream",
        ))
    except MeetingError as error:
        _raise(error)


@router.get(
    "/{meeting_id}/audio",
    openapi_extra={"x-requirement-ids": ["FR-REC-03", "FR-REC-06", "FR-ID-04", "NFR-SEC-03"]},
    responses={200: {"content": {"audio/webm": {}}}},
)
async def download_meeting_audio(
    meeting_id: str, download: bool = Query(False), context: AuthContext = Depends(meeting_member),
) -> Response:
    try:
        content, content_type = meeting_service.audio(meeting_id, context.user_id)
    except MeetingError as error:
        _raise(error)
    disposition = f"attachment; filename=meeting-{meeting_id[:8]}.{EXTENSIONS.get(content_type, 'webm')}" if download else "inline; filename=meeting-audio"
    return Response(content=content, media_type=content_type, headers={
        "Cache-Control": "no-store", "Content-Disposition": disposition, "X-Content-Type-Options": "nosniff",
    })


@router.post(
    "/{meeting_id}/finish", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-02", "FR-REC-14", "NFR-SEC-03"]},
)
async def finish_meeting(meeting_id: str, payload: MeetingFinish | None = None, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.finish(
            meeting_id, context.user_id, duration_seconds=payload.duration_seconds if payload is not None else None,
        ))
    except MeetingError as error:
        _raise(error)


@router.patch(
    "/{meeting_id}/project", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-09", "FR-REC-10", "NFR-SEC-03"]},
)
async def set_meeting_project(
    meeting_id: str, payload: MeetingProjectUpdate, context: AuthContext = Depends(meeting_member),
) -> MeetingDetailOut:
    _project_in_scope(context, payload.project_id)
    try:
        return MeetingDetailOut.model_validate(meeting_service.set_project(meeting_id, payload.project_id, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.patch(
    "/{meeting_id}/speakers", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-06", "NFR-SEC-03"]},
)
async def rename_meeting_speakers(
    meeting_id: str, payload: MeetingSpeakersUpdate, context: AuthContext = Depends(meeting_member),
) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.rename_speakers(meeting_id, payload.names, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.patch(
    "/{meeting_id}", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-12", "NFR-SEC-03"]},
)
async def rename_meeting(meeting_id: str, payload: MeetingRename, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.rename(meeting_id, payload.title, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.delete(
    "/{meeting_id}", response_model=MeetingDeleted,
    openapi_extra={"x-requirement-ids": ["FR-REC-12", "NFR-SEC-03"]},
)
async def delete_meeting(meeting_id: str, context: AuthContext = Depends(meeting_member)) -> MeetingDeleted:
    """Deletes the recording, its transcript and its note for good. Intakes made from the note are kept."""
    try:
        return MeetingDeleted.model_validate(meeting_service.remove(meeting_id, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.patch(
    "/{meeting_id}/note", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-09", "NFR-SEC-03"]},
)
async def update_meeting_summary(
    meeting_id: str, payload: MeetingSummaryUpdate, context: AuthContext = Depends(meeting_member),
) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.update_summary(meeting_id, payload.summary, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.post(
    "/{meeting_id}/rewrite", response_model=MeetingDetailOut, status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-REC-11", "NFR-SEC-03"]},
)
async def rewrite_meeting_as_request(meeting_id: str, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    """Ask the AI worker to rewrite what was said as a short request. Poll the recording until `rewrite_status` settles."""
    try:
        return MeetingDetailOut.model_validate(meeting_service.request_rewrite(meeting_id, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.get(
    "/{meeting_id}/rewrite", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-11", "NFR-SEC-03"]},
)
async def get_meeting_rewrite(meeting_id: str, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    # Polled every second or two while the person waits, so it is not audited as a fresh opening of the transcript.
    try:
        return MeetingDetailOut.model_validate(meeting_service.detail(meeting_id, context.user_id, audit=False))
    except MeetingError as error:
        _raise(error)


@router.post(
    "/{meeting_id}/note/regenerate", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-09"]},
)
async def regenerate_meeting_note(meeting_id: str, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.regenerate_note(meeting_id, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.patch(
    "/{meeting_id}/note/items/{item_id}", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-09", "NFR-SEC-03"]},
)
async def update_meeting_note_item(
    meeting_id: str, item_id: str, payload: MeetingNoteItemUpdate, context: AuthContext = Depends(meeting_member),
) -> MeetingDetailOut:
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("project_code"):
        _project_in_scope(context, changes["project_code"])
    if "title" in changes and not (changes["title"] or "").strip() or "kind" in changes and not changes["kind"]:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title and kind cannot be empty")
    try:
        return MeetingDetailOut.model_validate(meeting_service.update_item(meeting_id, item_id, changes, context.user_id))
    except MeetingError as error:
        _raise(error)


@router.delete(
    "/{meeting_id}/note/items/{item_id}", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-09", "NFR-SEC-03"]},
)
async def remove_meeting_note_item(meeting_id: str, item_id: str, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.remove_item(meeting_id, item_id, context.user_id))
    except MeetingError as error:
        _raise(error)


def _intake_from_item(meeting_id: str, item_id: str, full_transcript: bool, actor_id: str) -> str:
    """Make the Intake a note item becomes and link it; the item ID keeps a retry from making a second one."""
    source = meeting_service.intake_source(meeting_id, item_id, full_transcript)
    try:
        intake = intake_store.create(
            IntakeCreate(
                project_id=source["project_code"], channel="MEETING",
                raw_text=source["raw_text"], sender_reference=source["sender_reference"],
            ),
            idempotency_key=f"meeting-note-item:{item_id}",
        )
    except KeyError as exc:
        raise MeetingError("PROJECT_REQUIRED", "The item's project is not active") from exc
    except RuntimeError as exc:
        raise MeetingError("NOTE_ITEM_HAS_INTAKE", "An Intake was already started from this item") from exc
    try:
        processing_repository.enqueue_normalization(intake.id)
    except RuntimeError:
        # The Intake exists and can be processed from its own page.
        pass
    meeting_service.link_intake(meeting_id, item_id, intake.id, actor_id)
    return str(intake.id)


def _default_channel(project_id: str) -> str:
    """The channel a marketing project posts on most; Facebook page until there is history."""
    from sqlalchemy import func

    from app.db import get_session
    from app.models import WorkItem

    with get_session() as session:
        row = session.execute(
            select(WorkItem.channel, func.count()).where(WorkItem.project_id == project_id, WorkItem.channel.is_not(None)).group_by(WorkItem.channel).order_by(func.count().desc())
        ).first()
    return str(row[0]) if row else "FACEBOOK_PAGE"


WORK_ITEM_TYPES = {"ACTION": "TASK", "BUG": "BUG", "REQUIREMENT": "FEATURE", "SCOPE_CHANGE": "SCOPE_CHANGE", "QUESTION": "QUESTION", "RISK": "FEEDBACK"}


def _work_from_item(meeting_id: str, spec, context: AuthContext) -> dict:
    """A note item goes straight to the board (FR-REC-19): its Intake is made from the item's own words, approved for
    the WORK route in the same breath with source MEETING, and the work takes the person, date and column settled
    on the line. No AI reads it: the note already is the normalized form."""
    from datetime import datetime, timezone

    from app.db import get_session
    from app.models import IntakeItem, Project, WorkforceProjectMembership
    from app.modules.work.service import WorkError, work_service
    from app.schemas import IntakeDecision

    source = meeting_service.intake_source(meeting_id, spec.item_id, False, for_work=True)
    project_id = str(source["project_id"])
    if not context.allows(project_id):
        raise MeetingError("PROJECT_NOT_ALLOWED", "This item belongs to a project you do not manage")
    if spec.member_id:
        with get_session() as session:
            on_project = session.scalar(select(WorkforceProjectMembership.id).where(
                WorkforceProjectMembership.project_id == project_id, WorkforceProjectMembership.member_id == spec.member_id,
                WorkforceProjectMembership.active.is_(True),
            )) is not None
        if not on_project:
            raise MeetingError("MEMBER_NOT_IN_PROJECT", "The person is not on this project")
    kind = str(source["kind"])
    try:
        intake = intake_store.create(
            IntakeCreate(project_id=str(source["project_code"]), channel="MEETING", raw_text=str(source["raw_text"]), sender_reference=str(source["sender_reference"])),
            idempotency_key=f"meeting-note-item:{spec.item_id}",
        )
    except KeyError as exc:
        raise MeetingError("PROJECT_REQUIRED", "The item's project is not active") from exc
    except RuntimeError as exc:
        raise MeetingError("NOTE_ITEM_HAS_INTAKE", "An Intake was already started from this item") from exc
    title = " ".join(str(source["title"]).split())[:255]
    detail = str(source.get("detail") or "").strip()
    with get_session() as session:
        item = session.get(IntakeItem, intake.id)
        item.normalized_title, item.normalized_summary = title, detail or title
        item.item_type = WORK_ITEM_TYPES.get(kind, "TASK")
        item.suggested_priority, item.proposed_route = ("P2" if kind == "BUG" else "P3"), "WORK"
        item.status = "PENDING_APPROVAL"
        item.updated_at = datetime.now(timezone.utc)
        session.commit()
        version, priority = item.version, item.suggested_priority
    approved = intake_store.approve(str(intake.id), IntakeDecision(
        approved_route="WORK", approved_priority=priority, reason=f"Từ cuộc họp: {source['meeting_title']}"[:2000], expected_version=version,
    ), actor_id=context.user_id, source="MEETING")
    work_id = approved.work_item.id if approved.work_item else None
    meeting_service.link_intake(meeting_id, spec.item_id, str(intake.id), context.user_id)
    if work_id:
        with get_session() as session:
            marketing = (session.get(Project, project_id).kind == "NON_CODE")
        wanted = spec.status or ("DISCUSS" if marketing else ("READY" if kind == "ACTION" else "DISCUSS"))
        try:
            current = work_service.get(work_id) or {}
            if spec.channel or marketing:
                code = spec.channel or _default_channel(project_id)
                stamp = spec.publish_at or (datetime.combine(spec.due_date, datetime.min.time(), tzinfo=timezone.utc).replace(hour=2) if spec.due_date else None)
                current = work_service.add_channel(work_id, channel=code, publish_at=stamp, actor_id=context.user_id)
            if spec.member_id or spec.due_date:
                current = work_service.update(work_id, expected_version=int(current["version"]), actor_id=context.user_id, member_id=spec.member_id, due_date=spec.due_date)
            if wanted != current.get("status"):
                current = work_service.move(work_id, expected_version=int(current["version"]), status=wanted, note=None, actor_id=context.user_id)
        except WorkError as error:
            raise MeetingError(error.code, str(error)) from error
        return {"item_id": spec.item_id, "work_id": work_id, "code": current.get("code"), "intake_id": str(intake.id)}
    return {"item_id": spec.item_id, "intake_id": str(intake.id)}


@router.post(
    "/{meeting_id}/note/items/work", response_model=MeetingNoteWorkOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-REC-19", "FR-WRK-06", "NFR-SEC-03"]},
)
async def work_from_note_items(meeting_id: str, payload: MeetingNoteWorkCreate, context: AuthContext = Depends(meeting_member)) -> MeetingNoteWorkOut:
    """Chosen items go straight to the board; one that cannot is reported, the others still go."""
    results = []
    seen: set[str] = set()
    for spec in payload.items:
        if spec.item_id in seen:
            continue
        seen.add(spec.item_id)
        try:
            results.append(_work_from_item(meeting_id, spec, context))
        except MeetingError as error:
            results.append({"item_id": spec.item_id, "error": error.code})
    try:
        detail = meeting_service.detail(meeting_id, context.user_id, audit=False)
    except MeetingError as error:
        _raise(error)
    return MeetingNoteWorkOut.model_validate({"results": results, "meeting": detail})


@router.post(
    "/{meeting_id}/note/items/intakes", response_model=MeetingNoteBulkIntakeOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-REC-16", "FR-REC-15", "FR-INT-01", "FR-AI-01", "NFR-SEC-03"]},
)
async def create_intakes_from_note_items(meeting_id: str, payload: MeetingNoteBulkIntake, context: AuthContext = Depends(meeting_member)) -> MeetingNoteBulkIntakeOut:
    """One Intake per chosen item; an item that cannot become one is reported, the others still go through."""
    results = []
    for item_id in dict.fromkeys(payload.item_ids):
        try:
            results.append({"item_id": item_id, "intake_id": _intake_from_item(meeting_id, item_id, payload.full_transcript, context.user_id)})
        except MeetingError as error:
            results.append({"item_id": item_id, "error": error.code})
    try:
        detail = meeting_service.detail(meeting_id, context.user_id, audit=False)
    except MeetingError as error:
        _raise(error)
    return MeetingNoteBulkIntakeOut.model_validate({"results": results, "meeting": detail})


@router.post(
    "/{meeting_id}/note/items/{item_id}/intake", response_model=MeetingDetailOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-REC-10", "FR-REC-15", "FR-INT-01", "FR-AI-01", "NFR-SEC-03"]},
)
async def create_intake_from_note_item(
    meeting_id: str, item_id: str, full_transcript: bool = Query(default=False), context: AuthContext = Depends(meeting_member),
) -> MeetingDetailOut:
    try:
        _intake_from_item(meeting_id, item_id, full_transcript, context.user_id)
        return MeetingDetailOut.model_validate(meeting_service.detail(meeting_id, context.user_id, audit=False))
    except MeetingError as error:
        _raise(error)


@router.post(
    "/{meeting_id}/transcript/retry", response_model=MeetingDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-REC-18", "NFR-SEC-03"]},
)
async def retry_meeting_transcription(meeting_id: str, context: AuthContext = Depends(meeting_member)) -> MeetingDetailOut:
    try:
        return MeetingDetailOut.model_validate(meeting_service.retry_transcription(meeting_id, context.user_id))
    except MeetingError as error:
        _raise(error)
