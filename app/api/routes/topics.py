"""What a marketing project listens to and the hot topics it hears (FR-MKT-08..10, ADR-0068): pillars, sources,
networks and the AI schedule of one project for its owner and the CTO; the networks and caps the CTO opens for all;
the topics of the week with Thành bài, Thành chuỗi and Bỏ."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.errors import api_exception
from app.api.routes.watch import _routes_open
from app.api.security import AuthContext, ensure_project, require_account, require_cto, require_member
from app.modules.projects.service import project_catalog_service
from app.modules.watch.platforms import PlatformError, ai_runs_cap, list_platforms, set_ai_runs_cap, update_platform
from app.modules.watch.service import CONTENT_TRACK, WatchError, watch_service
from app.modules.watch.topics import topics_service
from app.modules.work import publishing
from app.modules.work.service import WorkError
from app.schemas import (
    PillarKeywordsOut,
    PillarKeywordsUpdate,
    PillarOut,
    PillarsUpdate,
    PublishPauseOut,
    PublishPauseUpdate,
    WatchDemandOut,
    WatchDemandUpdate,
    WatchHealthOut,
    WatchLimitsOut,
    WatchLimitsUpdate,
    WatchPlatformOut,
    WatchPlatformUpdate,
    WatchRequestOut,
    WatchSettingsOut,
    WatchSettingsUpdate,
    WatchSourceChange,
    WatchSourceCreate,
    WatchSourceOut,
    WatchTopicPost,
    WatchTopicsOut,
    WatchTopicsRequested,
    WorkDetail,
)

router = APIRouter(tags=["watch-projects"])

IDS = {"x-requirement-ids": ["FR-MKT-08"]}
TOPIC_IDS = {"x-requirement-ids": ["FR-MKT-09", "FR-MKT-10"]}
STATUS = {
    "SOURCE_NOT_FOUND": status.HTTP_404_NOT_FOUND, "TOPIC_NOT_FOUND": status.HTTP_404_NOT_FOUND,
    "SOURCE_EXISTS": status.HTTP_409_CONFLICT, "SOURCES_FULL": status.HTTP_409_CONFLICT, "NO_PILLARS": status.HTTP_409_CONFLICT,
    "WATCH_NOT_FOR_PROJECT": status.HTTP_409_CONFLICT, "TOPIC_CLOSED": status.HTTP_409_CONFLICT, "TOPICS_LIMIT": status.HTTP_429_TOO_MANY_REQUESTS,
}


def _raise(error: WatchError) -> None:
    raise api_exception(STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_ENTITY), error.code, error.message) from error


def _project(context: AuthContext, reference: str):
    """A marketing project the caller may act on: the CTO, or the owner of that project."""
    project = project_catalog_service.get_project(reference)
    if project is None or project.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project(context, project.id, "Project")
    if project.kind != "NON_CODE":
        raise api_exception(status.HTTP_409_CONFLICT, "WATCH_NOT_FOR_PROJECT", "Chỉ dự án marketing mới có nguồn và trụ để nghe")
    return project


# ---- one project's listening settings (owner and CTO)

@router.get("/projects/{code}/watch/pillars", response_model=list[PillarOut], openapi_extra=IDS)
async def get_pillars(code: str, context: AuthContext = Depends(require_member)) -> list[dict]:
    project = _project(context, code)
    try:
        return [PillarOut.model_validate(row).model_dump() for row in watch_service.pillars(str(project.id))]
    except WatchError as error:
        _raise(error)


@router.put("/projects/{code}/watch/pillars", response_model=list[PillarOut], openapi_extra=IDS)
async def put_pillars(code: str, payload: PillarsUpdate, context: AuthContext = Depends(require_member)) -> list[dict]:
    project = _project(context, code)
    try:
        rows = watch_service.save_pillars(str(project.id), [row.model_dump() for row in payload.pillars], context.user_id)
    except WatchError as error:
        _raise(error)
    return [PillarOut.model_validate(row).model_dump() for row in rows]


@router.get("/projects/{code}/watch/settings", response_model=WatchSettingsOut, openapi_extra=IDS)
async def get_watch_settings(code: str, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        return WatchSettingsOut.model_validate(watch_service.watch_settings(str(project.id))).model_dump()
    except WatchError as error:
        _raise(error)


@router.put("/projects/{code}/watch/settings", response_model=WatchSettingsOut, openapi_extra={"x-requirement-ids": ["FR-MKT-08", "FR-MKT-10"]})
async def put_watch_settings(code: str, payload: WatchSettingsUpdate, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        row = watch_service.save_watch_settings(str(project.id), networks=payload.networks, times=payload.times, weekdays=payload.weekdays,
                                                scan_every_hours=payload.scan_every_hours, actor_id=context.user_id)
    except WatchError as error:
        _raise(error)
    return WatchSettingsOut.model_validate(row).model_dump()


@router.get("/projects/{code}/watch/sources", response_model=list[WatchSourceOut], openapi_extra=IDS)
async def project_sources(code: str, context: AuthContext = Depends(require_member)) -> list[dict]:
    project = _project(context, code)
    return [WatchSourceOut.model_validate(row).model_dump() for row in watch_service.sources(str(project.id))]


@router.post("/projects/{code}/watch/sources", response_model=WatchSourceOut, status_code=status.HTTP_201_CREATED, openapi_extra=IDS)
async def project_add_source(code: str, payload: WatchSourceCreate, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        row = watch_service.add_source(payload.url, CONTENT_TRACK, payload.label, payload.kind, payload.note, context.user_id, project_id=str(project.id))
    except WatchError as error:
        _raise(error)
    return WatchSourceOut.model_validate(row).model_dump()


@router.patch("/projects/{code}/watch/sources/{source_id}", response_model=WatchSourceOut, openapi_extra=IDS)
async def project_change_source(code: str, source_id: str, payload: WatchSourceChange, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    changes = {name: getattr(payload, name) for name in payload.model_fields_set if name != "track"}
    try:
        row = watch_service.change_source(source_id, changes, context.user_id, project_id=str(project.id))
    except WatchError as error:
        _raise(error)
    return WatchSourceOut.model_validate(row).model_dump()


@router.delete("/projects/{code}/watch/sources/{source_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra=IDS)
async def project_remove_source(code: str, source_id: str, context: AuthContext = Depends(require_member)) -> Response:
    project = _project(context, code)
    try:
        watch_service.remove_source(source_id, context.user_id, project_id=str(project.id))
    except WatchError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/projects/{code}/watch/keywords", response_model=PillarKeywordsOut, openapi_extra=IDS)
async def project_keywords(code: str, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        return PillarKeywordsOut.model_validate(watch_service.keywords(CONTENT_TRACK, project_id=str(project.id))).model_dump()
    except WatchError as error:
        _raise(error)


@router.put("/projects/{code}/watch/keywords", response_model=PillarKeywordsOut, openapi_extra=IDS)
async def project_save_keywords(code: str, payload: PillarKeywordsUpdate, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        return PillarKeywordsOut.model_validate(watch_service.save_keywords(CONTENT_TRACK, payload.pillars, context.user_id, project_id=str(project.id))).model_dump()
    except WatchError as error:
        _raise(error)


@router.post("/projects/{code}/watch/keywords/suggest", response_model=WatchRequestOut, status_code=status.HTTP_202_ACCEPTED, openapi_extra=IDS)
async def project_suggest_keywords(code: str, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        return WatchRequestOut.model_validate(watch_service.request_keywords(CONTENT_TRACK, context.user_id, project_id=str(project.id))).model_dump()
    except WatchError as error:
        _raise(error)


@router.get("/projects/{code}/watch/demand", response_model=WatchDemandOut, openapi_extra=IDS)
async def project_demand(code: str, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        return WatchDemandOut.model_validate(watch_service.demand(CONTENT_TRACK, project_id=str(project.id))).model_dump()
    except WatchError as error:
        _raise(error)


@router.put("/projects/{code}/watch/demand", response_model=WatchDemandOut, openapi_extra=IDS)
async def project_save_demand(code: str, payload: WatchDemandUpdate, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    try:
        row = watch_service.save_demand(CONTENT_TRACK, payload.wanted_per_week, payload.weekday, payload.time, payload.lookback_days, context.user_id, project_id=str(project.id))
    except WatchError as error:
        _raise(error)
    return WatchDemandOut.model_validate(row).model_dump()


@router.get("/projects/{code}/watch/health", response_model=WatchHealthOut, openapi_extra=IDS)
async def project_health(code: str, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    return WatchHealthOut.model_validate(watch_service.health(str(project.id))).model_dump()


@router.post("/projects/{code}/watch/health/check", response_model=WatchHealthOut, openapi_extra=IDS)
async def project_check_now(code: str, context: AuthContext = Depends(require_member)) -> dict:
    project = _project(context, code)
    watch_service.check(_routes_open())
    return WatchHealthOut.model_validate(watch_service.health(str(project.id))).model_dump()


# ---- hot topics of the week

@router.get("/watch-topics", response_model=WatchTopicsOut, openapi_extra=TOPIC_IDS)
async def list_topics(project: str = Query(..., min_length=1, max_length=64), context: AuthContext = Depends(require_account)) -> dict:
    """This week's topics for everyone on the project; the buttons are the owner's."""
    row = project_catalog_service.get_project(project)
    if row is None or row.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project(context, row.id, "Project")
    if row.kind != "NON_CODE":
        raise api_exception(status.HTTP_409_CONFLICT, "WATCH_NOT_FOR_PROJECT", "Chỉ dự án marketing mới có chủ đề nóng")
    try:
        return WatchTopicsOut.model_validate(topics_service.list(str(row.id))).model_dump()
    except WatchError as error:
        _raise(error)


@router.post("/watch-topics/refresh", response_model=WatchTopicsRequested, status_code=status.HTTP_202_ACCEPTED, openapi_extra=TOPIC_IDS)
async def refresh_topics(project: str = Query(..., min_length=1, max_length=64), context: AuthContext = Depends(require_member)) -> dict:
    row = _project(context, project)
    try:
        return WatchTopicsRequested.model_validate(topics_service.request_build(str(row.id), context.user_id)).model_dump()
    except WatchError as error:
        _raise(error)


@router.post("/watch-topics/{topic_id}/post", response_model=WorkDetail, status_code=status.HTTP_201_CREATED, openapi_extra=TOPIC_IDS)
async def topic_to_post(topic_id: str, payload: WatchTopicPost, project: str = Query(..., min_length=1, max_length=64), context: AuthContext = Depends(require_member)) -> dict:
    """Thành bài or Thành chuỗi: a post in Ý tưởng, with the topic's sources as links."""
    row = _project(context, project)
    try:
        made = topics_service.to_post(str(row.id), topic_id, actor_id=context.user_id, mode=payload.mode, angle=payload.angle, member_id=payload.member_id, week=payload.week)
    except WatchError as error:
        _raise(error)
    except WorkError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error))
    return WorkDetail.model_validate(made).model_dump()


