from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.security import AuthContext, require_cto
from app.modules.notify import linking
from app.modules.notify.reminders import recent_messages
from app.modules.planning import scope as planning_scope
from app.schemas import HolidaysUpdate, TelegramInviteOut, TelegramMessageOut, TelegramStatusOut

router = APIRouter(prefix="/notify", tags=["notify"])


@router.get("/telegram", response_model=TelegramStatusOut, openapi_extra={"x-requirement-ids": ["FR-NTF-02", "FR-NTF-03"]})
async def get_telegram_status(_: AuthContext = Depends(require_cto)) -> TelegramStatusOut:
    """Is the bot set up, which project groups and which people are linked, and the holidays."""
    return TelegramStatusOut.model_validate(linking.status())


@router.post("/telegram/members/{member_id}/invite", response_model=TelegramInviteOut, openapi_extra={"x-requirement-ids": ["FR-NTF-03"]})
async def create_telegram_invite(member_id: str, context: AuthContext = Depends(require_cto)) -> TelegramInviteOut:
    """A one-time link for one person: opening it in Telegram ties their private chat to this member."""
    created = linking.create_invite(member_id, context.user_id)
    if created is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")
    return TelegramInviteOut.model_validate(created)


@router.delete("/telegram/members/{member_id}/link", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-NTF-03"]})
async def unlink_telegram_member(member_id: str, context: AuthContext = Depends(require_cto)) -> None:
    if not linking.unlink_member(member_id, context.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Member not found")


@router.delete("/telegram/projects/{project_ref}/link", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-NTF-02"]})
async def unlink_telegram_project(project_ref: str, context: AuthContext = Depends(require_cto)) -> None:
    resolved = planning_scope.project_ids([project_ref])
    if not resolved or resolved[0] is None or not linking.unlink_project(str(resolved[0]), context.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")


@router.get("/holidays", openapi_extra={"x-requirement-ids": ["FR-NTF-04"]})
async def list_holidays(_: AuthContext = Depends(require_cto)) -> list[dict[str, object]]:
    return linking.holidays()


@router.put("/holidays", openapi_extra={"x-requirement-ids": ["FR-NTF-04"]})
async def replace_holidays(payload: HolidaysUpdate, context: AuthContext = Depends(require_cto)) -> list[dict[str, object]]:
    """The days reminders stay silent, besides weekends. The list given replaces the old one."""
    days: list[tuple[date, str | None]] = [(row.day, row.note) for row in payload.days]
    return linking.set_holidays(days, context.user_id)


@router.get("/telegram/messages", response_model=list[TelegramMessageOut], openapi_extra={"x-requirement-ids": ["FR-NTF-05"]})
async def list_telegram_messages(days: int = Query(default=7, ge=1, le=60), _: AuthContext = Depends(require_cto)) -> list[TelegramMessageOut]:
    """What the bot sent lately, and what it could not."""
    return [TelegramMessageOut.model_validate(row) for row in recent_messages(days)]
