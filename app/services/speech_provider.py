"""Batch speech-to-text with speaker separation (ElevenLabs Scribe). Only the meeting gateway may call this."""
from __future__ import annotations

import time

import httpx

from app.config import get_settings


class SpeechProviderError(RuntimeError):
    def __init__(self, code: str, *, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


EXTENSIONS = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/wav": "wav", "audio/mpeg": "mp3"}


def build_turns(words: list[dict]) -> list[dict[str, object]]:
    """Merge the provider's word list into speaker turns, keeping the order speakers first appear in."""
    turns: list[dict[str, object]] = []
    for word in words:
        if word.get("type") == "audio_event":
            continue
        speaker = str(word.get("speaker_id") or "speaker_0")
        text = str(word.get("text") or "")
        if turns and turns[-1]["speaker"] == speaker:
            turns[-1]["text"] = f"{turns[-1]['text']}{text}"
            if word.get("end") is not None:
                turns[-1]["end_ms"] = int(float(word["end"]) * 1000)
            continue
        if not text.strip():
            continue
        turns.append({
            "speaker": speaker, "text": text,
            "start_ms": int(float(word["start"]) * 1000) if word.get("start") is not None else None,
            "end_ms": int(float(word["end"]) * 1000) if word.get("end") is not None else None,
        })
    order: dict[str, str] = {}
    for turn in turns:
        turn["text"] = str(turn["text"]).strip()
        label = order.setdefault(str(turn["speaker"]), f"Thành viên {len(order) + 1}")
        turn["speaker"] = label
    return [turn for turn in turns if turn["text"]]


def transcribe(audio: bytes, content_type: str, *, language: str, keyterms: list[str], max_speakers: int) -> dict[str, object]:
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        raise SpeechProviderError("PROVIDER_NOT_CONFIGURED", transient=False)
    # httpx encodes a list value as a repeated multipart field; a list of tuples is not accepted alongside files.
    data: dict[str, object] = {
        "model_id": settings.elevenlabs_batch_model, "language_code": language, "diarize": "true",
        "num_speakers": str(max(1, min(max_speakers, 32))), "timestamps_granularity": "word",
    }
    if keyterms:
        data["keyterms"] = list(keyterms)
    filename = f"meeting.{EXTENSIONS.get(content_type, 'webm')}"
    try:
        response = httpx.post(
            f"{settings.elevenlabs_base_url}/v1/speech-to-text",
            headers={"xi-api-key": settings.elevenlabs_api_key},
            data=data, files={"file": (filename, audio, content_type)}, timeout=600,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise SpeechProviderError("PROVIDER_UNAVAILABLE", transient=True) from exc
    if response.status_code == 429 or response.status_code >= 500:
        raise SpeechProviderError("PROVIDER_TRANSIENT", transient=True)
    if response.status_code >= 400:
        raise SpeechProviderError("PROVIDER_REJECTED", transient=False)
    payload = response.json()
    return {
        "transcription_id": payload.get("transcription_id"),
        "duration_seconds": int(float(payload["audio_duration_secs"])) if payload.get("audio_duration_secs") is not None else None,
        "turns": build_turns(payload.get("words") or []),
    }


def delete_transcript(transcription_id: str, attempts: int = 4) -> bool:
    """The provider answers 404 for a few seconds after creating a transcript, so deletion is retried."""
    settings = get_settings()
    for attempt in range(attempts):
        try:
            response = httpx.delete(
                f"{settings.elevenlabs_base_url}/v1/speech-to-text/transcripts/{transcription_id}",
                headers={"xi-api-key": settings.elevenlabs_api_key or ""}, timeout=30,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            response = None
        if response is not None and response.status_code == 200:
            return True
        if attempt + 1 < attempts:
            time.sleep(3)
    return False
