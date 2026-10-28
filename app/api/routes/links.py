"""The short links of posts (FR-MKT-12): `/p/<code>` sends the visitor on and counts the click. No login, no envelope:
a browser follows a redirect, not JSON."""
from fastapi import APIRouter, Header, Response, status
from fastapi.responses import RedirectResponse

from app.modules.work.links import follow

router = APIRouter(tags=["short-links"])


@router.get("/p/{code}", openapi_extra={"x-requirement-ids": ["FR-MKT-12"]}, include_in_schema=True)
async def follow_short_link(code: str, referer: str | None = Header(default=None), user_agent: str | None = Header(default=None)) -> Response:
    target = follow(code, referrer=referer, user_agent=user_agent)
    if target is None:
        return Response(status_code=status.HTTP_404_NOT_FOUND, content="Not found", media_type="text/plain")
    return RedirectResponse(target, status_code=status.HTTP_302_FOUND, headers={"Cache-Control": "no-store"})
