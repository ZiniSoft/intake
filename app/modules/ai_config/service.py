"""CTO-managed LLM providers and per-task routes (FR-AI-15..19, ADR-0070). Keys go in encrypted and never come out."""
from __future__ import annotations

import asyncio
import base64
import io
import ipaddress
import wave
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_session
from app.models import AiModelCheck, AiProvider, AiRoute
from app.modules.ai_config.routing import ROUTE_KEYS, ResolvedRoute, is_elevenlabs, resolve_route
from app.services import raw_crypto, speech_provider

BLOCKED_HOSTS = {"metadata.google.internal", "metadata"}
TEST_TIMEOUT_SECONDS = 15


class AiConfigError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def clean_base_url(value: str) -> str:
    """http or https only, and never a link-local address (cloud metadata); private addresses stay allowed for Ollama."""
    url = (value or "").strip().rstrip("/")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not host:
        raise AiConfigError("AI_BASE_URL_INVALID", "Base URL phải bắt đầu bằng http:// hoặc https://")
    blocked = host in BLOCKED_HOSTS
    try:
        address = ipaddress.ip_address(host)
        blocked = blocked or address.is_link_local or address.is_unspecified or address.is_multicast
    except ValueError:
        pass
    if blocked:
        raise AiConfigError("AI_BASE_URL_INVALID", "Base URL này không được dùng")
    return url


def _key_state(row: AiProvider) -> tuple[str, bool]:
    if not row.api_key_enc:
        return "", False
    try:
        return (raw_crypto.decrypt(row.api_key_enc) or "")[-4:], True
    except Exception:  # noqa: BLE001 - SECRET_KEY changed since the key was saved
        return "", False


def _view(row: AiProvider) -> dict[str, object]:
    hint, ok = _key_state(row)
    return {
        "id": str(row.id), "name": row.name, "base_url": row.base_url, "enabled": row.enabled,
        "key_hint": hint, "key_ok": ok, "extra_body": row.extra_body,
        "last_test_at": row.last_test_at, "last_test_ok": row.last_test_ok, "last_test_error": row.last_test_error,
    }


def _clean_name(value: str) -> str:
    name = (value or "").strip()
    if not name or len(name) > 32:
        raise AiConfigError("AI_PROVIDER_NAME_INVALID", "Tên nhà cung cấp dài 1 đến 32 ký tự")
    return name


