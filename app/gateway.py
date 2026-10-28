"""Realtime meeting gateway: the only process that holds the speech-to-text provider key.

The browser streams 16 kHz mono PCM over a WebSocket; this service relays it to the provider and
sends transcripts back. Audio storage does not go through here, so a provider outage never loses a recording.
"""
from __future__ import annotations

import asyncio
import time
import base64
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect as provider_connect
from websockets.exceptions import ConnectionClosed, WebSocketException

from app.api.security import _decode_token
from app.config import get_settings
from app.db import init_db
from app.modules.identity.service import identity_service
from app.modules.meetings.service import meeting_service
from app.services import speech_provider


logger = logging.getLogger("intake.meeting.gateway")
PCM_SAMPLE_RATE = 16000
MAX_CLIENT_FRAME_BYTES = 64_000
PROVIDER_RECONNECT_LIMIT = 5


def transcribe_next() -> str | None:
    """Run the speaker-separated transcription for one finished meeting. Returns its ID, or None when idle."""
    settings = get_settings()
    meeting_id = meeting_service.claim_transcription()
    if meeting_id is None:
        return None
    try:
        source = meeting_service.transcription_input(meeting_id)
        result = speech_provider.transcribe(
            source["audio"], source["content_type"], language=source["language"],
            keyterms=source["keyterms"], max_speakers=settings.meeting_max_speakers,
        )
    except speech_provider.SpeechProviderError as exc:
        meeting_service.transcription_failed(meeting_id, exc.code, final=not exc.transient)
        return meeting_id
    except Exception as exc:  # storage or decoding problems must not stop the loop
        logger.exception("transcription failed for meeting %s", meeting_id)
        meeting_service.transcription_failed(meeting_id, type(exc).__name__, final=False)
        return meeting_id
    meeting_service.save_transcript(meeting_id, result["turns"], result["transcription_id"], result["duration_seconds"])
    return meeting_id


def delete_provider_copies() -> int:
    if not get_settings().elevenlabs_delete_after_meeting:
        return 0
    removed = 0
    for meeting_id, transcription_id in meeting_service.pending_provider_deletes():
        if speech_provider.delete_transcript(transcription_id):
            meeting_service.provider_deleted(meeting_id)
            removed += 1
    return removed


async def housekeeping() -> None:
    last_purge = 0.0
    while True:
        try:
            await asyncio.to_thread(meeting_service.fail_stale_recordings)
            if get_settings().meeting_capture_enabled and get_settings().elevenlabs_api_key:
                while await asyncio.to_thread(transcribe_next):
                    pass
                await asyncio.to_thread(delete_provider_copies)
            loop_time = asyncio.get_running_loop().time()
            if loop_time - last_purge > 3600:
                await asyncio.to_thread(meeting_service.purge_expired)
                last_purge = loop_time
        except Exception:
            logger.exception("meeting housekeeping failed")
        await asyncio.sleep(15)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    worker = asyncio.create_task(housekeeping()) if get_settings().meeting_background_enabled else None
    yield
    if worker is not None:
        worker.cancel()


