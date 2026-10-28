"""Which provider, model and key serve an AI task (FR-AI-17, FR-AI-18, ADR-0070).

Order: the task's own route, then the `default` route, then the old `.env` settings, then nothing. A route whose
provider is switched off or whose key cannot be decrypted is skipped, so a half-set screen never breaks a worker.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings, get_settings
from app.db import get_session
from app.models import AiProvider, AiRoute
from app.services import raw_crypto

logger = logging.getLogger(__name__)

TASKS = ("normalize", "report", "meeting", "vision", "content")
ROUTE_KEYS = ("default", *TASKS)
ENV_PROVIDER_NAME = "UMODELVERSE"


@dataclass(frozen=True)
class ResolvedRoute:
    provider: str
    base_url: str
    api_key: str
    model: str
    extra_body: dict | None
    source: str  # route | default | env

    def __repr__(self) -> str:  # never print the key
        return f"ResolvedRoute(provider={self.provider!r}, model={self.model!r}, source={self.source!r})"


def _from_db(task: str) -> ResolvedRoute | None:
    try:
        with get_session() as session:
            for key in (task, "default"):
                route = session.get(AiRoute, key)
                if route is None:
                    continue
                provider = session.get(AiProvider, route.provider_id)
                if provider is None or not provider.enabled or not provider.api_key_enc:
                    continue
                try:
                    api_key = raw_crypto.decrypt(provider.api_key_enc)
                except Exception:  # noqa: BLE001 - a changed SECRET_KEY leaves the key unreadable
                    logger.warning("AI provider %s key cannot be decrypted", provider.name)
                    continue
                if not api_key:
                    continue
                return ResolvedRoute(
                    provider.name, provider.base_url, api_key, route.model, provider.extra_body,
                    "route" if key == task else "default",
                )
    except SQLAlchemyError:
        logger.warning("AI routes could not be read; falling back to .env", exc_info=True)
    return None


def _from_env(task: str, settings: Settings) -> ResolvedRoute | None:
    if not settings.umodelverse_api_key:
        return None
    model = settings.umodelverse_vision_model if task == "vision" else settings.umodelverse_model
    return ResolvedRoute(ENV_PROVIDER_NAME, settings.umodelverse_base_url, settings.umodelverse_api_key, model, None, "env")


def resolve_route(task: str, settings: Settings | None = None) -> ResolvedRoute | None:
    key = task if task in TASKS else "default"
    return _from_db(key) or _from_env(key, settings or get_settings())


def db_route(task: str) -> ResolvedRoute | None:
    """Only a route set on the screen; the old two-provider chain keeps serving the install that never set one."""
    return _from_db(task if task in TASKS else "default")