@router.delete("/watch-topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra=TOPIC_IDS)
async def dismiss_topic(topic_id: str, project: str = Query(..., min_length=1, max_length=64), context: AuthContext = Depends(require_member)) -> Response:
    row = _project(context, project)
    try:
        topics_service.dismiss(str(row.id), topic_id, context.user_id)
    except WatchError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---- what the CTO opens for everyone

@router.get("/settings/watch-platforms", response_model=list[WatchPlatformOut], openapi_extra={"x-requirement-ids": ["FR-MKT-08", "FR-MKT-10"]})
async def get_platforms(context: AuthContext = Depends(require_account)) -> list[dict]:
    """Which networks are open, read by every login so the owner's page can say "cần CTO bật"."""
    return [WatchPlatformOut.model_validate(row).model_dump() for row in list_platforms()]


@router.put("/settings/watch-platforms/{code}", response_model=WatchPlatformOut, openapi_extra={"x-requirement-ids": ["FR-MKT-08"]})
async def put_platform(code: str, payload: WatchPlatformUpdate, context: AuthContext = Depends(require_cto)) -> dict:
    try:
        row = update_platform(code.upper(), payload.model_dump(exclude_unset=True), actor_id=context.user_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Network not found")
    except PlatformError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error))
    return WatchPlatformOut.model_validate(row).model_dump()


