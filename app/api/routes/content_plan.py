from datetime import date

from fastapi import APIRouter, Depends, Query, status

from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto
from app.modules.content_plan.service import PlanError, content_plan_service
from app.schemas import (
    DraftTrack,
    PlanProposalCreate,
    PlanProposalOut,
    PlanSlotAccepted,
    PlanSlotChange,
    PlanSlotOut,
    PlanWeekOut,
    RhythmUpdate,
)
from app.services.processing_repository import processing_repository

# The week plan belongs to the private space, so to the CTO role (ADR-0037).
router = APIRouter(prefix="/private-space/plan", tags=["content-plan"])

PLAN_STATUS = {
    "SLOT_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "IDEA_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "SLOT_LOCKED": status.HTTP_409_CONFLICT,
    "NO_SUGGESTION": status.HTTP_409_CONFLICT,
    "NO_OPEN_SLOT": status.HTTP_409_CONFLICT,
    "WEEK_NOT_OPEN": status.HTTP_409_CONFLICT,
    "PRIVATE_SPACE_MISSING": status.HTTP_409_CONFLICT,
}


def _plan_error(error: PlanError) -> None:
    raise api_exception(PLAN_STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_ENTITY), error.code, error.message) from error


@router.get("", response_model=PlanWeekOut, openapi_extra={"x-requirement-ids": ["FR-CNT-07", "NFR-SEC-03"]})
async def get_week_plan(week: date | None = Query(default=None), context: AuthContext = Depends(require_cto)) -> PlanWeekOut:
    try:
        return PlanWeekOut.model_validate(content_plan_service.week(week))
    except PlanError as error:
        _plan_error(error)


@router.put("/rhythm", response_model=PlanWeekOut, openapi_extra={"x-requirement-ids": ["FR-CNT-07", "NFR-SEC-03"]})
async def save_rhythm(
    payload: RhythmUpdate, track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto),
) -> PlanWeekOut:
    try:
        return PlanWeekOut.model_validate(content_plan_service.save_rhythm(track, [slot.model_dump() for slot in payload.slots], context.user_id))
    except PlanError as error:
        _plan_error(error)


@router.post(
    "/propose", response_model=PlanProposalOut, status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-CNT-09", "NFR-SEC-03"]},
)
async def propose_week(payload: PlanProposalCreate, context: AuthContext = Depends(require_cto)) -> PlanProposalOut:
    """Ask the AI worker to propose ideas for the open slots. Poll the week until the track's `request` settles."""
    try:
        return PlanProposalOut.model_validate(content_plan_service.request_proposal(payload.track, payload.week_start, payload.keywords, context.user_id))
    except PlanError as error:
        _plan_error(error)


@router.get("/slots/{slot_id}", response_model=PlanSlotOut, openapi_extra={"x-requirement-ids": ["FR-CNT-07", "NFR-SEC-03"]})
async def get_slot(slot_id: str, context: AuthContext = Depends(require_cto)) -> PlanSlotOut:
    try:
        return PlanSlotOut.model_validate(content_plan_service.slot(slot_id))
    except PlanError as error:
        _plan_error(error)


@router.patch("/slots/{slot_id}", response_model=PlanSlotOut, openapi_extra={"x-requirement-ids": ["FR-CNT-07", "NFR-SEC-03"]})
async def change_slot(slot_id: str, payload: PlanSlotChange, context: AuthContext = Depends(require_cto)) -> PlanSlotOut:
    # Only what was sent is changed: `intake_id: null` empties the slot, leaving it out keeps the idea.
    changes = {name: getattr(payload, name) for name in payload.model_fields_set}
    try:
        return PlanSlotOut.model_validate(content_plan_service.change_slot(slot_id, changes, context.user_id))
    except PlanError as error:
        _plan_error(error)


@router.post("/slots/{slot_id}/accept", response_model=PlanSlotAccepted, openapi_extra={"x-requirement-ids": ["FR-CNT-09", "NFR-SEC-03"]})
async def accept_suggestion(slot_id: str, context: AuthContext = Depends(require_cto)) -> PlanSlotAccepted:
    try:
        slot, created = content_plan_service.accept(slot_id, context.user_id)
    except PlanError as error:
        _plan_error(error)
    if created:
        # A new angle is read like any saved idea; it is kept whether or not AI can read it right now.
        try:
            processing_repository.enqueue_normalization(created)
        except Exception:
            pass
    return PlanSlotAccepted(slot=PlanSlotOut.model_validate(slot), created_idea_id=created)
