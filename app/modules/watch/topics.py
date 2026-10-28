"""Hot topics of a marketing project (FR-MKT-09, ADR-0068): the signals of the last days grouped by keyword, scored by
rule, then summed up and read for angles by AI. The owner makes a post, or a series across channels, of a topic, or
drops it. AI never chooses: a topic without the owner's click goes nowhere.

The rule part always runs and always leaves a readable topic; the AI part only improves the words. An AI failure is
written into the audit and the rule text stands."""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import urlsplit
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db import get_session
from app.models import AuditEvent, Project, WatchSignal, WatchSource, WatchTopic
from app.modules.watch.service import CONTENT_TRACK, USED_MEMORY_DAYS, WatchError, demand_of, is_content_project, pillars_of, watch_of, watch_service

LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")
TOPIC_LIMIT = 10
SIGNALS_PER_TOPIC = 8
LINKS_PER_POST = 5
MANUAL_RUNS_PER_DAY = 3
FRESH_HOURS = 48
ANGLE_LIMIT = 3
# The channels a series takes when the pillar names none: the page first, the English versions a day later.
DEFAULT_SERIES = ("FACEBOOK_PAGE", "LINKEDIN", "X")
ENGLISH_CHANNELS = {"X", "LINKEDIN"}
# How close two beat ticks may be before the second one is the same run.
TICK_MINUTES = 30


def _monday(now: datetime) -> date:
    local = now.astimezone(LOCAL).date()
    return local - timedelta(days=local.weekday())


def _norm(value: object) -> str:
    return " ".join(str(value or "").lower().lstrip("#").split())


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower().removeprefix("www.")


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def candidates(session, project: Project, now: datetime | None = None) -> list[dict[str, object]]:
    """The signal groups worth a topic this week, scored by rule, best first. Nothing here calls AI."""
    now = now or datetime.now(timezone.utc)
    demand = demand_of(project).get(CONTENT_TRACK) or {}
    cutoff = now - timedelta(days=int(demand.get("lookback_days") or 7))
    rows = session.scalars(select(WatchSignal).where(
        WatchSignal.project_id == project.id, WatchSignal.track == CONTENT_TRACK, WatchSignal.state == "NEW", WatchSignal.received_at >= cutoff,
    ).order_by(WatchSignal.received_at.desc())).all()
    # A keyword a used topic stood on lately still counts against a new one on the same keyword.
    used_since = now - timedelta(days=USED_MEMORY_DAYS)
    used_keys = {_norm(keyword) for keyword in session.scalars(select(WatchSignal.keyword).where(
        WatchSignal.project_id == project.id, WatchSignal.state == "USED", WatchSignal.received_at >= used_since, WatchSignal.keyword.is_not(None),
    )).all() if _norm(keyword)}
    groups: dict[str, list[WatchSignal]] = {}
    for row in rows:
        key = _norm(row.keyword) or _norm(row.pillar) or _host(row.url)
        groups.setdefault(key, []).append(row)
    fresh_after = now - timedelta(hours=FRESH_HOURS)
    scored = []
    for key, signals in groups.items():
        sources = {str(row.source_id) if row.source_id else _host(row.url) for row in signals}
        pillars = Counter(row.pillar for row in signals if row.pillar)
        fresh = any(_aware(row.published_at) is not None and _aware(row.published_at) >= fresh_after for row in signals)
        high = any(row.priority == "high" for row in signals)
        # What a scraping service or a hashtag brought is one notch below what a whitelisted source wrote.
        penalty = any(row.via in ("scrape", "agent") for row in signals) or any(str(row.keyword or "").startswith("#") for row in signals)
        score = 2 * len(sources) + min(len(signals), 5) + (2 if pillars else 0) + (2 if fresh else 0) + (1 if high else 0) - (1 if penalty else 0) - (3 if key in used_keys else 0)
        # Newest first; a signal that names its date comes before one that does not; the scanner's order breaks ties.
        ordered = sorted(enumerate(signals), key=lambda pair: (_aware(pair[1].published_at) or datetime.min.replace(tzinfo=timezone.utc), -pair[0]), reverse=True)
        ordered = [row for _, row in ordered][:SIGNALS_PER_TOPIC]
        scored.append({
            "key": key, "score": score, "sources": len(sources), "count": len(signals), "pillar": pillars.most_common(1)[0][0] if pillars else None,
            "keyword": next((row.keyword for row in ordered if row.keyword), None), "signals": ordered, "fresh": fresh,
        })
    scored.sort(key=lambda group: (group["score"], group["count"]), reverse=True)
    return scored[:TOPIC_LIMIT]


