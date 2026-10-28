from fastapi import APIRouter, Depends

from app.api.security import AuthContext, require_member
from app.modules.changelog import changelog
from app.schemas import ChangelogOut

router = APIRouter(prefix="/changelog", tags=["changelog"])


@router.get("", response_model=ChangelogOut, openapi_extra={"x-requirement-ids": ["FR-UI-14"]})
async def get_changelog(context: AuthContext = Depends(require_member)) -> ChangelogOut:
    """What changed, newest first, with the build that is running. Entries for the CTO's private space stay with the CTO."""
    return ChangelogOut.model_validate(changelog(include_cto=context.role == "CTO"))
