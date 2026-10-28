from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select, update

from app.config import get_settings
from app.db import get_session, init_db
from app.models import AuditEvent, GlossaryTerm, Meeting, MeetingNoteItem, MeetingSegment, Project, WorkItem
from app.modules.private_space.service import private_project_ids
from app.services.object_storage import get_object_storage
from app.services.raw_crypto import decrypt, decrypt_bytes, encrypt, encrypt_bytes


REALTIME_KEYTERM_LIMIT = 50
REALTIME_KEYTERM_MAX_LENGTH = 20
BATCH_KEYTERM_LIMIT = 1000
BATCH_KEYTERM_MAX_LENGTH = 50
# How much of the transcript travels with a note item into its Intake (FR-REC-15).
TRANSCRIPT_EXCERPT_CHARS = 3000
TRANSCRIPT_FULL_CHARS = 12000
TRANSCRIPT_STOPWORDS = {
    "của", "và", "cho", "các", "được", "trong", "với", "một", "này", "đã", "có", "là", "để", "không", "khi", "thì", "những",
    "cũng", "như", "về", "từ", "bị", "sẽ", "đang", "trên", "theo", "vào", "ra", "lại", "hay", "hoặc", "nên", "cần", "phải",
    "làm", "việc", "anh", "chị", "em", "mình", "bạn", "the", "and", "for", "with", "that", "this",
}
MAX_AUDIO_CHUNK_BYTES = 5 * 1024 * 1024
AUDIO_CONTENT_TYPES = {"audio/webm", "audio/ogg", "audio/mp4", "audio/x-m4a", "audio/wav", "audio/x-wav", "audio/mpeg"}
WORK_ATTEMPTS = 3
STALE_CLAIM = timedelta(minutes=20)
NOTE_KINDS = ("DECISION", "REQUIREMENT", "BUG", "SCOPE_CHANGE", "ACTION", "QUESTION", "RISK")
# Kinds that describe work for a project and may become an Intake.
INTAKE_KINDS = {"REQUIREMENT", "BUG", "SCOPE_CHANGE", "ACTION"}
# What may go straight to the board as work (FR-REC-19): everything but a decision, which is only recorded.
WORK_KINDS = {"REQUIREMENT", "BUG", "SCOPE_CHANGE", "ACTION", "QUESTION", "RISK"}
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


class MeetingError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; PostgreSQL returns aware ones.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def audio_object_key(meeting_id: str, sequence: int) -> str:
    return f"meetings/{meeting_id}/audio/{sequence:06d}"


