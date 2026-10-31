"""What a project watches, and what a scanning flow outside Intake found there (ADR-0039, ADR-0068).

Intake never opens these addresses itself. It keeps, per project, the list of sources and the keywords of each
pillar, hands both to a flow the CTO runs elsewhere, and takes back what that flow found as signals: short,
untrusted, and gone after a month unless they became an idea or a post.

Two kinds of project listen. The CTO's private space has its two tracks and its voices (ADR-0042). A marketing
project (`kind = NON_CODE`) has one track, `content`, and its own pillars with keywords, hashtags, audience and share
of the week (FR-MKT-08), which every AI run reads through `context_for_ai`.
"""
from __future__ import annotations

import hashlib
import math
import re
from datetime import datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete as sql_delete, func, or_, select

from app.db import get_session
from app.models import AuditEvent, Project, WatchCheck, WatchContact, WatchRequest, WatchSignal, WatchSource, WatchTopic
from app.modules.private_space import content_settings as private_content_settings
from app.modules.private_space.service import PRIVATE_FLAG, TRACKS, by_track, master_dna_of, private_project_ids, private_space_service, voices_of
from app.modules.watch.platforms import PLATFORM_CODES, ai_runs_cap, enabled_codes

KEYWORDS_KEY = "keywords"
DEMAND_KEY = "watch_demand"
PILLARS_KEY = "pillars"
WATCH_KEY = "watch"
LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")
# A marketing project has one track; its name is what the team reads on the screen.
CONTENT_TRACK = "content"
CONTENT_TRACKS = {CONTENT_TRACK: "Nội dung"}
# A track with no demand set is scanned without a weekly target; the store limit still holds.
DEFAULT_DEMAND = {"wanted_per_week": 0, "weekday": 7, "time": "20:00", "lookback_days": 7}
# A marketing project starts with a target, so the hot topics have something to work from: a calendar week.
CONTENT_DEMAND = {"wanted_per_week": 30, "weekday": 1, "time": "06:00", "lookback_days": 7}
DEFAULT_WATCH = {"networks": ["WEB", "TRENDS"], "schedule": {"times": ["06:00", "13:00"], "weekdays": [1, 2, 3, 4, 5, 6, 7]}, "scan_every_hours": 2}
SCAN_HOURS = (2, 4, 6)
WANTED_LIMIT = 50
# How much more than what was asked for is still taken in a week, so a scanner run wild cannot fill the store.
SPARE = 1.5
# The scanner is checked this often; a track still short of signals with none arriving in that time is a warning.
CHECK_HOURS = 12
CHECK_KEEP_DAYS = 30
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
SOURCE_KINDS = ("WEB", "FACEBOOK", "X", "YOUTUBE", "LINKEDIN", "OTHER")
SOURCE_TRACKS = (*TRACKS, "both")
SOURCE_LIMIT = 80
KEYWORD_LIMIT = 12
PILLAR_LIMIT = 6
SAMPLE_LIMIT = 2
TERM_KINDS = ("keyword", "hashtag")
TERM_PRIORITIES = ("high", "normal")
VIAS = ("api", "scrape", "agent")
SIGNAL_DAYS = 30
SIGNAL_LIMIT = 600
BATCH_LIMIT = 50
# How far back a used topic still counts against a new one on the same keyword (FR-MKT-09).
USED_MEMORY_DAYS = 14
_HOSTS = (("facebook.com", "FACEBOOK"), ("fb.com", "FACEBOOK"), ("x.com", "X"), ("twitter.com", "X"), ("youtube.com", "YOUTUBE"), ("youtu.be", "YOUTUBE"), ("linkedin.com", "LINKEDIN"))


class WatchError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _publish(request_id: str) -> None:
    from app.queue.celery_app import celery_app

    celery_app.send_task("intake.watch.keywords", args=[request_id], queue="ai.normalize")


def web_address(value: object, limit: int) -> str | None:
    """An http(s) address with a host, or None. Nothing here is ever fetched: the check only keeps junk out."""
    text = str(value or "").strip()
    if not text or len(text) > limit or any(char.isspace() for char in text):
        return None
    parts = urlsplit(text)
    return text if parts.scheme in ("http", "https") and parts.hostname else None


