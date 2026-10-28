from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from pydantic import ValidationError

from app.api import machine_auth
from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto
from app.config import get_settings
from app.modules.watch.service import WatchError, watch_service
from app.schemas import (
    DraftTrack,
    PillarKeywordsOut,
    PillarKeywordsUpdate,
    WatchBatch,
    WatchBatchOut,
    WatchConfigOut,
    WatchDemandOut,
    WatchDemandUpdate,
    WatchHealthOut,
    WatchRequestOut,
    WatchSignalKept,
    WatchSignalOut,
    WatchSourceChange,
    WatchSourceCreate,
    WatchSourceOut,
)
from app.services.processing_repository import processing_repository

# What the owner watches belongs to the private space, so to the CTO role (ADR-0039).
router = APIRouter(prefix="/private-space/watch", tags=["watch"])
# The scanning flow outside Intake: reads what to scan, sends back what it found.
flow_router = APIRouter(prefix="/watch", tags=["watch-flow"])

WATCH_STATUS = {
    "SOURCE_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "SIGNAL_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "SOURCE_EXISTS": status.HTTP_409_CONFLICT,
    "SOURCES_FULL": status.HTTP_409_CONFLICT,
    "NO_PILLARS": status.HTTP_409_CONFLICT,
    "PRIVATE_SPACE_MISSING": status.HTTP_409_CONFLICT,
}
IDS = {"x-requirement-ids": ["FR-CNT-11", "NFR-SEC-03"]}
FLOW_IDS = {"x-requirement-ids": ["FR-CNT-12", "NFR-SEC-03"]}


def _watch_error(error: WatchError) -> None:
    raise api_exception(WATCH_STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_ENTITY), error.code, error.message) from error


@router.get("/sources", response_model=list[WatchSourceOut], openapi_extra=IDS)
async def list_sources(context: AuthContext = Depends(require_cto)) -> list[WatchSourceOut]:
    return [WatchSourceOut.model_validate(row) for row in watch_service.sources()]


@router.post("/sources", response_model=WatchSourceOut, status_code=status.HTTP_201_CREATED, openapi_extra=IDS)
async def add_source(payload: WatchSourceCreate, context: AuthContext = Depends(require_cto)) -> WatchSourceOut:
    try:
        return WatchSourceOut.model_validate(watch_service.add_source(payload.url, payload.track, payload.label, payload.kind, payload.note, context.user_id))
    except WatchError as error:
        _watch_error(error)


@router.patch("/sources/{source_id}", response_model=WatchSourceOut, openapi_extra=IDS)
async def change_source(source_id: str, payload: WatchSourceChange, context: AuthContext = Depends(require_cto)) -> WatchSourceOut:
    changes = {name: getattr(payload, name) for name in payload.model_fields_set}
    try:
        return WatchSourceOut.model_validate(watch_service.change_source(source_id, changes, context.user_id))
    except WatchError as error:
        _watch_error(error)


@router.delete("/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra=IDS)
async def remove_source(source_id: str, context: AuthContext = Depends(require_cto)) -> Response:
    try:
        watch_service.remove_source(source_id, context.user_id)
    except WatchError as error:
        _watch_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/keywords", response_model=PillarKeywordsOut, openapi_extra=IDS)
async def get_keywords(track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto)) -> PillarKeywordsOut:
    return PillarKeywordsOut.model_validate(watch_service.keywords(track))


@router.put("/keywords", response_model=PillarKeywordsOut, openapi_extra=IDS)
async def save_keywords(
    payload: PillarKeywordsUpdate, track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto),
) -> PillarKeywordsOut:
    try:
        return PillarKeywordsOut.model_validate(watch_service.save_keywords(track, payload.pillars, context.user_id))
    except WatchError as error:
        _watch_error(error)


@router.post("/keywords/suggest", response_model=WatchRequestOut, status_code=status.HTTP_202_ACCEPTED, openapi_extra=IDS)
async def suggest_keywords(track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto)) -> WatchRequestOut:
    """Ask the AI worker for keywords of each pillar. Poll `GET …/keywords` until `request` settles; nothing is saved until the owner saves."""
    try:
        return WatchRequestOut.model_validate(watch_service.request_keywords(track, context.user_id))
    except WatchError as error:
        _watch_error(error)


@router.get("/demand", response_model=WatchDemandOut, openapi_extra=IDS)
async def get_demand(track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto)) -> WatchDemandOut:
    return WatchDemandOut.model_validate(watch_service.demand(track))


