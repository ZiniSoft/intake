"""GitHub tokens the CTO adds on a screen (FR-INTG-21, ADR-0076). Stored encrypted; only a 4-character hint is shown."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, GithubToken, ProjectIntegration
from app.services import raw_crypto

NAME = re.compile(r"^GITHUB_TOKEN_[A-Z0-9_]{1,40}$")
LABEL = re.compile(r"[^A-Z0-9]+")


class GithubTokenError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def name_from(label: str) -> str:
    """"Khách A" becomes GITHUB_TOKEN_KHACH_A; a name already in the full form is kept."""
    raw = (label or "").strip()
    if NAME.match(raw):
        return raw
    import unicodedata

    plain = unicodedata.normalize("NFKD", raw).encode("ascii", "ignore").decode().upper()
    slug = LABEL.sub("_", plain).strip("_")[:40]
    if not slug:
        raise GithubTokenError("NAME_INVALID", "Give the token a short name made of letters and digits")
    return f"GITHUB_TOKEN_{slug}"


def _view(row: GithubToken, used_by: int) -> dict[str, object]:
    return {"name": row.name, "key_hint": row.key_hint, "used_by_projects": used_by, "updated_at": row.updated_at}


def list_tokens() -> list[dict[str, object]]:
    with get_session() as session:
        used: dict[str, int] = {}
        for ref in session.scalars(select(ProjectIntegration.credential_ref).where(ProjectIntegration.system == "GITHUB")).all():
            if ref:
                used[ref] = used.get(ref, 0) + 1
        return [_view(row, used.get(row.name, 0)) for row in session.scalars(select(GithubToken).order_by(GithubToken.name)).all()]


def put_token(label: str, token: str, actor_id: str) -> dict[str, object]:
    name, value = name_from(label), (token or "").strip()
    if len(value) < 20 or any(ch.isspace() for ch in value):
        raise GithubTokenError("TOKEN_INVALID", "That does not look like a GitHub token")
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(GithubToken, name)
        if row is None:
            row = GithubToken(name=name, token_enc=raw_crypto.encrypt(value) or "", key_hint=value[-4:], updated_by=actor_id, created_at=now, updated_at=now)
            session.add(row)
        else:
            row.token_enc, row.key_hint, row.updated_by, row.updated_at = raw_crypto.encrypt(value) or "", value[-4:], actor_id, now
        session.add(AuditEvent(
            id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="github_token.saved", entity_type="github_token",
            entity_id=None, details={"name": name}, created_at=now,
        ))
        session.commit()
        return _view(row, 0)


def delete_token(name: str, actor_id: str) -> None:
    with get_session() as session:
        row = session.get(GithubToken, name)
        if row is None:
            raise GithubTokenError("NOT_FOUND", "Token not found", 404)
        in_use = session.scalar(select(ProjectIntegration.id).where(ProjectIntegration.system == "GITHUB", ProjectIntegration.credential_ref == name, ProjectIntegration.enabled.is_(True)).limit(1))
        if in_use:
            raise GithubTokenError("TOKEN_IN_USE", "A project still uses this token; switch that project to another token first", 409)
        session.delete(row)
        session.add(AuditEvent(
            id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="github_token.deleted", entity_type="github_token",
            entity_id=None, details={"name": name}, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
