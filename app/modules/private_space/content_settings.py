"""Beta drafting and scanning settings owned by the CTO's private project.

The public marketing settings are intentionally not reused here. Keeping these
values in the private project's JSON settings prevents a personal-brand trial
from changing the behaviour of any company or customer project.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.db import get_session
from app.models import AuditEvent, Project
from app.modules.private_space.service import PrivateSpaceError, private_project_ids
from app.modules.watch.platforms import AI_RUNS_MAX, DEFAULT_AI_RUNS, DEFAULT_PLATFORMS, PlatformError, VIAS
from app.modules.work.channels import DEFAULT_RULES, EDITABLE as CHANNEL_EDITABLE, ChannelRuleError

CONTENT_SETTINGS_KEY = "private_content_settings"
CHANNELS_KEY = "channels"
PLATFORMS_KEY = "platforms"
AI_RUNS_KEY = "max_ai_runs_per_day"
PRIVATE_CHANNEL_EDITABLE = tuple(key for key in CHANNEL_EDITABLE if key != "auto_publish")


def _project(session) -> Project:
    ids = private_project_ids(session)
    project = session.get(Project, ids[0]) if ids else None
    if project is None:
        raise PrivateSpaceError("PRIVATE_SPACE_MISSING", "The private space has not been opened yet")
    return project


def _stored(project: Project) -> dict[str, object]:
    settings = project.project_settings if isinstance(project.project_settings, dict) else {}
    value = settings.get(CONTENT_SETTINGS_KEY)
    return dict(value) if isinstance(value, dict) else {}


def _save(session, project: Project, content: dict[str, object], *, actor_id: str, event: str, details: dict[str, object]) -> None:
    now = datetime.now(timezone.utc)
    project.project_settings = {**(project.project_settings or {}), CONTENT_SETTINGS_KEY: content}
    project.updated_at = now
    session.add(AuditEvent(
        id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id, event_type=event,
        entity_type="private_content_settings", entity_id=project.id, details=details, created_at=now,
    ))
    session.commit()


def channel_rules_of(project: Project, *, enabled_only: bool = False) -> list[dict[str, object]]:
    content = _stored(project)
    overrides = content.get(CHANNELS_KEY)
    overrides = overrides if isinstance(overrides, dict) else {}
    rows: list[dict[str, object]] = []
    for order, spec in enumerate(DEFAULT_RULES, start=1):
        code = str(spec["code"])
        saved = overrides.get(code)
        saved = saved if isinstance(saved, dict) else {}
        row = {
            **spec,
            "long_max_chars": spec.get("long_max_chars"),
            "enabled": True,
            "auto_publish": False,
            "sort_order": order,
            **{key: value for key, value in saved.items() if key in PRIVATE_CHANNEL_EDITABLE},
            "updated_at": project.updated_at,
        }
        if not enabled_only or bool(row["enabled"]):
            rows.append(row)
    return rows


def list_channel_rules(*, enabled_only: bool = False) -> list[dict[str, object]]:
    with get_session() as session:
        return channel_rules_of(_project(session), enabled_only=enabled_only)


def update_channel_rule(code: str, fields: dict[str, object], *, actor_id: str) -> dict[str, object]:
    with get_session() as session:
        project = _project(session)
        current = next((row for row in channel_rules_of(project) if row["code"] == code), None)
        if current is None:
            raise KeyError(code)
        changed: dict[str, object] = {}
        for key, value in fields.items():
            if key not in PRIVATE_CHANNEL_EDITABLE or value is None and key not in ("recommended_chars", "long_max_chars", "image_ratio", "video_ratio", "tone"):
                continue
            if key in ("max_chars", "recommended_chars", "long_max_chars", "max_images", "hashtag_max", "link_chars", "sort_order") and value is not None:
                if not isinstance(value, int) or value < 0 or value > 1_000_000:
                    raise ChannelRuleError("RULE_VALUE_INVALID", f"{key} must be a whole number")
            if key == "best_hours":
                hours = [str(hour).strip() for hour in (value or [])]
                if any(len(hour) != 5 or hour[2] != ":" or not hour[:2].isdigit() or not hour[3:].isdigit() for hour in hours):
                    raise ChannelRuleError("RULE_VALUE_INVALID", "best_hours must be written HH:MM")
                value = hours
            if key == "language" and value not in ("vi", "en"):
                raise ChannelRuleError("RULE_VALUE_INVALID", "language must be vi or en")
            if key == "label":
                value = " ".join(str(value).split())[:60]
                if not value:
                    raise ChannelRuleError("RULE_VALUE_INVALID", "label is required")
            if current.get(key) != value:
                changed[key] = value
        if changed:
            content = _stored(project)
            overrides = dict(content.get(CHANNELS_KEY)) if isinstance(content.get(CHANNELS_KEY), dict) else {}
            before = dict(overrides.get(code)) if isinstance(overrides.get(code), dict) else {}
            overrides[code] = {**before, **changed}
            content[CHANNELS_KEY] = overrides
            _save(session, project, content, actor_id=actor_id, event="private_content.channel_updated", details={"code": code, **changed})
        return next(row for row in channel_rules_of(project) if row["code"] == code)


def platforms_of(project: Project) -> list[dict[str, object]]:
    content = _stored(project)
    overrides = content.get(PLATFORMS_KEY)
    overrides = overrides if isinstance(overrides, dict) else {}
    rows: list[dict[str, object]] = []
    for order, spec in enumerate(DEFAULT_PLATFORMS, start=1):
        code = str(spec["code"])
        saved = overrides.get(code)
        saved = saved if isinstance(saved, dict) else {}
        rows.append({**spec, **{key: value for key, value in saved.items() if key in ("label", "enabled", "via", "note")}, "sort_order": order, "updated_at": project.updated_at})
    return rows


def list_platforms() -> list[dict[str, object]]:
    with get_session() as session:
        return platforms_of(_project(session))


def enabled_codes_of(project: Project) -> list[str]:
    return [str(row["code"]) for row in platforms_of(project) if row["enabled"] and row["via"] != "none"]


def update_platform(code: str, fields: dict[str, object], *, actor_id: str) -> dict[str, object]:
    with get_session() as session:
        project = _project(session)
        current = next((row for row in platforms_of(project) if row["code"] == code), None)
        if current is None:
            raise KeyError(code)
        changed: dict[str, object] = {}
        for key, value in fields.items():
            if key not in ("label", "enabled", "via", "note") or value is None and key != "note":
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
            if current.get(key) != value:
                changed[key] = value
        if changed and bool(changed.get("enabled", current["enabled"])) and changed.get("via", current["via"]) == "none":
            raise PlatformError("PLATFORM_VALUE_INVALID", "A network with no way to read it cannot be turned on")
        if changed:
            content = _stored(project)
            overrides = dict(content.get(PLATFORMS_KEY)) if isinstance(content.get(PLATFORMS_KEY), dict) else {}
            before = dict(overrides.get(code)) if isinstance(overrides.get(code), dict) else {}
            overrides[code] = {**before, **changed}
            content[PLATFORMS_KEY] = overrides
            _save(session, project, content, actor_id=actor_id, event="private_content.platform_updated", details={"code": code, **changed})
        return next(row for row in platforms_of(project) if row["code"] == code)


def ai_runs_cap_of(project: Project) -> int:
    value = _stored(project).get(AI_RUNS_KEY)
    return int(value) if isinstance(value, int) and 0 <= value <= AI_RUNS_MAX else DEFAULT_AI_RUNS


def get_ai_runs_cap() -> int:
    with get_session() as session:
        return ai_runs_cap_of(_project(session))


def set_ai_runs_cap(value: int, *, actor_id: str) -> int:
    if not isinstance(value, int) or not 0 <= value <= AI_RUNS_MAX:
        raise PlatformError("PLATFORM_VALUE_INVALID", f"The cap is 0 to {AI_RUNS_MAX} AI runs a day")
    with get_session() as session:
        project = _project(session)
        content = _stored(project)
        if content.get(AI_RUNS_KEY) != value:
            content[AI_RUNS_KEY] = value
            _save(session, project, content, actor_id=actor_id, event="private_content.ai_cap_updated", details={"value": value})
        return ai_runs_cap_of(project)


def private_project_id() -> str:
    with get_session() as session:
        return str(_project(session).id)
