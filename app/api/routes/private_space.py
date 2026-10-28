from fastapi import APIRouter, Depends, Query, Response, status

from app.api.errors import api_exception
from app.api.routes.intakes import intake_member
from app.api.security import AuthContext, require_cto
from app.modules.drafts.service import DraftError, draft_service
from app.modules.identity.service import identity_service
from app.modules.private_space.service import IDEA_STATES, PrivateSpaceError, private_space_service
from app.schemas import (
    PostDraftApprove,
    PostDraftCreate,
    PostDraftOut,
    PostDraftUpdate,
    DraftTrack,
    PrivateIdeaOut,
    PrivateIdeaTrack,
    PrivateSpaceOut,
    MasterDna,
    PrivateVoice,
    PromptPreviewOut,
    PromptPreviewRequest,
    VoiceTrialOut,
    VoiceTrialRequest,
    TrackNoteCreate,
    TrackNoteOut,
)

# The private space belongs to the CTO role (ADR-0031). A Project Owner gets 403 here and 404 on anything inside it.
router = APIRouter(prefix="/private-space", tags=["private-space"])
drafts_router = APIRouter(prefix="/intakes/{intake_id}/drafts", tags=["drafts"])

DRAFT_STATUS = {
    "DRAFT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "INTAKE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "DRAFTS_NOT_FOR_KIND": status.HTTP_409_CONFLICT,
    "DRAFT_NOT_READY": status.HTTP_409_CONFLICT,
    "SOURCE_DRAFT_NOT_READY": status.HTTP_409_CONFLICT,
    "DRAFT_APPROVED": status.HTTP_409_CONFLICT,
    "DRAFT_POSTED": status.HTTP_409_CONFLICT,
    "SLOT_TAKEN": status.HTTP_409_CONFLICT,
    "SLOT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
}


def _draft_error(error: DraftError) -> None:
    raise api_exception(DRAFT_STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_ENTITY), error.code, error.message) from error


@router.get("", response_model=PrivateSpaceOut, openapi_extra={"x-requirement-ids": ["FR-CNT-03", "NFR-SEC-03"]})
async def get_private_space(context: AuthContext = Depends(require_cto)) -> PrivateSpaceOut:
    return PrivateSpaceOut.model_validate(private_space_service.overview())


@router.post(
    "", response_model=PrivateSpaceOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-CNT-03", "NFR-SEC-03"]},
)
async def open_private_space(context: AuthContext = Depends(require_cto)) -> PrivateSpaceOut:
    try:
        return PrivateSpaceOut.model_validate(private_space_service.create(context.user_id))
    except PrivateSpaceError as error:
        raise api_exception(status.HTTP_409_CONFLICT, error.code, error.message) from error


@router.get("/ideas", response_model=list[PrivateIdeaOut], openapi_extra={"x-requirement-ids": ["FR-CNT-03", "NFR-SEC-03"]})
async def list_private_ideas(
    state: str = Query(default="ALL"), search: str | None = Query(default=None, max_length=255),
    track: str | None = Query(default=None, max_length=32),
    context: AuthContext = Depends(require_cto),
) -> list[PrivateIdeaOut]:
    if state not in IDEA_STATES:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "IDEA_STATE_UNKNOWN", "Unknown idea state")
    return [PrivateIdeaOut.model_validate(row) for row in private_space_service.ideas(state, search, track)]


def _idea_error(error: PrivateSpaceError) -> None:
    raise api_exception(status.HTTP_404_NOT_FOUND if error.code == "IDEA_NOT_FOUND" else status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error


@router.get("/ideas/{intake_id}/track", response_model=PrivateIdeaTrack, openapi_extra={"x-requirement-ids": ["FR-CNT-04", "NFR-SEC-03"]})
async def get_idea_track(intake_id: str, context: AuthContext = Depends(require_cto)) -> PrivateIdeaTrack:
    try:
        return PrivateIdeaTrack(track=private_space_service.track_of(intake_id))
    except PrivateSpaceError as error:
        _idea_error(error)


@router.put("/ideas/{intake_id}/track", response_model=PrivateIdeaTrack, openapi_extra={"x-requirement-ids": ["FR-CNT-04", "NFR-SEC-03"]})
async def set_idea_track(intake_id: str, payload: PrivateIdeaTrack, context: AuthContext = Depends(require_cto)) -> PrivateIdeaTrack:
    try:
        private_space_service.set_track(intake_id, payload.track, context.user_id)
    except PrivateSpaceError as error:
        _idea_error(error)
    return payload


@router.put("/voice", response_model=PrivateSpaceOut, openapi_extra={"x-requirement-ids": ["FR-CNT-02", "NFR-SEC-03"]})
async def save_private_voice(
    payload: PrivateVoice, track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto),
) -> PrivateSpaceOut:
    try:
        return PrivateSpaceOut.model_validate(private_space_service.save_voice(payload.model_dump(), context.user_id, track))
    except PrivateSpaceError as error:
        raise api_exception(status.HTTP_409_CONFLICT, error.code, error.message) from error