@router.put("/demand", response_model=WatchDemandOut, openapi_extra=IDS)
async def save_demand(
    payload: WatchDemandUpdate, track: DraftTrack = Query(default="business"), context: AuthContext = Depends(require_cto),
) -> WatchDemandOut:
    """How many signals the track wants each week and by when, so the scanner outside can pace itself."""
    try:
        return WatchDemandOut.model_validate(watch_service.save_demand(track, payload.wanted_per_week, payload.weekday, payload.time, payload.lookback_days, context.user_id))
    except WatchError as error:
        _watch_error(error)


def _routes_open() -> bool:
    settings = get_settings()
    return all(len((value or "").strip()) >= machine_auth.MIN_SECRET for value in (settings.watch_api_key, settings.watch_webhook_secret))


@router.get("/health", response_model=WatchHealthOut, openapi_extra={"x-requirement-ids": ["FR-CNT-13", "NFR-SEC-03"]})
async def watch_health(context: AuthContext = Depends(require_cto)) -> WatchHealthOut:
    """When the scanner last called, and what the last twelve-hour check found for each track."""
    return WatchHealthOut.model_validate(watch_service.health())


@router.post("/health/check", response_model=WatchHealthOut, openapi_extra={"x-requirement-ids": ["FR-CNT-13", "NFR-SEC-03"]})
async def check_watch_now(context: AuthContext = Depends(require_cto)) -> WatchHealthOut:
    """Run the check now instead of waiting for the next scheduled one."""
    watch_service.check(_routes_open())
    return WatchHealthOut.model_validate(watch_service.health())


@router.get("/signals", response_model=list[WatchSignalOut], openapi_extra=IDS)
async def list_signals(
    track: DraftTrack = Query(default="business"), state: str = Query(default="NEW", max_length=16), context: AuthContext = Depends(require_cto),
) -> list[WatchSignalOut]:
    try:
        return [WatchSignalOut.model_validate(row) for row in watch_service.signals(track, state)]
    except WatchError as error:
        _watch_error(error)


@router.post("/signals/{signal_id}/idea", response_model=WatchSignalKept, openapi_extra=IDS)
async def keep_signal(signal_id: str, context: AuthContext = Depends(require_cto)) -> WatchSignalKept:
    try:
        signal, created = watch_service.to_idea(signal_id, context.user_id)
    except WatchError as error:
        _watch_error(error)
    # Read like any saved idea; it is kept whether or not AI can read it right now.
    try:
        processing_repository.enqueue_normalization(created)
    except Exception:
        pass
    return WatchSignalKept(signal=WatchSignalOut.model_validate(signal), idea_id=created)


@router.delete("/signals/{signal_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra=IDS)
async def dismiss_signal(signal_id: str, context: AuthContext = Depends(require_cto)) -> Response:
    try:
        watch_service.dismiss(signal_id, context.user_id)
    except WatchError as error:
        _watch_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@flow_router.get("/config", response_model=WatchConfigOut, openapi_extra=FLOW_IDS)
async def watch_config(authorization: str = Header(default="")) -> WatchConfigOut:
    """Active sources and the keywords of each pillar, by track. `Authorization: Bearer <WATCH_API_KEY>`."""
    secret = machine_auth.configured(get_settings().watch_api_key)
    machine_auth.check_bearer(secret, authorization, "WATCH_UNAUTHORIZED")
    return WatchConfigOut.model_validate(watch_service.config())


@flow_router.post("/signals", response_model=WatchBatchOut, openapi_extra=FLOW_IDS)
async def receive_signals(
    request: Request,
    timestamp: str = Header(default="", alias="X-Intake-Timestamp"),
    signature: str = Header(default="", alias="X-Intake-Signature"),
) -> WatchBatchOut:
    """What the scanning flow found, at most 50 items a call. Signed like the posting call back, with `WATCH_WEBHOOK_SECRET`."""
    secret = machine_auth.configured(get_settings().watch_webhook_secret)
    body = await request.body()
    if len(body) > 256 * 1024:
        raise api_exception(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "BATCH_TOO_LARGE", "The batch is too large")
    machine_auth.check_signature(secret, timestamp, signature, body, "WATCH_UNAUTHORIZED")
    try:
        batch = WatchBatch.model_validate_json(body)
    except ValidationError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "BATCH_INVALID", "The batch does not match the expected shape") from error
    try:
        return WatchBatchOut.model_validate(watch_service.receive([item.model_dump() for item in batch.items]))
    except WatchError as error:
        _watch_error(error)