class MeetingService:
    def __init__(self) -> None:
        init_db()

    # --- helpers --------------------------------------------------------------------------------

    @staticmethod
    def _project(session, project_ref: str | None) -> Project | None:
        if not project_ref:
            return None
        project = session.scalar(select(Project).where(Project.code == project_ref, Project.status == "ACTIVE"))
        if project is None:
            project = session.get(Project, project_ref) if len(project_ref) == 36 else None
        if project is None or project.status != "ACTIVE":
            raise MeetingError("PROJECT_NOT_ACTIVE", "Project does not exist or is inactive")
        return project

    @staticmethod
    def _audit(session, event_type: str, actor_id: str, meeting: Meeting, details: dict | None = None, actor_type: str = "USER") -> None:
        session.add(AuditEvent(
            id=str(uuid4()), project_id=meeting.project_id, actor_type=actor_type, actor_id=actor_id,
            event_type=event_type, entity_type="meeting", entity_id=meeting.id, details=details,
            created_at=datetime.now(timezone.utc),
        ))

    @staticmethod
    def _get(session, meeting_id: str) -> Meeting:
        meeting = session.get(Meeting, meeting_id)
        if meeting is None:
            raise MeetingError("MEETING_NOT_FOUND", "Meeting not found")
        return meeting

    # --- recording ------------------------------------------------------------------------------

    def create(
        self, *, project_ref: str | None, title: str | None, source: str, actor_id: str, kind: str = "MEETING",
        continues_meeting_id: str | None = None,
    ) -> dict[str, object]:
        settings = get_settings()
        if not settings.meeting_capture_enabled:
            raise MeetingError("MEETING_CAPTURE_DISABLED", "Meeting capture is disabled")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            series_id, part_number = None, 1
            if continues_meeting_id:
                # The next part of a meeting that hit the time limit: same project, numbered after the previous part.
                previous = self._get(session, continues_meeting_id)
                project = session.get(Project, previous.project_id) if previous.project_id else None
                if previous.series_id is None:
                    previous.series_id = str(previous.id)
                series_id, part_number = str(previous.series_id), int(previous.part_number) + 1
                title = f"{re.sub(r'\s*\(phần \d+\)$', '', previous.title)} (phần {part_number})"
            else:
                project = self._project(session, project_ref)
            if project is None:
                raise MeetingError("MEETING_PROJECT_REQUIRED", "Choose the project this meeting is about")
            meeting = Meeting(
                id=str(uuid4()), project_id=str(project.id), series_id=series_id, part_number=part_number,
                title=(title or "").strip() or f"{'Nói để nhập' if kind == 'DICTATION' else 'Cuộc họp'} {now.astimezone(LOCAL_TZ).strftime('%d/%m/%Y %H:%M')}",
                kind=kind, status="RECORDING", source=source, language=settings.meeting_language, started_at=now,
                audio_chunk_count=0, audio_bytes=0, created_by=actor_id, transcript_status="NONE", note_status="NONE",
                transcript_attempts=0, note_attempts=0, speaker_names={},
                purge_after=now + timedelta(days=settings.raw_retention_days), created_at=now, updated_at=now,
            )
            session.add(meeting)
            self._audit(session, "meeting.started", actor_id, meeting, {"source": source, "kind": kind, "part_number": part_number})
            session.commit()
            return self._summary(session, meeting)

    def fail_stale_recordings(self, now: datetime | None = None, stale_minutes: int = 60) -> int:
        """A recording that stopped receiving sound long ago was abandoned (a reloaded tab, a closed laptop). One
        that already holds sound or live text is finished as cut short: what reached the server is transcribed and
        summarised, and the card says the upload broke off. One with nothing is marked failed so it can be deleted,
        instead of showing "recording" forever (FR-REC-18)."""
        current = now or datetime.now(timezone.utc)
        cutoff = current - timedelta(minutes=stale_minutes)
        with get_session() as session:
            rows = session.scalars(select(Meeting).where(Meeting.status == "RECORDING", Meeting.updated_at <= cutoff)).all()
            for meeting in rows:
                has_text = self._has_text(session, str(meeting.id))
                last_sound = _aware(meeting.updated_at)
                if meeting.audio_chunk_count > 0 or has_text:
                    meeting.status = "FINISHED"
                    meeting.ended_at = last_sound
                    meeting.duration_seconds = max(int((last_sound - _aware(meeting.started_at)).total_seconds()), 0)
                    meeting.transcript_error = "UPLOAD_STALLED"
                    if meeting.kind == "DICTATION":
                        meeting.transcript_status, meeting.note_status = "SKIPPED", "SKIPPED"
                    elif meeting.audio_chunk_count > 0:
                        meeting.transcript_status = "PENDING"
                    else:
                        meeting.transcript_status, meeting.note_status = "SKIPPED", "PENDING"
                    self._audit(session, "meeting.finished", "meeting-gateway", meeting, {
                        "reason": "UPLOAD_STALLED", "audio_chunks": meeting.audio_chunk_count, "live_text": has_text, "duration_seconds": meeting.duration_seconds,
                    }, actor_type="WORKER")
                else:
                    meeting.status = "FAILED"
                    meeting.ended_at = current
                    meeting.transcript_status = "SKIPPED"
                    meeting.note_status = "SKIPPED"
                    meeting.transcript_error = "UPLOAD_STALLED"
                    self._audit(session, "meeting.failed", "meeting-gateway", meeting, {"reason": "UPLOAD_STALLED", "audio_chunks": meeting.audio_chunk_count}, actor_type="WORKER")
                meeting.updated_at = current
            session.commit()
            return len(rows)

    def retry_transcription(self, meeting_id: str, actor_id: str) -> dict[str, object]:
        """Ask for the speaker-separated transcript again after it failed or was skipped (FR-REC-18)."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            if (meeting.status != "FINISHED" or meeting.kind != "MEETING" or meeting.audio_chunk_count == 0
                    or meeting.purged_at is not None or meeting.transcript_status not in ("FAILED", "SKIPPED")):
                raise MeetingError("TRANSCRIPT_RETRY_NOT_ALLOWED", "Only a finished meeting whose transcription failed can be transcribed again")
            meeting.transcript_status = "PENDING"
            meeting.transcript_attempts = 0
            meeting.transcript_error = None
            meeting.transcript_claimed_at = None
            meeting.updated_at = now
            self._audit(session, "meeting.transcript.retried", actor_id, meeting)
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    def append_audio(self, meeting_id: str, sequence: int, content: bytes, content_type: str) -> dict[str, object]:
        settings = get_settings()
        base_type = content_type.split(";", 1)[0].strip().lower()
        if base_type not in AUDIO_CONTENT_TYPES:
            raise MeetingError("AUDIO_TYPE_NOT_ALLOWED", "Audio content type is not allowed")
        if not content or len(content) > MAX_AUDIO_CHUNK_BYTES:
            raise MeetingError("AUDIO_CHUNK_SIZE_INVALID", "Audio chunk is empty or larger than 5 MB")
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            if meeting.status != "RECORDING":
                raise MeetingError("MEETING_NOT_RECORDING", "Meeting is no longer recording")
            if sequence < meeting.audio_chunk_count:
                # A retried upload of a chunk that is already stored.
                return self._summary(session, meeting)
            if sequence != meeting.audio_chunk_count:
                raise MeetingError("AUDIO_CHUNK_OUT_OF_ORDER", f"Expected chunk {meeting.audio_chunk_count}")
            if meeting.audio_bytes + len(content) > settings.meeting_max_audio_mb * 1024 * 1024:
                raise MeetingError("AUDIO_TOO_LARGE", f"Recording exceeds {settings.meeting_max_audio_mb} MB")
            get_object_storage().put(audio_object_key(meeting_id, sequence), encrypt_bytes(content), "application/octet-stream")
            meeting.audio_chunk_count += 1
            meeting.audio_bytes += len(content)
            meeting.audio_content_type = base_type
            meeting.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._summary(session, meeting)

    def add_realtime_segment(self, meeting_id: str, text: str) -> int | None:
        cleaned = text.strip()
        if not cleaned:
            return None
        with get_session() as session:
            if session.get(Meeting, meeting_id) is None:
                return None
            sequence = session.scalar(select(func.count()).select_from(MeetingSegment).where(
                MeetingSegment.meeting_id == meeting_id, MeetingSegment.source == "REALTIME",
            )) or 0
            session.add(MeetingSegment(
                id=str(uuid4()), meeting_id=meeting_id, source="REALTIME", sequence=int(sequence),
                text_ciphertext=encrypt(cleaned), created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            return int(sequence)

    def finish(self, meeting_id: str, actor_id: str, duration_seconds: int | None = None) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            if meeting.status == "RECORDING":
                meeting.status = "FINISHED"
                meeting.ended_at = now
                wall = max(int((now - _aware(meeting.started_at)).total_seconds()), 0)
                # The browser's measure wins when it has one: the sound may have reached here long after the talk
                # ended, from a computer whose line was down. It can never be longer than the wall clock.
                meeting.duration_seconds = min(duration_seconds, wall) if duration_seconds is not None else wall
                meeting.updated_at = now
                if meeting.kind == "DICTATION":
                    # One person spoke a request: the live transcript is the text. No speaker separation, no note.
                    meeting.transcript_status = "SKIPPED"
                    meeting.note_status = "SKIPPED"
                elif meeting.audio_chunk_count > 0:
                    meeting.transcript_status = "PENDING"
                else:
                    meeting.transcript_status = "SKIPPED"
                    meeting.note_status = "PENDING" if self._has_text(session, meeting_id) else "SKIPPED"
                self._audit(session, "meeting.finished", actor_id, meeting, {
                    "duration_seconds": meeting.duration_seconds, "audio_chunks": meeting.audio_chunk_count,
                })
                session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    def recording_context(self, meeting_id: str) -> dict[str, object] | None:
        """What the realtime gateway needs to open a provider session; None when the meeting is not recording."""
        settings = get_settings()
        with get_session() as session:
            meeting = session.get(Meeting, meeting_id)
            if meeting is None or meeting.status != "RECORDING" or meeting.source == "FILE":
                return None
            return {
                "language": meeting.language,
                "deadline": _aware(meeting.started_at) + timedelta(minutes=settings.meeting_max_minutes),
                "keyterms": self.keyterms(session, meeting.project_id, REALTIME_KEYTERM_LIMIT, REALTIME_KEYTERM_MAX_LENGTH),
            }

    @staticmethod
    def keyterms(session, project_id: str | None, limit: int, max_length: int) -> list[str]:
        rows = session.scalars(select(GlossaryTerm).where(
            (GlossaryTerm.project_id == project_id) | GlossaryTerm.project_id.is_(None),
        ).order_by(GlossaryTerm.project_id.is_(None), GlossaryTerm.created_at)).all()
        terms: list[str] = []
        for row in rows:
            # Project terms come first so they survive the provider limit.
            if len(row.term) <= max_length and row.term.lower() not in {term.lower() for term in terms}:
                terms.append(row.term)
        return terms[:limit]

    @staticmethod
    def _has_text(session, meeting_id: str) -> bool:
        return bool(session.scalar(select(func.count()).select_from(MeetingSegment).where(MeetingSegment.meeting_id == meeting_id)))

    # --- speaker-separated transcript (run by the gateway) ----------------------------------------

    def claim_transcription(self) -> str | None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            rows = session.scalars(select(Meeting).where(
                Meeting.status == "FINISHED", Meeting.transcript_status.in_(("PENDING", "RUNNING")),
                Meeting.purged_at.is_(None),
            ).order_by(Meeting.ended_at)).all()
            for meeting in rows:
                stale = meeting.transcript_claimed_at is None or now - _aware(meeting.transcript_claimed_at) > STALE_CLAIM
                if meeting.transcript_status == "RUNNING" and not stale:
                    continue
                if meeting.transcript_attempts >= WORK_ATTEMPTS:
                    self._transcript_failed(session, meeting, meeting.transcript_error or "ATTEMPTS_EXHAUSTED")
                    session.commit()
                    continue
                meeting.transcript_status = "RUNNING"
                meeting.transcript_attempts += 1
                meeting.transcript_claimed_at = now
                session.commit()
                return str(meeting.id)
        return None

    def transcription_input(self, meeting_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            return {
                "audio": self._audio(meeting), "content_type": meeting.audio_content_type or "audio/webm",
                "language": meeting.language,
                "keyterms": self.keyterms(session, meeting.project_id, BATCH_KEYTERM_LIMIT, BATCH_KEYTERM_MAX_LENGTH),
            }

    @staticmethod
    def _audio(meeting: Meeting) -> bytes:
        storage = get_object_storage()
        return b"".join(
            decrypt_bytes(storage.get(audio_object_key(str(meeting.id), sequence)))
            for sequence in range(meeting.audio_chunk_count)
        )

    def save_transcript(self, meeting_id: str, turns: list[dict], transcription_id: str | None, duration_seconds: int | None) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            session.execute(delete(MeetingSegment).where(MeetingSegment.meeting_id == meeting_id, MeetingSegment.source == "BATCH"))
            for sequence, turn in enumerate(turns):
                session.add(MeetingSegment(
                    id=str(uuid4()), meeting_id=meeting_id, source="BATCH", sequence=sequence,
                    speaker_label=str(turn["speaker"]), start_ms=turn.get("start_ms"), end_ms=turn.get("end_ms"),
                    text_ciphertext=encrypt(str(turn["text"])), created_at=now,
                ))
            meeting.transcript_status = "DONE"
            meeting.transcript_error = None
            meeting.provider_transcription_id = transcription_id
            meeting.provider_deleted_at = None
            if meeting.source == "FILE" and duration_seconds is not None:
                meeting.duration_seconds = duration_seconds
            meeting.note_status = "PENDING" if turns or self._has_text(session, meeting_id) else "SKIPPED"
            meeting.note_attempts = 0
            meeting.updated_at = now
            self._audit(session, "meeting.transcribed", "meeting-gateway", meeting, {"turns": len(turns)}, actor_type="WORKER")
            session.commit()

    def transcription_failed(self, meeting_id: str, code: str, *, final: bool) -> None:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            meeting.transcript_error = code[:128]
            if final or meeting.transcript_attempts >= WORK_ATTEMPTS:
                self._transcript_failed(session, meeting, code)
            else:
                meeting.transcript_status = "PENDING"
            session.commit()

    def _transcript_failed(self, session, meeting: Meeting, code: str) -> None:
        meeting.transcript_status = "FAILED"
        meeting.transcript_error = code[:128]
        # The live transcript is still a usable basis for the note.
        meeting.note_status = "PENDING" if self._has_text(session, str(meeting.id)) else "SKIPPED"

    def pending_provider_deletes(self) -> list[tuple[str, str]]:
        with get_session() as session:
            rows = session.scalars(select(Meeting).where(
                Meeting.provider_transcription_id.is_not(None), Meeting.provider_deleted_at.is_(None),
            )).all()
            return [(str(row.id), str(row.provider_transcription_id)) for row in rows]

    def provider_deleted(self, meeting_id: str) -> None:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            meeting.provider_deleted_at = datetime.now(timezone.utc)
            self._audit(session, "meeting.provider_data_deleted", "meeting-gateway", meeting, actor_type="WORKER")
            session.commit()

    # --- meeting note (run by the AI worker) -------------------------------------------------------

    # --- the spoken words rewritten as a short request (run by the AI worker) ------------------------

    def request_rewrite(self, meeting_id: str, actor_id: str, publisher=None) -> dict[str, object]:
        """Ask for the transcript to be rewritten as a short request. The AI worker does it; the caller polls."""
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            if meeting.status != "FINISHED" or not self._has_text(session, meeting_id):
                raise MeetingError("MEETING_HAS_NO_TRANSCRIPT", "Recording has no transcript to rewrite")
            if meeting.rewrite_status != "PENDING":
                meeting.rewrite_status = "PENDING"
                meeting.rewrite_error = None
                meeting.updated_at = datetime.now(timezone.utc)
                self._audit(session, "meeting.rewrite_requested", actor_id, meeting, {})
                session.commit()
                (publisher or _publish_rewrite)(str(meeting.id))
        return self.detail(meeting_id, actor_id, audit=False)

    def rewrite_input(self, meeting_id: str) -> dict[str, str] | None:
        with get_session() as session:
            meeting = session.get(Meeting, meeting_id)
            if meeting is None or meeting.rewrite_status != "PENDING":
                return None
            segments = session.scalars(select(MeetingSegment).where(MeetingSegment.meeting_id == meeting_id).order_by(MeetingSegment.sequence)).all()
            # The speaker-separated transcript is the better one when it exists.
            chosen = [row for row in segments if row.source == "BATCH"] or segments
            text = "\n".join(filter(None, (decrypt(row.text_ciphertext) for row in chosen)))
            project = session.get(Project, meeting.project_id) if meeting.project_id else None
            return {"transcript": text, "project": project.name if project else ""} if text.strip() else None

    def save_rewrite(self, meeting_id: str, text: str | None, error_code: str | None = None) -> None:
        with get_session() as session:
            meeting = session.get(Meeting, meeting_id)
            if meeting is None:
                return
            meeting.rewrite_status = "DONE" if text else "FAILED"
            meeting.rewrite_text_ciphertext = encrypt(text.strip()) if text else None
            meeting.rewrite_error = None if text else (error_code or "REWRITE_FAILED")[:128]
            meeting.updated_at = datetime.now(timezone.utc)
            self._audit(session, "meeting.rewrite_done" if text else "meeting.rewrite_failed", "ai-worker", meeting, {"error": meeting.rewrite_error}, actor_type="WORKER")
            session.commit()

    def claim_note(self) -> str | None:
        with get_session() as session:
            meeting = session.scalar(select(Meeting).where(
                Meeting.status == "FINISHED", Meeting.note_status == "PENDING",
                Meeting.transcript_status.in_(("DONE", "FAILED", "SKIPPED")), Meeting.purged_at.is_(None),
            ).order_by(Meeting.ended_at))
            if meeting is None:
                return None
            meeting.note_attempts += 1
            session.commit()
            return str(meeting.id)

    def note_input(self, meeting_id: str) -> dict[str, object] | None:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            segments = self._segments(session, meeting)
            if not segments:
                return None
            names = meeting.speaker_names or {}
            lines = [
                f"{names.get(segment.speaker_label, segment.speaker_label)}: {decrypt(segment.text_ciphertext)}"
                if segment.speaker_label else str(decrypt(segment.text_ciphertext))
                for segment in segments
            ]
            projects = session.scalars(select(Project).where(Project.status == "ACTIVE").order_by(Project.code)).all()
            selected = session.get(Project, meeting.project_id) if meeting.project_id else None
            return {
                "transcript": "\n".join(lines), "projects": [project.name for project in projects],
                "selected_project": selected.name if selected else None,
            }

    @staticmethod
    def _segments(session, meeting: Meeting) -> list[MeetingSegment]:
        """The speaker-separated transcript when it exists, otherwise the live one."""
        for source in ("BATCH", "REALTIME"):
            rows = session.scalars(select(MeetingSegment).where(
                MeetingSegment.meeting_id == meeting.id, MeetingSegment.source == source,
            ).order_by(MeetingSegment.sequence)).all()
            if rows:
                return list(rows)
        return []

    def save_note(self, meeting_id: str, note, *, model: str) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            projects = {project.name.lower(): project for project in session.scalars(select(Project).where(Project.status == "ACTIVE")).all()}
            # Items already turned into an Intake are part of the record and survive regeneration.
            session.execute(delete(MeetingNoteItem).where(
                MeetingNoteItem.meeting_id == meeting_id, MeetingNoteItem.intake_id.is_(None),
            ))
            position = session.scalar(select(func.count()).select_from(MeetingNoteItem).where(MeetingNoteItem.meeting_id == meeting_id)) or 0

            def add(kind: str, title: str, detail: str | None = None, project: str | None = None, owner: str | None = None, due: str | None = None, topic: str | None = None) -> None:
                nonlocal position
                matched = projects.get((project or "").strip().lower())
                session.add(MeetingNoteItem(
                    id=str(uuid4()), meeting_id=meeting_id, kind=kind, position=int(position), topic=(topic or "").strip()[:120] or None,
                    title_ciphertext=encrypt(title.strip()[:500]), detail_ciphertext=encrypt(detail.strip()) if detail and detail.strip() else None,
                    owner=(owner or "").strip()[:255] or None, due_text=(due or "").strip()[:255] or None,
                    # A meeting is about one project: every item takes it. The AI's guess only fills in for
                    # older meetings that were recorded without a project.
                    project_id=meeting.project_id or (str(matched.id) if matched else None),
                    edited=False, created_at=now,
                ))
                position += 1

            for topic in note.topics:
                for entry in topic.entries:
                    add(entry.kind, entry.title, entry.detail, None, entry.owner if entry.kind == "ACTION" else None, entry.due if entry.kind == "ACTION" else None, topic.name)
            for decision in note.decisions:
                add("DECISION", decision)
            for item in note.items:
                add(item.kind, item.title, item.detail, item.project)
            for action in note.actions:
                add("ACTION", action.title, None, action.project, action.owner, action.due)
            for question in note.questions:
                add("QUESTION", question)
            for risk in note.risks:
                add("RISK", risk)
            meeting.note_summary_ciphertext = encrypt(note.summary.strip())
            meeting.note_status = "DONE"
            meeting.note_error = None
            meeting.note_model = model[:128]
            meeting.updated_at = now
            self._audit(session, "meeting.note_generated", "ai-worker", meeting, {"items": int(position)}, actor_type="WORKER")
            session.commit()

    def note_failed(self, meeting_id: str, code: str, *, final: bool) -> bool:
        """Returns True when the note will not be retried."""
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            meeting.note_error = code[:128]
            exhausted = final or meeting.note_attempts >= WORK_ATTEMPTS
            if exhausted:
                meeting.note_status = "FAILED"
            session.commit()
            return exhausted

    def regenerate_note(self, meeting_id: str, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            # A meeting cut short still has its live text; "recording" or nothing at all has no note to make.
            if meeting.status not in ("FINISHED", "FAILED") or not self._has_text(session, meeting_id):
                raise MeetingError("MEETING_HAS_NO_TRANSCRIPT", "Cuộc họp chưa kết thúc hoặc chưa có chữ nào để tạo note")
            meeting.note_status = "PENDING"
            meeting.note_attempts = 0
            meeting.note_error = None
            self._audit(session, "meeting.note_regenerate_requested", actor_id, meeting)
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    # --- CTO edits -----------------------------------------------------------------------------------

    def rename_speakers(self, meeting_id: str, names: dict[str, str], actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            labels = {segment.speaker_label for segment in self._segments(session, meeting) if segment.speaker_label}
            updated = dict(meeting.speaker_names or {})
            for label, name in names.items():
                if label not in labels:
                    raise MeetingError("SPEAKER_NOT_FOUND", f"Speaker '{label}' is not in this meeting")
                cleaned = " ".join(name.split())[:80]
                if cleaned:
                    updated[label] = cleaned
                else:
                    updated.pop(label, None)
            meeting.speaker_names = updated
            self._audit(session, "meeting.speakers_renamed", actor_id, meeting, {"speakers": sorted(names)})
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    def set_project(self, meeting_id: str, project_ref: str, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            project = self._project(session, project_ref)
            if project is None:
                raise MeetingError("MEETING_PROJECT_REQUIRED", "Choose the project this meeting is about")
            meeting.project_id = str(project.id)
            meeting.updated_at = datetime.now(timezone.utc)
            # Items that already became an Intake belong to that Intake's project and stay as they are.
            moved = session.execute(update(MeetingNoteItem).where(
                MeetingNoteItem.meeting_id == meeting_id, MeetingNoteItem.intake_id.is_(None),
            ).values(project_id=str(project.id))).rowcount
            self._audit(session, "meeting.project_changed", actor_id, meeting, {"project": project.code, "note_items": int(moved or 0)})
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    def rename(self, meeting_id: str, title: str, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            cleaned = " ".join(title.split())
            if not cleaned:
                raise MeetingError("MEETING_TITLE_EMPTY", "Meeting title cannot be empty")
            if cleaned != meeting.title:
                meeting.title = cleaned[:200]
                meeting.updated_at = datetime.now(timezone.utc)
                self._audit(session, "meeting.renamed", actor_id, meeting)
                session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    def remove(self, meeting_id: str, actor_id: str) -> dict[str, object]:
        """Delete a recording for good: audio, transcript and note. Intakes already made from its note stay."""
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            if meeting.status == "RECORDING" or meeting.transcript_status == "RUNNING":
                raise MeetingError("MEETING_BUSY", "Meeting is still being recorded or transcribed")
            if meeting.provider_transcription_id is not None and meeting.provider_deleted_at is None and get_settings().elevenlabs_delete_after_meeting:
                # Deleting now would lose the only record of the copy still held by the speech provider.
                raise MeetingError("MEETING_BUSY", "The speech provider's copy is still being removed; try again shortly")
            storage = get_object_storage()
            if meeting.purged_at is None:
                for sequence in range(meeting.audio_chunk_count):
                    storage.delete(audio_object_key(str(meeting.id), sequence))
            kept = session.scalar(select(func.count()).select_from(MeetingNoteItem).where(
                MeetingNoteItem.meeting_id == meeting.id, MeetingNoteItem.intake_id.is_not(None),
            )) or 0
            self._audit(session, "meeting.deleted", actor_id, meeting, {
                "kind": meeting.kind, "audio_chunks": meeting.audio_chunk_count, "intakes_kept": int(kept),
            })
            session.execute(delete(MeetingSegment).where(MeetingSegment.meeting_id == meeting.id))
            session.execute(delete(MeetingNoteItem).where(MeetingNoteItem.meeting_id == meeting.id))
            session.delete(meeting)
            session.commit()
            return {"deleted": True, "intakes_kept": int(kept)}

    def update_summary(self, meeting_id: str, summary: str, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            meeting.note_summary_ciphertext = encrypt(summary.strip())
            self._audit(session, "meeting.note_summary_updated", actor_id, meeting)
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    def _item(self, session, meeting_id: str, item_id: str) -> MeetingNoteItem:
        item = session.get(MeetingNoteItem, item_id)
        if item is None or str(item.meeting_id) != meeting_id:
            raise MeetingError("NOTE_ITEM_NOT_FOUND", "Meeting note item not found")
        return item

    def update_item(self, meeting_id: str, item_id: str, changes: dict[str, object], actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            item = self._item(session, meeting_id, item_id)
            if "project_code" in changes:
                project = self._project(session, changes["project_code"] or None)
                item.project_id = str(project.id) if project else None
            if "title" in changes:
                item.title_ciphertext = encrypt(str(changes["title"]).strip())
            if "detail" in changes:
                detail = str(changes["detail"] or "").strip()
                item.detail_ciphertext = encrypt(detail) if detail else None
            for field_name in ("kind", "owner", "due_text"):
                if field_name in changes:
                    setattr(item, field_name, changes[field_name] or None)
            item.edited = True
            self._audit(session, "meeting.note_item_updated", actor_id, meeting, {"item_id": item_id, "fields": sorted(changes)})
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    def remove_item(self, meeting_id: str, item_id: str, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            item = self._item(session, meeting_id, item_id)
            if item.intake_id is not None:
                raise MeetingError("NOTE_ITEM_HAS_INTAKE", "An item that already became an Intake cannot be removed")
            session.delete(item)
            self._audit(session, "meeting.note_item_removed", actor_id, meeting, {"item_id": item_id})
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    @staticmethod
    def _keywords(*texts: str | None) -> set[str]:
        words: set[str] = set()
        for text in texts:
            for word in re.findall(r"\w+", (text or "").lower()):
                if len(word) >= 3 and word not in TRANSCRIPT_STOPWORDS:
                    words.add(word)
        return words

    def _transcript_excerpt(self, session, meeting: Meeting, item: MeetingNoteItem, full: bool) -> str | None:
        """The spoken words behind a note item: the turns that share its words, with their neighbours, in order
        of time, within a budget; or the whole transcript when asked for or when it is short (FR-REC-15)."""
        names = meeting.speaker_names or {}
        segments = self._segments(session, meeting)
        turns = [((names.get(row.speaker_label) or row.speaker_label or "") if row.speaker_label else "", decrypt(row.text_ciphertext) or "") for row in segments]
        lines = [f"{speaker}: {text}" if speaker else text for speaker, text in turns if text.strip()]
        if not lines:
            return None
        whole = "\n".join(lines)
        if full or len(whole) <= TRANSCRIPT_EXCERPT_CHARS:
            return whole[:TRANSCRIPT_FULL_CHARS]
        keys = self._keywords(decrypt(item.title_ciphertext), item.topic, decrypt(item.detail_ciphertext) if item.detail_ciphertext else None)
        scores = [len(self._keywords(line) & keys) for line in lines]
        hits = sorted((index for index, score in enumerate(scores) if score > 0), key=lambda index: -scores[index])
        if not hits:
            return whole[:TRANSCRIPT_EXCERPT_CHARS]
        chosen: set[int] = set()
        size = 0
        for index in hits:
            block = [i for i in (index - 1, index, index + 1) if 0 <= i < len(lines) and i not in chosen]
            cost = sum(len(lines[i]) + 1 for i in block)
            if size + cost > TRANSCRIPT_EXCERPT_CHARS:
                continue
            chosen.update(block)
            size += cost
        return "\n".join(lines[i] for i in sorted(chosen))

    def intake_source(self, meeting_id: str, item_id: str, full_transcript: bool = False, *, for_work: bool = False) -> dict[str, object]:
        """Text and project for the Intake a note item becomes; the caller creates the Intake. For work on the board
        (FR-REC-19) questions and risks qualify too, and the item's own fields come along."""
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            item = self._item(session, meeting_id, item_id)
            if item.intake_id is not None:
                raise MeetingError("NOTE_ITEM_HAS_INTAKE", "This item already became an Intake")
            if item.kind not in (WORK_KINDS if for_work else INTAKE_KINDS):
                raise MeetingError("NOTE_ITEM_NOT_ACTIONABLE", "Only requirements, bugs, scope changes and actions can become an Intake")
            project = session.get(Project, item.project_id) if item.project_id else None
            if project is None:
                raise MeetingError("PROJECT_REQUIRED", "Choose a project for this item first")
            lines = [str(decrypt(item.title_ciphertext))]
            if item.detail_ciphertext:
                lines.append(str(decrypt(item.detail_ciphertext)))
            if item.owner or item.due_text:
                lines.append(" · ".join(part for part in (f"Phụ trách: {item.owner}" if item.owner else "", f"Hạn: {item.due_text}" if item.due_text else "") if part))
            lines.append(f"Nguồn: {meeting.title} ({_aware(meeting.started_at).astimezone(LOCAL_TZ).strftime('%d/%m/%Y')})")
            excerpt = self._transcript_excerpt(session, meeting, item, full_transcript)
            if excerpt:
                lines.append("Trích bản chữ cuộc họp (lời người nói, theo thứ tự thời gian):\n" + excerpt)
            return {
                "project_code": project.code, "project_id": str(project.id), "raw_text": "\n\n".join(lines), "sender_reference": f"Cuộc họp: {meeting.title}"[:255],
                "kind": item.kind, "title": str(decrypt(item.title_ciphertext)), "detail": decrypt(item.detail_ciphertext) if item.detail_ciphertext else None,
                "owner": item.owner, "due_text": item.due_text, "meeting_title": meeting.title,
            }

    def link_intake(self, meeting_id: str, item_id: str, intake_id: str, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            item = self._item(session, meeting_id, item_id)
            item.intake_id = intake_id
            self._audit(session, "meeting.note_item_to_intake", actor_id, meeting, {"item_id": item_id, "intake_id": intake_id})
            session.commit()
        return self.detail(meeting_id, actor_id, audit=False)

    # --- reads -----------------------------------------------------------------------------------------

    def list(self, allowed_project_ids: frozenset[str] | None = None, include_dictation: bool = False) -> list[dict[str, object]]:
        with get_session() as session:
            query = select(Meeting).order_by(Meeting.started_at.desc()).limit(100)
            if not include_dictation:
                query = query.where(Meeting.kind == "MEETING")
            if allowed_project_ids is not None:
                query = query.where(Meeting.project_id.in_(sorted(allowed_project_ids)))
            rows = session.scalars(query).all()
            # What was spoken into the private space is not a company recording (ADR-0031).
            hidden = set(private_project_ids(session))
            return [self._summary(session, row) for row in rows if str(row.project_id) not in hidden]

    def project_of(self, meeting_id: str) -> tuple[bool, str | None]:
        """Whether the meeting exists, and its project (an older meeting may have none)."""
        with get_session() as session:
            try:
                row = session.execute(select(Meeting.id, Meeting.project_id).where(Meeting.id == meeting_id)).first()
            except Exception:  # a malformed ID is simply not a meeting
                session.rollback()
                return False, None
            return (row is not None), (str(row.project_id) if row is not None and row.project_id else None)

    def term_project(self, term_id: str) -> tuple[bool, str | None]:
        with get_session() as session:
            try:
                row = session.execute(select(GlossaryTerm.id, GlossaryTerm.project_id).where(GlossaryTerm.id == term_id)).first()
            except Exception:
                session.rollback()
                return False, None
            return (row is not None), (str(row.project_id) if row is not None and row.project_id else None)

    def detail(self, meeting_id: str, actor_id: str, *, audit: bool = True) -> dict[str, object]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            segments = self._segments(session, meeting)
            items = session.scalars(select(MeetingNoteItem).where(
                MeetingNoteItem.meeting_id == meeting_id,
            ).order_by(MeetingNoteItem.position)).all()
            projects = {str(project.id): project for project in session.scalars(select(Project)).all()}
            names = meeting.speaker_names or {}
            labels: list[str] = []
            for segment in segments:
                if segment.speaker_label and segment.speaker_label not in labels:
                    labels.append(segment.speaker_label)
            if audit:
                self._audit(session, "meeting.transcript.read", actor_id, meeting)
                session.commit()
            parts = session.scalars(select(Meeting).where(Meeting.series_id == meeting.series_id).order_by(Meeting.part_number)).all() if meeting.series_id else []
            # The work a note item became on the board (FR-REC-19), found through its Intake.
            linked = [str(item.intake_id) for item in items if item.intake_id]
            work_of = {str(row.intake_id): (str(row.id), row.code) for row in session.scalars(select(WorkItem).where(WorkItem.intake_id.in_(linked))).all()} if linked else {}
            return {
                **self._summary(session, meeting),
                "parts": [{
                    "id": str(part.id), "part_number": int(part.part_number or 1), "title": part.title, "status": part.status,
                    "transcript_status": part.transcript_status, "note_status": part.note_status,
                } for part in parts],
                "transcript_source": segments[0].source if segments else None,
                "speakers": [{"label": label, "name": names.get(label)} for label in labels],
                "segments": [{
                    "id": str(segment.id), "source": segment.source, "sequence": segment.sequence,
                    "speaker_label": segment.speaker_label, "speaker_name": names.get(segment.speaker_label) if segment.speaker_label else None,
                    "start_ms": segment.start_ms, "end_ms": segment.end_ms, "text": decrypt(segment.text_ciphertext),
                } for segment in segments],
                "note_summary": decrypt(meeting.note_summary_ciphertext),
                "rewrite_status": meeting.rewrite_status, "rewrite_text": decrypt(meeting.rewrite_text_ciphertext) if meeting.rewrite_text_ciphertext else None,
                "rewrite_error": meeting.rewrite_error,
                "note_items": [{
                    "work_id": work_of.get(str(item.intake_id), (None, None))[0] if item.intake_id else None,
                    "work_code": work_of.get(str(item.intake_id), (None, None))[1] if item.intake_id else None,
                    "can_become_work": item.kind in WORK_KINDS and item.intake_id is None,
                    "id": str(item.id), "kind": item.kind, "topic": item.topic, "title": decrypt(item.title_ciphertext),
                    "detail": decrypt(item.detail_ciphertext), "owner": item.owner, "due_text": item.due_text,
                    "project_code": projects[str(item.project_id)].code if item.project_id else None,
                    "project_name": projects[str(item.project_id)].name if item.project_id else None,
                    "intake_id": str(item.intake_id) if item.intake_id else None, "edited": item.edited,
                    "can_become_intake": item.kind in INTAKE_KINDS and item.intake_id is None,
                } for item in items],
            }

    def audio(self, meeting_id: str, actor_id: str) -> tuple[bytes, str]:
        with get_session() as session:
            meeting = self._get(session, meeting_id)
            if meeting.purged_at is not None or meeting.audio_chunk_count == 0:
                raise MeetingError("AUDIO_NOT_AVAILABLE", "Recording is not available")
            content = self._audio(meeting)
            self._audit(session, "meeting.audio.read", actor_id, meeting)
            session.commit()
            return content, meeting.audio_content_type or "audio/webm"

    @staticmethod
    def _summary(session, meeting: Meeting) -> dict[str, object]:
        project = session.get(Project, meeting.project_id) if meeting.project_id else None
        return {
            "id": str(meeting.id), "title": meeting.title, "status": meeting.status, "source": meeting.source, "kind": meeting.kind,
            "language": meeting.language, "project_code": project.code if project else None,
            "project_name": project.name if project else None, "started_at": meeting.started_at,
            "ended_at": meeting.ended_at, "duration_seconds": meeting.duration_seconds,
            "audio_chunk_count": meeting.audio_chunk_count, "audio_bytes": meeting.audio_bytes,
            "max_minutes": get_settings().meeting_max_minutes,
            "series_id": str(meeting.series_id) if meeting.series_id else None, "part_number": int(meeting.part_number or 1),
            "transcript_status": meeting.transcript_status, "note_status": meeting.note_status,
            "transcript_error": meeting.transcript_error, "note_error": meeting.note_error,
            "provider_data_deleted": meeting.provider_transcription_id is None or meeting.provider_deleted_at is not None,
            "audio_available": meeting.purged_at is None and meeting.audio_chunk_count > 0,
        }

    # --- retention -------------------------------------------------------------------------------------

    def purge_expired(self, now: datetime | None = None) -> int:
        """Delete recordings and transcripts past retention; the meeting note stays as normalized content."""
        current = now or datetime.now(timezone.utc)
        purged = 0
        with get_session() as session:
            rows = session.scalars(select(Meeting).where(
                Meeting.purge_after <= current, Meeting.purged_at.is_(None), Meeting.status != "RECORDING",
            )).all()
            storage = get_object_storage()
            for meeting in rows:
                for sequence in range(meeting.audio_chunk_count):
                    storage.delete(audio_object_key(str(meeting.id), sequence))
                session.execute(delete(MeetingSegment).where(MeetingSegment.meeting_id == meeting.id))
                meeting.purged_at = current
                self._audit(session, "retention.meeting_purged", "retention-worker", meeting, {"audio_chunks": meeting.audio_chunk_count}, actor_type="WORKER")
                purged += 1
            session.commit()
        return purged

    # --- glossary ----------------------------------------------------------------------------------------

    def glossary(self, project_ref: str | None = None) -> list[dict[str, object]]:
        with get_session() as session:
            project = self._project(session, project_ref)
            query = select(GlossaryTerm)
            if project is not None:
                query = query.where((GlossaryTerm.project_id == project.id) | GlossaryTerm.project_id.is_(None))
            else:
                query = query.where(GlossaryTerm.project_id.is_(None))
            rows = session.scalars(query.order_by(GlossaryTerm.project_id.is_(None).desc(), GlossaryTerm.term)).all()
            codes = {str(row.id): row.code for row in session.scalars(select(Project)).all()}
            return [{
                "id": str(row.id), "term": row.term,
                "project_code": codes.get(str(row.project_id)) if row.project_id else None,
                "usable_in_realtime": len(row.term) <= REALTIME_KEYTERM_MAX_LENGTH,
            } for row in rows]

    def add_term(self, term: str, project_ref: str | None) -> dict[str, object]:
        cleaned = " ".join(term.split())
        if not cleaned or len(cleaned) > BATCH_KEYTERM_MAX_LENGTH:
            raise MeetingError("GLOSSARY_TERM_INVALID", "Term must be 1 to 50 characters")
        with get_session() as session:
            project = self._project(session, project_ref)
            project_id = str(project.id) if project else None
            scope = GlossaryTerm.project_id == project_id if project_id else GlossaryTerm.project_id.is_(None)
            if session.scalar(select(GlossaryTerm).where(scope, func.lower(GlossaryTerm.term) == cleaned.lower())) is not None:
                raise MeetingError("GLOSSARY_TERM_EXISTS", "Term already exists in this list")
            total = session.scalar(select(func.count()).select_from(GlossaryTerm)) or 0
            if total >= BATCH_KEYTERM_LIMIT:
                raise MeetingError("GLOSSARY_FULL", "Glossary holds the maximum number of terms")
            row = GlossaryTerm(id=str(uuid4()), project_id=project_id, term=cleaned, created_at=datetime.now(timezone.utc))
            session.add(row)
            session.commit()
            return {
                "id": str(row.id), "term": row.term, "project_code": project.code if project else None,
                "usable_in_realtime": len(row.term) <= REALTIME_KEYTERM_MAX_LENGTH,
            }

    def remove_term(self, term_id: str) -> bool:
        with get_session() as session:
            row = session.get(GlossaryTerm, term_id)
            if row is None:
                return False
            session.delete(row)
            session.commit()
            return True


def _publish_rewrite(meeting_id: str) -> None:
    from app.queue.celery_app import celery_app

    celery_app.send_task("intake.meetings.rewrite", args=[meeting_id], queue="ai.normalize")


meeting_service = MeetingService()
