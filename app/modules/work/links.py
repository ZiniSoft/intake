"""Short links of channel versions (FR-MKT-12, ADR-0068): Intake redirects `/p/<code>` to the page a post points at,
with UTM tags naming the channel and the campaign, and counts the clicks itself. Every channel is then measured with
the same ruler, API or not. No address of the visitor is kept."""
from __future__ import annotations

import secrets
import unicodedata
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

from sqlalchemy import func, select

from app.config import get_settings
from app.db import get_session
from app.models import AuditEvent, PostClick, PostLink, WorkChannel, WorkItem

# Letters and digits that are not confused with each other when read aloud or copied by hand.
ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
CODE_LENGTH = 8
BOT_MARKS = ("bot", "crawler", "spider", "facebookexternalhit", "slurp", "preview", "fetch", "curl", "python-requests", "headless")


class LinkError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _slug(value: str) -> str:
    """ASCII letters and digits with dashes: a UTM value a website's analytics reads without escaping."""
    plain = unicodedata.normalize("NFKD", value.lower().strip().replace("đ", "d"))
    kept = "".join(ch if ch.isascii() and ch.isalnum() else "-" for ch in plain if not unicodedata.combining(ch))
    return "-".join(part for part in kept.split("-") if part)[:60]


def with_utm(target: str, *, channel: str, campaign: str) -> str:
    """The landing page with the three tags that tell the website where a visitor came from."""
    parts = urlsplit(target)
    held = [(key, value) for key, value in [piece.split("=", 1) if "=" in piece else (piece, "") for piece in parts.query.split("&") if piece] if not key.startswith("utm_")]
    held += [("utm_source", channel.lower()), ("utm_medium", "social"), ("utm_campaign", _slug(campaign) or "intake")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(held), parts.fragment))


def short_url(code: str) -> str:
    base = (get_settings().short_link_base or "").strip().rstrip("/")
    return f"{base}/p/{code}" if base else f"/p/{code}"


def _dict(row: PostLink, clicks: int) -> dict[str, object]:
    return {"code": row.code, "url": short_url(row.code), "target_url": row.target_url, "clicks": clicks, "created_at": row.created_at}


def links_of(session, channel_ids: list[str]) -> dict[str, dict[str, object]]:
    """The short link of each channel version that has one, with its human clicks."""
    if not channel_ids:
        return {}
    rows = session.scalars(select(PostLink).where(PostLink.work_channel_id.in_(channel_ids))).all()
    if not rows:
        return {}
    counts = dict(session.execute(
        select(PostClick.link_id, func.count()).where(PostClick.link_id.in_([row.id for row in rows]), PostClick.is_bot.is_(False)).group_by(PostClick.link_id)
    ).all())
    return {str(row.work_channel_id): _dict(row, int(counts.get(row.id, 0))) for row in rows}


def issue_link(work_id: str, channel_id: str, *, target_url: str, actor_id: str) -> dict[str, object]:
    """One short link per channel version; asking again returns the same code, with the target as it is now."""
    address = (target_url or "").strip()
    parts = urlsplit(address)
    if parts.scheme not in ("http", "https") or not parts.hostname or len(address) > 900 or any(ch.isspace() for ch in address):
        raise LinkError("TARGET_INVALID", "Paste the full http(s) address of the page the post sends people to")
    now = datetime.now(timezone.utc)
    with get_session() as session:
        version = session.get(WorkChannel, channel_id)
        if version is None or str(version.work_id) != str(work_id):
            raise KeyError(channel_id)
        work = session.get(WorkItem, work_id)
        target = with_utm(address, channel=version.channel, campaign=work.campaign or work.code)
        row = session.scalar(select(PostLink).where(PostLink.work_channel_id == version.id))
        if row is None:
            code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            while session.scalar(select(PostLink.id).where(PostLink.code == code)) is not None:
                code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
            row = PostLink(id=str(uuid4()), work_channel_id=version.id, code=code, target_url=target, created_by=actor_id, created_at=now)
            session.add(row)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=work.project_id, actor_type="USER", actor_id=actor_id, event_type="post.link_issued",
                entity_type="work", entity_id=work.id, details={"channel": version.channel, "code": code}, created_at=now,
            ))
        elif row.target_url != target:
            row.target_url = target
        session.commit()
        clicks = int(session.scalar(select(func.count()).select_from(PostClick).where(PostClick.link_id == row.id, PostClick.is_bot.is_(False))) or 0)
        return _dict(row, clicks)


def follow(code: str, *, referrer: str | None, user_agent: str | None) -> str | None:
    """Where a short code goes, after the click is counted. None when the code is not one of ours."""
    clean = (code or "").strip().lower()
    if not clean or len(clean) > 12 or any(ch not in ALPHABET for ch in clean):
        return None
    agent = (user_agent or "").lower()
    with get_session() as session:
        row = session.scalar(select(PostLink).where(PostLink.code == clean))
        if row is None:
            return None
        host = (urlsplit(referrer or "").hostname or "")[:120] or None
        session.add(PostClick(id=str(uuid4()), link_id=row.id, at=datetime.now(timezone.utc), referrer_host=host, is_bot=any(mark in agent for mark in BOT_MARKS) or not agent))
        session.commit()
        return row.target_url
