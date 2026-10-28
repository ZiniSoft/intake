"""Post drafts written by AI from one idea (ADR-0031).

The API takes the request, the AI worker writes, the browser asks again until it is there. Nothing is ever posted:
a draft is text for a person to edit, copy and schedule elsewhere.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, IdeaTrack, IntakeItem, PlanSlot, PostDraft, Project, SourceMessage
from app.modules.private_space.service import (
    AUDIENCES, CHANNELS, COMMERCIAL_TRACK, COMMERCIALS, CONTEXTS, DEFAULT_TRACK, GOALS, GROUPS, LONG_CHANNELS, TRACKS,
    PrivateSpaceService, master_dna_of, voices_of,
)
from app.services.raw_crypto import decrypt, encrypt

DRAFT_KINDS = {"IDEA", "NON_CODE"}


class DraftError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _publish(draft_id: str) -> None:
    from app.queue.celery_app import celery_app

    celery_app.send_task("intake.drafts.write", args=[draft_id], queue="ai.normalize")


class DraftService:
    @staticmethod
    def _out(draft: PostDraft, slot_id: str | None = None) -> dict[str, object]:
        return {
            "approved_at": draft.approved_at, "scheduled_for": draft.scheduled_for, "posted_url": draft.posted_url,
            "posted_via": draft.posted_via, "publish_error": draft.publish_error, "slot_id": slot_id,
            "id": str(draft.id), "intake_id": str(draft.intake_id), "channel": draft.channel, "kind": draft.kind or "POST", "status": draft.status,
            "text": decrypt(draft.text_ciphertext) if draft.text_ciphertext else None,
            "hooks": list(draft.hooks or []), "gaps": list(draft.gaps or []),
            "angle": decrypt(draft.angle_ciphertext) if draft.angle_ciphertext else None,
            "source_draft_id": str(draft.source_draft_id) if draft.source_draft_id else None,
            "track": draft.track, "goal": draft.goal, "audience": draft.audience, "pillar": draft.pillar, "group_context": draft.group_context,
            "context": draft.context, "commercial": draft.commercial,
            "error": draft.error, "edited_at": draft.edited_at, "posted_at": draft.posted_at,
            "created_at": draft.created_at, "updated_at": draft.updated_at,
        }

    @staticmethod
    def _audit(session, event_type: str, actor_id: str, draft: PostDraft, details: dict | None = None, actor_type: str = "USER") -> None:
        session.add(AuditEvent(
            id=str(uuid4()), project_id=draft.project_id, actor_type=actor_type, actor_id=actor_id,
            event_type=event_type, entity_type="post_draft", entity_id=draft.id,
            details={"intake_id": str(draft.intake_id), "channel": draft.channel, **(details or {})},
            created_at=datetime.now(timezone.utc),
        ))

    @staticmethod
    def _get(session, intake_id: str, draft_id: str) -> PostDraft:
        try:
            draft = session.get(PostDraft, draft_id)
        except Exception:  # a malformed ID is simply not a draft
            session.rollback()
            draft = None
        if draft is None or str(draft.intake_id) != str(intake_id):
            raise DraftError("DRAFT_NOT_FOUND", "Draft not found")
        return draft

    def list(self, intake_id: str) -> list[dict[str, object]]:
        with get_session() as session:
            rows = session.scalars(select(PostDraft).where(PostDraft.intake_id == intake_id).order_by(PostDraft.created_at.desc())).all()
            slots = {
                str(slot.draft_id): str(slot.id)
                for slot in session.scalars(select(PlanSlot).where(PlanSlot.draft_id.in_([row.id for row in rows]))).all()
            } if rows else {}
            return [self._out(row, slots.get(str(row.id))) for row in rows]

    def request(
        self, intake_id: str, *, channel: str, angle: str | None, source_draft_id: str | None,
        actor_id: str, may_read_raw: bool, publisher=None,
        track: str | None = None, goal: str | None = None, audience: str | None = None, pillar: str | None = None,
        group_context: str | None = None, outline: bool = False, context: str | None = None, commercial: str | None = None,
    ) -> dict[str, object]:
        if group_context:
            # A post for an industry group is always a rewrite for that group, whatever channel was named.
            channel = "FACEBOOK_GROUP"
            # The group is the reader; an audience carried over from the draft being rewritten would pull against it.
            audience = None
        if channel not in CHANNELS:
            raise DraftError("CHANNEL_UNKNOWN", "Unknown channel")
        if (channel == "FACEBOOK_GROUP") != bool(group_context) or (group_context and group_context not in GROUPS):
            raise DraftError("GROUP_UNKNOWN", "A group post needs one of the known industries")
        if (track and track not in TRACKS) or (goal and goal not in GOALS) or (audience and audience not in AUDIENCES):
            raise DraftError("CHOICE_UNKNOWN", "Unknown track, goal or audience")
        if (context and context not in CONTEXTS) or (commercial and commercial not in COMMERCIALS):
            raise DraftError("CHOICE_UNKNOWN", "Unknown context or commercial relation")
        if outline and channel not in LONG_CHANNELS:
            raise DraftError("OUTLINE_NOT_FOR_CHANNEL", "An outline comes before a blog post or a video script")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            intake = session.get(IntakeItem, intake_id)
            if intake is None:
                raise DraftError("INTAKE_NOT_FOUND", "Intake not found")
            project = session.get(Project, intake.project_id)
            if project is None or project.kind not in DRAFT_KINDS:
                raise DraftError("DRAFTS_NOT_FOR_KIND", "Post drafts are for idea and non-code projects")
            source = None
            if source_draft_id:
                source = self._get(session, intake_id, source_draft_id)
                if source.status != "DONE" or not source.text_ciphertext:
                    raise DraftError("SOURCE_DRAFT_NOT_READY", "The draft to adapt is not written yet")
            # The direction: the one asked for; else, when adapting, the source draft's; else the idea's own; else the first.
            filed = session.get(IdeaTrack, intake.id)
            chosen = track or (source.track if source is not None and source.track in TRACKS else None) or (filed.track if filed is not None and filed.track in TRACKS else DEFAULT_TRACK)
            # Money behind a piece belongs to the technical direction only; the business direction never carries it.
            if commercial and commercial != "NONE" and chosen != COMMERCIAL_TRACK:
                raise DraftError("COMMERCIAL_NOT_FOR_TRACK", "Sponsored or affiliate content belongs to the technical direction")
            draft = PostDraft(
                id=str(uuid4()), intake_id=intake.id, project_id=project.id, channel=channel, kind="OUTLINE" if outline else "POST", status="PENDING",
                angle_ciphertext=encrypt(angle.strip()) if angle and angle.strip() else None,
                source_draft_id=source_draft_id or None,
                track=chosen,
                goal=goal or None, audience=audience or None, pillar=(pillar or "").strip()[:120] or None, group_context=group_context or None,
                context=context or None, commercial=(commercial if commercial and commercial != "NONE" else None),
                # Someone who may not read the original must not get it back rewritten as a draft.
                uses_raw=bool(may_read_raw), created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(draft)
            self._audit(session, "draft.requested", actor_id, draft, {"adapted": bool(source_draft_id), "uses_raw": bool(may_read_raw)})
            session.commit()
            result = self._out(draft)
        (publisher or _publish)(str(result["id"]))
        return result

    def input(self, draft_id: str) -> dict[str, object] | None:
        """What the AI reads for one draft; None when there is nothing left to write."""
        with get_session() as session:
            draft = session.get(PostDraft, draft_id)
            if draft is None or draft.status != "PENDING":
                return None
            intake = session.get(IntakeItem, draft.intake_id)
            project = session.get(Project, draft.project_id)
            if intake is None or project is None:
                return None
            raw = None
            if draft.uses_raw:
                source = session.scalar(select(SourceMessage).where(SourceMessage.intake_id == intake.id).order_by(SourceMessage.created_at))
                raw = decrypt(source.raw_content_ciphertext) if source is not None and source.raw_content_ciphertext else None
            previous = session.get(PostDraft, draft.source_draft_id) if draft.source_draft_id else None
            voices = voices_of(project.project_settings)
            track = draft.track if draft.track in voices else DEFAULT_TRACK
            titles = self._posted_titles(session, project, track, intake.id)
            return {
                "channel": draft.channel,
                "kind": draft.kind or "POST",
                "long": draft.channel in LONG_CHANNELS and (draft.kind or "POST") != "OUTLINE",
                "direction": TRACKS[track], "direction_note": voices[track].get("direction_note") or "",
                "master_dna": master_dna_of(project.project_settings),
                "references": list(voices[track].get("references") or []),
                "context": draft.context or "", "commercial": draft.commercial or "",
                "previous_kind": (previous.kind or "POST") if previous is not None else "",
                # A draft adapted from the other direction keeps its facts and changes its question, depth and call.
                "previous_track": TRACKS.get(previous.track, "") if previous is not None and previous.track in TRACKS and previous.track != track else "",
                "notes": [{"kind": note["kind"], "text": note["text"]} for note in PrivateSpaceService.notes_for(session, project.id, track)],
                "posted_titles": titles,
                "note": (raw or "").strip(),
                "title": intake.normalized_title or "",
                "summary": intake.normalized_summary or "",
                "angle": decrypt(draft.angle_ciphertext) if draft.angle_ciphertext else "",
                "previous_text": decrypt(previous.text_ciphertext) if previous is not None and previous.text_ciphertext else "",
                "previous_channel": previous.channel if previous is not None else "",
                "voice": voices[track],
                "goal": draft.goal or "", "audience": draft.audience or "", "pillar": draft.pillar or "", "group_context": draft.group_context or "",
            }

    @staticmethod
    def _posted_titles(session, project, track: str, but: object | None) -> list[str]:
        """What this track already published, so the same subject is not written twice."""
        posted_ids = [
            str(value) for value in session.scalars(
                select(PostDraft.intake_id).where(
                    PostDraft.project_id == project.id, PostDraft.track == track, PostDraft.posted_at.is_not(None),
                ).order_by(PostDraft.posted_at.desc()).limit(80)
            ).all() if str(value) != str(but)
        ]
        titles: list[str] = []
        for posted_id in dict.fromkeys(posted_ids):
            title = (session.get(IntakeItem, posted_id).normalized_title or "").strip()
            if title and len(titles) < 20:
                titles.append(title)
        return titles

    def preview_source(
        self, *, track: str, voice: dict[str, object] | None, intake_id: str | None, channel: str, outline: bool,
        goal: str | None, audience: str | None, pillar: str | None, group_context: str | None, angle: str | None,
        source_draft_id: str | None, may_read_raw: bool, actor_id: str,
        master_dna: str | None = None, context: str | None = None, commercial: str | None = None,
    ) -> tuple[dict[str, object], bool]:
        """What the AI would read for a draft asked for now, without asking for one.

        `voice` is the track's voice as it stands on the screen, saved or not. Without an idea, its place is held by
        marked placeholders. Returns the source and whether placeholders were used.
        """
        from app.modules.private_space.service import private_space_service

        if group_context:
            channel, audience = "FACEBOOK_GROUP", None
        if channel not in CHANNELS or track not in TRACKS:
            raise DraftError("CHANNEL_UNKNOWN", "Unknown channel or track")
        if (channel == "FACEBOOK_GROUP") != bool(group_context) or (group_context and group_context not in GROUPS):
            raise DraftError("GROUP_UNKNOWN", "A group post needs one of the known industries")
        if (goal and goal not in GOALS) or (audience and audience not in AUDIENCES):
            raise DraftError("CHOICE_UNKNOWN", "Unknown goal or audience")
        if (context and context not in CONTEXTS) or (commercial and commercial not in COMMERCIALS):
            raise DraftError("CHOICE_UNKNOWN", "Unknown context or commercial relation")
        if commercial and commercial != "NONE" and track != COMMERCIAL_TRACK:
            raise DraftError("COMMERCIAL_NOT_FOR_TRACK", "Sponsored or affiliate content belongs to the technical direction")
        if outline and channel not in LONG_CHANNELS:
            raise DraftError("OUTLINE_NOT_FOR_CHANNEL", "An outline comes before a blog post or a video script")
        with get_session() as session:
            project = private_space_service._project(session)
            if project is None:
                raise DraftError("INTAKE_NOT_FOUND", "The private space has not been opened yet")
            intake, previous, raw = None, None, None
            if intake_id:
                try:
                    intake = session.get(IntakeItem, intake_id)
                except Exception:  # a malformed ID is simply not an idea
                    session.rollback()
                    intake = None
                if intake is None or str(intake.project_id) != str(project.id):
                    raise DraftError("INTAKE_NOT_FOUND", "Idea not found in the private space")
                if may_read_raw:
                    message = session.scalar(select(SourceMessage).where(SourceMessage.intake_id == intake.id).order_by(SourceMessage.created_at))
                    raw = decrypt(message.raw_content_ciphertext) if message is not None and message.raw_content_ciphertext else None
                if source_draft_id:
                    previous = self._get(session, intake_id, source_draft_id)
                # The idea's own words are read here as they would be for a draft.
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id, event_type="draft.prompt_previewed",
                    entity_type="intake", entity_id=intake.id, details={"channel": channel, "track": track}, created_at=datetime.now(timezone.utc),
                ))
                session.commit()
            placeholder = intake is None
            shown = {**voices_of(project.project_settings)[track], **(voice or {})}
            return {
                "channel": channel,
                "kind": "OUTLINE" if outline else "POST",
                "long": channel in LONG_CHANNELS and not outline,
                "direction": TRACKS[track], "direction_note": shown.get("direction_note") or "",
                "master_dna": master_dna if master_dna is not None else master_dna_of(project.project_settings),
                "references": list(shown.get("references") or []),
                "context": context or "", "commercial": (commercial if commercial and commercial != "NONE" else ""),
                "previous_kind": (previous.kind or "POST") if previous is not None else "",
                "previous_track": TRACKS.get(previous.track, "") if previous is not None and previous.track in TRACKS and previous.track != track else "",
                "notes": [{"kind": note["kind"], "text": note["text"]} for note in PrivateSpaceService.notes_for(session, project.id, track)],
                "posted_titles": self._posted_titles(session, project, track, intake.id if intake is not None else None),
                "note": "[ghi chú của ý tưởng]" if placeholder else (raw or "").strip(),
                "title": "[tiêu đề của ý tưởng]" if placeholder else intake.normalized_title or "",
                "summary": "[tóm tắt của ý tưởng]" if placeholder else intake.normalized_summary or "",
                "angle": (angle or "").strip(),
                "previous_text": decrypt(previous.text_ciphertext) if previous is not None and previous.text_ciphertext else "",
                "previous_channel": previous.channel if previous is not None else "",
                "voice": shown,
                "goal": goal or "", "audience": audience or "", "pillar": (pillar or "").strip()[:120], "group_context": group_context or "",
            }, placeholder

    def save(self, draft_id: str, *, text: str | None, hooks: list[str] | None = None, gaps: list[str] | None = None,
             error_code: str | None = None, prompt_version: str | None = None, model: str | None = None) -> None:
        with get_session() as session:
            draft = session.get(PostDraft, draft_id)
            if draft is None:
                return
            draft.status = "DONE" if text else "FAILED"
            draft.text_ciphertext = encrypt(text.strip()) if text else None
            draft.hooks = [hook.strip() for hook in (hooks or []) if hook and hook.strip()][:3] if text else []
            draft.gaps = [gap.strip() for gap in (gaps or []) if gap and gap.strip()][:8] if text else []
            draft.error = None if text else (error_code or "DRAFT_FAILED")[:128]
            draft.prompt_version = prompt_version
            draft.model = model
            draft.updated_at = datetime.now(timezone.utc)
            self._audit(session, "draft.written" if text else "draft.failed", "ai-worker", draft, {"error": draft.error}, actor_type="WORKER")
            session.commit()

    @staticmethod
    def _slot_of(session, draft: PostDraft) -> PlanSlot | None:
        return session.scalar(select(PlanSlot).where(PlanSlot.draft_id == draft.id).limit(1))

    def update(
        self, intake_id: str, draft_id: str, *, text: str | None, posted: bool | None, actor_id: str,
        posted_at: datetime | None = None, posted_url: str | None = None,
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            draft = self._get(session, intake_id, draft_id)
            if draft.status != "DONE":
                raise DraftError("DRAFT_NOT_READY", "The draft is not written yet")
            if text is not None:
                if draft.approved_at is not None or draft.posted_at is not None:
                    # What was approved is what goes out: take the approval back to change it.
                    raise DraftError("DRAFT_APPROVED", "An approved draft is locked; take the approval back to edit it")
                if not text.strip():
                    raise DraftError("DRAFT_EMPTY", "A draft cannot be empty")
                draft.text_ciphertext = encrypt(text.strip())
                draft.edited_at = now
                self._audit(session, "draft.edited", actor_id, draft)
            if posted is True:
                if draft.kind == "OUTLINE":
                    raise DraftError("OUTLINE_NOT_POSTABLE", "An outline is not a post")
                if posted_at is not None and posted_at > now + timedelta(minutes=5):
                    raise DraftError("POSTED_IN_FUTURE", "A post cannot have gone out in the future")
                first = draft.posted_at is None
                draft.posted_at = posted_at or draft.posted_at or now
                draft.posted_url = (posted_url or "").strip()[:500] or (None if posted_url is not None else draft.posted_url)
                draft.posted_via, draft.publish_error = "MANUAL", None
                self._audit(session, "draft.marked_posted" if first else "draft.post_corrected", actor_id, draft, {"has_url": bool(draft.posted_url)})
            elif posted is False and draft.posted_at is not None:
                draft.posted_at, draft.posted_url, draft.posted_via = None, None, None
                self._audit(session, "draft.unmarked_posted", actor_id, draft)
            draft.updated_at = now
            session.commit()
            slot = self._slot_of(session, draft)
            return self._out(draft, str(slot.id) if slot is not None else None)

    def approve(self, intake_id: str, draft_id: str, *, slot_id: str | None, scheduled_for: datetime | None, actor_id: str) -> dict[str, object]:
        """Fix the text and say when it goes out. With a slot, the draft fills that slot of the week plan."""
        from app.modules.content_plan.service import slot_moment

        now = datetime.now(timezone.utc)
        with get_session() as session:
            draft = self._get(session, intake_id, draft_id)
            if draft.status != "DONE":
                raise DraftError("DRAFT_NOT_READY", "The draft is not written yet")
            if draft.kind == "OUTLINE":
                raise DraftError("OUTLINE_NOT_POSTABLE", "An outline is not a post")
            if draft.posted_at is not None:
                raise DraftError("DRAFT_POSTED", "The draft is already posted")
            held = self._slot_of(session, draft)
            slot = None
            if slot_id:
                try:
                    slot = session.get(PlanSlot, slot_id)
                except Exception:  # a malformed ID is simply not a slot
                    session.rollback()
                    slot = None
                if slot is None or str(slot.project_id) != str(draft.project_id):
                    raise DraftError("SLOT_NOT_FOUND", "Slot not found")
                if slot.skipped or (slot.intake_id is not None and str(slot.intake_id) != str(draft.intake_id)) or (slot.draft_id is not None and str(slot.draft_id) != str(draft.id)):
                    raise DraftError("SLOT_TAKEN", "The slot is skipped or already holds another idea or post")
                if held is not None and held.id != slot.id:
                    held.draft_id = None
                slot.intake_id, slot.draft_id, slot.suggestion_ciphertext, slot.updated_at = draft.intake_id, draft.id, None, now
            else:
                slot = held
            draft.approved_at, draft.approved_by = now, actor_id
            draft.scheduled_for = scheduled_for or (slot_moment(slot) if slot is not None else None)
            draft.updated_at = now
            self._audit(session, "draft.approved", actor_id, draft, {"slot": str(slot.id) if slot is not None else None})
            session.commit()
            return self._out(draft, str(slot.id) if slot is not None else None)

    def unapprove(self, intake_id: str, draft_id: str, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            draft = self._get(session, intake_id, draft_id)
            if draft.posted_at is not None:
                raise DraftError("DRAFT_POSTED", "The draft is already posted")
            if draft.approved_at is not None:
                # The slot keeps its idea and waits for another approved draft.
                slot = self._slot_of(session, draft)
                if slot is not None:
                    slot.draft_id = None
                draft.approved_at, draft.approved_by, draft.scheduled_for, draft.publish_error = None, None, None, None
                draft.updated_at = datetime.now(timezone.utc)
                self._audit(session, "draft.approval_withdrawn", actor_id, draft)
                session.commit()
            return self._out(draft)

    # ---- The posting flow outside Intake (ADR-0038): it reads what was approved, and says what happened.

    def publish_queue(self, channel: str | None = None) -> list[dict[str, object]]:
        with get_session() as session:
            query = select(PostDraft).where(PostDraft.status == "DONE", PostDraft.approved_at.is_not(None), PostDraft.posted_at.is_(None))
            if channel:
                query = query.where(PostDraft.channel == channel)
            rows = [row for row in session.scalars(query).all() if (row.kind or "POST") == "POST" and row.text_ciphertext]
            far = datetime.max.replace(tzinfo=timezone.utc)
            rows.sort(key=lambda row: ((row.scheduled_for.replace(tzinfo=timezone.utc) if row.scheduled_for and row.scheduled_for.tzinfo is None else row.scheduled_for) or far))
            return [{
                "draft_id": str(row.id), "track": row.track, "channel": row.channel, "group_context": row.group_context, "pillar": row.pillar,
                "title": session.get(IntakeItem, row.intake_id).normalized_title, "text": decrypt(row.text_ciphertext),
                "scheduled_for": row.scheduled_for, "approved_at": row.approved_at,
            } for row in rows]

    def record_publish(
        self, draft_id: str, *, posted: bool, posted_at: datetime | None, url: str | None, platform: str | None, error: str | None,
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            try:
                draft = session.get(PostDraft, draft_id)
            except Exception:  # a malformed ID is simply not a draft
                session.rollback()
                draft = None
            if draft is None:
                raise DraftError("DRAFT_NOT_FOUND", "Draft not found")
            # The flow may only speak about a post the owner approved: nothing else is its business.
            if draft.approved_at is None:
                raise DraftError("DRAFT_NOT_APPROVED", "The draft is not approved")
            details = {"platform": (platform or "")[:40] or None}
            if draft.posted_at is not None:
                pass  # said twice, or already recorded by hand: the first record stands
            elif posted:
                if posted_at is not None and posted_at.tzinfo is None:
                    posted_at = posted_at.replace(tzinfo=timezone.utc)
                draft.posted_at = posted_at if posted_at is not None and posted_at <= now + timedelta(minutes=5) else now
                draft.posted_url = (url or "").strip()[:500] or None
                draft.posted_via, draft.publish_error, draft.updated_at = "WEBHOOK", None, now
                self._audit(session, "draft.posted_by_flow", "publish-flow", draft, {**details, "has_url": bool(draft.posted_url)}, actor_type="INTEGRATION")
            else:
                draft.publish_error, draft.updated_at = " ".join((error or "POST_FAILED").split())[:200], now
                self._audit(session, "draft.post_failed", "publish-flow", draft, details, actor_type="INTEGRATION")
            session.commit()
            return {
                "draft_id": str(draft.id), "posted_at": draft.posted_at, "posted_url": draft.posted_url,
                "posted_via": draft.posted_via, "publish_error": draft.publish_error,
            }

    def remove(self, intake_id: str, draft_id: str, actor_id: str) -> None:
        with get_session() as session:
            draft = self._get(session, intake_id, draft_id)
            if draft.approved_at is not None and draft.posted_at is None:
                raise DraftError("DRAFT_APPROVED", "An approved draft is locked; take the approval back to delete it")
            slot = self._slot_of(session, draft)
            if slot is not None:
                slot.draft_id = None
            self._audit(session, "draft.deleted", actor_id, draft)
            session.delete(draft)
            session.commit()


draft_service = DraftService()
