"""The door for the posting flow that runs outside Intake (ADR-0038).

Intake holds no key that can post anywhere. A flow the owner builds elsewhere reads the approved posts here with a
read-only key, posts them, and calls back to say what happened. These two routes are the only ones reached without a
signed-in person, so each is closed until its own secret is set, and each checks that secret on every call.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, Query, Request, status
from pydantic import ValidationError

from app.api.errors import api_exception
from app.api.machine_auth import check_bearer, check_signature, configured
from app.config import get_settings
from app.modules.drafts.service import DraftError, draft_service
from app.modules.work import publishing
from app.schemas import PublishEvent, PublishEventOut, PublishQueueItem

router = APIRouter(prefix="/publish", tags=["publish"])

@router.get("/queue", response_model=list[PublishQueueItem], openapi_extra={"x-requirement-ids": ["FR-CNT-10", "NFR-SEC-03"]})
async def publish_queue(
    channel: str | None = Query(default=None, max_length=16),
    authorization: str = Header(default=""),
) -> list[PublishQueueItem]:
    """Approved posts that have not gone out yet, soonest first. `Authorization: Bearer <PUBLISH_API_KEY>`."""
    key = configured(get_settings().publish_api_key)
    check_bearer(key, authorization, "PUBLISH_UNAUTHORIZED")
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
    secret = configured(get_settings().publish_webhook_secret)
    body = await request.body()
    check_signature(secret, timestamp, signature, body, "PUBLISH_UNAUTHORIZED")
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
