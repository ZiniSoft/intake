"""Help inside the app (FR-UI-17): which page introductions a person has read, and how often each hint is opened.
The words of the hints live in the web build (frontend/src/hints.ts); the server only remembers and counts."""
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import func, select

from app.api.errors import api_exception
from app.api.security import AuthContext, require_account, require_cto
from app.db import get_session
from app.models import HintOpen, UserHintDismissal

router = APIRouter(prefix="/hints", tags=["hints"])

KEY = re.compile(r"^[a-z0-9_.-]{2,64}$", re.IGNORECASE)


def _key(value: str) -> str:
    if not KEY.match(value or ""):
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "HINT_KEY_INVALID", "Hint key must be short and plain")
    return value


@router.get("", response_model=dict, openapi_extra={"x-requirement-ids": ["FR-UI-17"]})
async def my_hints(context: AuthContext = Depends(require_account)) -> dict:
    """The page introductions this person has already read."""
    with get_session() as session:
        keys = session.scalars(select(UserHintDismissal.key).where(UserHintDismissal.user_id == context.user_id)).all()
    return {"dismissed": sorted(keys)}


@router.post("/{key}/dismiss", response_model=dict, openapi_extra={"x-requirement-ids": ["FR-UI-17"]})
async def dismiss_hint(key: str, context: AuthContext = Depends(require_account)) -> dict:
    key = _key(key)
    with get_session() as session:
        if session.get(UserHintDismissal, (context.user_id, key)) is None:
            session.add(UserHintDismissal(user_id=context.user_id, key=key, dismissed_at=datetime.now(timezone.utc)))
            session.commit()
        keys = session.scalars(select(UserHintDismissal.key).where(UserHintDismissal.user_id == context.user_id)).all()
    return {"dismissed": sorted(keys)}


@router.delete("/{key}/dismiss", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-UI-17"]})
async def undismiss_hint(key: str, context: AuthContext = Depends(require_account)) -> Response:
    key = _key(key)
    with get_session() as session:
        row = session.get(UserHintDismissal, (context.user_id, key))
        if row is not None:
            session.delete(row)
            session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{key}/opened", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-UI-17"]})
async def hint_opened(key: str, context: AuthContext = Depends(require_account)) -> Response:
    """One line per open, so the week shows which hints people reach for and which nobody needs."""
    key = _key(key)
    with get_session() as session:
        session.add(HintOpen(id=str(uuid4()), user_id=context.user_id, key=key, opened_at=datetime.now(timezone.utc)))
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/stats", response_model=dict, openapi_extra={"x-requirement-ids": ["FR-UI-17"]})
async def hint_stats(days: int = Query(default=7, ge=1, le=90), _: AuthContext = Depends(require_cto)) -> dict:
    """How often each hint was opened, and by how many people, over the last days. CTO only."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    with get_session() as session:
        rows = session.execute(
            select(HintOpen.key, func.count(), func.count(func.distinct(HintOpen.user_id)))
            .where(HintOpen.opened_at >= since).group_by(HintOpen.key).order_by(func.count().desc())
        ).all()
        read = session.execute(
            select(UserHintDismissal.key, func.count()).where(UserHintDismissal.dismissed_at >= since).group_by(UserHintDismissal.key)
        ).all()
    return {
        "days": days, "since": since,
        "opened": [{"key": key, "opens": int(opens), "people": int(people)} for key, opens, people in rows],
        "dismissed": [{"key": key, "people": int(people)} for key, people in read],
    }