def _test_headers(base_url: str, api_key: str | None) -> dict[str, str]:
    """Bearer for OpenAI-compatible hosts; Anthropic's native model list also wants x-api-key and a version header (without them it answers 400)."""
    if not api_key:
        return {}
    headers = {"Authorization": f"Bearer {api_key}"}
    if (urlparse(base_url).hostname or "") == "api.anthropic.com":
        headers.update({"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    return headers


def _elevenlabs_key_valid_but_scoped(response: httpx.Response) -> bool:
    """ElevenLabs answers 401 status=missing_permissions when a restricted key is real but lacks the user_read scope."""
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return False
    return isinstance(detail, dict) and detail.get("status") == "missing_permissions"


def _check_view(checks: dict, task: str, provider_id: str | None, model: str | None) -> dict[str, object]:
    """Whether the model that serves the row passed its sample (None = not tried). The `default` row reports the
    picture check, so the screen can say the text model cannot read pictures."""
    kind = "vision" if task == "default" else task
    check = checks.get((provider_id, model, kind)) if kind in PROBE_KINDS and provider_id and model else None
    return {
        "check_ok": check.ok if check else None,
        "check_error": check.error if check else None,
        "checked_at": check.checked_at if check else None,
    }


class AiConfigService:
    # Tests point this at an httpx.MockTransport.
    transport: httpx.AsyncBaseTransport | None = None

    def list_providers(self) -> list[dict[str, object]]:
        with get_session() as session:
            rows = session.scalars(select(AiProvider).order_by(AiProvider.name)).all()
            return [_view(row) for row in rows]

    def create_provider(self, actor_id: str, *, name: str, base_url: str, api_key: str, enabled: bool = True, extra_body: dict | None = None) -> dict[str, object]:
        clean = _clean_name(name)
        url = clean_base_url(base_url)
        if not (api_key or "").strip():
            raise AiConfigError("AI_KEY_REQUIRED", "Cần nhập khóa API")
        with get_session() as session:
            if session.scalar(select(AiProvider.id).where(AiProvider.name == clean)) is not None:
                raise AiConfigError("AI_PROVIDER_NAME_TAKEN", "Tên này đã có", 409)
            row = AiProvider(id=str(uuid4()), name=clean, base_url=url, api_key_enc=raw_crypto.encrypt(api_key.strip()),
                             extra_body=extra_body or None, enabled=enabled, updated_by=actor_id)
            session.add(row)
            session.commit()
            return _view(row)

    def update_provider(self, actor_id: str, provider_id: str, changes: dict[str, object]) -> dict[str, object]:
        with get_session() as session:
            row = session.get(AiProvider, provider_id)
            if row is None:
                raise AiConfigError("AI_PROVIDER_NOT_FOUND", "Không thấy nhà cung cấp này", 404)
            if changes.get("name") is not None:
                name = _clean_name(str(changes["name"]))
                taken = session.scalar(select(AiProvider.id).where(AiProvider.name == name, AiProvider.id != row.id))
                if taken is not None:
                    raise AiConfigError("AI_PROVIDER_NAME_TAKEN", "Tên này đã có", 409)
                row.name = name
            stale = False
            if changes.get("base_url") is not None:
                url = clean_base_url(str(changes["base_url"]))
                stale = url != row.base_url
                row.base_url = url
            if str(changes.get("api_key") or "").strip():
                row.api_key_enc = raw_crypto.encrypt(str(changes["api_key"]).strip())
                stale = True
            if stale:
                # Another key or host may reach other models; the old checks no longer say anything.
                session.execute(delete(AiModelCheck).where(AiModelCheck.provider_id == row.id))
            if changes.get("enabled") is not None:
                row.enabled = bool(changes["enabled"])
            if "extra_body" in changes:
                row.extra_body = changes["extra_body"] or None  # type: ignore[assignment]
            row.updated_by, row.updated_at = actor_id, datetime.now(timezone.utc)
            session.commit()
            return _view(row)

    def delete_provider(self, provider_id: str) -> None:
        with get_session() as session:
            row = session.get(AiProvider, provider_id)
            if row is None:
                raise AiConfigError("AI_PROVIDER_NOT_FOUND", "Không thấy nhà cung cấp này", 404)
            if session.scalar(select(AiRoute.task).where(AiRoute.provider_id == row.id)) is not None:
                raise AiConfigError("PROVIDER_IN_USE", "Còn tác vụ đang dùng nhà cung cấp này; đổi hoặc xóa route trước", 409)
            session.execute(delete(AiModelCheck).where(AiModelCheck.provider_id == row.id))
            session.delete(row)
            session.commit()

    def list_routes(self) -> list[dict[str, object]]:
        with get_session() as session:
            rows = {row.task: row for row in session.scalars(select(AiRoute)).all()}
            providers = session.scalars(select(AiProvider)).all()
            names = {str(p.id): p.name for p in providers}
            ids = {p.name: str(p.id) for p in providers}
            checks = {(str(c.provider_id), c.model, c.kind): c for c in session.scalars(select(AiModelCheck)).all()}
        out: list[dict[str, object]] = []
        for key in ROUTE_KEYS:
            row = rows.get(key)
            resolved = resolve_route(key, get_settings())
            if key == "stt" and resolved is None and get_settings().elevenlabs_api_key:
                # The old .env ElevenLabs key still serves meetings until a route is set on the screen.
                s = get_settings()
                resolved = ResolvedRoute("ELEVENLABS", s.elevenlabs_base_url, "", s.elevenlabs_batch_model, None, "env")
            out.append({
                "task": key,
                "provider_id": str(row.provider_id) if row else None,
                "provider_name": names.get(str(row.provider_id)) if row else None,
                "model": row.model if row else None,
                "source": resolved.source if resolved else "none",
                "effective_provider": resolved.provider if resolved else None,
                "effective_model": resolved.model if resolved else None,
                **_check_view(checks, key, ids.get(resolved.provider) if resolved else None, resolved.model if resolved else None),
            })
        return out

    def set_route(self, actor_id: str, task: str, provider_id: str | None, model: str | None) -> list[dict[str, object]]:
        if task not in ROUTE_KEYS:
            raise AiConfigError("AI_TASK_UNKNOWN", "Tác vụ không có trong danh sách", 404)
        with get_session() as session:
            row = session.get(AiRoute, task)
            if provider_id is None:
                if row is not None:
                    session.delete(row)
                    session.commit()
                return self.list_routes()
            clean_model = (model or "").strip()
            if not clean_model or len(clean_model) > 128:
                raise AiConfigError("AI_MODEL_INVALID", "Cần nhập tên model (tối đa 128 ký tự)")
            if session.get(AiProvider, provider_id) is None:
                raise AiConfigError("AI_PROVIDER_NOT_FOUND", "Không thấy nhà cung cấp này", 422)
            now = datetime.now(timezone.utc)
            if row is None:
                session.add(AiRoute(task=task, provider_id=provider_id, model=clean_model, updated_by=actor_id, updated_at=now))
            else:
                row.provider_id, row.model, row.updated_by, row.updated_at = provider_id, clean_model, actor_id, now
            session.commit()
        return self.list_routes()

    async def test_provider(self, provider_id: str) -> dict[str, object]:
        """GET {base_url}/models; the outcome is saved as a code, never the provider's own message."""
        with get_session() as session:
            row = session.get(AiProvider, provider_id)
            if row is None:
                raise AiConfigError("AI_PROVIDER_NOT_FOUND", "Không thấy nhà cung cấp này", 404)
            base_url, key_enc = row.base_url, row.api_key_enc
        elevenlabs = is_elevenlabs(base_url)
        models: list[str] = []
        error: str | None = None
        try:
            api_key = raw_crypto.decrypt(key_enc) if key_enc else None
        except Exception:  # noqa: BLE001
            api_key, error = None, "KEY_UNREADABLE"
        if error is None:
            try:
                if elevenlabs:
                    # ElevenLabs has no OpenAI-style model list; the account endpoint proves the key, and Scribe models are fixed.
                    parts = urlparse(base_url)
                    async with httpx.AsyncClient(base_url=f"{parts.scheme}://{parts.netloc}", timeout=TEST_TIMEOUT_SECONDS, transport=self.transport) as client:
                        response = await client.get("/v1/user", headers={"xi-api-key": api_key or ""})
                else:
                    async with httpx.AsyncClient(base_url=base_url, timeout=TEST_TIMEOUT_SECONDS, transport=self.transport) as client:
                        response = await client.get("/models", headers=_test_headers(base_url, api_key))
                if elevenlabs and response.status_code in (401, 403) and _elevenlabs_key_valid_but_scoped(response):
                    # A key limited to Speech to Text cannot read the account, yet the provider accepted it.
                    models = ["scribe_v2"]
                elif response.status_code in (401, 403):
                    error = "AUTH"
                elif response.status_code >= 400:
                    error = f"HTTP_{response.status_code}"
                elif elevenlabs:
                    models = ["scribe_v2"]
                else:
                    try:
                        models = sorted({str(item["id"]) for item in response.json().get("data", []) if isinstance(item, dict) and item.get("id")})
                    except (ValueError, AttributeError):
                        models = []
            except httpx.TimeoutException:
                error = "TIMEOUT"
            except httpx.HTTPError:
                error = "NETWORK"
        with get_session() as session:
            row = session.get(AiProvider, provider_id)
            if row is not None:
                row.last_test_at, row.last_test_ok, row.last_test_error = datetime.now(timezone.utc), error is None, error
                session.commit()
        return {"ok": error is None, "error": error, "models": models}

    def _provider_secret(self, provider_id: str) -> tuple[str, str]:
        with get_session() as session:
            row = session.get(AiProvider, provider_id)
            if row is None:
                raise AiConfigError("AI_PROVIDER_NOT_FOUND", "Không thấy nhà cung cấp này", 404)
            base_url, key_enc = row.base_url, row.api_key_enc
        try:
            return base_url, (raw_crypto.decrypt(key_enc) if key_enc else "") or ""
        except Exception:  # noqa: BLE001
            return base_url, ""

    async def probe(self, provider_id: str, kind: str, model: str) -> dict[str, object]:
        """Send a sample picture or a sample sound to one model and keep whether it worked (FR-AI-21, ADR-0077)."""
        if kind not in PROBE_KINDS:
            raise AiConfigError("AI_PROBE_KIND_INVALID", "Chỉ thử được ảnh hoặc âm thanh")
        clean_model = (model or "").strip()
        if not clean_model or len(clean_model) > 128:
            raise AiConfigError("AI_MODEL_INVALID", "Cần nhập tên model (tối đa 128 ký tự)")
        base_url, api_key = self._provider_secret(provider_id)
        if not api_key:
            error: str | None = "KEY_UNREADABLE"
        elif kind == "vision":
            error = await self._probe_vision(base_url, api_key, clean_model)
        else:
            error = await self._probe_stt(base_url, api_key, clean_model)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            if session.get(AiProvider, provider_id) is not None:
                row = session.get(AiModelCheck, (provider_id, clean_model, kind))
                if row is None:
                    session.add(AiModelCheck(provider_id=provider_id, model=clean_model, kind=kind, ok=error is None, error=error, checked_at=now))
                else:
                    row.ok, row.error, row.checked_at = error is None, error, now
                session.commit()
        return {"kind": kind, "model": clean_model, "ok": error is None, "error": error, "checked_at": now}

    async def _probe_vision(self, base_url: str, api_key: str, model: str) -> str | None:
        if is_elevenlabs(base_url):
            return "NOT_SUPPORTED"
        payload = {
            "model": model, "temperature": 0, "stream": False,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": "What number is written in this picture? Reply with the number only."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64," + base64.b64encode(sample_picture()).decode("ascii")}},
            ]}],
        }
        try:
            async with httpx.AsyncClient(base_url=base_url, timeout=PROBE_TIMEOUT_SECONDS, transport=self.transport) as client:
                response = await client.post("/chat/completions", json=payload, headers=_test_headers(base_url, api_key))
        except httpx.TimeoutException:
            return "TIMEOUT"
        except httpx.HTTPError:
            return "NETWORK"
        if response.status_code in (401, 403):
            return "AUTH"
        if response.status_code == 429:
            # Out of quota, or a model the key's plan does not include (Gemini free tier answers 429 at once).
            return "QUOTA"
        if response.status_code == 404:
            # Wrong name, or a model the provider retired for new keys (Gemini 2.5 answers 404 with the newer name to use).
            return "MODEL_NOT_FOUND"
        if response.status_code >= 500:
            return "PROVIDER_TRANSIENT"
        if response.status_code >= 400:
            # Most text-only models answer 400 when a message carries an image.
            return "NOT_SUPPORTED" if response.status_code in (400, 415, 422) else f"HTTP_{response.status_code}"
        try:
            message = (response.json().get("choices") or [{}])[0].get("message") or {}
            content = message.get("content")
            text = content if isinstance(content, str) else " ".join(str(part.get("text") or "") for part in content or [] if isinstance(part, dict))
        except (ValueError, AttributeError, IndexError):
            return "NOT_READ"
        return None if PROBE_NUMBER in text.replace(" ", "") else "NOT_READ"

    async def _probe_stt(self, base_url: str, api_key: str, model: str) -> str | None:
        target = speech_provider.target_for(base_url, api_key, model)
        try:
            await asyncio.to_thread(
                speech_provider.transcribe_with, target, sample_sound(), "audio/wav",
                language="vi", keyterms=[], max_speakers=1,
            )
        except speech_provider.SpeechProviderError as exc:
            return {"PROVIDER_REJECTED": "NOT_SUPPORTED", "PROVIDER_MODEL_NOT_FOUND": "MODEL_NOT_FOUND", "PROVIDER_UNAVAILABLE": "NETWORK", "PROVIDER_QUOTA": "QUOTA"}.get(exc.code, exc.code)
        except (ValueError, KeyError, AttributeError, IndexError):
            return "NOT_READ"
        return None


PROBE_KINDS = ("vision", "stt")
PROBE_TIMEOUT_SECONDS = 45
PROBE_NUMBER = "482"


def sample_picture() -> bytes:
    """A small PNG with a number on it; a model that reads images answers with that number."""
    import fitz  # pymupdf

    document = fitz.open()
    page = document.new_page(width=360, height=160)
    page.insert_text((40, 110), f"INTAKE {PROBE_NUMBER}", fontsize=48)
    picture = page.get_pixmap(dpi=96).tobytes("png")
    document.close()
    return picture


def sample_sound() -> bytes:
    """One and a half seconds of silence as WAV; a speech-to-text model accepts it and returns empty text."""
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\x00\x00" * 24000)
    return buffer.getvalue()


ai_config_service = AiConfigService()
