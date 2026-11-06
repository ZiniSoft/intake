from datetime import datetime

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field

from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto
from app.modules.integrations import github_tokens

router = APIRouter(prefix="/integrations/github-tokens", tags=["integrations"])


class GithubTokenOut(BaseModel):
    name: str
    key_hint: str
    used_by_projects: int
    updated_at: datetime


class GithubTokenIn(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    token: str = Field(min_length=1, max_length=400)


def _fail(error: github_tokens.GithubTokenError):
    return api_exception(error.status, error.code, error.message)


@router.get("", response_model=list[GithubTokenOut], openapi_extra={"x-requirement-ids": ["FR-INTG-21"]})
async def list_tokens(_: AuthContext = Depends(require_cto)) -> list[GithubTokenOut]:
    return [GithubTokenOut.model_validate(row) for row in github_tokens.list_tokens()]


@router.put("", response_model=GithubTokenOut, openapi_extra={"x-requirement-ids": ["FR-INTG-21"]})
async def save_token(payload: GithubTokenIn, context: AuthContext = Depends(require_cto)) -> GithubTokenOut:
    try:
        return GithubTokenOut.model_validate(github_tokens.put_token(payload.label, payload.token, context.user_id))
    except github_tokens.GithubTokenError as error:
        raise _fail(error) from error


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-INTG-21"]})
async def delete_token(name: str, context: AuthContext = Depends(require_cto)) -> Response:
    try:
        github_tokens.delete_token(name, context.user_id)
    except github_tokens.GithubTokenError as error:
        raise _fail(error) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
