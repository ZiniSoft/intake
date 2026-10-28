"""The CTO's private space (ADR-0031): one project whose ideas never show on the company's working screens.

It is ordinary Intake data in a project flagged private, so capture, encryption, AI and backups are the same.
What makes it private is that every company list and count leaves this project out.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from app.db import get_session
from app.models import AuditEvent, IdeaTrack, IntakeItem, PostDraft, Project, SourceMessage, TrackNote
from app.services.raw_crypto import decrypt, encrypt

PRIVATE_FLAG = "private"
VOICE_KEY = "voice"
VOICES_KEY = "voices"
# The master brand document: one core shared by every track, each track being one direction of it (ADR-0042).
MASTER_DNA_KEY = "master_dna"
MASTER_DNA_LIMIT = 40000
REFERENCE_LIMIT = 2
CHANNELS = ("FACEBOOK", "LINKEDIN", "THREADS", "FACEBOOK_GROUP", "BLOG", "VIDEO_SCRIPT")
# Two directions of one author's content run side by side (ADR-0035, ADR-0042): for business readers and for the trade.
TRACKS = {"business": "Kinh doanh", "technical": "Kỹ thuật"}
DEFAULT_TRACK = "business"
# What a track was called before ADR-0042; settings written under the old names are still read.
LEGACY_TRACKS = {"personal": "technical"}
DIRECTION_NOTES = {"business": "Hướng Kinh doanh trong Master DNA", "technical": "Hướng Kỹ thuật trong Master DNA"}
# What the idea behind a draft is: something that happened, an example made up to show a point, or another source.
CONTEXTS = ("REAL", "EXAMPLE", "SOURCE")
# Money behind a piece, which the reader must be told about. Only the technical direction takes it.
COMMERCIALS = ("NONE", "SPONSORED", "AFFILIATE")
COMMERCIAL_TRACK = "technical"
GOALS = ("AUTHORITY", "DISCUSSION", "REACH", "CONVERSATION", "FOLLOW")
AUDIENCES = ("SME", "AGENCY", "CONSULTANT", "DEVELOPER", "AI_USER")
# Long pieces: written from an outline, read for minutes rather than seconds.
LONG_CHANNELS = ("BLOG", "VIDEO_SCRIPT")
# The notebook, in the order the AI reads it: what is true, what may be shown, what was decided, what worked.
NOTE_KINDS = ("FACT", "PROOF", "DECISION", "RESULT")
NOTE_LIMIT = 60
GROUPS = ("FNB", "EDUCATION", "RETAIL", "SERVICE", "AGENCY", "CONSULTING")
IDEA_STATES = ("ALL", "NO_DRAFT", "DRAFTED", "POSTED", "DROPPED")


class PrivateSpaceError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def private_project_ids(session) -> list[str]:
    """Projects flagged private. There are few projects, so the flag is read in Python and works on any database."""
    rows = session.execute(select(Project.id, Project.project_settings)).all()
    return [str(project_id) for project_id, settings in rows if isinstance(settings, dict) and settings.get(PRIVATE_FLAG) is True]


def is_private(project_id: object) -> bool:
    with get_session() as session:
        return str(project_id) in private_project_ids(session)


def track_key(value: object) -> str:
    """A track's key today, whatever name it was stored under."""
    return LEGACY_TRACKS.get(str(value), str(value))


def by_track(stored: object) -> dict[str, object]:
    """A settings dict keyed by track, read under the keys tracks have today."""
    return {track_key(key): value for key, value in stored.items()} if isinstance(stored, dict) else {}


def empty_voice(track: str = DEFAULT_TRACK) -> dict[str, object]:
    return {
        "name": TRACKS.get(track, track), "direction_note": DIRECTION_NOTES.get(track, ""), "positioning": "", "audience": "",
        "pillars": [], "tone": "", "avoid": "", "default_channel": "FACEBOOK", "samples": [], "references": [],
    }


def voices_of(settings: object) -> dict[str, dict[str, object]]:
    """Every track with its voice. A space made before tracks existed keeps its one voice as the first track."""
    stored = by_track(settings.get(VOICES_KEY)) if isinstance(settings, dict) else {}
    legacy = settings.get(VOICE_KEY) if isinstance(settings, dict) else None
    voices = {}
    for track in TRACKS:
        saved = stored.get(track)
        if saved is None and track == DEFAULT_TRACK and isinstance(legacy, dict):
            saved = legacy
        # A brand document a track held before the core was shared is read by `master_dna_of`, not as the voice.
        voices[track] = {**empty_voice(track), **{key: value for key, value in (saved if isinstance(saved, dict) else {}).items() if key != "dna"}}
        # The names the tracks had by default before ADR-0042 are not what a direction is called.
        if voices[track]["name"] in ("Kinh doanh", "Cá nhân"):
            voices[track]["name"] = TRACKS[track]
        voices[track]["references"] = [
            {"title": str(item.get("title") or "")[:120], "text": str(item.get("text") or "")}
            for item in (voices[track].get("references") or []) if isinstance(item, dict) and str(item.get("text") or "").strip()
        ][:REFERENCE_LIMIT]
    return voices


