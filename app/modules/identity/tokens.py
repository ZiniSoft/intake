"""Personal tokens: a person lets an agent (Codex, Claude Code, Claude Desktop) call Intake as them (FR-MCP-01).

A token is shown once, stored hashed, carries the person's own role and projects, and can be revoked any time.
It is minted from a signed-in session only, never from another token.
"""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import ApiToken, User

TOKEN_PREFIX = "itk_"
TOKEN_DAYS = 365
TOKEN_LIMIT = 10
# How often last_used_at is written: a token is used on every tool call, and the row need not follow each one.
TOUCH_EVERY = timedelta(minutes=5)


def _hash(plain: str) -> str:
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def _aware(value: datetime | None) -> datetime | None:
    return value if value is None or value.tzinfo else value.replace(tzinfo=timezone.utc)


class ApiTokenService:
    @staticmethod
    def _dict(row: ApiToken) -> dict[str, object]:
        return {
            "id": str(row.id), "name": row.name, "prefix": row.prefix, "created_at": row.created_at,
            "last_used_at": row.last_used_at, "expires_at": row.expires_at, "revoked_at": row.revoked_at,
        }

    def issue(self, user_id: str, name: str) -> dict[str, object]:
        plain = TOKEN_PREFIX + secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            live = session.scalars(select(ApiToken).where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None))).all()
            if len(live) >= TOKEN_LIMIT:
                raise ValueError("TOKEN_LIMIT")
            row = ApiToken(
                id=str(uuid4()), user_id=user_id, name=" ".join(name.split())[:80] or "Token", token_hash=_hash(plain),
                prefix=plain[:12], created_at=now, expires_at=now + timedelta(days=TOKEN_DAYS),
            )
            session.add(row)
            session.commit()
            return {**self._dict(row), "token": plain}

    def list(self, user_id: str) -> list[dict[str, object]]:
        with get_session() as session:
            rows = session.scalars(select(ApiToken).where(ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None)).order_by(ApiToken.created_at.desc())).all()
            return [self._dict(row) for row in rows]

    def revoke(self, user_id: str, token_id: str) -> bool:
        with get_session() as session:
            row = session.get(ApiToken, token_id)
            if row is None or str(row.user_id) != str(user_id) or row.revoked_at is not None:
                return False
            row.revoked_at = datetime.now(timezone.utc)
            session.commit()
            return True

    def resolve(self, plain: str) -> str | None:
        """The auth subject behind a presented token, or None when it is unknown, revoked, expired or its user is gone."""
        if not plain.startswith(TOKEN_PREFIX):
            return None
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.scalar(select(ApiToken).where(ApiToken.token_hash == _hash(plain)))
            if row is None or row.revoked_at is not None:
                return None
            expires = _aware(row.expires_at)
            if expires is not None and expires <= now:
                return None
            user = session.get(User, row.user_id)
            if user is None or not user.is_active:
                return None
            last = _aware(row.last_used_at)
            if last is None or now - last >= TOUCH_EVERY:
                row.last_used_at = now
                session.commit()
            return user.auth_subject


api_token_service = ApiTokenService()
