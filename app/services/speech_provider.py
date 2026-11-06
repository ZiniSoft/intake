"""Batch speech-to-text with speaker separation (ElevenLabs Scribe). Only the meeting gateway may call this."""
from __future__ import annotations

import base64
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.config import get_settings
from app.modules.ai_config.routing import db_route, is_elevenlabs, is_gemini


class SpeechProviderError(RuntimeError):
    def __init__(self, code: str, *, transient: bool) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


@dataclass(frozen=True)
class SttTarget:
    kind: str  # elevenlabs | openai_compatible | gemini
    base_url: str
    api_key: str
    model: str

    def __repr__(self) -> str:  # never print the key
        return f"SttTarget(kind={self.kind!r}, model={self.model!r})"

    @property
    def live_text(self) -> bool:
        return self.kind == "elevenlabs"


def target_for(base_url: str, api_key: str, model: str) -> SttTarget:
    """How one provider hears audio, picked from its host."""
    if is_elevenlabs(base_url) or is_gemini(base_url):
        parts = urlsplit(base_url)
        return SttTarget("elevenlabs" if is_elevenlabs(base_url) else "gemini", f"{parts.scheme}://{parts.netloc}", api_key, model)
    return SttTarget("openai_compatible", base_url.rstrip("/"), api_key, model)


def resolve_stt() -> SttTarget | None:
    """The route set on the screen wins; otherwise the ElevenLabs key in .env keeps serving an install that never set one."""
    settings = get_settings()
    route = db_route("stt")
    if route is not None:
        return target_for(route.base_url, route.api_key, route.model)
    if settings.elevenlabs_api_key:
        return SttTarget("elevenlabs", settings.elevenlabs_base_url, settings.elevenlabs_api_key, settings.elevenlabs_batch_model)
    return None


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


def _check(response: httpx.Response) -> None:
    if response.status_code == 429:
        # Still retried like any passing failure; the own code lets the screen say "out of quota" instead of "busy".
        raise SpeechProviderError("PROVIDER_QUOTA", transient=True)
    if response.status_code >= 500:
        raise SpeechProviderError("PROVIDER_TRANSIENT", transient=True)
    if response.status_code == 404:
        # Wrong model name, or one the provider retired for new keys; retrying the same name cannot help.
        raise SpeechProviderError("PROVIDER_MODEL_NOT_FOUND", transient=False)
    if response.status_code >= 400:
        raise SpeechProviderError("PROVIDER_REJECTED", transient=False)


# OpenAI and Groq refuse files over 25 MB and Gemini takes 20 MB inline; longer meetings go in slices of this length.
MAX_PIECE_BYTES = 20 * 1024 * 1024
SLICE_SECONDS = 600


