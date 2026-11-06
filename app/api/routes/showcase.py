from pydantic import BaseModel
from fastapi import APIRouter, Depends, status

from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto
from app.modules.showcase import service
from app.modules.showcase.service import ShowcaseError

router = APIRouter(prefix="/showcase", tags=["showcase"])


class ShowcaseItemOut(BaseModel):
    key: str
    kind: str
    group: str
    name: str
    summary: str
    repo_url: str
    languages: list[str]
    license: str
    state: str  # off | on | archived
    project_code: str | None = None
    sample_requests: int = 0
    in_catalog: bool = True


class ShowcaseOut(BaseModel):
    version: int
    groups: dict[str, str]
    items: list[ShowcaseItemOut]


class ShowcaseToggleIn(BaseModel):
    enabled: bool


class SamplesRemovedOut(BaseModel):
    removed: int


def _raise(error: ShowcaseError):
    code = status.HTTP_404_NOT_FOUND if error.code == "NOT_FOUND" else status.HTTP_422_UNPROCESSABLE_ENTITY
    if error.code in {"PROJECT_CODE_TAKEN", "DEMO_CODE_TAKEN"}:
        code = status.HTTP_409_CONFLICT
    return api_exception(code, error.code, error.message)


@router.get("", response_model=ShowcaseOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-15"]})
async def list_showcase(context: AuthContext = Depends(require_cto)) -> ShowcaseOut:
    return ShowcaseOut.model_validate(service.list_items())


@router.put("/{key}", response_model=ShowcaseOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-15"]})
async def toggle_showcase(key: str, payload: ShowcaseToggleIn, context: AuthContext = Depends(require_cto)) -> ShowcaseOut:
    try:
        return ShowcaseOut.model_validate(service.set_enabled(key, payload.enabled, context.user_id))
    except ShowcaseError as error:
        raise _raise(error) from error


@router.delete("/{key}/samples", response_model=SamplesRemovedOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-16"]})
async def remove_showcase_samples(key: str, context: AuthContext = Depends(require_cto)) -> SamplesRemovedOut:
    try:
        return SamplesRemovedOut(removed=service.remove_samples(key, context.user_id))
    except ShowcaseError as error:
        raise _raise(error) from error
