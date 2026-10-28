"""Doors for outside services into a marketing project (FR-MKT-13): the door itself, reached without a login with
the door's own secret; the CTO's screen to make, map, try and watch doors; the owner's read-only view."""
import json

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status

from app.api.errors import api_exception
from app.api.security import AuthContext, ensure_project, require_cto, require_member
from app.modules.projects.service import project_catalog_service
from app.modules.watch.connectors import BODY_LIMIT, ConnectorError, PRESETS, connector_service
from app.schemas import ConnectorBatchOut, ConnectorCreate, ConnectorDelivery, ConnectorOut, ConnectorSummary, ConnectorTryOut, ConnectorUpdate

router = APIRouter(tags=["watch-connectors"])
IDS = {"x-requirement-ids": ["FR-MKT-13", "NFR-SEC-03"]}
STATUS = {
    "NOT_FOUND": status.HTTP_404_NOT_FOUND, "CONNECTOR_NOT_FOUND": status.HTTP_404_NOT_FOUND, "UNAUTHORIZED": status.HTTP_401_UNAUTHORIZED,
    "BODY_TOO_LARGE": status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "WATCH_NOT_FOR_PROJECT": status.HTTP_409_CONFLICT, "CONNECTORS_FULL": status.HTTP_409_CONFLICT,
}


def _raise(error: ConnectorError) -> None:
    raise api_exception(STATUS.get(error.code, status.HTTP_422_UNPROCESSABLE_ENTITY), error.code, error.message) from error


def _project(context: AuthContext, reference: str):
    project = project_catalog_service.get_project(reference)
    if project is None or project.status != "ACTIVE":
        raise api_exception(status.HTTP_404_NOT_FOUND, "PROJECT_NOT_FOUND", "Project not found")
    ensure_project(context, project.id, "Project")
    if project.kind != "NON_CODE":
        raise api_exception(status.HTTP_409_CONFLICT, "WATCH_NOT_FOR_PROJECT", "Chỉ dự án marketing mới có cổng nhận")
    return project


# ---- the door itself: no login, the door's secret

@router.post("/watch/inbound/{connector_id}", response_model=ConnectorBatchOut, openapi_extra=IDS)
async def inbound(connector_id: str, request: Request, token: str = Header(default="", alias="X-Intake-Token"), authorization: str = Header(default="")) -> dict:
    """An outside service pushes its findings. `X-Intake-Token: <secret of this door>` (or `Authorization: Bearer`). JSON body, at most 512 KB."""
    body = await request.body()
    given = token.strip() or (authorization[7:].strip() if authorization.startswith("Bearer ") else "")
    if len(body) > BODY_LIMIT:
        try:
            connector_service.deliver(connector_id, given, None, size=len(body))
        except ConnectorError as error:
            _raise(error)
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "BATCH_INVALID", "The body is not JSON")
    try:
        return ConnectorBatchOut.model_validate(connector_service.deliver(connector_id, given, payload, size=len(body))).model_dump()
    except ConnectorError as error:
        _raise(error)


# ---- the CTO's doors

@router.get("/settings/watch-connectors", response_model=list[ConnectorOut], openapi_extra=IDS)
async def list_connectors(project: str = Query(..., min_length=1, max_length=64), context: AuthContext = Depends(require_cto)) -> list[dict]:
    row = _project(context, project)
    try:
        return [ConnectorOut.model_validate(item).model_dump() for item in connector_service.list(str(row.id))]
    except ConnectorError as error:
        _raise(error)


@router.get("/settings/watch-connectors/presets", response_model=dict, openapi_extra=IDS)
async def connector_presets(context: AuthContext = Depends(require_cto)) -> dict:
    return PRESETS


@router.post("/settings/watch-connectors", response_model=ConnectorOut, status_code=status.HTTP_201_CREATED, openapi_extra=IDS)
async def create_connector(payload: ConnectorCreate, context: AuthContext = Depends(require_cto)) -> dict:
    """A new door; the secret is in this answer only."""
    row = _project(context, payload.project)
    try:
        made = connector_service.create(str(row.id), name=payload.name, kind=payload.kind, via=payload.via, default_pillar=payload.default_pillar,
                                        mapping=payload.mapping.model_dump() if payload.mapping else None, actor_id=context.user_id)
    except ConnectorError as error:
        _raise(error)
    return ConnectorOut.model_validate(made).model_dump()


@router.patch("/settings/watch-connectors/{connector_id}", response_model=ConnectorOut, openapi_extra=IDS)
async def update_connector(connector_id: str, payload: ConnectorUpdate, context: AuthContext = Depends(require_cto)) -> dict:
    changes = {name: getattr(payload, name) for name in payload.model_fields_set}
    if "mapping" in changes and changes["mapping"] is not None:
        changes["mapping"] = payload.mapping.model_dump()
    try:
        return ConnectorOut.model_validate(connector_service.update(connector_id, changes, actor_id=context.user_id)).model_dump()
    except ConnectorError as error:
        _raise(error)


@router.post("/settings/watch-connectors/{connector_id}/rotate", response_model=ConnectorOut, openapi_extra=IDS)
async def rotate_connector(connector_id: str, context: AuthContext = Depends(require_cto)) -> dict:
    try:
        return ConnectorOut.model_validate(connector_service.rotate(connector_id, actor_id=context.user_id)).model_dump()
    except ConnectorError as error:
        _raise(error)


@router.delete("/settings/watch-connectors/{connector_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra=IDS)
async def delete_connector(connector_id: str, context: AuthContext = Depends(require_cto)) -> Response:
    try:
        connector_service.remove(connector_id, actor_id=context.user_id)
    except ConnectorError as error:
        _raise(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/settings/watch-connectors/{connector_id}/try", response_model=ConnectorTryOut, openapi_extra=IDS)
async def try_connector(connector_id: str, request: Request, context: AuthContext = Depends(require_cto)) -> dict:
    """What the door would make of this payload, without keeping anything."""
    body = await request.body()
    if len(body) > BODY_LIMIT:
        raise api_exception(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "BODY_TOO_LARGE", "The payload is too large")
    try:
        payload = json.loads(body or b"null")
    except ValueError:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "BATCH_INVALID", "The body is not JSON")
    try:
        return ConnectorTryOut.model_validate(connector_service.try_payload(connector_id, payload)).model_dump()
    except ConnectorError as error:
        _raise(error)


@router.get("/settings/watch-connectors/{connector_id}/deliveries", response_model=list[ConnectorDelivery], openapi_extra=IDS)
async def connector_deliveries(connector_id: str, context: AuthContext = Depends(require_cto)) -> list[dict]:
    try:
        return [ConnectorDelivery.model_validate(row).model_dump() for row in connector_service.deliveries(connector_id)]
    except ConnectorError as error:
        _raise(error)


# ---- the owner's view

@router.get("/projects/{code}/watch/connectors", response_model=list[ConnectorSummary], openapi_extra=IDS)
async def project_connectors(code: str, context: AuthContext = Depends(require_member)) -> list[dict]:
    row = _project(context, code)
    try:
        return [ConnectorSummary.model_validate(item).model_dump() for item in connector_service.summary(str(row.id))]
    except ConnectorError as error:
        _raise(error)