def split_audio(audio: bytes, content_type: str, *, extension: str | None = None) -> list[tuple[bytes, str]]:
    """Cut a long recording into ten-minute pieces without re-encoding. A short one is returned as it is."""
    ext = extension or EXTENSIONS.get(content_type, "webm")
    if len(audio) <= MAX_PIECE_BYTES and extension is None:
        return [(audio, content_type)]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        if len(audio) <= MAX_PIECE_BYTES:
            return [(audio, content_type)]
        raise SpeechProviderError("AUDIO_TOO_LARGE", transient=False)
    with tempfile.TemporaryDirectory() as folder:
        source = Path(folder) / f"in.{EXTENSIONS.get(content_type, 'webm')}"
        source.write_bytes(audio)
        pattern = str(Path(folder) / f"piece-%04d.{ext}")
        try:
            done = subprocess.run(
                [ffmpeg, "-v", "error", "-i", str(source), "-vn", "-c:a", "copy", "-f", "segment",
                 "-segment_time", str(SLICE_SECONDS), "-reset_timestamps", "1", pattern],
                capture_output=True, timeout=300, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SpeechProviderError("AUDIO_SPLIT_FAILED", transient=False) from exc
        pieces = sorted(Path(folder).glob(f"piece-*.{ext}"))
        if done.returncode != 0 or not pieces:
            raise SpeechProviderError("AUDIO_SPLIT_FAILED", transient=False)
        mime = {"ogg": "audio/ogg", "webm": "audio/webm", "m4a": "audio/mp4", "mp3": "audio/mpeg", "wav": "audio/wav"}.get(ext, content_type)
        return [(piece.read_bytes(), mime) for piece in pieces]


def _one_block(text: str) -> dict[str, object]:
    turns = [{"speaker": "Thành viên 1", "text": text, "start_ms": None, "end_ms": None}] if text else []
    return {"transcription_id": None, "duration_seconds": None, "turns": turns}


def _transcribe_gemini(target: SttTarget, audio: bytes, content_type: str, *, language: str, keyterms: list[str]) -> dict[str, object]:
    """Gemini hears audio through generateContent, not an OpenAI-style endpoint. It takes ogg, not webm, so pieces are cut as ogg."""
    prompt = "Transcribe this audio word for word. Reply with the transcript only, no comments."
    if language:
        prompt += f" The language is {language}."
    if keyterms:
        prompt += " Names and terms that may appear: " + ", ".join(keyterms)[:800] + "."
    texts: list[str] = []
    for piece, mime in split_audio(audio, content_type, extension="ogg"):
        body = {"contents": [{"parts": [{"text": prompt}, {"inline_data": {"mime_type": mime, "data": base64.b64encode(piece).decode()}}]}]}
        try:
            response = httpx.post(
                f"{target.base_url}/v1beta/models/{target.model}:generateContent",
                headers={"x-goog-api-key": target.api_key}, json=body, timeout=600,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise SpeechProviderError("PROVIDER_UNAVAILABLE", transient=True) from exc
        _check(response)
        parts = (((response.json().get("candidates") or [{}])[0].get("content") or {}).get("parts")) or []
        texts.append("".join(str(part.get("text") or "") for part in parts).strip())
    return _one_block("\n\n".join(text for text in texts if text))


def _transcribe_openai(target: SttTarget, audio: bytes, content_type: str, *, language: str, keyterms: list[str]) -> dict[str, object]:
    """OpenAI and Groq share POST /audio/transcriptions. There is no speaker separation, so the text is one block."""
    texts = [_openai_piece(target, piece, mime, language=language, keyterms=keyterms) for piece, mime in split_audio(audio, content_type)]
    return _one_block("\n\n".join(text for text in texts if text))


def _openai_piece(target: SttTarget, audio: bytes, content_type: str, *, language: str, keyterms: list[str]) -> str:
    data: dict[str, str] = {"model": target.model, "response_format": "json"}
    if language:
        data["language"] = language.split("-")[0]
    if keyterms:
        data["prompt"] = ", ".join(keyterms)[:800]
    filename = f"meeting.{EXTENSIONS.get(content_type, 'webm')}"
    try:
        response = httpx.post(
            f"{target.base_url}/audio/transcriptions", headers={"Authorization": f"Bearer {target.api_key}"},
            data=data, files={"file": (filename, audio, content_type)}, timeout=600,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise SpeechProviderError("PROVIDER_UNAVAILABLE", transient=True) from exc
    if response.status_code == 413:
        raise SpeechProviderError("AUDIO_TOO_LARGE", transient=False)
    _check(response)
    return str(response.json().get("text") or "").strip()


def transcribe(audio: bytes, content_type: str, *, language: str, keyterms: list[str], max_speakers: int) -> dict[str, object]:
    target = resolve_stt()
    if target is None:
        raise SpeechProviderError("PROVIDER_NOT_CONFIGURED", transient=False)
    return transcribe_with(target, audio, content_type, language=language, keyterms=keyterms, max_speakers=max_speakers)


def transcribe_with(target: SttTarget, audio: bytes, content_type: str, *, language: str, keyterms: list[str], max_speakers: int) -> dict[str, object]:
    if target.kind == "gemini":
        return _transcribe_gemini(target, audio, content_type, language=language, keyterms=keyterms)
    if target.kind == "openai_compatible":
        return _transcribe_openai(target, audio, content_type, language=language, keyterms=keyterms)
    # httpx encodes a list value as a repeated multipart field; a list of tuples is not accepted alongside files.
    data: dict[str, object] = {
        "model_id": target.model, "language_code": language, "diarize": "true",
        "num_speakers": str(max(1, min(max_speakers, 32))), "timestamps_granularity": "word",
    }
    if keyterms:
        data["keyterms"] = list(keyterms)
    filename = f"meeting.{EXTENSIONS.get(content_type, 'webm')}"
    try:
        response = httpx.post(
            f"{target.base_url}/v1/speech-to-text",
            headers={"xi-api-key": target.api_key},
            data=data, files={"file": (filename, audio, content_type)}, timeout=600,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        raise SpeechProviderError("PROVIDER_UNAVAILABLE", transient=True) from exc
    _check(response)
    payload = response.json()
    return {
        "transcription_id": payload.get("transcription_id"),
        "duration_seconds": int(float(payload["audio_duration_secs"])) if payload.get("audio_duration_secs") is not None else None,
        "turns": build_turns(payload.get("words") or []),
    }


def delete_transcript(transcription_id: str, attempts: int = 4) -> bool:
    """The provider answers 404 for a few seconds after creating a transcript, so deletion is retried."""
    target = resolve_stt()
    if target is None or target.kind != "elevenlabs":
        return False
    for attempt in range(attempts):
        try:
            response = httpx.delete(
                f"{target.base_url}/v1/speech-to-text/transcripts/{transcription_id}",
                headers={"xi-api-key": target.api_key}, timeout=30,
            )
        except (httpx.TimeoutException, httpx.TransportError):
            response = None
        if response is not None and response.status_code == 200:
            return True
        if attempt + 1 < attempts:
            time.sleep(3)
    return False