@router.put("/master-dna", response_model=PrivateSpaceOut, openapi_extra={"x-requirement-ids": ["FR-CNT-15", "NFR-SEC-03"]})
async def save_master_dna(payload: MasterDna, context: AuthContext = Depends(require_cto)) -> PrivateSpaceOut:
    """The one brand document every track reads: a shared core and its directions."""
    try:
        return PrivateSpaceOut.model_validate(private_space_service.save_master_dna(payload.text, context.user_id))
    except PrivateSpaceError as error:
        raise api_exception(status.HTTP_409_CONFLICT if error.code == "PRIVATE_SPACE_MISSING" else status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error


@router.post("/voice-trial", response_model=VoiceTrialOut, openapi_extra={"x-requirement-ids": ["FR-CNT-16", "NFR-SEC-03"]})
async def try_voice(payload: VoiceTrialRequest, context: AuthContext = Depends(require_cto)) -> VoiceTrialOut:
    """A short piece written now, in the voice as it stands on the screen, to hear it. Nothing is saved."""
    from app.config import get_settings
    from app.modules.drafts.message import build_draft_message
    from app.services.ai_processor import POST_DRAFT_PROMPT_VERSION, AIProviderPermanentError, AIProviderTransientError, umodelverse_adapter

    try:
        source, _ = draft_service.preview_source(
            track=payload.track, voice=payload.voice.model_dump() if payload.voice is not None else None, intake_id=None,
            channel=payload.channel, outline=False, goal=None, audience=None, pillar=None, group_context=None, angle=None,
            source_draft_id=None, may_read_raw=False, actor_id=context.user_id, master_dna=payload.master_dna,
        )
    except DraftError as error:
        _draft_error(error)
    idea = " ".join(payload.idea.split()) or "Một tình huống nhỏ trong công việc mà người đọc hay gặp, để nghe thử giọng."
    source.update({"trial": True, "note": idea, "title": idea[:120], "summary": ""})
    message = build_draft_message(source)
    try:
        result = await umodelverse_adapter.write_post_draft(message)
    except (AIProviderTransientError, AIProviderPermanentError) as error:
        raise api_exception(status.HTTP_503_SERVICE_UNAVAILABLE, error.code, "AI chưa trả lời được lúc này") from error
    private_space_service.audit_trial(context.user_id, payload.track, len(message))
    return VoiceTrialOut(text=result.text, prompt_version=POST_DRAFT_PROMPT_VERSION, model=get_settings().umodelverse_model, message_chars=len(message))


@router.post("/prompt-preview", response_model=PromptPreviewOut, openapi_extra={"x-requirement-ids": ["FR-CNT-14", "NFR-SEC-03"]})
async def preview_prompt(payload: PromptPreviewRequest, context: AuthContext = Depends(require_cto)) -> PromptPreviewOut:
    """Exactly what the AI would be sent for a draft asked for now. Nothing is sent to the AI and nothing is saved."""
    from app.config import get_settings
    from app.modules.drafts.message import draft_blocks
    from app.services.ai_processor import POST_DRAFT_PROMPT_VERSION, POST_DRAFT_SYSTEM_PROMPT

    try:
        source, placeholder = draft_service.preview_source(
            track=payload.track, voice=payload.voice.model_dump() if payload.voice is not None else None, intake_id=payload.intake_id,
            channel=payload.channel, outline=payload.outline, goal=payload.goal, audience=payload.audience, pillar=payload.pillar,
            group_context=payload.group_context, angle=payload.angle, source_draft_id=payload.source_draft_id,
            may_read_raw=identity_service.can_access_raw(context.subject), actor_id=context.user_id,
            master_dna=payload.master_dna, context=payload.context, commercial=payload.commercial,
        )
    except DraftError as error:
        _draft_error(error)
    blocks = [{"key": block["key"], "trust": block["trust"], "text": "\n".join(block["lines"]).strip(), "cuts": block["cuts"]} for block in draft_blocks(source)]
    for block in blocks:
        block["chars"] = len(block["text"])
    # The model gets the blocks joined by a blank line.
    joined = "\n\n".join(block["text"] for block in blocks).strip()
    return PromptPreviewOut(
        prompt_version=POST_DRAFT_PROMPT_VERSION, model=get_settings().umodelverse_model, system_prompt=POST_DRAFT_SYSTEM_PROMPT,
        system_chars=len(POST_DRAFT_SYSTEM_PROMPT), blocks=blocks, message_chars=len(joined), placeholder=placeholder,
    )


@router.get("/notes", response_model=list[TrackNoteOut], openapi_extra={"x-requirement-ids": ["FR-CNT-06", "NFR-SEC-03"]})
async def list_track_notes(track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto)) -> list[TrackNoteOut]:
    return [TrackNoteOut.model_validate(row) for row in private_space_service.notes(track)]