def kind_of(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    return next((kind for name, kind in _HOSTS if host == name or host.endswith("." + name)), "WEB")


def _line(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _is_private(project: Project | None) -> bool:
    return project is not None and isinstance(project.project_settings, dict) and project.project_settings.get(PRIVATE_FLAG) is True


def is_content_project(project: Project | None) -> bool:
    """A marketing project: one track, pillars of its own, read by the posts side."""
    return project is not None and project.kind == "NON_CODE" and not _is_private(project)


def tracks_of(project: Project | None) -> dict[str, str]:
    """The tracks a project listens on, by key. A project with none does not listen."""
    if _is_private(project):
        return dict(TRACKS)
    if is_content_project(project):
        return dict(CONTENT_TRACKS)
    return {}


def _term(value: object) -> dict[str, str] | None:
    """One keyword or hashtag of a pillar, cleaned: `{text, kind, priority}`."""
    if isinstance(value, str):
        value = {"text": value}
    if not isinstance(value, dict):
        return None
    text = _line(value.get("text"), 60)
    if not text:
        return None
    kind = str(value.get("kind") or ("hashtag" if text.startswith("#") else "keyword"))
    priority = str(value.get("priority") or "normal")
    if kind not in TERM_KINDS or priority not in TERM_PRIORITIES:
        return None
    if kind == "hashtag":
        text = "#" + text.lstrip("#").replace(" ", "")
    return {"text": text, "kind": kind, "priority": priority}


def _clean_terms(values: object) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for raw in values if isinstance(values, list) else []:
        term = _term(raw)
        if term is not None:
            seen.setdefault(term["text"].lower(), term)
    return list(seen.values())


def clean_pillar(raw: object) -> dict[str, object] | None:
    """A marketing pillar as stored: name, one line, audience, channels, share, terms, samples, what to avoid."""
    if not isinstance(raw, dict):
        return None
    name = _line(raw.get("name"), 60)
    if not name:
        return None
    channels = [str(code).upper() for code in (raw.get("channels") or []) if isinstance(code, str)]
    share = raw.get("share_pct")
    samples = []
    for item in raw.get("samples") or []:
        if isinstance(item, dict) and web_address(item.get("url"), 1000):
            samples.append({"title": _line(item.get("title"), 120) or (urlsplit(str(item["url"])).hostname or ""), "url": str(item["url"]).strip()})
    return {
        "name": name, "description": _line(raw.get("description"), 200), "audience": _line(raw.get("audience"), 120),
        "channels": list(dict.fromkeys(channels))[:12], "share_pct": int(share) if isinstance(share, int) and 0 <= share <= 100 else 0,
        "keywords": _clean_terms(raw.get("keywords"))[:KEYWORD_LIMIT], "samples": samples[:SAMPLE_LIMIT], "avoid": _line(raw.get("avoid"), 300),
    }


def pillars_of(project: Project | None) -> dict[str, list[dict[str, object]]]:
    """Every track's pillars as full objects. A private track's pillars are names from its voice."""
    settings = project.project_settings if project is not None and isinstance(project.project_settings, dict) else {}
    if _is_private(project):
        voices = voices_of(settings)
        return {track: [{"name": str(pillar), "description": "", "audience": "", "channels": [], "share_pct": 0, "keywords": [], "samples": [], "avoid": ""}
                        for pillar in voices[track].get("pillars") or []] for track in TRACKS}
    if is_content_project(project):
        kept = [pillar for pillar in (clean_pillar(raw) for raw in (settings.get(PILLARS_KEY) or [])) if pillar is not None]
        return {CONTENT_TRACK: kept[:PILLAR_LIMIT]}
    return {}


def pillar_names_of(project: Project | None) -> dict[str, list[str]]:
    return {track: [str(pillar["name"]) for pillar in pillars] for track, pillars in pillars_of(project).items()}


def keywords_of(settings: object) -> dict[str, dict[str, list[str]]]:
    """Keywords by track and pillar of the private space, for the pillars the track has now."""
    stored = by_track(settings.get(KEYWORDS_KEY)) if isinstance(settings, dict) else {}
    voices = voices_of(settings)
    result: dict[str, dict[str, list[str]]] = {}
    for track in TRACKS:
        held = stored.get(track) if isinstance(stored.get(track), dict) else {}
        result[track] = {str(pillar): [str(word) for word in (held.get(pillar) or [])] for pillar in voices[track].get("pillars") or []}
    return result


def terms_of(project: Project | None) -> dict[str, dict[str, list[dict[str, str]]]]:
    """Every track's terms by pillar, in one shape for both kinds of project: `{text, kind, priority}`."""
    if _is_private(project):
        return {track: {pillar: [{"text": word, "kind": "keyword", "priority": "normal"} for word in words] for pillar, words in held.items()}
                for track, held in keywords_of(project.project_settings).items()}
    return {track: {str(pillar["name"]): list(pillar["keywords"]) for pillar in pillars} for track, pillars in pillars_of(project).items()}


def demand_of(project: Project | None) -> dict[str, dict[str, object]]:
    settings = project.project_settings if project is not None and isinstance(project.project_settings, dict) else {}
    stored = by_track(settings.get(DEMAND_KEY))
    base = CONTENT_DEMAND if is_content_project(project) else DEFAULT_DEMAND
    return {track: {**base, **(stored.get(track) if isinstance(stored.get(track), dict) else {})} for track in tracks_of(project)}


def watch_of(settings: object) -> dict[str, object]:
    """A marketing project's collection settings, cleaned: networks, the AI schedule, how often to scan."""
    stored = settings.get(WATCH_KEY) if isinstance(settings, dict) and isinstance(settings.get(WATCH_KEY), dict) else {}
    schedule = stored.get("schedule") if isinstance(stored.get("schedule"), dict) else {}
    times = sorted({str(value) for value in (schedule.get("times") or []) if _TIME.match(str(value))}) or list(DEFAULT_WATCH["schedule"]["times"])
    weekdays = sorted({int(value) for value in (schedule.get("weekdays") or []) if isinstance(value, int) and 1 <= value <= 7}) or list(DEFAULT_WATCH["schedule"]["weekdays"])
    hours = stored.get("scan_every_hours")
    networks = stored.get("networks") if isinstance(stored.get("networks"), list) else list(DEFAULT_WATCH["networks"])
    return {
        "networks": [str(code) for code in networks if str(code) in PLATFORM_CODES],
        "schedule": {"times": times, "weekdays": weekdays},
        "scan_every_hours": int(hours) if isinstance(hours, int) and hours in SCAN_HOURS else DEFAULT_WATCH["scan_every_hours"],
    }


def window_of(demand: dict[str, object], now: datetime | None = None) -> tuple[datetime, datetime]:
    """The collection week a moment falls in: from the last deadline to the next one, as absolute times."""
    now = (now or datetime.now(timezone.utc)).astimezone(LOCAL)
    hour = time.fromisoformat(str(demand["time"]))
    days = (int(demand["weekday"]) - 1 - now.weekday()) % 7
    deadline = datetime.combine(now.date() + timedelta(days=days), hour, tzinfo=LOCAL)
    if deadline <= now:
        deadline += timedelta(days=7)
    return (deadline - timedelta(days=7)).astimezone(timezone.utc), deadline.astimezone(timezone.utc)


class WatchService:
    @staticmethod
    def _demand_out(session, project, track: str) -> dict[str, object]:
        """What the track asks of the scanner this week, and how far it has come."""
        demand = demand_of(project)[track]
        wanted = int(demand["wanted_per_week"])
        opened, deadline = window_of(demand)
        received = int(session.scalar(select(func.count()).select_from(WatchSignal).where(
            WatchSignal.project_id == project.id, WatchSignal.track == track, WatchSignal.received_at > opened,
        )) or 0)
        ceiling = math.ceil(wanted * SPARE) if wanted else None
        return {
            "wanted_per_week": wanted, "weekday": int(demand["weekday"]), "time": str(demand["time"]), "lookback_days": int(demand["lookback_days"]),
            "timezone": str(LOCAL), "window_start": opened if wanted else None, "deadline": deadline if wanted else None,
            "received": received, "remaining": max(0, wanted - received),
            # How many more this week's window still takes; None when the track sets no target.
            "accept_up_to": max(0, ceiling - received) if ceiling is not None else None,
        }

    def demand(self, track: str, project_id: str | None = None) -> dict[str, object]:
        with get_session() as session:
            project = self._project(session, project_id, required=False)
            if project is None:
                if track not in TRACKS:
                    raise WatchError("TRACK_UNKNOWN", "Unknown track")
                return {**DEFAULT_DEMAND, "timezone": str(LOCAL), "window_start": None, "deadline": None, "received": 0, "remaining": 0, "accept_up_to": None}
            self._check_track(project, track)
            return self._demand_out(session, project, track)

    def save_demand(self, track: str, wanted: int, weekday: int, hour: str, lookback_days: int, actor_id: str, project_id: str | None = None) -> dict[str, object]:
        if not 0 <= wanted <= WANTED_LIMIT or weekday not in range(1, 8) or not _TIME.match(hour or "") or not 1 <= lookback_days <= 30:
            raise WatchError("DEMAND_INVALID", "A demand is 0 to 50 signals a week, a weekday, an hour written HH:MM, and 1 to 30 days to look back")
        with get_session() as session:
            project = self._project(session, project_id)
            self._check_track(project, track)
            current = project.project_settings or {}
            stored = by_track(current.get(DEMAND_KEY))
            stored[track] = {"wanted_per_week": wanted, "weekday": weekday, "time": hour, "lookback_days": lookback_days}
            # A new dict, so the JSON column is seen as changed.
            project.project_settings = {**current, DEMAND_KEY: stored}
            project.updated_at = datetime.now(timezone.utc)
            self._audit(session, project, "watch.demand_saved", actor_id, "project", project.id, {"track": track, "wanted": wanted, "weekday": weekday, "time": hour})
            session.commit()
            return self._demand_out(session, project, track)

    @staticmethod
    def _project(session, project_id: str | None = None, required: bool = True):
        """The private space when no project is named, else a project that listens (private or marketing)."""
        if project_id is None:
            project = private_space_service._project(session)
            if project is None and required:
                raise WatchError("PRIVATE_SPACE_MISSING", "The private space has not been opened yet")
            return project
        try:
            UUID(str(project_id))
            project = session.get(Project, project_id)
        except (ValueError, TypeError):
            project = None
        if project is None or not tracks_of(project):
            raise WatchError("WATCH_NOT_FOR_PROJECT", "This project does not listen for signals")
        return project

    @staticmethod
    def _projects(session) -> list[Project]:
        """Every project that listens: the private space first, then the active marketing projects."""
        private = {str(project_id) for project_id in private_project_ids(session)}
        rows = session.scalars(select(Project).where(Project.status == "ACTIVE").order_by(Project.created_at)).all()
        kept = [row for row in rows if str(row.id) in private] + [row for row in rows if str(row.id) not in private and is_content_project(row)]
        return [row for row in kept if tracks_of(row)]

    @staticmethod
    def _check_track(project, track: str) -> None:
        if track not in tracks_of(project):
            raise WatchError("TRACK_UNKNOWN", "Unknown track")

    @staticmethod
    def _audit(session, project, event: str, actor_id: str, entity: str, entity_id: str, details: dict, actor_type: str = "USER") -> None:
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project.id, actor_type=actor_type, actor_id=actor_id, event_type=event,
            entity_type=entity, entity_id=entity_id, details=details, created_at=datetime.now(timezone.utc),
        ))

    # ---- sources

    @staticmethod
    def _source_out(row: WatchSource) -> dict[str, object]:
        return {"id": str(row.id), "kind": row.kind, "url": row.url, "label": row.label, "track": row.track, "active": row.active, "note": row.note, "created_at": row.created_at}

    def sources(self, project_id: str | None = None) -> list[dict[str, object]]:
        with get_session() as session:
            project = self._project(session, project_id, required=False)
            if project is None:
                return []
            rows = session.scalars(select(WatchSource).where(WatchSource.project_id == project.id).order_by(WatchSource.created_at)).all()
            return [self._source_out(row) for row in rows]

    def add_source(self, url: str, track: str, label: str | None, kind: str | None, note: str | None, actor_id: str, project_id: str | None = None) -> dict[str, object]:
        address = web_address(url, 500)
        if address is None:
            raise WatchError("SOURCE_INVALID", "A source is an http or https address")
        if kind and kind not in SOURCE_KINDS:
            raise WatchError("SOURCE_INVALID", "Unknown track or kind of source")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = self._project(session, project_id)
            if track not in tracks_of(project) and track != "both":
                raise WatchError("SOURCE_INVALID", "Unknown track or kind of source")
            held = session.scalars(select(WatchSource).where(WatchSource.project_id == project.id)).all()
            if any(row.url.rstrip("/").lower() == address.rstrip("/").lower() for row in held):
                raise WatchError("SOURCE_EXISTS", "This address is already on the list")
            if len(held) >= SOURCE_LIMIT:
                raise WatchError("SOURCES_FULL", "The list of sources is full")
            row = WatchSource(
                id=str(uuid4()), project_id=project.id, kind=kind or kind_of(address), url=address,
                label=_line(label, 120) or (urlsplit(address).hostname or address), track=track, active=True,
                note=_line(note, 300) or None, created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(row)
            self._audit(session, project, "watch.source_added", actor_id, "watch_source", row.id, {"kind": row.kind, "track": track})
            session.commit()
            return self._source_out(row)

    @staticmethod
    def _source(session, project, source_id: str) -> WatchSource:
        try:
            row = session.get(WatchSource, source_id)
        except Exception:  # a malformed ID is simply not a source
            session.rollback()
            row = None
        if row is None or str(row.project_id) != str(project.id):
            raise WatchError("SOURCE_NOT_FOUND", "Source not found")
        return row

    def change_source(self, source_id: str, changes: dict[str, object], actor_id: str, project_id: str | None = None) -> dict[str, object]:
        with get_session() as session:
            project = self._project(session, project_id)
            row = self._source(session, project, source_id)
            if "track" in changes:
                if changes["track"] not in tracks_of(project) and changes["track"] != "both":
                    raise WatchError("SOURCE_INVALID", "Unknown track")
                row.track = str(changes["track"])
            if "active" in changes:
                row.active = bool(changes["active"])
            if "label" in changes:
                row.label = _line(changes["label"], 120) or row.label
            if "note" in changes:
                row.note = _line(changes["note"], 300) or None
            row.updated_at = datetime.now(timezone.utc)
            self._audit(session, project, "watch.source_changed", actor_id, "watch_source", row.id, {"changed": sorted(changes)})
            session.commit()
            return self._source_out(row)

    def remove_source(self, source_id: str, actor_id: str, project_id: str | None = None) -> None:
        with get_session() as session:
            project = self._project(session, project_id)
            row = self._source(session, project, source_id)
            self._audit(session, project, "watch.source_removed", actor_id, "watch_source", row.id, {"kind": row.kind})
            session.delete(row)
            session.commit()

    # ---- pillars and collection settings of a marketing project (FR-MKT-08)

    def pillars(self, project_id: str) -> list[dict[str, object]]:
        with get_session() as session:
            project = self._project(session, project_id)
            return pillars_of(project).get(CONTENT_TRACK, [])

    def save_pillars(self, project_id: str, pillars: list[dict[str, object]], actor_id: str) -> list[dict[str, object]]:
        """The marketing pillars as the owner wrote them; a pillar that lost its name is dropped, the rest kept whole."""
        cleaned = [pillar for pillar in (clean_pillar(raw) for raw in pillars) if pillar is not None]
        if len(cleaned) > PILLAR_LIMIT:
            raise WatchError("PILLARS_TOO_MANY", f"A project has at most {PILLAR_LIMIT} pillars")
        names = [str(pillar["name"]).lower() for pillar in cleaned]
        if len(set(names)) != len(names):
            raise WatchError("PILLAR_DUPLICATE", "Two pillars have the same name")
        with get_session() as session:
            project = self._project(session, project_id)
            if not is_content_project(project):
                raise WatchError("WATCH_NOT_FOR_PROJECT", "Only a marketing project has pillars of its own")
            current = project.project_settings or {}
            project.project_settings = {**current, PILLARS_KEY: cleaned}
            project.updated_at = datetime.now(timezone.utc)
            self._audit(session, project, "watch.pillars_saved", actor_id, "project", project.id,
                        {"pillars": len(cleaned), "keywords": sum(len(pillar["keywords"]) for pillar in cleaned)})
            session.commit()
            return pillars_of(project).get(CONTENT_TRACK, [])

    def watch_settings(self, project_id: str) -> dict[str, object]:
        with get_session() as session:
            project = self._project(session, project_id)
            return self._watch_out(session, project)

    def _watch_out(self, session, project) -> dict[str, object]:
        stored = watch_of(project.project_settings)
        open_codes = private_content_settings.enabled_codes_of(project) if _is_private(project) else enabled_codes()
        cap = private_content_settings.ai_runs_cap_of(project) if _is_private(project) else ai_runs_cap()
        runs = len(stored["schedule"]["times"]) * len(stored["schedule"]["weekdays"])
        return {
            **stored, "networks": [code for code in stored["networks"] if code in open_codes], "open_networks": open_codes,
            "max_ai_runs_per_day": cap, "ai_runs_per_week": runs, "scan_hours": list(SCAN_HOURS),
        }

    def save_watch_settings(self, project_id: str, *, networks: list[str] | None, times: list[str] | None, weekdays: list[int] | None,
                            scan_every_hours: int | None, actor_id: str) -> dict[str, object]:
        """What the owner may change within what the CTO opened: networks among the open ones, AI runs within the cap."""
        with get_session() as session:
            project = self._project(session, project_id)
            if not is_content_project(project):
                raise WatchError("WATCH_NOT_FOR_PROJECT", "Only a marketing project has collection settings")
            current = watch_of(project.project_settings)
            cap = private_content_settings.ai_runs_cap_of(project) if _is_private(project) else ai_runs_cap()
            if networks is not None:
                open_codes = set(private_content_settings.enabled_codes_of(project) if _is_private(project) else enabled_codes())
                unknown = [code for code in networks if code not in open_codes]
                if unknown:
                    raise WatchError("NETWORK_NOT_OPEN", "The CTO has not opened that network: " + ", ".join(unknown))
                current["networks"] = list(dict.fromkeys(str(code) for code in networks))
            if times is not None:
                kept = sorted({str(value) for value in times if _TIME.match(str(value))})
                if not kept or len(kept) > cap:
                    raise WatchError("SCHEDULE_INVALID", f"Choose 1 to {cap} times a day, written HH:MM")
                current["schedule"]["times"] = kept
            if weekdays is not None:
                kept_days = sorted({int(value) for value in weekdays if isinstance(value, int) and 1 <= value <= 7})
                if not kept_days:
                    raise WatchError("SCHEDULE_INVALID", "Choose at least one weekday")
                current["schedule"]["weekdays"] = kept_days
            if scan_every_hours is not None:
                if scan_every_hours not in SCAN_HOURS:
                    raise WatchError("SCHEDULE_INVALID", "Scan every 2, 4 or 6 hours")
                current["scan_every_hours"] = scan_every_hours
            project.project_settings = {**(project.project_settings or {}), WATCH_KEY: current}
            project.updated_at = datetime.now(timezone.utc)
            self._audit(session, project, "watch.settings_saved", actor_id, "project", project.id, {"networks": current["networks"], "times": current["schedule"]["times"], "scan_every_hours": current["scan_every_hours"]})
            session.commit()
            return self._watch_out(session, project)

    @staticmethod
    def context_for_ai(session, project, used_days: int = USED_MEMORY_DAYS) -> dict[str, object]:
        """The one package every AI run on a marketing project reads: the pillars as the owner wrote them, the
        channel rules that are on, and the topics already used lately (titles only). Nothing about accounts or keys."""
        from app.modules.work.channels import list_rules

        cutoff = datetime.now(timezone.utc) - timedelta(days=used_days)
        used = session.scalars(select(WatchTopic.title).where(
            WatchTopic.project_id == project.id, WatchTopic.state == "USED", WatchTopic.updated_at >= cutoff,
        ).order_by(WatchTopic.updated_at.desc()).limit(30)).all()
        source_rules = private_content_settings.channel_rules_of(project, enabled_only=True) if _is_private(project) else list_rules(enabled_only=True)
        rules = [{"code": rule["code"], "label": rule["label"], "language": rule["language"], "max_chars": rule["max_chars"], "recommended_chars": rule["recommended_chars"], "best_hours": rule["best_hours"], "tone": rule["tone"]}
                 for rule in source_rules]
        return {"project": project.name, "pillars": pillars_of(project).get(CONTENT_TRACK, []), "channel_rules": rules, "used_titles": [str(title) for title in used]}

    # ---- keywords of each pillar

    def keywords(self, track: str, project_id: str | None = None) -> dict[str, object]:
        with get_session() as session:
            project = self._project(session, project_id, required=False)
            if project is None:
                if track not in TRACKS:
                    raise WatchError("TRACK_UNKNOWN", "Unknown track")
                return {"track": track, "pillars": [], "request": None, "suggested": {}}
            self._check_track(project, track)
            request = session.scalar(select(WatchRequest).where(WatchRequest.project_id == project.id, WatchRequest.track == track).order_by(WatchRequest.created_at.desc()).limit(1))
            held = {pillar: [term["text"] for term in terms] for pillar, terms in terms_of(project)[track].items()}
            suggested = request.result if request is not None and request.status == "DONE" and isinstance(request.result, dict) else {}
            return {
                "track": track,
                "pillars": [{"pillar": pillar, "keywords": words} for pillar, words in held.items()],
                "request": {"status": request.status, "error": request.error} if request is not None else None,
                # What the AI offered and the owner has not taken yet.
                "suggested": {pillar: [word for word in words if word.lower() not in {kept.lower() for kept in held.get(pillar, [])}] for pillar, words in suggested.items() if pillar in held},
            }

    def save_keywords(self, track: str, pillars: dict[str, list[str]], actor_id: str, project_id: str | None = None) -> dict[str, object]:
        with get_session() as session:
            project = self._project(session, project_id)
            self._check_track(project, track)
            current = project.project_settings or {}
            known = set(pillar_names_of(project)[track])
            cleaned: dict[str, list[str]] = {}
            for pillar, words in pillars.items():
                if pillar not in known:
                    raise WatchError("PILLAR_UNKNOWN", "Keywords belong to a pillar of this track")
                seen: dict[str, str] = {}
                for word in words:
                    text = _line(word, 60)
                    if text:
                        seen.setdefault(text.lower(), text)
                if len(seen) > KEYWORD_LIMIT:
                    raise WatchError("KEYWORDS_TOO_MANY", f"A pillar has at most {KEYWORD_LIMIT} keywords")
                cleaned[pillar] = list(seen.values())
            if is_content_project(project):
                # A marketing pillar keeps its terms inside itself; a word kept before keeps its kind and priority.
                stored_pillars = []
                for pillar in pillars_of(project)[CONTENT_TRACK]:
                    if pillar["name"] in cleaned:
                        before = {term["text"].lower(): term for term in pillar["keywords"]}
                        pillar["keywords"] = [before.get(word.lower()) or _term(word) for word in cleaned[pillar["name"]]]
                    stored_pillars.append(pillar)
                project.project_settings = {**current, PILLARS_KEY: stored_pillars}
            else:
                stored = by_track(current.get(KEYWORDS_KEY))
                stored[track] = {**{pillar: words for pillar, words in (stored.get(track) or {}).items() if pillar in known}, **cleaned}
                # A new dict, so the JSON column is seen as changed.
                project.project_settings = {**current, PRIVATE_FLAG: True, KEYWORDS_KEY: stored}
            project.updated_at = datetime.now(timezone.utc)
            self._audit(session, project, "watch.keywords_saved", actor_id, "project", project.id, {"track": track, "pillars": len(cleaned), "keywords": sum(len(words) for words in cleaned.values())})
            session.commit()
        return self.keywords(track, project_id)

    def request_keywords(self, track: str, actor_id: str, publisher=None, project_id: str | None = None) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = self._project(session, project_id)
            self._check_track(project, track)
            if not pillar_names_of(project)[track]:
                raise WatchError("NO_PILLARS", "The track has no pillars to find keywords for")
            request = WatchRequest(id=str(uuid4()), project_id=project.id, track=track, status="PENDING", created_by=actor_id, created_at=now, updated_at=now)
            session.add(request)
            self._audit(session, project, "watch.keywords_requested", actor_id, "watch_request", request.id, {"track": track})
            session.commit()
            request_id = str(request.id)
        (publisher or _publish)(request_id)
        return {"id": request_id, "status": "PENDING"}

    def keywords_input(self, request_id: str) -> dict[str, object] | None:
        with get_session() as session:
            request = session.get(WatchRequest, request_id)
            project = session.get(Project, request.project_id) if request is not None else None
            if request is None or request.status != "PENDING" or project is None or not tracks_of(project):
                return None
            held = {pillar: [term["text"] for term in terms] for pillar, terms in terms_of(project)[request.track].items()}
            if is_content_project(project):
                pillars = pillars_of(project)[CONTENT_TRACK]
                voice = {
                    "name": CONTENT_TRACKS[CONTENT_TRACK], "direction_note": "", "pillars": [pillar["name"] for pillar in pillars],
                    "positioning": "; ".join(f"{pillar['name']}: {pillar['description']}" for pillar in pillars if pillar["description"]),
                    "audience": "; ".join(dict.fromkeys(str(pillar["audience"]) for pillar in pillars if pillar["audience"])),
                    "avoid": "; ".join(dict.fromkeys(str(pillar["avoid"]) for pillar in pillars if pillar["avoid"])),
                }
                return {"track": request.track, "voice": voice, "master_dna": "", "held": held}
            voice = voices_of(project.project_settings)[request.track]
            return {"track": request.track, "voice": voice, "master_dna": master_dna_of(project.project_settings), "held": held}

    def save_suggestion(self, request_id: str, pillars: list[dict[str, object]] | None, error_code: str | None = None) -> None:
        with get_session() as session:
            request = session.get(WatchRequest, request_id)
            project = session.get(Project, request.project_id) if request is not None else None
            if request is None or project is None or not tracks_of(project):
                return
            known = set(pillar_names_of(project)[request.track])
            result: dict[str, list[str]] = {}
            for row in pillars or []:
                pillar = str(row.get("pillar") or "")
                if pillar in known:
                    seen: dict[str, str] = {}
                    for word in row.get("keywords") or []:
                        text = _line(word, 60)
                        if text:
                            seen.setdefault(text.lower(), text)
                    result[pillar] = list(seen.values())[:KEYWORD_LIMIT]
            request.status = "DONE" if any(result.values()) else "FAILED"
            request.result = result if request.status == "DONE" else None
            request.error = None if request.status == "DONE" else (error_code or "KEYWORDS_EMPTY")[:128]
            request.updated_at = datetime.now(timezone.utc)
            self._audit(session, project, "watch.keywords_suggested" if request.status == "DONE" else "watch.keywords_failed", "ai-worker", "watch_request", request.id, {"track": request.track, "error": request.error}, actor_type="WORKER")
            session.commit()

    # ---- is the scanner alive: when it last called, and a check every twelve hours

    @staticmethod
    def _aware(value: datetime | None) -> datetime | None:
        # SQLite hands back naive datetimes; they were stored as UTC.
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value

    @staticmethod
    def _touch(session, project, *, config: bool = False, signal: bool = False) -> None:
        contact = session.get(WatchContact, project.id)
        if contact is None:
            contact = WatchContact(project_id=project.id)
            session.add(contact)
        now = datetime.now(timezone.utc)
        if config:
            contact.last_config_at = now
        if signal:
            contact.last_signal_at = now

    def check(self, routes_open: bool, now: datetime | None = None) -> list[dict[str, object]]:
        """One check of every track that asked for signals, on every project that listens. A track that asked for none is not checked."""
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(hours=CHECK_HOURS)
        results = []
        with get_session() as session:
            for project in self._projects(session):
                sources = session.scalars(select(WatchSource).where(WatchSource.project_id == project.id, WatchSource.active.is_(True))).all()
                if not sources and is_content_project(project):
                    # A marketing project that has not named a source yet has not started listening: nothing to check.
                    continue
                session.execute(sql_delete(WatchCheck).where(WatchCheck.project_id == project.id, WatchCheck.checked_at < now - timedelta(days=CHECK_KEEP_DAYS)))
                contact = session.get(WatchContact, project.id)
                called = self._aware(contact.last_config_at) if contact is not None else None
                words = terms_of(project)
                for track in tracks_of(project):
                    demand = self._demand_out(session, project, track)
                    if not demand["wanted_per_week"]:
                        continue
                    received = int(session.scalar(select(func.count()).select_from(WatchSignal).where(
                        WatchSignal.project_id == project.id, WatchSignal.track == track, WatchSignal.received_at > since,
                    )) or 0)
                    short = demand["remaining"] > 0 and received == 0
                    reason = None
                    if short:
                        # The first cause that explains the silence, from what the owner can fix to what the scanner must.
                        if not routes_open:
                            reason = "ROUTES_CLOSED"
                        elif not any(row.track in (track, "both") for row in sources):
                            reason = "NO_SOURCES"
                        elif not any(words[track].values()):
                            reason = "NO_KEYWORDS"
                        elif called is None or called < since:
                            reason = "FLOW_SILENT"
                        else:
                            reason = "NOTHING_SENT"
                    row = WatchCheck(
                        id=str(uuid4()), project_id=project.id, track=track, checked_at=now, status="WARNING" if short else "OK", reason=reason,
                        received=received, remaining=int(demand["remaining"]), deadline=demand["deadline"],
                    )
                    session.add(row)
                    if short:
                        self._audit(session, project, "watch.check_warning", "scheduler", "watch_check", row.id, {"track": track, "reason": reason, "remaining": row.remaining}, actor_type="WORKER")
                    results.append({"track": track, "status": row.status, "reason": reason, "received": received, "remaining": row.remaining})
            session.commit()
        return results

    def health(self, project_id: str | None = None) -> dict[str, object]:
        with get_session() as session:
            project = self._project(session, project_id, required=False)
            if project is None:
                return {"check_hours": CHECK_HOURS, "last_config_at": None, "last_signal_at": None, "tracks": []}
            contact = session.get(WatchContact, project.id)
            names = tracks_of(project)
            voices = voices_of(project.project_settings) if _is_private(project) else {}
            tracks = []
            for track in names:
                demand = self._demand_out(session, project, track)
                last = session.scalar(select(WatchCheck).where(WatchCheck.project_id == project.id, WatchCheck.track == track).order_by(WatchCheck.checked_at.desc()).limit(1))
                arrived = int(session.scalar(select(func.count()).select_from(WatchSignal).where(
                    WatchSignal.project_id == project.id, WatchSignal.track == track, WatchSignal.received_at > last.checked_at,
                )) or 0) if last is not None else 0
                # A warning stands until the next check, unless signals came in or the track stopped asking.
                warning = last is not None and last.status == "WARNING" and arrived == 0 and demand["wanted_per_week"] > 0
                tracks.append({
                    "track": track, "name": (voices.get(track) or {}).get("name") or names[track], "wanted_per_week": demand["wanted_per_week"],
                    "received": demand["received"], "remaining": demand["remaining"], "deadline": demand["deadline"],
                    "checked_at": last.checked_at if last is not None else None, "warning": warning,
                    "reason": last.reason if warning else None, "received_in_check": last.received if last is not None else None,
                })
            return {
                "check_hours": CHECK_HOURS,
                "last_config_at": contact.last_config_at if contact is not None else None,
                "last_signal_at": contact.last_signal_at if contact is not None else None,
                "tracks": tracks,
            }

    # ---- what the scanning flow reads

    @staticmethod
    def _next_scan_at(contact: WatchContact | None, every_hours: int) -> datetime | None:
        """When the flow should read this project again: the last read plus the project's rhythm, on a half hour."""
        last = contact.last_config_at if contact is not None else None
        if last is None:
            return None
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        due = last + timedelta(hours=every_hours)
        minutes = (due.minute // 30 + (1 if due.minute % 30 else 0)) * 30
        return due.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=minutes)

    def _track_config(self, session, project, track: str, name: str, rows: list[WatchSource]) -> dict[str, object]:
        terms = terms_of(project)[track]
        return {
            "track": track, "name": name,
            "pillars": [{"pillar": pillar, "keywords": [term["text"] for term in kept], "terms": sorted(kept, key=lambda term: term["priority"] != "high")} for pillar, kept in terms.items()],
            "sources": [{"id": str(row.id), "kind": row.kind, "url": row.url, "label": row.label} for row in rows if row.track in (track, "both")],
            "demand": self._demand_out(session, project, track),
        }

    def config(self) -> dict[str, object]:
        """What every listening project wants scanned. `tracks` is the private space as before; `projects` has them all."""
        with get_session() as session:
            projects = self._projects(session)
            out: dict[str, object] = {"tracks": [], "projects": []}
            global_open_codes = enabled_codes()
            for project in projects:
                open_codes = private_content_settings.enabled_codes_of(project) if _is_private(project) else global_open_codes
                rows = session.scalars(select(WatchSource).where(WatchSource.project_id == project.id, WatchSource.active.is_(True)).order_by(WatchSource.created_at)).all()
                if not rows and not _is_private(project):
                    continue
                contact = session.get(WatchContact, project.id)
                watch = watch_of(project.project_settings) if is_content_project(project) else dict(DEFAULT_WATCH)
                next_scan = self._next_scan_at(contact, int(watch["scan_every_hours"]))
                self._touch(session, project, config=True)
                names = tracks_of(project)
                voices = voices_of(project.project_settings) if _is_private(project) else {}
                tracks = [self._track_config(session, project, track, (voices.get(track) or {}).get("name") or names[track], rows) for track in names]
                if _is_private(project):
                    out["tracks"] = tracks
                out["projects"].append({
                    "project": project.intake_key, "name": project.name, "kind": "PRIVATE" if _is_private(project) else project.kind,
                    "networks": [code for code in watch["networks"] if code in open_codes] if is_content_project(project) else open_codes,
                    "scan_every_hours": int(watch["scan_every_hours"]), "next_scan_at": next_scan, "tracks": tracks,
                })
            session.commit()
            return out

    # ---- signals: what the flow found

    @staticmethod
    def _signal_out(row: WatchSignal, source: WatchSource | None = None) -> dict[str, object]:
        return {
            "id": str(row.id), "track": row.track, "url": row.url, "title": row.title, "excerpt": row.excerpt, "author": row.author,
            "pillar": row.pillar, "keyword": row.keyword, "source_id": str(row.source_id) if row.source_id else None,
            "source_label": source.label if source is not None else (urlsplit(row.url).hostname or None),
            "published_at": row.published_at, "received_at": row.received_at, "state": row.state,
            "intake_id": str(row.intake_id) if row.intake_id else None, "via": row.via, "priority": row.priority,
        }

    @staticmethod
    def _expire(session, project) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=SIGNAL_DAYS)
        # A signal that became an idea is kept for as long as that idea is.
        session.execute(sql_delete(WatchSignal).where(
            WatchSignal.project_id == project.id, WatchSignal.received_at < cutoff,
            or_(WatchSignal.state != "USED", WatchSignal.intake_id.is_(None)),
        ))

    def receive(self, items: list[dict[str, object]]) -> dict[str, object]:
        """Take a batch from the scanning flow. Every field is untrusted text from the internet: trimmed, never followed.
        Each item lands on the project of its source, else on the project its `project` key names, else on the private space."""
        now = datetime.now(timezone.utc)
        accepted, duplicates, rejected = 0, 0, []
        with get_session() as session:
            listening = {str(project.id): project for project in self._projects(session)}
            by_key = {str(project.intake_key).upper(): project for project in listening.values()}
            private = next((project for project in listening.values() if _is_private(project)), None)
            sources = {str(row.id): row for row in session.scalars(select(WatchSource).where(WatchSource.project_id.in_(list(listening)))).all()} if listening else {}
            groups: dict[str, list[tuple[int, dict[str, object]]]] = {}
            for index, item in enumerate(items[:BATCH_LIMIT]):
                source = sources.get(str(item.get("source_id") or ""))
                if source is not None:
                    project = listening.get(str(source.project_id))
                elif item.get("project"):
                    project = by_key.get(str(item.get("project")).strip().upper())
                else:
                    project = private
                if project is None:
                    rejected.append({"index": index, "reason": "unknown project"})
                    continue
                groups.setdefault(str(project.id), []).append((index, item))
            for project_id, batch in groups.items():
                project = listening[project_id]
                self._expire(session, project)
                names = tracks_of(project)
                pillars = {track: set(kept) for track, kept in pillar_names_of(project).items()}
                room = SIGNAL_LIMIT - int(session.scalar(select(func.count()).select_from(WatchSignal).where(WatchSignal.project_id == project.id)) or 0)
                # What each track still takes in its collection week; None means the track set no target.
                quota = {track: self._demand_out(session, project, track)["accept_up_to"] for track in names}
                seen: set[tuple[str, str]] = set()
                taken = 0
                for index, item in batch:
                    address, title = web_address(item.get("url"), 1000), _line(item.get("title"), 300)
                    source = sources.get(str(item.get("source_id") or ""))
                    track = str(item.get("track") or "") or (source.track if source is not None and source.track in names else "") or (CONTENT_TRACK if is_content_project(project) else "")
                    if address is None or not title or track not in names:
                        rejected.append({"index": index, "reason": "url, title and a known track are required"})
                        continue
                    digest = hashlib.sha256(address.encode("utf-8")).hexdigest()
                    known = session.scalar(select(WatchSignal.id).where(WatchSignal.project_id == project.id, WatchSignal.track == track, WatchSignal.url_hash == digest).limit(1))
                    if known or (track, digest) in seen:
                        duplicates += 1
                        continue
                    if room <= 0:
                        rejected.append({"index": index, "reason": "the signal store is full"})
                        continue
                    if quota[track] is not None and quota[track] <= 0:
                        rejected.append({"index": index, "reason": "this week's quota for the track is reached"})
                        continue
                    published = item.get("published_at")
                    if isinstance(published, datetime) and published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    pillar = _line(item.get("pillar"), 120)
                    via = str(item.get("via") or "api")
                    priority = str(item.get("priority") or "normal")
                    session.add(WatchSignal(
                        id=str(uuid4()), project_id=project.id, track=track, source_id=source.id if source is not None else None, url=address,
                        url_hash=digest, title=title, excerpt=_line(item.get("excerpt"), 1000) or None, author=_line(item.get("author"), 120) or None,
                        pillar=pillar if pillar in pillars.get(track, set()) else None, keyword=_line(item.get("keyword"), 120) or None,
                        published_at=published if isinstance(published, datetime) and published <= now + timedelta(days=1) else None,
                        received_at=now, state="NEW", via=via if via in VIAS else "api", priority=priority if priority in TERM_PRIORITIES else "normal",
                    ))
                    seen.add((track, digest))
                    accepted, room, taken = accepted + 1, room - 1, taken + 1
                    if quota[track] is not None:
                        quota[track] -= 1
                if taken:
                    self._touch(session, project, signal=True)
                    self._audit(session, project, "watch.signals_received", "watch-flow", "project", project.id, {"accepted": taken}, actor_type="INTEGRATION")
            session.commit()
        rejected.sort(key=lambda row: row["index"])
        return {"accepted": accepted, "duplicates": duplicates, "rejected": rejected + [{"index": index, "reason": "more than the batch limit"} for index in range(BATCH_LIMIT, len(items))]}

    def signals(self, track: str, state: str = "NEW", project_id: str | None = None) -> list[dict[str, object]]:
        if state not in ("NEW", "USED", "DISMISSED"):
            raise WatchError("SIGNAL_FILTER_UNKNOWN", "Unknown track or state")
        with get_session() as session:
            project = self._project(session, project_id, required=False)
            if project is None:
                if track not in TRACKS:
                    raise WatchError("SIGNAL_FILTER_UNKNOWN", "Unknown track or state")
                return []
            if track not in tracks_of(project):
                raise WatchError("SIGNAL_FILTER_UNKNOWN", "Unknown track or state")
            self._expire(session, project)
            session.commit()
            rows = session.scalars(select(WatchSignal).where(
                WatchSignal.project_id == project.id, WatchSignal.track == track, WatchSignal.state == state,
            ).order_by(WatchSignal.received_at.desc()).limit(100)).all()
            sources = {str(row.id): row for row in session.scalars(select(WatchSource).where(WatchSource.project_id == project.id)).all()}
            return [self._signal_out(row, sources.get(str(row.source_id))) for row in rows]

    @staticmethod
    def for_plan(session, project, track: str) -> list[dict[str, object]]:
        """Fresh signals the weekly proposal may lean on: untrusted, short, the newest first."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=14)
        rows = session.scalars(select(WatchSignal).where(
            WatchSignal.project_id == project.id, WatchSignal.track == track, WatchSignal.state == "NEW", WatchSignal.received_at >= cutoff,
        ).order_by(WatchSignal.received_at.desc()).limit(25)).all()
        return [{"title": row.title, "pillar": row.pillar or "", "keyword": row.keyword or "", "host": urlsplit(row.url).hostname or ""} for row in rows]

    def _signal(self, session, project, signal_id: str) -> WatchSignal:
        try:
            row = session.get(WatchSignal, signal_id)
        except Exception:  # a malformed ID is simply not a signal
            session.rollback()
            row = None
        if row is None or str(row.project_id) != str(project.id):
            raise WatchError("SIGNAL_NOT_FOUND", "Signal not found")
        return row

    def dismiss(self, signal_id: str, actor_id: str, project_id: str | None = None) -> None:
        with get_session() as session:
            project = self._project(session, project_id)
            row = self._signal(session, project, signal_id)
            if row.state == "NEW":
                row.state = "DISMISSED"
                self._audit(session, project, "watch.signal_dismissed", actor_id, "watch_signal", row.id, {"track": row.track})
                session.commit()

    def to_idea(self, signal_id: str, actor_id: str) -> tuple[dict[str, object], str]:
        """Keep a signal as an idea of its track: the link and what was found, for the owner to write their own take."""
        with get_session() as session:
            project = self._project(session)
            row = self._signal(session, project, signal_id)
            if row.intake_id is not None:
                return self._signal_out(row), str(row.intake_id)
            code, track = project.code, row.track
            text = "\n".join(part for part in (row.title, row.excerpt or "", row.url) if part)
        from app.schemas import IntakeCreate
        from app.services.intake_service import intake_store

        created = str(intake_store.create(IntakeCreate(project_id=code, channel="MANUAL", raw_text=text)).id)
        private_space_service.set_track(created, track, actor_id)
        with get_session() as session:
            project = self._project(session)
            row = self._signal(session, project, signal_id)
            row.state, row.intake_id = "USED", created
            self._audit(session, project, "watch.signal_kept", actor_id, "watch_signal", row.id, {"track": row.track})
            session.commit()
            return self._signal_out(row), created


watch_service = WatchService()