@router.get("/settings/publish-pause", response_model=PublishPauseOut, openapi_extra={"x-requirement-ids": ["FR-MKT-14"]})
async def get_publish_pause(context: AuthContext = Depends(require_account)) -> dict:
    """Whether the posting flow's queue for marketing posts is paused (the emergency stop)."""
    return {"paused": publishing.is_paused()}


@router.put("/settings/publish-pause", response_model=PublishPauseOut, openapi_extra={"x-requirement-ids": ["FR-MKT-14"]})
async def put_publish_pause(payload: PublishPauseUpdate, context: AuthContext = Depends(require_cto)) -> dict:
    return {"paused": publishing.set_paused(payload.paused, actor_id=context.user_id)}


@router.get("/settings/watch-limits", response_model=WatchLimitsOut, openapi_extra={"x-requirement-ids": ["FR-MKT-10"]})
async def get_watch_limits(context: AuthContext = Depends(require_account)) -> dict:
    return {"max_ai_runs_per_day": ai_runs_cap()}


@router.put("/settings/watch-limits", response_model=WatchLimitsOut, openapi_extra={"x-requirement-ids": ["FR-MKT-10"]})
async def put_watch_limits(payload: WatchLimitsUpdate, context: AuthContext = Depends(require_cto)) -> dict:
    try:
        return {"max_ai_runs_per_day": set_ai_runs_cap(payload.max_ai_runs_per_day, actor_id=context.user_id)}
    except PlatformError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error))