@router.post(
    "/notes", response_model=TrackNoteOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-CNT-06", "NFR-SEC-03"]},
)
async def add_track_note(payload: TrackNoteCreate, context: AuthContext = Depends(require_cto)) -> TrackNoteOut:
    try:
        return TrackNoteOut.model_validate(private_space_service.add_note(payload.track, payload.kind, payload.text, context.user_id))
    except PrivateSpaceError as error:
        raise api_exception(status.HTTP_409_CONFLICT if error.code in ("NOTES_FULL", "PRIVATE_SPACE_MISSING") else status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-CNT-06", "NFR-SEC-03"]})
async def remove_track_note(note_id: str, context: AuthContext = Depends(require_cto)) -> Response:
    try:
        private_space_service.remove_note(note_id, context.user_id)
    except PrivateSpaceError as error:
        raise api_exception(status.HTTP_404_NOT_FOUND, error.code, error.message) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@drafts_router.get("", response_model=list[PostDraftOut], openapi_extra={"x-requirement-ids": ["FR-CNT-01", "NFR-SEC-03"]})
async def list_drafts(intake_id: str, context: AuthContext = Depends(intake_member)) -> list[PostDraftOut]:
    return [PostDraftOut.model_validate(row) for row in draft_service.list(intake_id)]


@drafts_router.post(
    "", response_model=PostDraftOut, status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-CNT-01", "FR-ID-04", "NFR-SEC-03"]},
)
async def request_draft(intake_id: str, payload: PostDraftCreate, context: AuthContext = Depends(intake_member)) -> PostDraftOut:
    """Ask the AI worker for a post draft. Poll the list until the draft's `status` settles."""
    try:
        return PostDraftOut.model_validate(draft_service.request(
            intake_id, channel=payload.channel, angle=payload.angle, source_draft_id=payload.source_draft_id,
            actor_id=context.user_id, may_read_raw=identity_service.can_access_raw(context.subject),
            track=payload.track, goal=payload.goal, audience=payload.audience, pillar=payload.pillar, group_context=payload.group_context,
            outline=payload.outline, context=payload.context, commercial=payload.commercial,
        ))
    except DraftError as error:
        _draft_error(error)


@drafts_router.patch("/{draft_id}", response_model=PostDraftOut, openapi_extra={"x-requirement-ids": ["FR-CNT-01", "NFR-SEC-03"]})
async def update_draft(
    intake_id: str, draft_id: str, payload: PostDraftUpdate, context: AuthContext = Depends(intake_member),
) -> PostDraftOut:
    try:
        return PostDraftOut.model_validate(draft_service.update(
            intake_id, draft_id, text=payload.text, posted=payload.posted, actor_id=context.user_id,
            posted_at=payload.posted_at, posted_url=payload.posted_url,
        ))
    except DraftError as error:
        _draft_error(error)


@drafts_router.post("/{draft_id}/approve", response_model=PostDraftOut, openapi_extra={"x-requirement-ids": ["FR-CNT-08", "NFR-SEC-03"]})
async def approve_draft(
    intake_id: str, draft_id: str, payload: PostDraftApprove, context: AuthContext = Depends(intake_member),
) -> PostDraftOut:
    """Lock the text and say when it goes out; with `slot_id` the draft fills that slot of the week plan."""
    try:
        return PostDraftOut.model_validate(draft_service.approve(
            intake_id, draft_id, slot_id=payload.slot_id, scheduled_for=payload.scheduled_for, actor_id=context.user_id,
        ))
    except DraftError as error:
        _draft_error(error)


@drafts_router.delete("/{draft_id}/approve", response_model=PostDraftOut, openapi_extra={"x-requirement-ids": ["FR-CNT-08", "NFR-SEC-03"]})
async def withdraw_draft_approval(intake_id: str, draft_id: str, context: AuthContext = Depends(intake_member)) -> PostDraftOut:
    try:
        return PostDraftOut.model_validate(draft_service.unapprove(intake_id, draft_id, context.user_id))
    except DraftError as error:
        _draft_error(error)


@drafts_router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-CNT-01", "NFR-SEC-03"]})
async def delete_draft(intake_id: str, draft_id: str, context: AuthContext = Depends(intake_member)) -> Response:
    try:
        draft_service.remove(intake_id, draft_id, context.user_id)
    except DraftError as error:
        _draft_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
