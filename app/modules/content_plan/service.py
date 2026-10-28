"""The week plan of the private space (ADR-0037).

A track has a rhythm: the slots it means to fill every week. A week is those slots, each waiting for an idea, a
draft, an approval and a post. Nothing here publishes anything: a slot only records what is meant and what happened.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, IdeaTrack, IntakeItem, PlanRequest, PlanSlot, PostDraft
from app.modules.private_space.service import CHANNELS, PRIVATE_FLAG, TRACKS, PrivateSpaceService, by_track, master_dna_of, private_space_service, voices_of
from app.modules.watch.service import WatchService
from app.services.raw_crypto import decrypt, encrypt

LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")
RHYTHM_KEY = "rhythm"
SLOT_LIMIT = 7
IDEA_LIMIT = 40
# Posts are planned for the morning when the rhythm names no hour.
DEFAULT_TIME = time(9, 0)
WEEKDAYS = ("Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ nhật")
_TIME = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


class PlanError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def this_week() -> date:
    return monday(datetime.now(LOCAL).date())


def rhythm_of(settings: object) -> dict[str, list[dict[str, object]]]:
    stored = by_track(settings.get(RHYTHM_KEY)) if isinstance(settings, dict) else {}
    return {track: [dict(slot) for slot in (stored.get(track) or [])] for track in TRACKS}


def slot_moment(slot: PlanSlot) -> datetime:
    """When the slot's post is meant to go out, as an absolute time."""
    hour = time.fromisoformat(slot.time) if slot.time else DEFAULT_TIME
    return datetime.combine(slot.week_start + timedelta(days=slot.weekday - 1), hour, tzinfo=LOCAL).astimezone(timezone.utc)


def _publish(request_id: str) -> None:
    from app.queue.celery_app import celery_app

    celery_app.send_task("intake.plan.propose", args=[request_id], queue="ai.normalize")


