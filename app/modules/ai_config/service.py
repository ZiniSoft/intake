"""CTO-managed LLM providers and per-task routes (FR-AI-15..19, ADR-0070). Keys go in encrypted and never come out."""
from __future__ import annotations

import ipaddress
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import AiProvider, AiRoute
from app.modules.ai_config.routing import ROUTE_KEYS, resolve_route
from app.services import raw_crypto

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
            if changes.get("base_url") is not None:
                row.base_url = clean_base_url(str(changes["base_url"]))
            if str(changes.get("api_key") or "").strip():
                row.api_key_enc = raw_crypto.encrypt(str(changes["api_key"]).strip())
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
            session.delete(row)
            session.commit()

    def list_routes(self) -> list[dict[str, object]]:
        with get_session() as session:
            rows = {row.task: row for row in session.scalars(select(AiRoute)).all()}
            names = {str(p.id): p.name for p in session.scalars(select(AiProvider)).all()}
        out: list[dict[str, object]] = []
        for key in ROUTE_KEYS:
            row = rows.get(key)
            resolved = resolve_route(key, get_settings())
            out.append({
                "task": key,
                "provider_id": str(row.provider_id) if row else None,
                "provider_name": names.get(str(row.provider_id)) if row else None,
                "model": row.model if row else None,
                "source": resolved.source if resolved else "none",
                "effective_provider": resolved.provider if resolved else None,
                "effective_model": resolved.model if resolved else None,
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
        models: list[str] = []
        error: str | None = None
        try:
            api_key = raw_crypto.decrypt(key_enc) if key_enc else None
        except Exception:  # noqa: BLE001
            api_key, error = None, "KEY_UNREADABLE"
        if error is None:
            try:
                async with httpx.AsyncClient(base_url=base_url, timeout=TEST_TIMEOUT_SECONDS, transport=self.transport) as client:
                    response = await client.get("/models", headers={"Authorization": f"Bearer {api_key}"} if api_key else {})
                if response.status_code in (401, 403):
                    error = "AUTH"
                elif response.status_code >= 400:
                    error = f"HTTP_{response.status_code}"
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


ai_config_service = AiConfigService()
