"""The door for the posting flow that runs outside Intake (ADR-0038).

Intake holds no key that can post anywhere. A flow the owner builds elsewhere reads the approved posts here with a
read-only key, posts them, and calls back to say what happened. These two routes are the only ones reached without a
signed-in person, so each is closed until its own secret is set, and each checks that secret on every call.
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import ValidationError

from app.api.errors import api_exception
from app.config import get_settings
from app.modules.drafts.service import DraftError, draft_service
from app.modules.work import publishing
from app.schemas import PublishEvent, PublishEventOut, PublishQueueItem

router = APIRouter(prefix="/publish", tags=["publish"])

# A secret shorter than this is treated as not set: a short one can be guessed.
MIN_SECRET = 24
# How far the clock of the caller may be from ours, and so how long a captured call can be replayed.
MAX_SKEW_SECONDS = 300


def _secret(value: str | None) -> str:
    secret = (value or "").strip()
    if len(secret) < MIN_SECRET:
        # Not configured: the route does not exist as far as a caller can tell.
        raise api_exception(status.HTTP_404_NOT_FOUND, "NOT_FOUND", "Not found")
    return secret


def _denied() -> None:
    raise api_exception(status.HTTP_401_UNAUTHORIZED, "PUBLISH_UNAUTHORIZED", "Invalid credentials")


@router.get("/queue", response_model=list[PublishQueueItem], openapi_extra={"x-requirement-ids": ["FR-CNT-10", "NFR-SEC-03"]})
async def publish_queue(
    channel: str | None = Query(default=None, max_length=16),
    authorization: str = Header(default=""),
) -> list[PublishQueueItem]:
    """Approved posts that have not gone out yet, soonest first. `Authorization: Bearer <PUBLISH_API_KEY>`."""
    key = _secret(get_settings().publish_api_key)
    given = authorization[7:].strip() if authorization.startswith("Bearer ") else ""
    if not hmac.compare_digest(given.encode(), key.encode()):
        _denied()
    # The private space's drafts, then the marketing posts' versions on auto-publish channels (FR-MKT-14).
    rows = [{**row, "kind": "draft"} for row in draft_service.publish_queue(channel)] + publishing.queue(channel)
    return [PublishQueueItem.model_validate(row) for row in rows]


@router.post("/events", response_model=PublishEventOut, openapi_extra={"x-requirement-ids": ["FR-CNT-10", "NFR-SEC-03"]})
async def publish_event(
    request: Request,
    timestamp: str = Header(default="", alias="X-Intake-Timestamp"),
    signature: str = Header(default="", alias="X-Intake-Signature"),
) -> PublishEventOut:
    """The posting flow says a post went out, or failed.

    Signed: `X-Intake-Signature` is the hex HMAC-SHA256 of `<X-Intake-Timestamp>.<raw body>` with
    `PUBLISH_WEBHOOK_SECRET`; the timestamp is Unix seconds and must be within five minutes of now.
    """
    secret = _secret(get_settings().publish_webhook_secret)
    body = await request.body()
    if not timestamp.isdigit() or abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS:
        _denied()
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.strip().lower().encode(), expected.encode()):
        _denied()
    try:
        event = PublishEvent.model_validate_json(body)
    except ValidationError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "EVENT_INVALID", "The event does not match the expected shape") from error
    if event.draft_id.startswith(publishing.QUEUE_PREFIX):
        try:
            return PublishEventOut.model_validate(publishing.record(
                event.draft_id, posted=event.status == "POSTED", posted_at=event.posted_at, url=event.url, platform=event.platform, error=event.error,
            ))
        except publishing.PublishingError as error:
            code = status.HTTP_404_NOT_FOUND if error.code == "DRAFT_NOT_FOUND" else status.HTTP_409_CONFLICT
            raise api_exception(code, error.code, error.message) from error
    try:
        return PublishEventOut.model_validate(draft_service.record_publish(
            event.draft_id, posted=event.status == "POSTED", posted_at=event.posted_at, url=event.url,
            platform=event.platform, error=event.error,
        ))
    except DraftError as error:
        code = status.HTTP_404_NOT_FOUND if error.code == "DRAFT_NOT_FOUND" else status.HTTP_409_CONFLICT
        raise api_exception(code, error.code, error.message) from error
