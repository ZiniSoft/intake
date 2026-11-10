"""The company GitLab connected on a screen (FR-INTG-22, ADR-0080).

One row holds the GitLab address and a personal access token, encrypted like the GitHub tokens (ADR-0076); only the
last four characters are ever shown. The row wins over GITLAB_BASE_URL / GITLAB_TOKEN from the environment, which stay
as the fallback so an install configured through .env keeps working. The same token also reads the project context
file (scope read_repository); GITLAB_REPO_READ_TOKEN, when still set, is used for that read instead.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import AuditEvent, GitlabConnection, ProjectIntegration
from app.services import raw_crypto

ROW_ID = "default"
BASE_URL = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?(/[A-Za-z0-9._~\-/]*)?$")


class GitlabConnectionError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass(frozen=True)
class Credentials:
    base_url: str
    token: str
    source: str  # APP (saved on a screen), ENV (.env fallback) or NONE


def clean_base_url(value: str) -> str:
    """"https://gitlab.example.com/api/v4/" becomes "https://gitlab.example.com"."""
    url = (value or "").strip().rstrip("/")
    url = re.sub(r"/api/v4$", "", url).rstrip("/")
    if not BASE_URL.match(url):
        raise GitlabConnectionError("GITLAB_BASE_URL_INVALID", "The GitLab address must look like https://gitlab.example.com")
    return url


def _stored() -> tuple[str, str] | None:
    """The saved address and token. Any failure reads as "not saved", so the environment still answers."""
    try:
        with get_session() as session:
            row = session.get(GitlabConnection, ROW_ID)
            if row is None:
                return None
            token = (raw_crypto.decrypt(row.token_enc) or "").strip()
            return (row.base_url, token) if token else None
    except Exception:  # noqa: BLE001 - a missing table or a changed secret key must not hide the environment fallback
        return None


def credentials() -> Credentials:
    stored = _stored()
    if stored:
        return Credentials(base_url=stored[0], token=stored[1], source="APP")
    settings = get_settings()
    token = (settings.gitlab_token or "").strip()
    return Credentials(base_url=settings.gitlab_base_url or "", token=token, source="ENV" if token else "NONE")


def read_token() -> tuple[str, str]:
    """Address and token for reading repository files: the separate read token when one is still set, else the main one."""
    settings = get_settings()
    separate = (settings.gitlab_repo_read_token or "").strip()
    current = credentials()
    if separate:
        return current.base_url or settings.gitlab_base_url, separate
    return current.base_url, current.token


class EffectiveSettings:
    """The process settings with the GitLab address and token taken from the screen when saved there."""

    def __init__(self) -> None:
        self._settings = get_settings()
        current = credentials()
        self.gitlab_base_url = current.base_url
        self.gitlab_token = current.token or None
        self.gitlab_source = current.source

    def __getattr__(self, name: str):
        return getattr(self._settings, name)


def configured_in_app() -> bool:
    try:
        with get_session() as session:
            return session.get(GitlabConnection, ROW_ID) is not None
    except Exception:  # noqa: BLE001
        return False


def view() -> dict[str, object]:
    """What the screen shows: never the token, only its last four characters."""
    with get_session() as session:
        row = session.get(GitlabConnection, ROW_ID)
        linked = len(session.scalars(select(ProjectIntegration.id).where(
            ProjectIntegration.system == "GITLAB", ProjectIntegration.project_external_id.is_not(None),
        )).all())
        if row is None:
            source = "ENV" if (get_settings().gitlab_token or "").strip() else "NONE"
            return {"configured": False, "source": source, "base_url": get_settings().gitlab_base_url or "", "key_hint": "",
                    "updated_at": None, "linked_projects": linked}
        return {"configured": True, "source": "APP", "base_url": row.base_url, "key_hint": row.key_hint, "updated_at": row.updated_at,
                "linked_projects": linked}


def _audit(session, actor_id: str, event: str, details: dict, now: datetime) -> None:
    session.add(AuditEvent(
        id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type=event, entity_type="gitlab_connection",
        entity_id=None, details=details, created_at=now,
    ))


def save(base_url: str, token: str | None, actor_id: str) -> dict[str, object]:
    """Save the address and, when given, a new token. Saving switches GitLab on for the linked projects that were only
    off because GITLAB_INTEGRATION_ENABLED was false; a project moved to GitHub (ADR-0079) stays off."""
    url = clean_base_url(base_url)
    value = (token or "").strip()
    if value and (len(value) < 20 or any(ch.isspace() for ch in value)):
        raise GitlabConnectionError("TOKEN_INVALID", "That does not look like a GitLab token")
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(GitlabConnection, ROW_ID)
        if row is None:
            if not value:
                raise GitlabConnectionError("TOKEN_REQUIRED", "Paste the GitLab token")
            row = GitlabConnection(id=ROW_ID, base_url=url, token_enc=raw_crypto.encrypt(value) or "", key_hint=value[-4:],
                                   updated_by=actor_id, created_at=now, updated_at=now)
            session.add(row)
        else:
            row.base_url, row.updated_by, row.updated_at = url, actor_id, now
            if value:
                row.token_enc, row.key_hint = raw_crypto.encrypt(value) or "", value[-4:]
        enabled = 0
        for mapping in session.scalars(select(ProjectIntegration).where(
            ProjectIntegration.system == "GITLAB", ProjectIntegration.enabled.is_(False),
            ProjectIntegration.project_external_id.is_not(None),
        )).all():
            if (mapping.config or {}).get("previous"):
                continue
            mapping.enabled, mapping.base_url, mapping.updated_at = True, url, now
            enabled += 1
        _audit(session, actor_id, "gitlab_connection.saved", {"base_url": url, "token_changed": bool(value), "projects_enabled": enabled}, now)
        session.commit()
    return {**view(), "projects_enabled": enabled}


def delete(actor_id: str) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(GitlabConnection, ROW_ID)
        if row is None:
            raise GitlabConnectionError("NOT_FOUND", "No GitLab connection is saved on this screen", 404)
        session.delete(row)
        _audit(session, actor_id, "gitlab_connection.deleted", {}, now)
        session.commit()
