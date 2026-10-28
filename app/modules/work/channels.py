"""Channel rules (FR-MKT-02, ADR-0067): what each channel allows. Seeded once with today's limits, then owned by
the CTO in settings; nothing here is read from code at render time, so a change on a platform is a form, not a
release."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, ChannelRule

CHANNEL_CODES = ("FACEBOOK_PAGE", "FACEBOOK_PERSONAL", "THREADS", "X", "LINKEDIN", "INSTAGRAM", "TIKTOK", "YOUTUBE", "REELS", "EMAIL", "WEBSITE", "BLOG")
FORMATS = ("POST", "IMAGE", "VIDEO", "LONGFORM", "EMAIL")
# The format a channel usually carries, for the form's default.
FORMAT_OF_CHANNEL = {"TIKTOK": "VIDEO", "YOUTUBE": "VIDEO", "REELS": "VIDEO", "EMAIL": "EMAIL", "BLOG": "LONGFORM", "WEBSITE": "LONGFORM"}

DEFAULT_RULES: list[dict[str, object]] = [
    {"code": "FACEBOOK_PAGE", "label": "Facebook trang công ty", "language": "vi", "max_chars": 63206, "recommended_chars": 500, "max_images": 10, "image_ratio": "1:1 hoặc 4:5", "video_ratio": "4:5 hoặc 16:9", "hashtag_max": 3, "link_counts_chars": True, "link_chars": 0, "best_hours": ["11:30", "19:30"], "tone": "Thân thiện, rõ ràng, nói với chủ doanh nghiệp nhỏ"},
    {"code": "FACEBOOK_PERSONAL", "label": "Facebook trang cá nhân", "language": "vi", "max_chars": 63206, "recommended_chars": 400, "max_images": 10, "image_ratio": "1:1 hoặc 4:5", "video_ratio": "4:5 hoặc 16:9", "hashtag_max": 2, "link_counts_chars": True, "link_chars": 0, "best_hours": ["07:30", "20:30"], "tone": "Giọng cá nhân, kể chuyện, có số thật"},
    {"code": "THREADS", "label": "Threads", "language": "vi", "max_chars": 500, "recommended_chars": 300, "max_images": 10, "image_ratio": "1:1 hoặc 4:5", "video_ratio": "9:16", "hashtag_max": 1, "link_counts_chars": True, "link_chars": 0, "best_hours": ["12:00", "21:00"], "tone": "Ngắn, một ý, như nói chuyện"},
    {"code": "X", "label": "X (Twitter)", "language": "en", "max_chars": 280, "recommended_chars": 240, "long_max_chars": 25000, "max_images": 4, "image_ratio": "16:9 hoặc 1:1", "video_ratio": "16:9", "hashtag_max": 2, "link_counts_chars": True, "link_chars": 23, "best_hours": ["09:00", "17:00"], "tone": "English, plain, one idea per post; long form only for analysis"},
    {"code": "LINKEDIN", "label": "LinkedIn", "language": "en", "max_chars": 3000, "recommended_chars": 1200, "max_images": 9, "image_ratio": "1.91:1 hoặc 1:1", "video_ratio": "16:9 hoặc 1:1", "hashtag_max": 5, "link_counts_chars": True, "link_chars": 0, "best_hours": ["08:00", "12:00"], "tone": "English, professional, first 210 characters must carry the point"},
    {"code": "INSTAGRAM", "label": "Instagram", "language": "vi", "max_chars": 2200, "recommended_chars": 150, "max_images": 10, "image_ratio": "1:1 hoặc 4:5", "video_ratio": "9:16", "hashtag_max": 30, "link_counts_chars": True, "link_chars": 0, "best_hours": ["11:00", "19:00"], "tone": "Hình là chính; link không bấm được trong chữ"},
    {"code": "TIKTOK", "label": "TikTok", "language": "vi", "max_chars": 4000, "recommended_chars": 150, "max_images": 0, "image_ratio": None, "video_ratio": "9:16", "hashtag_max": 5, "link_counts_chars": True, "link_chars": 0, "best_hours": ["12:00", "20:00"], "tone": "Caption ngắn, video dọc, 15 đến 60 giây"},
    {"code": "YOUTUBE", "label": "YouTube", "language": "vi", "max_chars": 5000, "recommended_chars": 800, "max_images": 1, "image_ratio": "16:9 (thumbnail)", "video_ratio": "16:9; Shorts 9:16", "hashtag_max": 3, "link_counts_chars": True, "link_chars": 0, "best_hours": ["18:00"], "tone": "Tiêu đề tối đa 100 ký tự; mô tả có mốc thời gian"},
    {"code": "REELS", "label": "Reels", "language": "vi", "max_chars": 2200, "recommended_chars": 120, "max_images": 0, "image_ratio": None, "video_ratio": "9:16", "hashtag_max": 5, "link_counts_chars": True, "link_chars": 0, "best_hours": ["12:00", "20:00"], "tone": "Video dọc tối đa 90 giây, chữ trên hình"},
    {"code": "EMAIL", "label": "Email", "language": "vi", "max_chars": 20000, "recommended_chars": 1500, "max_images": 5, "image_ratio": "600 px rộng", "video_ratio": None, "hashtag_max": 0, "link_counts_chars": False, "link_chars": 0, "best_hours": ["09:00"], "tone": "Tiêu đề tối đa 50 ký tự, dòng xem trước 90 ký tự, một kêu gọi"},
    {"code": "WEBSITE", "label": "Website", "language": "vi", "max_chars": 50000, "recommended_chars": 800, "max_images": 10, "image_ratio": "16:9", "video_ratio": "16:9", "hashtag_max": 0, "link_counts_chars": False, "link_chars": 0, "best_hours": [], "tone": "Trang đích hoặc tin; mô tả meta 155 ký tự"},
    {"code": "BLOG", "label": "Blog", "language": "vi", "max_chars": 50000, "recommended_chars": 1200, "max_images": 10, "image_ratio": "16:9", "video_ratio": "16:9", "hashtag_max": 0, "link_counts_chars": False, "link_chars": 0, "best_hours": ["09:00"], "tone": "800 đến 1.500 chữ, có H2, mô tả meta 155 ký tự"},
]
EDITABLE = ("label", "language", "max_chars", "recommended_chars", "long_max_chars", "max_images", "image_ratio", "video_ratio", "hashtag_max",
            "link_counts_chars", "link_chars", "best_hours", "tone", "enabled", "auto_publish", "sort_order")


_LINK = re.compile(r"https?://\S+")


def count_chars(text: str | None, rule: dict[str, object] | None) -> int:
    """How long a version is for its channel: a link counts as the channel says (X: 23), or as written."""
    value = text or ""
    if rule is None or not value:
        return len(value)
    if rule.get("link_counts_chars") and int(rule.get("link_chars") or 0) > 0:
        return len(_LINK.sub("x" * int(rule["link_chars"]), value))
    if not rule.get("link_counts_chars"):
        return len(_LINK.sub("", value))
    return len(value)


class ChannelRuleError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def ensure_channel_rules() -> int:
    """Seed the channels that are missing; a rule the CTO already edited is left alone."""
    with get_session() as session:
        present = set(session.scalars(select(ChannelRule.code)).all())
        added = 0
        for order, spec in enumerate(DEFAULT_RULES, start=1):
            if spec["code"] in present:
                continue
            session.add(ChannelRule(**spec, enabled=True, sort_order=order, updated_at=datetime.now(timezone.utc)))
            added += 1
        session.commit()
        return added


def _dict(row: ChannelRule) -> dict[str, object]:
    return {
        "code": row.code, "label": row.label, "language": row.language, "max_chars": row.max_chars, "recommended_chars": row.recommended_chars,
        "long_max_chars": row.long_max_chars, "max_images": row.max_images, "image_ratio": row.image_ratio, "video_ratio": row.video_ratio,
        "hashtag_max": row.hashtag_max, "link_counts_chars": row.link_counts_chars, "link_chars": row.link_chars, "best_hours": list(row.best_hours or []),
        "tone": row.tone, "enabled": row.enabled, "auto_publish": bool(row.auto_publish), "sort_order": row.sort_order, "updated_at": row.updated_at,
    }


def list_rules(*, enabled_only: bool = False) -> list[dict[str, object]]:
    ensure_channel_rules()
    with get_session() as session:
        query = select(ChannelRule).order_by(ChannelRule.sort_order, ChannelRule.code)
        if enabled_only:
            query = query.where(ChannelRule.enabled.is_(True))
        return [_dict(row) for row in session.scalars(query).all()]


def rule_of(code: str) -> dict[str, object] | None:
    ensure_channel_rules()
    with get_session() as session:
        row = session.get(ChannelRule, code)
        return _dict(row) if row is not None else None


def update_rule(code: str, fields: dict[str, object], *, actor_id: str) -> dict[str, object]:
    ensure_channel_rules()
    with get_session() as session:
        row = session.get(ChannelRule, code)
        if row is None:
            raise KeyError(code)
        changed: dict[str, object] = {}
        for key, value in fields.items():
            if key not in EDITABLE or value is None and key not in ("recommended_chars", "long_max_chars", "image_ratio", "video_ratio", "tone"):
                continue
            if key in ("max_chars", "recommended_chars", "long_max_chars", "max_images", "hashtag_max", "link_chars", "sort_order") and value is not None:
                if not isinstance(value, int) or value < 0 or value > 1_000_000:
                    raise ChannelRuleError("RULE_VALUE_INVALID", f"{key} must be a whole number")
            if key == "best_hours":
                hours = [str(h).strip() for h in (value or [])]
                if any(len(h) != 5 or h[2] != ":" or not h[:2].isdigit() or not h[3:].isdigit() for h in hours):
                    raise ChannelRuleError("RULE_VALUE_INVALID", "best_hours must be written HH:MM")
                value = hours
            if key == "language" and value not in ("vi", "en"):
                raise ChannelRuleError("RULE_VALUE_INVALID", "language must be vi or en")
            if key == "label":
                value = " ".join(str(value).split())[:60]
                if not value:
                    raise ChannelRuleError("RULE_VALUE_INVALID", "label is required")
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed[key] = value
        if changed:
            row.updated_by, row.updated_at = actor_id, datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=None, actor_type="USER", actor_id=actor_id, event_type="channel_rule.updated",
                entity_type="channel_rule", entity_id=str(uuid4()), details={"code": code, **{k: v for k, v in changed.items()}}, created_at=row.updated_at,
            ))
            session.commit()
        return _dict(row)
