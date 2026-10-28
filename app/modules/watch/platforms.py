"""The networks the scanning flow may read, opened for the whole system by the CTO (FR-MKT-08), and the few
system-wide numbers that go with them (FR-MKT-10). A Project Owner only turns on, for their project, what is open
here; what a network allows is stated once, in words a non-technical person can read."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import AppSetting, AuditEvent, WatchPlatform

VIAS = ("api", "scrape", "none")
# What each network allows today, in the order a marketing owner meets them. `via` says how it is read: an official
# API, a scraping service the CTO runs outside Intake, or nothing yet.
DEFAULT_PLATFORMS: list[dict[str, object]] = [
    {"code": "WEB", "label": "Web, blog, báo (RSS)", "enabled": True, "via": "api", "note": "Dán địa chỉ trang hoặc RSS; không cần API."},
    {"code": "TRENDS", "label": "Google Trends", "enabled": True, "via": "api", "note": "Chủ đề đang lên ở Việt Nam, đọc qua RSS."},
    {"code": "YOUTUBE", "label": "YouTube", "enabled": False, "via": "api", "note": "Kênh và tìm theo từ khóa qua Data API miễn phí, khoảng 100 lượt tìm mỗi ngày."},
    {"code": "INSTAGRAM", "label": "Instagram", "enabled": False, "via": "api", "note": "Hashtag qua API Meta, tối đa 30 hashtag mỗi 7 ngày; cần app review."},
    {"code": "THREADS", "label": "Threads", "enabled": False, "via": "api", "note": "Tìm theo từ khóa qua API Meta; cùng app review với Instagram."},
    {"code": "FACEBOOK", "label": "Facebook trang công khai", "enabled": False, "via": "scrape", "note": "Không có API đọc công khai; đi qua dịch vụ cào do CTO cài trong n8n."},
    {"code": "TIKTOK", "label": "TikTok", "enabled": False, "via": "scrape", "note": "Không có API đọc; đi qua dịch vụ cào do CTO cài trong n8n."},
    {"code": "X", "label": "X (Twitter)", "enabled": False, "via": "none", "note": "Chỉ đăng. Đọc từ khóa cần gói API trả phí riêng."},
    {"code": "LINKEDIN", "label": "LinkedIn", "enabled": False, "via": "none", "note": "Chưa có cách đọc nội dung công khai."},
]
PLATFORM_CODES = tuple(str(spec["code"]) for spec in DEFAULT_PLATFORMS)
EDITABLE = ("label", "enabled", "via", "note")

AI_RUNS_KEY = "watch.max_ai_runs_per_day"
DEFAULT_AI_RUNS = 4
AI_RUNS_MAX = 8


class PlatformError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def ensure_platforms() -> int:
    """Seed the networks that are missing; one the CTO already touched is left alone."""
    with get_session() as session:
        present = set(session.scalars(select(WatchPlatform.code)).all())
        added = 0
        for order, spec in enumerate(DEFAULT_PLATFORMS, start=1):
            if spec["code"] in present:
                continue
            session.add(WatchPlatform(**spec, sort_order=order, updated_at=datetime.now(timezone.utc)))
            added += 1
        session.commit()
        return added


def _dict(row: WatchPlatform) -> dict[str, object]:
    return {"code": row.code, "label": row.label, "enabled": row.enabled, "via": row.via, "note": row.note, "sort_order": row.sort_order, "updated_at": row.updated_at}


def list_platforms() -> list[dict[str, object]]:
    ensure_platforms()
    with get_session() as session:
        return [_dict(row) for row in session.scalars(select(WatchPlatform).order_by(WatchPlatform.sort_order, WatchPlatform.code)).all()]


def enabled_codes() -> list[str]:
    return [str(row["code"]) for row in list_platforms() if row["enabled"] and row["via"] != "none"]


def update_platform(code: str, fields: dict[str, object], *, actor_id: str) -> dict[str, object]:
    ensure_platforms()
    with get_session() as session:
        row = session.get(WatchPlatform, code)
        if row is None:
            raise KeyError(code)
        changed: dict[str, object] = {}
        for key, value in fields.items():
            if key not in EDITABLE or (value is None and key != "note"):
                continue
            if key == "via" and value not in VIAS:
                raise PlatformError("PLATFORM_VALUE_INVALID", "via must be api, scrape or none")
            if key == "label":
                value = " ".join(str(value).split())[:60]
                if not value:
                    raise PlatformError("PLATFORM_VALUE_INVALID", "label is required")
            if key == "note":
                value = (" ".join(str(value).split())[:300] or None) if value is not None else None
            if key == "enabled":
                value = bool(value)
            if getattr(row, key) != value:
                setattr(row, key, value)
                changed[key] = value
        if changed and changed.get("enabled") and (changed.get("via", row.via) == "none"):
            raise PlatformError("PLATFORM_VALUE_INVALID", "A network with no way to read it cannot be turned on")
        if changed:
            row.updated_by, row.updated_at = actor_id, datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=None, actor_type="USER", actor_id=actor_id, event_type="watch.platform_updated",
                entity_type="watch_platform", entity_id=str(uuid4()), details={"code": code, **changed}, created_at=row.updated_at,
            ))
            session.commit()
        return _dict(row)


def ai_runs_cap() -> int:
    with get_session() as session:
        row = session.get(AppSetting, AI_RUNS_KEY)
        value = row.value if row is not None else None
        return int(value) if isinstance(value, int) and 0 <= value <= AI_RUNS_MAX else DEFAULT_AI_RUNS


def set_ai_runs_cap(value: int, *, actor_id: str) -> int:
    if not isinstance(value, int) or not 0 <= value <= AI_RUNS_MAX:
        raise PlatformError("PLATFORM_VALUE_INVALID", f"The cap is 0 to {AI_RUNS_MAX} AI runs a day")
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(AppSetting, AI_RUNS_KEY)
        if row is None:
            row = AppSetting(key=AI_RUNS_KEY)
            session.add(row)
        if row.value != value:
            row.value, row.updated_by, row.updated_at = value, actor_id, now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=None, actor_type="USER", actor_id=actor_id, event_type="watch.ai_cap_updated",
                entity_type="app_setting", entity_id=str(uuid4()), details={"key": AI_RUNS_KEY, "value": value}, created_at=now,
            ))
            session.commit()
        return int(row.value)
