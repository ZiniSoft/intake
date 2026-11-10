from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto
from app.modules.integrations import gitlab_connection

router = APIRouter(prefix="/integrations/gitlab-connection", tags=["integrations"])


class GitlabConnectionOut(BaseModel):
    configured: bool
    # APP (saved on this screen), ENV (the .env fallback is in use) or NONE.
    source: str = "NONE"
    base_url: str
    key_hint: str
    updated_at: datetime | None = None
    linked_projects: int = 0
    projects_enabled: int | None = None


class GitlabConnectionIn(BaseModel):
    base_url: str = Field(min_length=1, max_length=255)
    # Left out to keep the saved token and change only the address.
    token: str | None = Field(default=None, max_length=400)


def _fail(error: gitlab_connection.GitlabConnectionError):
    return api_exception(error.status, error.code, error.message)


@router.get("", response_model=GitlabConnectionOut, openapi_extra={"x-requirement-ids": ["FR-INTG-22"]})
async def get_connection(_: AuthContext = Depends(require_cto)) -> GitlabConnectionOut:
    return GitlabConnectionOut.model_validate(gitlab_connection.view())


@router.put("", response_model=GitlabConnectionOut, openapi_extra={"x-requirement-ids": ["FR-INTG-22"]})
async def save_connection(payload: GitlabConnectionIn, context: AuthContext = Depends(require_cto)) -> GitlabConnectionOut:
    try:
        return GitlabConnectionOut.model_validate(gitlab_connection.save(payload.base_url, payload.token, context.user_id))
    except gitlab_connection.GitlabConnectionError as error:
        raise _fail(error) from error


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-INTG-22"]})
async def delete_connection(context: AuthContext = Depends(require_cto)) -> Response:
    try:
        gitlab_connection.delete(context.user_id)
    except gitlab_connection.GitlabConnectionError as error:
        raise _fail(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
