"""Doors for outside services (FR-MKT-13, ADR-0068): n8n, Make, Zapier, a scraping or listening service pushes what
it found into one marketing project through its own door, with its own secret and its own mapping from its payload
to Intake's signals. Every door ends in the same `receive`, so topics, trending and the agent tools see one thing.

The secret is kept hashed and shown once. A door only writes signals: with it nobody reads anything. The body is
untrusted JSON: it is walked by a small path resolver with hard limits, never evaluated."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete as sql_delete, func, select

from app.db import get_session
from app.models import AuditEvent, Project, WatchConnector, WatchDelivery
from app.modules.watch.service import CONTENT_TRACK, WatchError, is_content_project, pillar_names_of, watch_service

KINDS = ("GENERIC", "N8N", "MAKE", "APIFY", "MENTION")
VIAS = ("api", "scrape")
FIELDS = ("url", "title", "excerpt", "author", "published_at", "keyword", "pillar")
CONNECTOR_LIMIT = 12
DELIVERIES_KEPT = 30
BODY_LIMIT = 512 * 1024
ITEMS_LIMIT = 50
TOKEN_PREFIX = "iwk_"
_INDEX = re.compile(r"^(\w*)\[(\d+)\]$")

# What each kind of service sends, as a starting point the CTO can edit. Paths are dotted, from the body's root.
PRESETS: dict[str, dict[str, Any]] = {
    "GENERIC": {"items": "items", "fields": {"url": "url", "title": "title", "excerpt": "excerpt", "author": "author", "published_at": "published_at", "keyword": "keyword", "pillar": "pillar"}},
    "N8N": {"items": "items", "fields": {"url": "url", "title": "title", "excerpt": "excerpt", "author": "author", "published_at": "published_at", "keyword": "keyword", "pillar": "pillar"}},
    "MAKE": {"items": "", "fields": {"url": "link", "title": "title", "excerpt": "summary", "author": "author", "published_at": "date", "keyword": "query", "pillar": ""}},
    "APIFY": {"items": "", "fields": {"url": "url", "title": "title", "excerpt": "text", "author": "authorName", "published_at": "publishedAt", "keyword": "searchQuery", "pillar": ""}},
    "MENTION": {"items": "mentions", "fields": {"url": "original_url", "title": "title", "excerpt": "description", "author": "source_name", "published_at": "published_at", "keyword": "alert_name", "pillar": ""}},
}


class ConnectorError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _line(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def clean_mapping(raw: object, kind: str) -> dict[str, Any]:
    """A mapping as stored: an items path and one path per field, each a short dotted path."""
    base = PRESETS.get(kind, PRESETS["GENERIC"])
    source = raw if isinstance(raw, dict) else {}
    fields_raw = source.get("fields") if isinstance(source.get("fields"), dict) else {}
    items = _line(source.get("items", base["items"]), 120)
    fields = {name: _line(fields_raw.get(name, base["fields"].get(name, "")), 120) for name in FIELDS}
    if not fields["url"] or not fields["title"]:
        raise ConnectorError("MAPPING_INVALID", "The mapping needs a path for url and for title")
    return {"items": items, "fields": fields}


def resolve(data: Any, path: str) -> Any:
    """`a.b[0].c` from the body's root; `$` or an empty path is the root itself. Missing is None, never an error."""
    current = data
    clean = path.strip()
    if clean.startswith("$"):
        clean = clean[1:].lstrip(".")
    if not clean:
        return current
    for part in clean.split(".")[:12]:
        if current is None:
            return None
        match = _INDEX.match(part)
        name, index = (match.group(1), int(match.group(2))) if match else (part, None)
        if name:
            if not isinstance(current, dict):
                return None
            current = current.get(name)
        if index is not None:
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
    return current


