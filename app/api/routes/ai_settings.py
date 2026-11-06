from fastapi import APIRouter, Depends, Response, status

from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto
from app.modules.ai_config.service import AiConfigError, ai_config_service
from app.schemas import AiProbeIn, AiProbeOut, AiProviderIn, AiProviderOut, AiProviderPatch, AiProviderTestOut, AiRouteIn, AiRouteOut

router = APIRouter(prefix="/ai", tags=["ai-settings"])


def _fail(error: AiConfigError):
    return api_exception(error.status, error.code, error.message)


@router.get("/providers", response_model=list[AiProviderOut], openapi_extra={"x-requirement-ids": ["FR-AI-15", "FR-AI-16"]})
async def list_providers(context: AuthContext = Depends(require_cto)) -> list[AiProviderOut]:
    return [AiProviderOut.model_validate(row) for row in ai_config_service.list_providers()]


@router.post("/providers", response_model=AiProviderOut, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-AI-15", "FR-AI-16"]})
async def create_provider(payload: AiProviderIn, context: AuthContext = Depends(require_cto)) -> AiProviderOut:
    try:
        row = ai_config_service.create_provider(
            context.user_id, name=payload.name, base_url=payload.base_url, api_key=payload.api_key,
            enabled=payload.enabled, extra_body=payload.extra_body,
        )
    except AiConfigError as error:
        raise _fail(error) from error
    return AiProviderOut.model_validate(row)


@router.patch("/providers/{provider_id}", response_model=AiProviderOut, openapi_extra={"x-requirement-ids": ["FR-AI-15", "FR-AI-16"]})
async def update_provider(provider_id: str, payload: AiProviderPatch, context: AuthContext = Depends(require_cto)) -> AiProviderOut:
    try:
        row = ai_config_service.update_provider(context.user_id, provider_id, payload.model_dump(exclude_unset=True))
    except AiConfigError as error:
        raise _fail(error) from error
    return AiProviderOut.model_validate(row)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-AI-15"]})
async def delete_provider(provider_id: str, context: AuthContext = Depends(require_cto)) -> Response:
    try:
        ai_config_service.delete_provider(provider_id)
    except AiConfigError as error:
        raise _fail(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/providers/{provider_id}/test", response_model=AiProviderTestOut, openapi_extra={"x-requirement-ids": ["FR-AI-19"]})
async def test_provider(provider_id: str, context: AuthContext = Depends(require_cto)) -> AiProviderTestOut:
    try:
        return AiProviderTestOut.model_validate(await ai_config_service.test_provider(provider_id))
    except AiConfigError as error:
        raise _fail(error) from error


@router.post("/providers/{provider_id}/probe", response_model=AiProbeOut, openapi_extra={"x-requirement-ids": ["FR-AI-21"]})
async def probe_model(provider_id: str, payload: AiProbeIn, context: AuthContext = Depends(require_cto)) -> AiProbeOut:
    """A sample picture or a sample sound to one model; the outcome is kept as a code and steers picture reading."""
    try:
        return AiProbeOut.model_validate(await ai_config_service.probe(provider_id, payload.kind, payload.model))
    except AiConfigError as error:
        raise _fail(error) from error


@router.get("/routes", response_model=list[AiRouteOut], openapi_extra={"x-requirement-ids": ["FR-AI-17", "FR-AI-18"]})
async def list_routes(context: AuthContext = Depends(require_cto)) -> list[AiRouteOut]:
    return [AiRouteOut.model_validate(row) for row in ai_config_service.list_routes()]


@router.put("/routes/{task}", response_model=list[AiRouteOut], openapi_extra={"x-requirement-ids": ["FR-AI-17", "FR-AI-18"]})
async def put_route(task: str, payload: AiRouteIn, context: AuthContext = Depends(require_cto)) -> list[AiRouteOut]:
    try:
        rows = ai_config_service.set_route(context.user_id, task, payload.provider_id, payload.model)
    except AiConfigError as error:
        raise _fail(error) from error
    return [AiRouteOut.model_validate(row) for row in rows]