def master_dna_of(settings: object) -> str:
    """The master brand document. Before it had its own place, each track held a copy: the longest one stands in."""
    if not isinstance(settings, dict):
        return ""
    text = settings.get(MASTER_DNA_KEY)
    if isinstance(text, str) and text.strip():
        return text
    held = [str(voice.get("dna") or "") for voice in by_track(settings.get(VOICES_KEY)).values() if isinstance(voice, dict)]
    legacy = settings.get(VOICE_KEY)
    if isinstance(legacy, dict):
        held.append(str(legacy.get("dna") or ""))
    return max(held, key=len) if any(held) else ""


class PrivateSpaceService:
    @staticmethod
    def _project(session) -> Project | None:
        ids = private_project_ids(session)
        return session.get(Project, ids[0]) if ids else None

    def project_id(self) -> str | None:
        with get_session() as session:
            project = self._project(session)
            return str(project.id) if project else None

    def create(self, actor_id: str) -> dict[str, object]:
        """Open the space: one IDEA project, flagged private. Asking twice returns the same space."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            if self._project(session) is None:
                taken_codes = set(session.scalars(select(Project.code)).all())
                taken_keys = set(session.scalars(select(Project.intake_key)).all())
                code = next(value for value in ("rieng", "rieng-cto", f"rieng-{uuid4().hex[:6]}") if value not in taken_codes)
                key = next((value for value in ("RIE", "RNG", "PRV", "MYI") if value not in taken_keys), None)
                if key is None:
                    raise PrivateSpaceError("INTAKE_KEY_TAKEN", "No free Intake key for the private space")
                project = Project(
                    id=str(uuid4()), code=code, intake_key=key, name="Riêng", kind="IDEA", status="ACTIVE",
                    project_settings={PRIVATE_FLAG: True, VOICE_KEY: empty_voice()}, created_at=now, updated_at=now,
                )
                session.add(project)
                # The audit row points at the project, so the project must exist first.
                session.flush()
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                    event_type="private_space.created", entity_type="project", entity_id=project.id, details=None, created_at=now,
                ))
                session.commit()
        return self.overview()

    def overview(self) -> dict[str, object]:
        with get_session() as session:
            project = self._project(session)
            if project is None:
                return {"project": None, "voice": None, "voices": {}, "master_dna": "", "counts": {"ideas": 0, "no_draft": 0, "drafted": 0, "posted": 0, "dropped": 0, "unposted_drafts": 0}}
            ideas = self._ideas(session, project)
            live = [idea for idea in ideas if idea["state"] != "DROPPED"]
            # An empty list must not reach the database as an empty UUID.
            unposted = session.scalar(select(func.count()).select_from(PostDraft).where(
                PostDraft.project_id == project.id, PostDraft.status == "DONE", PostDraft.posted_at.is_(None),
                PostDraft.intake_id.in_([idea["id"] for idea in live]),
            )) if live else 0
            return {
                "project": {"id": str(project.id), "code": project.code, "name": project.name},
                "voice": self._voice(project),
                "voices": voices_of(project.project_settings),
                "master_dna": master_dna_of(project.project_settings),
                "counts": {
                    "ideas": len(live),
                    "no_draft": sum(idea["state"] == "NO_DRAFT" for idea in live),
                    "drafted": sum(idea["state"] == "DRAFTED" for idea in live),
                    "posted": sum(idea["state"] == "POSTED" for idea in live),
                    "dropped": len(ideas) - len(live),
                    "unposted_drafts": int(unposted or 0),
                },
            }

    @staticmethod
    def _ideas(session, project: Project) -> list[dict[str, object]]:
        items = session.scalars(select(IntakeItem).where(IntakeItem.project_id == project.id).order_by(IntakeItem.created_at.desc()).limit(300)).all()
        ids = [str(item.id) for item in items]
        drafts: dict[str, list[PostDraft]] = {}
        if ids:
            for draft in session.scalars(select(PostDraft).where(PostDraft.intake_id.in_(ids), PostDraft.status == "DONE")).all():
                drafts.setdefault(str(draft.intake_id), []).append(draft)
        tracks = {str(row.intake_id): row.track for row in session.scalars(select(IdeaTrack).where(IdeaTrack.intake_id.in_(ids))).all()} if ids else {}
        notes: dict[str, str] = {}
        if ids:
            for source in session.scalars(select(SourceMessage).where(SourceMessage.intake_id.in_(ids)).order_by(SourceMessage.created_at.desc())).all():
                if source.raw_content_ciphertext:
                    notes[str(source.intake_id)] = (decrypt(source.raw_content_ciphertext) or "").strip()
        ideas = []
        for item in items:
            own = drafts.get(str(item.id), [])
            posted = [draft.posted_at for draft in own if draft.posted_at is not None]
            note = notes.get(str(item.id), "")
            ideas.append({
                "id": str(item.id), "public_id": item.public_id,
                "title": item.normalized_title or (note.splitlines()[0][:120] if note else None),
                "note": " ".join(note.split())[:200] or None,
                "analysed": item.normalized_title is not None,
                "status": item.status,
                "state": "DROPPED" if item.status == "REJECTED" else "POSTED" if posted else "DRAFTED" if own else "NO_DRAFT",
                "channels": sorted({draft.channel for draft in own}),
                "track": tracks.get(str(item.id)),
                "posted_at": max(posted) if posted else None,
                "created_at": item.created_at, "version": item.version,
            })
        return ideas

    def _idea(self, session, intake_id: str) -> IntakeItem:
        project = self._project(session)
        try:
            item = session.get(IntakeItem, intake_id)
        except Exception:  # a malformed ID is simply not an idea
            session.rollback()
            item = None
        if project is None or item is None or str(item.project_id) != str(project.id):
            raise PrivateSpaceError("IDEA_NOT_FOUND", "Idea not found in the private space")
        return item

    def track_of(self, intake_id: str) -> str | None:
        with get_session() as session:
            row = session.get(IdeaTrack, self._idea(session, intake_id).id)
            return row.track if row is not None else None

    def set_track(self, intake_id: str, track: str | None, actor_id: str) -> None:
        if track is not None and track not in TRACKS:
            raise PrivateSpaceError("TRACK_UNKNOWN", "Unknown track")
        with get_session() as session:
            item = self._idea(session, intake_id)
            row = session.get(IdeaTrack, item.id)
            if track is None:
                if row is not None:
                    session.delete(row)
            elif row is None:
                session.add(IdeaTrack(intake_id=item.id, track=track, updated_at=datetime.now(timezone.utc)))
            else:
                row.track = track
                row.updated_at = datetime.now(timezone.utc)
            session.commit()

    def ideas(self, state: str = "ALL", search: str | None = None, track: str | None = None) -> list[dict[str, object]]:
        with get_session() as session:
            project = self._project(session)
            if project is None:
                return []
            ideas = self._ideas(session, project)
        wanted = (search or "").strip().lower()
        if wanted:
            ideas = [idea for idea in ideas if wanted in f"{idea['public_id']} {idea['title'] or ''} {idea['note'] or ''}".lower()]
        if track:
            ideas = [idea for idea in ideas if idea["track"] == track]
        if state == "ALL":
            return [idea for idea in ideas if idea["state"] != "DROPPED"]
        return [idea for idea in ideas if idea["state"] == state]

    @staticmethod
    def notes_for(session, project_id: object, track: str) -> list[dict[str, object]]:
        rows = session.scalars(
            select(TrackNote).where(TrackNote.project_id == project_id, TrackNote.track == track).order_by(TrackNote.created_at.desc())
        ).all()
        notes = [{"id": str(row.id), "track": row.track, "kind": row.kind, "text": decrypt(row.text_ciphertext) or "", "created_at": row.created_at} for row in rows]
        return sorted(notes, key=lambda note: NOTE_KINDS.index(note["kind"]))

    def notes(self, track: str) -> list[dict[str, object]]:
        if track not in TRACKS:
            raise PrivateSpaceError("TRACK_UNKNOWN", "Unknown track")
        with get_session() as session:
            project = self._project(session)
            return self.notes_for(session, project.id, track) if project is not None else []

    def add_note(self, track: str, kind: str, text: str, actor_id: str) -> dict[str, object]:
        if track not in TRACKS or kind not in NOTE_KINDS:
            raise PrivateSpaceError("NOTE_UNKNOWN", "Unknown track or kind of note")
        cleaned = " ".join(text.split())
        if not cleaned:
            raise PrivateSpaceError("NOTE_EMPTY", "A note cannot be empty")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = self._project(session)
            if project is None:
                raise PrivateSpaceError("PRIVATE_SPACE_MISSING", "The private space has not been opened yet")
            held = session.scalar(select(func.count()).select_from(TrackNote).where(TrackNote.project_id == project.id, TrackNote.track == track))
            if int(held or 0) >= NOTE_LIMIT:
                raise PrivateSpaceError("NOTES_FULL", "The notebook of this track is full")
            note = TrackNote(id=str(uuid4()), project_id=project.id, track=track, kind=kind, text_ciphertext=encrypt(cleaned), created_by=actor_id, created_at=now)
            session.add(note)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="private_space.note_added", entity_type="track_note", entity_id=note.id,
                details={"track": track, "kind": kind}, created_at=now,
            ))
            session.commit()
            return {"id": str(note.id), "track": track, "kind": kind, "text": cleaned, "created_at": now}

    def remove_note(self, note_id: str, actor_id: str) -> None:
        with get_session() as session:
            project = self._project(session)
            try:
                note = session.get(TrackNote, note_id)
            except Exception:  # a malformed ID is simply not a note
                session.rollback()
                note = None
            if project is None or note is None or str(note.project_id) != str(project.id):
                raise PrivateSpaceError("NOTE_NOT_FOUND", "Note not found")
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="private_space.note_removed", entity_type="track_note", entity_id=note.id,
                details={"track": note.track, "kind": note.kind}, created_at=datetime.now(timezone.utc),
            ))
            session.delete(note)
            session.commit()

    @staticmethod
    def _voice(project: Project) -> dict[str, object]:
        return voices_of(project.project_settings)[DEFAULT_TRACK]

    def voice_of(self, project_id: object) -> dict[str, object]:
        with get_session() as session:
            project = session.get(Project, str(project_id))
            return self._voice(project) if project is not None else empty_voice()

    def save_voice(self, voice: dict[str, object], actor_id: str, track: str = DEFAULT_TRACK) -> dict[str, object]:
        if track not in TRACKS:
            raise PrivateSpaceError("TRACK_UNKNOWN", "Unknown track")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = self._project(session)
            if project is None:
                raise PrivateSpaceError("PRIVATE_SPACE_MISSING", "The private space has not been opened yet")
            # A new dict, so the JSON column is seen as changed.
            current = project.project_settings or {}
            master = master_dna_of(current)
            voices = {key: value for key, value in voices_of(current).items()}
            voices[track] = {
                **empty_voice(track), **{key: value for key, value in voice.items() if key != "dna"},
                "name": (str(voice.get("name") or "").strip() or TRACKS[track]),
                "direction_note": (" ".join(str(voice.get("direction_note") or "").split()) or DIRECTION_NOTES.get(track, "")),
                "references": [{"title": " ".join(str(item.get("title") or "").split())[:120] or "Tài liệu tham chiếu", "text": str(item.get("text") or "")} for item in (voice.get("references") or []) if str(item.get("text") or "").strip()][:REFERENCE_LIMIT],
            }
            # The voices are rewritten under today's keys; the shared document keeps its own place from now on.
            project.project_settings = {**{key: value for key, value in current.items() if key != VOICE_KEY}, PRIVATE_FLAG: True, VOICES_KEY: voices, MASTER_DNA_KEY: master}
            project.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="private_space.voice_updated", entity_type="project", entity_id=project.id,
                details={"track": track, "samples": len(voice.get("samples") or []), "pillars": len(voice.get("pillars") or []), "references": len(voices[track]["references"])}, created_at=now,
            ))
            session.commit()
        return self.overview()

    def audit_trial(self, actor_id: str, track: str, chars: int) -> None:
        """A trial sent the voice and a made-up line to the AI provider; that is worth a line in the log."""
        with get_session() as session:
            project = self._project(session)
            if project is None:
                return
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="private_space.voice_tried", entity_type="project", entity_id=project.id,
                details={"track": track, "chars": chars}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()

    def save_master_dna(self, text: str, actor_id: str) -> dict[str, object]:
        """The one brand document every track reads (ADR-0042)."""
        if len(text) > MASTER_DNA_LIMIT:
            raise PrivateSpaceError("MASTER_DNA_TOO_LONG", f"The master brand document holds at most {MASTER_DNA_LIMIT} characters")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = self._project(session)
            if project is None:
                raise PrivateSpaceError("PRIVATE_SPACE_MISSING", "The private space has not been opened yet")
            current = project.project_settings or {}
            project.project_settings = {**current, PRIVATE_FLAG: True, MASTER_DNA_KEY: text}
            project.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="private_space.master_dna_updated", entity_type="project", entity_id=project.id,
                details={"chars": len(text)}, created_at=now,
            ))
            session.commit()
        return self.overview()


private_space_service = PrivateSpaceService()