def _aware(value: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes; they were stored as UTC.
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


class ContentPlanService:
    @staticmethod
    def _key(slot: object) -> tuple[int, str, str]:
        get = slot.get if isinstance(slot, dict) else lambda name: getattr(slot, name)
        return int(get("weekday")), str(get("time") or ""), str(get("channel"))

    @staticmethod
    def _untouched(slot: PlanSlot) -> bool:
        return slot.intake_id is None and slot.draft_id is None and not slot.skipped and not slot.suggestion_ciphertext

    def _sync(self, session, project, track: str, week_start: date) -> None:
        """Bring a week in line with the rhythm, leaving alone every slot that already holds something."""
        wanted = {self._key(slot): slot for slot in rhythm_of(project.project_settings)[track]}
        held = session.scalars(select(PlanSlot).where(
            PlanSlot.project_id == project.id, PlanSlot.track == track, PlanSlot.week_start == week_start,
        )).all()
        seen = set()
        for slot in held:
            key = self._key(slot)
            if key in wanted and key not in seen:
                seen.add(key)
                slot.pillar = slot.pillar if not self._untouched(slot) else (wanted[key].get("pillar") or None)
            elif self._untouched(slot):
                session.delete(slot)
        now = datetime.now(timezone.utc)
        for key, slot in wanted.items():
            if key not in seen:
                session.add(PlanSlot(
                    id=str(uuid4()), project_id=project.id, track=track, week_start=week_start, weekday=key[0], time=key[1] or None,
                    channel=key[2], pillar=slot.get("pillar") or None, skipped=False, created_at=now, updated_at=now,
                ))

    @staticmethod
    def _suggestion(slot: PlanSlot) -> dict[str, object] | None:
        if not slot.suggestion_ciphertext:
            return None
        try:
            value = json.loads(decrypt(slot.suggestion_ciphertext) or "")
        except ValueError:
            return None
        return value if isinstance(value, dict) else None

    def _slot_out(self, session, slot: PlanSlot) -> dict[str, object]:
        idea = session.get(IntakeItem, slot.intake_id) if slot.intake_id else None
        draft = session.get(PostDraft, slot.draft_id) if slot.draft_id else None
        suggestion = self._suggestion(slot)
        if slot.skipped:
            state = "SKIPPED"
        elif draft is not None and draft.posted_at is not None:
            state = "POSTED"
        elif draft is not None and draft.approved_at is not None:
            state = "APPROVED"
        elif idea is not None:
            written = session.scalar(select(PostDraft.id).where(PostDraft.intake_id == idea.id, PostDraft.status == "DONE").limit(1))
            state = "DRAFTED" if written else "IDEA"
        elif suggestion is not None:
            state = "PROPOSED"
        else:
            state = "EMPTY"
        suggested = session.get(IntakeItem, suggestion["idea_id"]) if suggestion and suggestion.get("idea_id") else None
        return {
            "id": str(slot.id), "track": slot.track, "week_start": slot.week_start,
            "day": slot.week_start + timedelta(days=slot.weekday - 1), "weekday": slot.weekday, "time": slot.time,
            "planned_for": slot_moment(slot), "channel": slot.channel, "pillar": slot.pillar, "state": state,
            "idea": {"id": str(idea.id), "public_id": idea.public_id, "title": idea.normalized_title} if idea is not None else None,
            "draft": {
                "id": str(draft.id), "channel": draft.channel, "approved_at": _aware(draft.approved_at),
                "scheduled_for": _aware(draft.scheduled_for), "posted_at": _aware(draft.posted_at),
                "posted_url": draft.posted_url, "posted_via": draft.posted_via,
            } if draft is not None else None,
            "suggestion": {
                "title": str(suggestion.get("title") or ""), "reason": str(suggestion.get("reason") or ""),
                "pillar": suggestion.get("pillar") or None, "from_store": suggested is not None,
            } if suggestion is not None and idea is None else None,
        }

    @staticmethod
    def _posted(session, project, track: str, since: datetime, until: datetime) -> list[PostDraft]:
        rows = session.scalars(select(PostDraft).where(
            PostDraft.project_id == project.id, PostDraft.posted_at.is_not(None), PostDraft.posted_at >= since, PostDraft.posted_at < until,
        )).all()
        # A draft written before tracks existed belongs to the first one.
        return [row for row in rows if (row.track or next(iter(TRACKS))) == track]

    def _stats(self, session, project, track: str, week_start: date, slots: list[dict[str, object]]) -> dict[str, object]:
        start = datetime.combine(week_start, time(0, 0), tzinfo=LOCAL).astimezone(timezone.utc)
        end = start + timedelta(days=7)
        recent = self._posted(session, project, track, start - timedelta(days=21), end)
        counts: dict[str, int] = {}
        for draft in recent:
            counts[draft.pillar or ""] = counts.get(draft.pillar or "", 0) + 1
        lately = {draft.pillar for draft in recent if _aware(draft.posted_at) >= start - timedelta(days=14)}
        pillars = [str(pillar) for pillar in voices_of(project.project_settings)[track].get("pillars") or []]
        in_week = [draft for draft in recent if _aware(draft.posted_at) >= start]
        planned = {slot["draft"]["id"] for slot in slots if slot["draft"]}
        drafted = session.scalars(select(PostDraft).where(
            PostDraft.project_id == project.id, PostDraft.status == "DONE", PostDraft.created_at >= start, PostDraft.created_at < end,
        )).all()
        return {
            "slots": sum(slot["state"] != "SKIPPED" for slot in slots),
            "posted": sum(slot["state"] == "POSTED" for slot in slots),
            "approved": sum(slot["state"] == "APPROVED" for slot in slots),
            "open": sum(slot["state"] in ("EMPTY", "PROPOSED") for slot in slots),
            "drafted_ideas": len({str(draft.intake_id) for draft in drafted if (draft.track or next(iter(TRACKS))) == track}),
            "posted_total": len(in_week),
            # Posted this week without a slot: the measure of writing outside the plan.
            "off_plan": sum(str(draft.id) not in planned for draft in in_week),
            "pillars": [{"pillar": pillar, "posted": counts.get(pillar, 0)} for pillar in pillars] + ([{"pillar": "", "posted": counts[""]}] if counts.get("") else []),
            "missing_pillars": [pillar for pillar in pillars if pillar not in lately],
        }

    def _week(self, session, project, week_start: date) -> dict[str, object]:
        tracks: dict[str, object] = {}
        voices = voices_of(project.project_settings)
        for track in TRACKS:
            rows = session.scalars(select(PlanSlot).where(
                PlanSlot.project_id == project.id, PlanSlot.track == track, PlanSlot.week_start == week_start,
            ).order_by(PlanSlot.weekday, PlanSlot.time, PlanSlot.created_at)).all()
            slots = [self._slot_out(session, row) for row in rows]
            request = session.scalar(select(PlanRequest).where(
                PlanRequest.project_id == project.id, PlanRequest.track == track, PlanRequest.week_start == week_start,
            ).order_by(PlanRequest.created_at.desc()).limit(1))
            tracks[track] = {
                "name": voices[track].get("name") or TRACKS[track], "slots": slots,
                "stats": self._stats(session, project, track, week_start, slots),
                "request": {"status": request.status, "error": request.error} if request is not None else None,
            }
        return {
            "week_start": week_start, "this_week": this_week(), "editable": week_start >= this_week(),
            "tracks": tracks, "rhythm": rhythm_of(project.project_settings),
        }

    def week(self, week_start: date | None = None) -> dict[str, object]:
        week_start = week_start or this_week()
        if week_start.weekday() != 0:
            raise PlanError("WEEK_INVALID", "A week starts on a Monday")
        with get_session() as session:
            project = private_space_service._project(session)
            if project is None:
                return {"week_start": week_start, "this_week": this_week(), "editable": False, "tracks": {}, "rhythm": rhythm_of(None)}
            # Only this week and the next are laid out from the rhythm; the past stays as it was.
            if week_start in (this_week(), this_week() + timedelta(days=7)):
                for track in TRACKS:
                    self._sync(session, project, track, week_start)
                session.commit()
            return self._week(session, project, week_start)

    def save_rhythm(self, track: str, slots: list[dict[str, object]], actor_id: str) -> dict[str, object]:
        if track not in TRACKS:
            raise PlanError("TRACK_UNKNOWN", "Unknown track")
        if len(slots) > SLOT_LIMIT:
            raise PlanError("RHYTHM_TOO_LONG", f"A track has at most {SLOT_LIMIT} slots a week")
        cleaned: dict[tuple[int, str, str], dict[str, object]] = {}
        for slot in slots:
            weekday, hour, channel = int(slot.get("weekday") or 0), (str(slot.get("time") or "").strip() or None), str(slot.get("channel") or "")
            if weekday not in range(1, 8) or channel not in CHANNELS or (hour is not None and not _TIME.match(hour)):
                raise PlanError("RHYTHM_INVALID", "A slot needs a weekday, a known channel and an hour written HH:MM")
            pillar = " ".join(str(slot.get("pillar") or "").split())[:120] or None
            cleaned[(weekday, hour or "", channel)] = {"weekday": weekday, "time": hour, "channel": channel, "pillar": pillar}
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = private_space_service._project(session)
            if project is None:
                raise PlanError("PRIVATE_SPACE_MISSING", "The private space has not been opened yet")
            current = project.project_settings or {}
            rhythm = rhythm_of(current)
            rhythm[track] = [cleaned[key] for key in sorted(cleaned)]
            # Rewritten whole, so a rhythm stored under an old track name is carried over.
            # A new dict, so the JSON column is seen as changed.
            project.project_settings = {**current, PRIVATE_FLAG: True, RHYTHM_KEY: rhythm}
            project.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="private_space.rhythm_updated", entity_type="project", entity_id=project.id,
                details={"track": track, "slots": len(cleaned)}, created_at=now,
            ))
            session.flush()
            for week_start in (this_week(), this_week() + timedelta(days=7)):
                self._sync(session, project, track, week_start)
            session.commit()
            return self._week(session, project, this_week())

    @staticmethod
    def _slot(session, project, slot_id: str) -> PlanSlot:
        try:
            slot = session.get(PlanSlot, slot_id)
        except Exception:  # a malformed ID is simply not a slot
            session.rollback()
            slot = None
        if project is None or slot is None or str(slot.project_id) != str(project.id):
            raise PlanError("SLOT_NOT_FOUND", "Slot not found")
        return slot

    def slot(self, slot_id: str) -> dict[str, object]:
        with get_session() as session:
            return self._slot_out(session, self._slot(session, private_space_service._project(session), slot_id))

    def _locked(self, session, slot: PlanSlot) -> bool:
        draft = session.get(PostDraft, slot.draft_id) if slot.draft_id else None
        return draft is not None and (draft.approved_at is not None or draft.posted_at is not None)

    def change_slot(self, slot_id: str, changes: dict[str, object], actor_id: str) -> dict[str, object]:
        """Put an idea in a slot, take it out, skip the slot for this week, or wave a suggestion away."""
        with get_session() as session:
            project = private_space_service._project(session)
            slot = self._slot(session, project, slot_id)
            if "intake_id" in changes:
                if self._locked(session, slot):
                    raise PlanError("SLOT_LOCKED", "The slot holds an approved post; take the approval back first")
                wanted = changes["intake_id"]
                if wanted:
                    try:
                        idea = session.get(IntakeItem, str(wanted))
                    except Exception:
                        session.rollback()
                        idea = None
                    if idea is None or str(idea.project_id) != str(project.id) or idea.status == "REJECTED":
                        raise PlanError("IDEA_NOT_FOUND", "Idea not found in the private space")
                    slot.intake_id, slot.suggestion_ciphertext, slot.skipped = idea.id, None, False
                else:
                    slot.intake_id = None
                slot.draft_id = None
            if "skipped" in changes:
                if changes["skipped"] and self._locked(session, slot):
                    raise PlanError("SLOT_LOCKED", "The slot holds an approved post; take the approval back first")
                slot.skipped = bool(changes["skipped"])
            if changes.get("dismiss"):
                slot.suggestion_ciphertext = None
            slot.updated_at = datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="plan.slot_changed", entity_type="plan_slot", entity_id=slot.id,
                details={"track": slot.track, "week": slot.week_start.isoformat(), "changed": sorted(changes)}, created_at=slot.updated_at,
            ))
            session.commit()
            return self._slot_out(session, slot)

    def accept(self, slot_id: str, actor_id: str) -> tuple[dict[str, object], str | None]:
        """Take the AI's suggestion for a slot. A new angle becomes an idea in the store, filed under the slot's track."""
        with get_session() as session:
            project = private_space_service._project(session)
            slot = self._slot(session, project, slot_id)
            suggestion = self._suggestion(slot)
            if suggestion is None or slot.intake_id is not None:
                raise PlanError("NO_SUGGESTION", "This slot has no suggestion to take")
            code, track = project.code, slot.track
            idea_id = suggestion.get("idea_id")
            idea = session.get(IntakeItem, str(idea_id)) if idea_id else None
            if idea is not None and (str(idea.project_id) != str(project.id) or idea.status == "REJECTED"):
                idea = None
            text = "\n\n".join(part for part in (str(suggestion.get("title") or "").strip(), str(suggestion.get("reason") or "").strip()) if part)
        created = None
        if idea is None:
            from app.schemas import IntakeCreate
            from app.services.intake_service import intake_store

            created = str(intake_store.create(IntakeCreate(project_id=code, channel="MANUAL", raw_text=text)).id)
            private_space_service.set_track(created, track, actor_id)
        pillar = suggestion.get("pillar")
        result = self.change_slot(slot_id, {"intake_id": created or str(idea.id)}, actor_id)
        if pillar and not result["pillar"]:
            with get_session() as session:
                slot = session.get(PlanSlot, slot_id)
                slot.pillar = str(pillar)[:120]
                session.commit()
                result = self._slot_out(session, slot)
        return result, created

    # ---- AI proposal: the API takes the request, the worker fills the empty slots, the browser asks again.

    @staticmethod
    def _open(slots: list[PlanSlot]) -> list[PlanSlot]:
        return [slot for slot in slots if slot.intake_id is None and not slot.skipped]

    def request_proposal(self, track: str, week_start: date, keywords: str | None, actor_id: str, publisher=None) -> dict[str, object]:
        if track not in TRACKS:
            raise PlanError("TRACK_UNKNOWN", "Unknown track")
        if week_start.weekday() != 0 or week_start not in (this_week(), this_week() + timedelta(days=7)):
            raise PlanError("WEEK_NOT_OPEN", "Only this week and the next can be planned")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = private_space_service._project(session)
            if project is None:
                raise PlanError("PRIVATE_SPACE_MISSING", "The private space has not been opened yet")
            self._sync(session, project, track, week_start)
            session.flush()
            slots = session.scalars(select(PlanSlot).where(
                PlanSlot.project_id == project.id, PlanSlot.track == track, PlanSlot.week_start == week_start,
            )).all()
            if not self._open(slots):
                raise PlanError("NO_OPEN_SLOT", "Every slot of this week already has an idea")
            request = PlanRequest(
                id=str(uuid4()), project_id=project.id, track=track, week_start=week_start, status="PENDING",
                keywords_ciphertext=encrypt(keywords.strip()) if keywords and keywords.strip() else None,
                created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(request)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="plan.proposal_requested", entity_type="plan_request", entity_id=request.id,
                details={"track": track, "week": week_start.isoformat(), "keywords": bool(request.keywords_ciphertext)}, created_at=now,
            ))
            session.commit()
            request_id = str(request.id)
        (publisher or _publish)(request_id)
        return {"id": request_id, "status": "PENDING"}

    def proposal_input(self, request_id: str) -> dict[str, object] | None:
        """What the AI reads to fill a week; None when there is nothing left to do."""
        with get_session() as session:
            request = session.get(PlanRequest, request_id)
            project = private_space_service._project(session)
            if request is None or request.status != "PENDING" or project is None:
                return None
            track, week_start = request.track, request.week_start
            slots = self._open(session.scalars(select(PlanSlot).where(
                PlanSlot.project_id == project.id, PlanSlot.track == track, PlanSlot.week_start == week_start,
            ).order_by(PlanSlot.weekday, PlanSlot.time)).all())
            taken = {str(value) for value in session.scalars(select(PlanSlot.intake_id).where(PlanSlot.project_id == project.id, PlanSlot.intake_id.is_not(None))).all()}
            # Ideas of this track, and those not filed anywhere yet, that are neither used, posted nor dropped.
            ideas = [
                idea for idea in PrivateSpaceService._ideas(session, project)
                if idea["state"] in ("NO_DRAFT", "DRAFTED") and idea["track"] in (track, None) and idea["id"] not in taken
            ][:IDEA_LIMIT]
            stats = self._stats(session, project, track, week_start, [])
            start = datetime.combine(week_start, time(0, 0), tzinfo=LOCAL).astimezone(timezone.utc)
            titles = []
            for draft in sorted(self._posted(session, project, track, start - timedelta(days=120), start + timedelta(days=7)), key=lambda row: row.posted_at, reverse=True):
                title = (session.get(IntakeItem, draft.intake_id).normalized_title or "").strip()
                if title and title not in titles and len(titles) < 20:
                    titles.append(title)
            mapping = {
                "slots": {f"S{index}": str(slot.id) for index, slot in enumerate(slots, start=1)},
                "ideas": {f"I{index}": idea["id"] for index, idea in enumerate(ideas, start=1)},
            }
            request.mapping = mapping
            session.commit()
            return {
                "track": track,
                "voice": voices_of(project.project_settings)[track],
                "master_dna": master_dna_of(project.project_settings),
                "notes": [{"kind": note["kind"], "text": note["text"]} for note in PrivateSpaceService.notes_for(session, project.id, track)],
                "pillars": stats["pillars"], "missing_pillars": stats["missing_pillars"], "posted_titles": titles,
                "slots": [
                    {"key": key, "day": f"{WEEKDAYS[slot.weekday - 1]} {(slot.week_start + timedelta(days=slot.weekday - 1)).strftime('%d/%m')}",
                     "time": slot.time or "", "channel": slot.channel, "pillar": slot.pillar or ""}
                    for key, slot in zip(mapping["slots"], slots)
                ],
                "ideas": [{"key": key, "title": idea["title"] or "", "note": idea["note"] or ""} for key, idea in zip(mapping["ideas"], ideas)],
                "keywords": decrypt(request.keywords_ciphertext) if request.keywords_ciphertext else "",
                "signals": WatchService.for_plan(session, project, track),
            }

    def save_proposal(self, request_id: str, items: list[dict[str, object]] | None, error_code: str | None = None) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            request = session.get(PlanRequest, request_id)
            if request is None:
                return
            mapping = request.mapping or {}
            used: set[str] = set()
            filled = 0
            for item in items or []:
                slot = session.get(PlanSlot, (mapping.get("slots") or {}).get(str(item.get("slot") or ""), "")) if (mapping.get("slots") or {}).get(str(item.get("slot") or "")) else None
                title = " ".join(str(item.get("title") or "").split())[:200]
                # A slot filled by hand while the AI was thinking keeps what the person chose.
                if slot is None or slot.intake_id is not None or slot.skipped or not title:
                    continue
                idea_id = (mapping.get("ideas") or {}).get(str(item.get("idea") or ""))
                if idea_id in used:
                    idea_id = None
                if idea_id:
                    used.add(idea_id)
                slot.suggestion_ciphertext = encrypt(json.dumps({
                    "title": title, "reason": " ".join(str(item.get("reason") or "").split())[:400],
                    "pillar": " ".join(str(item.get("pillar") or "").split())[:120] or None, "idea_id": idea_id,
                }, ensure_ascii=False))
                slot.updated_at = now
                filled += 1
            request.status = "DONE" if items is not None and filled else "FAILED"
            request.error = None if request.status == "DONE" else (error_code or "PLAN_EMPTY")[:128]
            request.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=request.project_id, actor_type="WORKER", actor_id="ai-worker",
                event_type="plan.proposed" if request.status == "DONE" else "plan.proposal_failed", entity_type="plan_request", entity_id=request.id,
                details={"track": request.track, "week": request.week_start.isoformat(), "slots": filled, "error": request.error}, created_at=now,
            ))
            session.commit()


content_plan_service = ContentPlanService()