app = FastAPI(title="Intake meeting gateway", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


@app.get("/gateway-health")
async def health() -> dict[str, object]:
    settings = get_settings()
    return {"status": "ok", "provider_configured": bool(settings.elevenlabs_api_key), "enabled": settings.meeting_capture_enabled}


def provider_url(language: str, keyterms: list[str]) -> str:
    settings = get_settings()
    parts = urlsplit(settings.elevenlabs_base_url)
    scheme = "wss" if parts.scheme == "https" else "ws"
    query = [
        ("model_id", settings.elevenlabs_realtime_model), ("language_code", language),
        ("audio_format", f"pcm_{PCM_SAMPLE_RATE}"), ("commit_strategy", "vad"),
        # The provider default (1.5 s) keeps a whole exchange in one segment; shorter pauses give readable lines.
        ("vad_silence_threshold_secs", "0.6"),
    ]
    query.extend(("keyterms", term) for term in keyterms)
    return f"{scheme}://{parts.netloc}/v1/speech-to-text/realtime?{urlencode(query)}"


def audio_message(chunk: bytes) -> str:
    return json.dumps({
        "message_type": "input_audio_chunk", "audio_base_64": base64.b64encode(chunk).decode(),
        "commit": False, "sample_rate": PCM_SAMPLE_RATE,
    })


HEALTH_INTERVAL_SECONDS = 5
PCM_BYTES_PER_SECOND = PCM_SAMPLE_RATE * 2


class StreamHealth:
    """Where the live transcript is slow, measured at the gateway: audio the browser sent that has not reached the
    provider yet (the server's own line out), gaps between the browser's frames (the line in), and the provider's
    round trip. The browser shows these so the slow leg can be named instead of guessed."""

    def __init__(self, now=None) -> None:
        self._now = now or time.monotonic
        self.received_bytes = 0
        self.sent_bytes = 0
        self.dropped = 0
        self.provider_rtt_ms: int | None = None
        self._last_frame_at: float | None = None
        self._max_gap_ms = 0

    def received(self, size: int) -> None:
        now = self._now()
        if self._last_frame_at is not None:
            self._max_gap_ms = max(self._max_gap_ms, int((now - self._last_frame_at) * 1000))
        self._last_frame_at = now
        self.received_bytes += size

    def sent(self, size: int) -> None:
        self.sent_bytes += size

    def event(self) -> dict:
        """One report; the gap resets so each report covers its own window."""
        report = {
            "type": "health",
            "backlog_seconds": round(max(self.received_bytes - self.sent_bytes, 0) / PCM_BYTES_PER_SECOND, 1),
            "client_gap_ms": self._max_gap_ms,
            "provider_rtt_ms": self.provider_rtt_ms,
            "dropped": self.dropped,
        }
        self._max_gap_ms = 0
        return report


def client_event(provider_message: dict) -> dict | None:
    """Translate a provider message into the small contract the browser understands."""
    kind = provider_message.get("message_type", "")
    if kind == "partial_transcript":
        return {"type": "partial", "text": provider_message.get("text", "")}
    if kind.startswith("committed_transcript"):
        return {"type": "committed", "text": provider_message.get("text", "")}
    if kind == "session_started":
        return {"type": "ready"}
    if "error" in kind or provider_message.get("error"):
        # Provider error text may echo request details; the browser only needs a stable code.
        return {"type": "error", "code": "PROVIDER_ERROR"}
    return None


def same_origin(websocket: WebSocket) -> bool:
    origin = websocket.headers.get("origin")
    if not origin:
        return False
    forwarded_host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host", "")
    return urlsplit(origin).netloc == forwarded_host


def authorize(websocket: WebSocket, meeting_id: str | None = None) -> str | None:
    settings = get_settings()
    token = websocket.cookies.get(settings.auth_cookie_name)
    if not token or not same_origin(websocket):
        return None
    try:
        subject, auth_version = _decode_token(token)
        context = identity_service.get_context(subject)
    except (HTTPException, KeyError):
        return None
    if context.must_change_password or auth_version != context.auth_version:
        return None
    if context.role == "CTO":
        return subject
    if context.role != "PROJECT_OWNER" or meeting_id is None:
        return None
    exists, project_id = meeting_service.project_of(meeting_id)
    return subject if exists and project_id is not None and project_id in (context.project_ids or frozenset()) else None


@app.websocket("/api/v1/meetings/{meeting_id}/stream")
async def stream(websocket: WebSocket, meeting_id: str) -> None:
    settings = get_settings()
    if authorize(websocket, meeting_id) is None:
        await websocket.close(code=4401)
        return
    context = meeting_service.recording_context(meeting_id) if settings.meeting_capture_enabled else None
    if context is None:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    if not settings.elevenlabs_api_key:
        await websocket.send_json({"type": "error", "code": "PROVIDER_NOT_CONFIGURED"})
        await websocket.close(code=4503)
        return

    queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=200)
    deadline: datetime = context["deadline"]
    health = StreamHealth()

    async def read_client() -> None:
        try:
            while True:
                chunk = await websocket.receive_bytes()
                if datetime.now(timezone.utc) >= deadline:
                    await websocket.send_json({"type": "limit", "code": "MEETING_MAX_MINUTES"})
                    break
                if 0 < len(chunk) <= MAX_CLIENT_FRAME_BYTES:
                    health.received(len(chunk))
                    if queue.full():
                        health.dropped += 1
                    else:
                        queue.put_nowait(chunk)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            await queue.put(None)

    async def relay_provider() -> None:
        url = provider_url(context["language"], context["keyterms"])
        for attempt in range(PROVIDER_RECONNECT_LIMIT):
            try:
                async with provider_connect(url, additional_headers={"xi-api-key": settings.elevenlabs_api_key}, max_size=2**20) as provider:
                    async def pump_audio() -> bool:
                        while True:
                            chunk = await queue.get()
                            if chunk is None:
                                # Commit what was said last and give the provider a moment to return it.
                                await provider.send(json.dumps({
                                    "message_type": "input_audio_chunk", "commit": True, "sample_rate": PCM_SAMPLE_RATE,
                                    "audio_base_64": base64.b64encode(bytes(3200)).decode(),
                                }))
                                await asyncio.sleep(2.5)
                                return True
                            await provider.send(audio_message(chunk))
                            health.sent(len(chunk))

                    async def report_health() -> None:
                        # Every few seconds: ping the provider for its round trip, then tell the browser how the
                        # three legs are doing.
                        while True:
                            await asyncio.sleep(HEALTH_INTERVAL_SECONDS)
                            try:
                                started = time.monotonic()
                                await asyncio.wait_for(await provider.ping(), timeout=HEALTH_INTERVAL_SECONDS)
                                health.provider_rtt_ms = int((time.monotonic() - started) * 1000)
                            except (asyncio.TimeoutError, ConnectionClosed):
                                health.provider_rtt_ms = None
                            try:
                                await websocket.send_json(health.event())
                            except RuntimeError:
                                return

                    async def pump_text() -> None:
                        async for raw in provider:
                            event = client_event(json.loads(raw))
                            if event is None:
                                continue
                            if event["type"] == "committed":
                                meeting_service.add_realtime_segment(meeting_id, event["text"])
                            await websocket.send_json(event)

                    text_task = asyncio.create_task(pump_text())
                    health_task = asyncio.create_task(report_health())
                    try:
                        finished = await pump_audio()
                    finally:
                        text_task.cancel()
                        health_task.cancel()
                    if finished:
                        return
            except (ConnectionClosed, WebSocketException, OSError) as exc:
                # The provider documents no session length; a dropped session is reopened while audio keeps flowing.
                logger.warning("provider session %s closed for meeting %s: %s", attempt + 1, meeting_id, type(exc).__name__)
                try:
                    await websocket.send_json({"type": "reconnecting"})
                except RuntimeError:
                    return
                await asyncio.sleep(min(2 ** attempt, 8))
        try:
            await websocket.send_json({"type": "error", "code": "PROVIDER_UNAVAILABLE"})
        except RuntimeError:
            pass

    reader = asyncio.create_task(read_client())
    try:
        await relay_provider()
    finally:
        reader.cancel()
        try:
            await websocket.close()
        except RuntimeError:
            pass