class TopicsService:
    @staticmethod
    def _project(session, project_id: str) -> Project:
        project = watch_service._project(session, project_id)
        if not is_content_project(project):
            raise WatchError("WATCH_NOT_FOR_PROJECT", "Only a marketing project has hot topics")
        return project

    @staticmethod
    def _audit(session, project_id: str, event: str, actor_id: str, entity: str, entity_id: str, details: dict, actor_type: str = "USER") -> None:
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project_id, actor_type=actor_type, actor_id=actor_id, event_type=event,
            entity_type=entity, entity_id=entity_id, details=details, created_at=datetime.now(timezone.utc),
        ))

    @staticmethod
    def _rule_why(group: dict[str, object], lookback: int) -> str:
        parts = [f"{group['sources']} nguồn, {group['count']} bài trong {lookback} ngày"]
        if group["pillar"]:
            parts.append(f"trụ {group['pillar']}")
        if group["fresh"]:
            parts.append("có bài trong 48 giờ")
        return "; ".join(parts) + "."

    def build_rules(self, project_id: str, actor: str = "watch-topics", now: datetime | None = None) -> dict[str, object] | None:
        """Write this week's topics from the rules, and return what the AI should read. None when there is nothing."""
        now = now or datetime.now(timezone.utc)
        week = _monday(now)
        with get_session() as session:
            project = self._project(session, project_id)
            groups = candidates(session, project, now)
            if not groups:
                self._audit(session, project.id, "watch.topics_built", actor, "project", project.id, {"topics": 0, "ai": "off"}, actor_type="INTEGRATION")
                session.commit()
                return None
            lookback = int((demand_of(project).get(CONTENT_TRACK) or {}).get("lookback_days") or 7)
            out = []
            for group in groups:
                # One row per subject and week. A subject the owner already took or dropped this week, and that new
                # signals bring back, gets a fresh row: the closed one is a record, not a blocker.
                row, suffix = None, 1
                while True:
                    key = _key(str(group["key"]) + ("" if suffix == 1 else f"|{suffix}"))
                    row = session.scalar(select(WatchTopic).where(WatchTopic.project_id == project.id, WatchTopic.week_start == week, WatchTopic.key == key))
                    if row is None or row.state == "NEW" or suffix >= TOPIC_LIMIT:
                        break
                    suffix += 1
                if row is not None and row.state != "NEW":
                    continue
                newest = group["signals"][0]
                if row is None:
                    row = WatchTopic(id=str(uuid4()), project_id=project.id, week_start=week, key=key, title=newest.title[:200], created_at=now, state="NEW")
                    session.add(row)
                if not row.ai_written:
                    row.title, row.why, row.angles, row.channels, row.caution = newest.title[:200], self._rule_why(group, lookback), [], [], None
                row.pillar = (str(group["pillar"])[:60] if group["pillar"] else None)
                row.score, row.signal_ids, row.updated_at = int(group["score"]), [str(signal.id) for signal in group["signals"]], now
                out.append({
                    "id": str(row.id), "title": row.title, "why": row.why, "pillar": row.pillar, "keyword": group["keyword"], "score": row.score,
                    "signals": [{"title": signal.title, "host": _host(signal.url), "keyword": signal.keyword or "", "published_at": signal.published_at, "via": signal.via} for signal in group["signals"]],
                })
            session.commit()
            context = watch_service.context_for_ai(session, project)
            return {"project_id": str(project.id), "week_start": week, "topics": out, "context": context}

    def apply_ai(self, project_id: str, topics: list[dict[str, object]] | None, error: str | None = None, actor: str = "watch-topics") -> int:
        """Lay the AI's words on the NEW topics it was given; on an error, the rule words stand and the audit says so."""
        now = datetime.now(timezone.utc)
        written = 0
        with get_session() as session:
            project = self._project(session, project_id)
            if topics:
                pillars = {pillar["name"] for pillar in pillars_of(project).get(CONTENT_TRACK, [])}
                for spec in topics:
                    try:
                        row = session.get(WatchTopic, str(spec.get("id") or ""))
                    except Exception:
                        session.rollback()
                        row = None
                    if row is None or str(row.project_id) != str(project.id) or row.state != "NEW":
                        continue
                    title = " ".join(str(spec.get("title") or "").split())[:200]
                    if not title:
                        continue
                    row.title, row.why = title, " ".join(str(spec.get("why") or "").split())[:400] or row.why
                    row.angles = [" ".join(str(angle).split())[:160] for angle in (spec.get("angles") or []) if str(angle).strip()][:ANGLE_LIMIT]
                    row.channels = [str(code).upper() for code in (spec.get("channels") or []) if isinstance(code, str)][:6]
                    row.caution = " ".join(str(spec.get("caution") or "").split())[:300] or None
                    pillar = str(spec.get("pillar") or "")
                    if pillar in pillars:
                        row.pillar = pillar[:60]
                    row.ai_written, row.updated_at = True, now
                    written += 1
            self._audit(session, project.id, "watch.topics_built", actor, "project", project.id,
                        {"topics": written, "ai": "failed" if error else "ok", "error": error}, actor_type="INTEGRATION")
            session.commit()
        return written

    def build(self, project_id: str, actor: str = "watch-topics", ai: list[dict[str, object]] | None = None, error: str | None = None) -> dict[str, object] | None:
        """Rules, then whatever the AI (or a test standing in for it) answered."""
        rules = self.build_rules(project_id, actor)
        if rules is None:
            return None
        self.apply_ai(project_id, ai, error, actor)
        return rules

    # ---- what the owner sees and does

    @staticmethod
    def _today_local(now: datetime | None = None) -> tuple[datetime, datetime]:
        local = (now or datetime.now(timezone.utc)).astimezone(LOCAL)
        start = datetime.combine(local.date(), time(0, 0), tzinfo=LOCAL).astimezone(timezone.utc)
        return start, start + timedelta(days=1)

    def _manual_runs_today(self, session, project_id: str) -> int:
        start, end = self._today_local()
        return int(session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.project_id == project_id, AuditEvent.event_type == "watch.topics_requested", AuditEvent.created_at >= start, AuditEvent.created_at < end,
        )) or 0)

    @staticmethod
    def _topic_out(row: WatchTopic, signals: dict[str, WatchSignal]) -> dict[str, object]:
        kept = [signals[signal_id] for signal_id in (row.signal_ids or []) if signal_id in signals]
        return {
            "id": str(row.id), "week_start": row.week_start, "title": row.title, "why": row.why, "angles": list(row.angles or []), "channels": list(row.channels or []),
            "caution": row.caution, "pillar": row.pillar, "score": row.score, "state": row.state, "ai_written": bool(row.ai_written),
            "work_id": str(row.work_id) if row.work_id else None, "sources": len({_host(signal.url) for signal in kept}),
            "signals": [{"id": str(signal.id), "title": signal.title, "url": signal.url, "host": _host(signal.url), "keyword": signal.keyword, "published_at": signal.published_at, "via": signal.via} for signal in kept],
            "updated_at": row.updated_at,
        }

    def list(self, project_id: str, now: datetime | None = None) -> dict[str, object]:
        now = now or datetime.now(timezone.utc)
        week = _monday(now)
        with get_session() as session:
            project = self._project(session, project_id)
            rows = session.scalars(select(WatchTopic).where(WatchTopic.project_id == project.id, WatchTopic.week_start == week)
                                   .order_by(WatchTopic.score.desc(), WatchTopic.updated_at.desc())).all()
            ids = [signal_id for row in rows for signal_id in (row.signal_ids or [])]
            signals = {str(row.id): row for row in session.scalars(select(WatchSignal).where(WatchSignal.id.in_(ids))).all()} if ids else {}
            has_sources = session.scalar(select(func.count()).select_from(WatchSource).where(WatchSource.project_id == project.id, WatchSource.active.is_(True))) or 0
            built = session.scalar(select(AuditEvent.created_at).where(AuditEvent.project_id == project.id, AuditEvent.event_type == "watch.topics_built").order_by(AuditEvent.created_at.desc()).limit(1))
            schedule = watch_of(project.project_settings)["schedule"]
            order = {"NEW": 0, "USED": 1, "DISMISSED": 2}
            return {
                "week_start": week, "has_sources": bool(has_sources), "kept_this_week": sum(row.state == "USED" for row in rows),
                "refresh_left": max(0, MANUAL_RUNS_PER_DAY - self._manual_runs_today(session, project.id)), "built_at": built,
                "schedule": schedule, "topics": [self._topic_out(row, signals) for row in sorted(rows, key=lambda row: (order.get(row.state, 3), -row.score))],
            }

    def request_build(self, project_id: str, actor_id: str, publisher=None) -> dict[str, object]:
        """The owner asks for a fresh build now: at most three a day on a project, on top of the scheduled runs."""
        with get_session() as session:
            project = self._project(session, project_id)
            used = self._manual_runs_today(session, project.id)
            if used >= MANUAL_RUNS_PER_DAY:
                raise WatchError("TOPICS_LIMIT", f"Làm mới tối đa {MANUAL_RUNS_PER_DAY} lần mỗi ngày; lượt tự động vẫn chạy theo lịch")
            self._audit(session, project.id, "watch.topics_requested", actor_id, "project", project.id, {"run": used + 1})
            session.commit()
            project_id = str(project.id)
        (publisher or _publish)(project_id, actor_id)
        return {"status": "PENDING", "refresh_left": MANUAL_RUNS_PER_DAY - used - 1}

    def _topic(self, session, project: Project, topic_id: str) -> WatchTopic:
        try:
            UUID(str(topic_id))
            row = session.get(WatchTopic, topic_id)
        except (ValueError, TypeError):
            row = None
        if row is None or str(row.project_id) != str(project.id):
            raise WatchError("TOPIC_NOT_FOUND", "Topic not found")
        return row

    def dismiss(self, project_id: str, topic_id: str, actor_id: str, actor_type: str = "USER") -> None:
        with get_session() as session:
            project = self._project(session, project_id)
            row = self._topic(session, project, topic_id)
            if row.state == "NEW":
                row.state, row.updated_at = "DISMISSED", datetime.now(timezone.utc)
                # Its signals go with it, so the same findings do not come back as a topic at the next run.
                for signal in session.scalars(select(WatchSignal).where(WatchSignal.id.in_(row.signal_ids or []))).all() if row.signal_ids else []:
                    if signal.state == "NEW":
                        signal.state = "DISMISSED"
                self._audit(session, project.id, "watch.topic_dismissed", actor_id, "watch_topic", row.id, {"title": row.title[:120]}, actor_type=actor_type)
                session.commit()

    def trending(self, project_id: str, days: int = 7, pillar: str | None = None) -> dict[str, object]:
        """Keywords and hashtags rising in the sources the project watches: how many findings now against the same
        span before, from how many sites, and the newest title. Nothing about the platforms' own trends."""
        days = max(1, min(int(days), 30))
        now = datetime.now(timezone.utc)
        since, before = now - timedelta(days=days), now - timedelta(days=2 * days)
        with get_session() as session:
            project = self._project(session, project_id)
            rows = session.scalars(select(WatchSignal).where(
                WatchSignal.project_id == project.id, WatchSignal.track == CONTENT_TRACK, WatchSignal.received_at >= before, WatchSignal.keyword.is_not(None),
            ).order_by(WatchSignal.received_at.desc())).all()
            groups: dict[str, list[WatchSignal]] = {}
            for row in rows:
                key = _norm(row.keyword)
                if key:
                    groups.setdefault(key, []).append(row)
            out = []
            for key, signals in groups.items():
                current = [row for row in signals if _aware(row.received_at) >= since]
                if not current:
                    continue
                pillars = Counter(row.pillar for row in current if row.pillar)
                top_pillar = pillars.most_common(1)[0][0] if pillars else None
                if pillar and (top_pillar or "").lower() != pillar.lower():
                    continue
                newest = current[0]
                out.append({
                    "keyword": next(row.keyword for row in current if row.keyword), "kind": "hashtag" if key.startswith("#") or str(newest.keyword).startswith("#") else "keyword",
                    "pillar": top_pillar, "count": len(current), "previous": len(signals) - len(current), "sources": len({_host(row.url) for row in current}),
                    "priority": "high" if any(row.priority == "high" for row in current) else "normal",
                    "newest": {"title": newest.title, "host": _host(newest.url), "published_at": newest.published_at, "via": newest.via},
                })
            out.sort(key=lambda row: (row["count"], row["sources"]), reverse=True)
            return {"days": days, "since": since, "keywords": out[:20]}

    def to_post(self, project_id: str, topic_id: str, *, actor_id: str, mode: str = "post", angle: int | None = None,
                member_id: str | None = None, week: date | None = None, actor_type: str = "USER") -> dict[str, object]:
        """A post in Ý tưởng from a topic, or a series: one post with a version per channel of the pillar, dated by
        the channel's good hour. The topic and its signals are marked used; asking twice returns the same post."""
        from app.modules.work.channels import rule_of
        from app.modules.work.service import work_service

        if mode not in ("post", "series"):
            raise WatchError("TOPIC_MODE_INVALID", "mode is post or series")
        with get_session() as session:
            project = self._project(session, project_id)
            row = self._topic(session, project, topic_id)
            if row.work_id and row.state == "USED":
                return work_service.get(str(row.work_id)) or {}
            if row.state != "NEW":
                raise WatchError("TOPIC_CLOSED", "This topic was dropped; nothing to make of it")
            angles = list(row.angles or [])
            title = angles[angle] if angle is not None and 0 <= angle < len(angles) else row.title
            found = {str(signal.id): signal for signal in session.scalars(select(WatchSignal).where(WatchSignal.id.in_(row.signal_ids or []))).all()} if row.signal_ids else {}
            signals = [found[signal_id] for signal_id in (row.signal_ids or []) if signal_id in found]
            lines = [row.why or ""]
            if row.caution:
                lines.append(f"Lưu ý: {row.caution}")
            if signals:
                lines += ["", "Nguồn:"] + [f"- {signal.title} {signal.url}" for signal in signals[:LINKS_PER_POST]]
            description = "\n".join(line for line in lines if line is not None).strip()
            pillar = next((pillar for pillar in pillars_of(project).get(CONTENT_TRACK, []) if pillar["name"] == row.pillar), None)
            channels = None
            if mode == "series":
                codes = [code for code in (pillar["channels"] if pillar else []) if code] or list(DEFAULT_SERIES)
                # The day after the Monday of the week being looked at, never earlier than tomorrow.
                tomorrow = datetime.now(LOCAL).date() + timedelta(days=1)
                first_day = max(week + timedelta(days=1), tomorrow) if week is not None else tomorrow
                channels = []
                for code in codes:
                    rule = rule_of(code)
                    if rule is None:
                        continue
                    hour = time.fromisoformat(str((rule.get("best_hours") or ["09:00"])[0]))
                    day = first_day + timedelta(days=1 if code in ENGLISH_CHANNELS else 0)
                    channels.append({"channel": code, "publish_at": datetime.combine(day, hour, tzinfo=LOCAL).astimezone(timezone.utc), "language": "en" if code in ENGLISH_CHANNELS else None})
            project_id_str, signal_rows = str(project.id), [(signal.title, signal.url) for signal in signals[:LINKS_PER_POST]]
        made = work_service.create(project_id=project_id_str, title=title, description=description, priority="P2", member_id=member_id or None,
                                   due_date=None, status="DISCUSS", actor_id=actor_id, actor_type=actor_type, channels=channels)
        for link_title, url in signal_rows:
            try:
                work_service.add_link(made["id"], url=url, note=link_title[:300], actor_id=actor_id, actor_type=actor_type)
            except Exception:
                continue
        with get_session() as session:
            project = self._project(session, project_id)
            row = self._topic(session, project, topic_id)
            now = datetime.now(timezone.utc)
            row.state, row.work_id, row.updated_at = "USED", made["id"], now
            for signal in session.scalars(select(WatchSignal).where(WatchSignal.id.in_(row.signal_ids or []))).all() if row.signal_ids else []:
                if signal.state == "NEW":
                    signal.state = "USED"
            self._audit(session, project.id, "watch.topic_kept", actor_id, "watch_topic", row.id, {"work_id": made["id"], "mode": mode, "angle": angle, "title": title[:120]}, actor_type=actor_type)
            session.commit()
        return work_service.get(made["id"]) or made

    # ---- the clock: which projects are due a run

    def due_projects(self, now: datetime | None = None) -> list[str]:
        """Projects whose schedule names a time in the half hour that just passed and that were not run for it yet."""
        now = now or datetime.now(timezone.utc)
        local = now.astimezone(LOCAL)
        since = now - timedelta(minutes=TICK_MINUTES)
        due: list[str] = []
        with get_session() as session:
            for project in watch_service._projects(session):
                if not is_content_project(project):
                    continue
                if not session.scalar(select(WatchSource.id).where(WatchSource.project_id == project.id, WatchSource.active.is_(True)).limit(1)):
                    continue
                schedule = watch_of(project.project_settings)["schedule"]
                if local.isoweekday() not in schedule["weekdays"]:
                    continue
                hit = False
                for stamp in schedule["times"]:
                    moment = datetime.combine(local.date(), time.fromisoformat(stamp), tzinfo=LOCAL)
                    if since < moment.astimezone(timezone.utc) <= now:
                        hit = True
                if not hit:
                    continue
                recent = session.scalar(select(AuditEvent.id).where(
                    AuditEvent.project_id == project.id, AuditEvent.event_type == "watch.topics_scheduled", AuditEvent.created_at >= since,
                ).limit(1))
                if recent:
                    continue
                self._audit(session, project.id, "watch.topics_scheduled", "scheduler", "project", project.id, {"at": local.strftime("%H:%M")}, actor_type="WORKER")
                due.append(str(project.id))
            session.commit()
        return due


def _publish(project_id: str, actor_id: str) -> None:
    from app.queue.celery_app import celery_app

    celery_app.send_task("intake.watch.topics", args=[project_id, actor_id], queue="ai.normalize")


topics_service = TopicsService()