def _when(value: object) -> datetime | None:
    if isinstance(value, (int, float)) and value > 0:
        stamp = float(value) / (1000 if value > 10_000_000_000 else 1)
        try:
            return datetime.fromtimestamp(stamp, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def map_payload(mapping: dict[str, Any], body: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """The payload as Intake items, plus what could not be read. Field values are text; nothing is followed."""
    found = resolve(body, mapping["items"])
    if found is None:
        return [], [f"nothing at '{mapping['items'] or '$'}'"]
    rows = found if isinstance(found, list) else [found]
    problems: list[str] = []
    items: list[dict[str, Any]] = []
    for index, row in enumerate(rows[:ITEMS_LIMIT]):
        if not isinstance(row, dict):
            problems.append(f"item {index} is not an object")
            continue
        picked = {name: resolve(row, path) if path else None for name, path in mapping["fields"].items()}
        items.append({
            "url": _line(picked["url"], 1000), "title": _line(picked["title"], 300), "excerpt": _line(picked["excerpt"], 1000) or None,
            "author": _line(picked["author"], 120) or None, "keyword": _line(picked["keyword"], 120) or None, "pillar": _line(picked["pillar"], 120) or None,
            "published_at": _when(picked["published_at"]),
        })
    if len(rows) > ITEMS_LIMIT:
        problems.append(f"only the first {ITEMS_LIMIT} of {len(rows)} items are taken")
    return items, problems


class ConnectorService:
    @staticmethod
    def _project(session, project_id: str) -> Project:
        try:
            UUID(str(project_id))
            project = session.get(Project, project_id)
        except (ValueError, TypeError):
            project = None
        if project is None or not is_content_project(project):
            raise ConnectorError("WATCH_NOT_FOR_PROJECT", "Only a marketing project has doors for outside services")
        return project

    @staticmethod
    def _row(session, connector_id: str) -> WatchConnector:
        try:
            UUID(str(connector_id))
            row = session.get(WatchConnector, connector_id)
        except (ValueError, TypeError):
            row = None
        if row is None:
            raise ConnectorError("CONNECTOR_NOT_FOUND", "Connector not found")
        return row

    @staticmethod
    def _audit(session, project_id: str, event: str, actor_id: str, entity_id: str, details: dict, actor_type: str = "USER") -> None:
        session.add(AuditEvent(id=str(uuid4()), project_id=project_id, actor_type=actor_type, actor_id=actor_id, event_type=event,
                               entity_type="watch_connector", entity_id=entity_id, details=details, created_at=datetime.now(timezone.utc)))

    @staticmethod
    def _out(row: WatchConnector, project: Project | None = None) -> dict[str, Any]:
        return {
            "id": str(row.id), "project_id": str(row.project_id), "project_code": project.code if project else None, "name": row.name, "kind": row.kind,
            "token_prefix": row.token_prefix, "via": row.via, "default_pillar": row.default_pillar, "mapping": row.mapping or PRESETS[row.kind], "enabled": row.enabled,
            "received_count": row.received_count, "rejected_count": row.rejected_count, "last_received_at": row.last_received_at, "last_status": row.last_status,
            "path": f"/api/v1/watch/inbound/{row.id}", "created_at": row.created_at,
        }

    def list(self, project_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            project = self._project(session, project_id)
            rows = session.scalars(select(WatchConnector).where(WatchConnector.project_id == project.id).order_by(WatchConnector.created_at)).all()
            return [self._out(row, project) for row in rows]

    def summary(self, project_id: str) -> list[dict[str, Any]]:
        """What the owner sees: which doors exist and whether they deliver. No secret, no mapping."""
        return [{"id": row["id"], "name": row["name"], "kind": row["kind"], "enabled": row["enabled"], "last_received_at": row["last_received_at"],
                 "received_count": row["received_count"], "last_status": row["last_status"]} for row in self.list(project_id)]

    def create(self, project_id: str, *, name: str, kind: str, via: str, default_pillar: str | None, mapping: object, actor_id: str) -> dict[str, Any]:
        """A new door; the secret comes back once, in the answer, and is never shown again."""
        kind = (kind or "GENERIC").upper()
        if kind not in KINDS or via not in VIAS:
            raise ConnectorError("CONNECTOR_INVALID", "Unknown kind or via")
        clean_name = _line(name, 80)
        if not clean_name:
            raise ConnectorError("CONNECTOR_INVALID", "Give the door a name")
        cleaned = clean_mapping(mapping, kind)
        token = TOKEN_PREFIX + secrets.token_urlsafe(30)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = self._project(session, project_id)
            if int(session.scalar(select(func.count()).select_from(WatchConnector).where(WatchConnector.project_id == project.id)) or 0) >= CONNECTOR_LIMIT:
                raise ConnectorError("CONNECTORS_FULL", f"A project has at most {CONNECTOR_LIMIT} doors")
            pillar = _line(default_pillar, 60) or None
            if pillar and pillar not in pillar_names_of(project).get(CONTENT_TRACK, []):
                raise ConnectorError("PILLAR_UNKNOWN", "The default pillar must be one of the project's pillars")
            row = WatchConnector(id=str(uuid4()), project_id=project.id, name=clean_name, kind=kind, token_hash=_hash(token), token_prefix=token[:12], via=via,
                                 default_pillar=pillar, mapping=cleaned, enabled=True, created_by=actor_id, created_at=now, updated_at=now)
            session.add(row)
            self._audit(session, project.id, "watch.connector_created", actor_id, row.id, {"name": clean_name, "kind": kind, "via": via})
            session.commit()
            return {**self._out(row, project), "token": token}

    def update(self, connector_id: str, changes: dict[str, Any], *, actor_id: str) -> dict[str, Any]:
        with get_session() as session:
            row = self._row(session, connector_id)
            project = self._project(session, row.project_id)
            if "name" in changes:
                row.name = _line(changes["name"], 80) or row.name
            if "enabled" in changes:
                row.enabled = bool(changes["enabled"])
            if "via" in changes and changes["via"] in VIAS:
                row.via = str(changes["via"])
            if "default_pillar" in changes:
                pillar = _line(changes["default_pillar"], 60) or None
                if pillar and pillar not in pillar_names_of(project).get(CONTENT_TRACK, []):
                    raise ConnectorError("PILLAR_UNKNOWN", "The default pillar must be one of the project's pillars")
                row.default_pillar = pillar
            if "mapping" in changes:
                row.mapping = clean_mapping(changes["mapping"], row.kind)
            row.updated_at = datetime.now(timezone.utc)
            self._audit(session, project.id, "watch.connector_updated", actor_id, row.id, {"changed": sorted(changes)})
            session.commit()
            return self._out(row, project)

    def rotate(self, connector_id: str, *, actor_id: str) -> dict[str, Any]:
        """A new secret; the old one stops working at once."""
        token = TOKEN_PREFIX + secrets.token_urlsafe(30)
        with get_session() as session:
            row = self._row(session, connector_id)
            project = self._project(session, row.project_id)
            row.token_hash, row.token_prefix, row.updated_at = _hash(token), token[:12], datetime.now(timezone.utc)
            self._audit(session, project.id, "watch.connector_rotated", actor_id, row.id, {})
            session.commit()
            return {**self._out(row, project), "token": token}

    def remove(self, connector_id: str, *, actor_id: str) -> None:
        with get_session() as session:
            row = self._row(session, connector_id)
            self._audit(session, row.project_id, "watch.connector_removed", actor_id, row.id, {"name": row.name})
            session.execute(sql_delete(WatchDelivery).where(WatchDelivery.connector_id == row.id))
            session.delete(row)
            session.commit()

    def try_payload(self, connector_id: str, body: Any) -> dict[str, Any]:
        """What this door would make of a payload, without keeping anything: the items read, and what it could not read."""
        with get_session() as session:
            row = self._row(session, connector_id)
            project = self._project(session, row.project_id)
            items, problems = map_payload(row.mapping or PRESETS[row.kind], body)
            known = set(pillar_names_of(project).get(CONTENT_TRACK, []))
            preview = []
            for item in items:
                reasons = []
                if not item["url"].lower().startswith(("http://", "https://")):
                    reasons.append("url must be http(s)")
                if not item["title"]:
                    reasons.append("title is empty")
                pillar = item["pillar"] if item["pillar"] in known else (row.default_pillar if not item["pillar"] else None)
                if item["pillar"] and item["pillar"] not in known:
                    reasons.append(f"pillar '{item['pillar']}' is not one of the project's; left empty")
                preview.append({**item, "pillar": pillar, "would_reject": [r for r in reasons if "pillar" not in r], "notes": [r for r in reasons if "pillar" in r]})
            return {"items": preview, "problems": problems, "would_accept": sum(1 for row_ in preview if not row_["would_reject"])}

    def deliver(self, connector_id: str, token: str, body: Any, *, size: int) -> dict[str, Any]:
        """A service at the door: the secret is checked, the payload mapped, the signals received, the call logged."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            try:
                row = self._row(session, connector_id)
            except ConnectorError:
                raise ConnectorError("NOT_FOUND", "Not found")
            if not row.enabled:
                raise ConnectorError("NOT_FOUND", "Not found")
            if not token or not hmac.compare_digest(_hash(token.strip()).encode(), row.token_hash.encode()):
                self._log(session, row, "UNAUTHORIZED", note="wrong token", now=now)
                session.commit()
                raise ConnectorError("UNAUTHORIZED", "Invalid credentials")
            if size > BODY_LIMIT:
                self._log(session, row, "INVALID", note="body too large", now=now)
                session.commit()
                raise ConnectorError("BODY_TOO_LARGE", "The payload is too large")
            project = session.get(Project, row.project_id)
            mapping, via, pillar_default, key = row.mapping or PRESETS[row.kind], row.via, row.default_pillar, project.intake_key
            items, problems = map_payload(mapping, body)
            if not items:
                self._log(session, row, "EMPTY", note="; ".join(problems)[:300] or "no items", now=now)
                session.commit()
                return {"accepted": 0, "duplicates": 0, "rejected": [], "problems": problems}
        batch = [{**item, "pillar": item["pillar"] or pillar_default, "project": key, "track": CONTENT_TRACK, "via": via, "priority": "normal"} for item in items]
        try:
            result = watch_service.receive(batch)
        except WatchError as error:
            raise ConnectorError(error.code, error.message) from error
        with get_session() as session:
            row = self._row(session, connector_id)
            row.received_count += int(result["accepted"])
            row.rejected_count += len(result["rejected"])
            row.last_received_at, row.last_status, row.updated_at = now, "ACCEPTED" if result["accepted"] else "EMPTY", now
            self._log(session, row, "ACCEPTED" if result["accepted"] else "EMPTY", accepted=int(result["accepted"]), duplicates=int(result["duplicates"]),
                      rejected=len(result["rejected"]), note="; ".join(problems)[:300] or None, now=now)
            session.commit()
        return {**result, "problems": problems}

    @staticmethod
    def _log(session, row: WatchConnector, status: str, *, accepted: int = 0, duplicates: int = 0, rejected: int = 0, note: str | None = None, now: datetime) -> None:
        session.add(WatchDelivery(id=str(uuid4()), connector_id=row.id, at=now, status=status, accepted=accepted, duplicates=duplicates, rejected=rejected, note=note))
        if status in ("UNAUTHORIZED", "INVALID"):
            row.last_status, row.updated_at = status, now
        # The log is a window, not a history: the oldest beyond the window go.
        old = session.scalars(select(WatchDelivery.id).where(WatchDelivery.connector_id == row.id).order_by(WatchDelivery.at.desc()).offset(DELIVERIES_KEPT)).all()
        if old:
            session.execute(sql_delete(WatchDelivery).where(WatchDelivery.id.in_(old)))

    def deliveries(self, connector_id: str) -> list[dict[str, Any]]:
        with get_session() as session:
            row = self._row(session, connector_id)
            rows = session.scalars(select(WatchDelivery).where(WatchDelivery.connector_id == row.id).order_by(WatchDelivery.at.desc()).limit(DELIVERIES_KEPT)).all()
            return [{"at": d.at, "status": d.status, "accepted": d.accepted, "duplicates": d.duplicates, "rejected": d.rejected, "note": d.note} for d in rows]


connector_service = ConnectorService()
