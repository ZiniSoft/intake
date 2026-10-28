"""The project context pack (FR-CTX-01..03, ADR-0063): `docs/agent/CONTEXT.md` in the project's main repository,
read by Intake, split into its eight numbered sections and scored by a fixed rule. Nothing here calls an AI, and
nothing here writes to a repository."""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select

from app.db import get_session
from app.models import AuditEvent, IntakeItem, Project, ProjectContextSnapshot, ProjectContextSuggestion, ProjectIntegration, User
from app.queue.celery_app import celery_app

CONTEXT_PATH = "docs/agent/CONTEXT.md"
MAX_CONTENT_BYTES = 60 * 1024
MIN_LINES = 3
STALE_DAYS = 30
STALE_PENALTY = 10
REQUIRED_POINTS = 14
OPTIONAL_POINTS = 8
BAND_FULL, BAND_PARTIAL, BAND_MISSING = "FULL", "PARTIAL", "MISSING"
SUGGESTION_STATES = ("PENDING", "APPLIED", "DISMISSED")
SUGGESTION_LIMIT = 10


class ContextError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def empty_pack(project_id: str) -> dict[str, object]:
    """What a project without any snapshot looks like: nothing read, every required section missing."""
    return {
        "project_id": str(project_id), "source": "REPO", "path": CONTEXT_PATH, "sha": None, "fetched_at": None, "meta": {}, "sections": {},
        "score": 0, "band": BAND_MISSING, "missing": [f"{n}. {t}" for n, _, t, r, _ in SECTIONS if r], "stale_days": None, "error": None,
        "has_content": False, "approved": False, "approved_sha": None, "approved_at": None, "content": None, "pending_suggestions": 0,
    }

# number, key, title, required, sent to the AI provider with a request
SECTIONS: list[tuple[int, str, str, bool, bool]] = [
    (1, "product", "Sản phẩm và người dùng", False, True),
    (2, "modules", "Bản đồ module và thuật ngữ", True, True),
    (3, "environments", "Môi trường và truy cập", True, False),
    (4, "run_test_deploy", "Chạy, test, triển khai", True, False),
    (5, "conventions", "Quy ước mã và nhánh", False, False),
    (6, "done", "Định nghĩa xong và bằng chứng", True, False),
    (7, "sensitive", "Dữ liệu nhạy cảm", True, False),
    (8, "people", "Người quyết và điểm nóng", True, False),
]
HEADING = re.compile(r"^##\s*(\d)\s*[.)]?\s*(.*)$")
COMMAND = re.compile(r"`[^`\n]{2,}`")
NOTHING = re.compile(r"^\s*[-*]?\s*chưa có\s*\.?\s*$", re.IGNORECASE)


def parse_context(text: str) -> dict[str, object]:
    """The YAML head and the eight sections, by their number. Text outside a numbered section is ignored."""
    meta: dict[str, str] = {}
    body = text.replace("\r\n", "\n")
    if body.startswith("---\n"):
        end = body.find("\n---", 4)
        if end > 0:
            for line in body[4:end].splitlines():
                key, sep, value = line.partition(":")
                if sep and key.strip():
                    meta[key.strip().lower()] = value.strip().strip("'\"")
            body = body[end + 4:]
    sections: dict[int, dict[str, object]] = {}
    current: int | None = None
    for line in body.splitlines():
        heading = HEADING.match(line.strip())
        if heading:
            number = int(heading.group(1))
            if 1 <= number <= 8:
                current = number
                sections[number] = {"title": heading.group(2).strip(), "lines": []}
                continue
            current = None
            continue
        if current is not None:
            sections[current]["lines"].append(line)
    out: dict[str, object] = {"meta": meta, "sections": {}}
    for number, key, title, required, to_ai in SECTIONS:
        raw = sections.get(number, {}).get("lines", [])
        content = [row for row in raw if row.strip()]
        placeholder = any(NOTHING.match(row) for row in content) and len(content) <= 2
        present = len(content) >= MIN_LINES and not placeholder
        if number == 4 and present:
            present = any(COMMAND.search(row) for row in content)
        out["sections"][key] = {
            "number": number, "title": title, "required": required, "to_ai": to_ai,
            "present": present, "lines": len(content), "text": "\n".join(content).strip(),
        }
    return out


def score_context(parsed: dict[str, object], today: date | None = None) -> dict[str, object]:
    """The fixed rule: 14 points per required section, 8 per optional one; a missing required section makes the
    pack MISSING whatever the score; a pack older than 30 days loses 10."""
    today = today or datetime.now(timezone.utc).date()
    sections = parsed["sections"]
    score = 0
    missing: list[str] = []
    for number, key, title, required, _ in SECTIONS:
        if sections[key]["present"]:
            score += REQUIRED_POINTS if required else OPTIONAL_POINTS
        elif required:
            missing.append(f"{number}. {title}")
    stale_days = None
    updated = str((parsed.get("meta") or {}).get("updated") or "").strip()
    try:
        stale_days = (today - date.fromisoformat(updated)).days if updated else None
    except ValueError:
        stale_days = None
    stale = stale_days is not None and stale_days > STALE_DAYS
    if stale:
        score -= STALE_PENALTY
    score = max(0, min(100, score))
    band = BAND_MISSING if missing or score < 60 else BAND_FULL if score >= 85 else BAND_PARTIAL
    return {"score": score, "band": band, "missing": missing, "stale": stale, "stale_days": stale_days}


class ProjectContextService:
    def main_repo(self, project_id: str) -> dict[str, str] | None:
        """The project's main repository: the enabled GitLab or GitHub mapping, GitLab first."""
        with get_session() as session:
            for system in ("GITLAB", "GITHUB"):
                mapping = session.scalar(select(ProjectIntegration).where(
                    ProjectIntegration.project_id == project_id, ProjectIntegration.system == system,
                    ProjectIntegration.enabled.is_(True), ProjectIntegration.project_external_id.is_not(None),
                ))
                if mapping is not None:
                    return {"system": system, "target": str(mapping.project_external_id), "token_ref": str(mapping.credential_ref or "")}
        return None

    def store(self, project_id: str, *, source: str, content: str | None, sha: str | None, error: str | None = None, actor_id: str | None = None) -> dict[str, object]:
        """Keep what was read (or pasted), split and scored; one row per project, replaced on every read."""
        now = datetime.now(timezone.utc)
        text = (content or "")[:MAX_CONTENT_BYTES]
        parsed = parse_context(text) if text.strip() else {"meta": {}, "sections": {key: {"number": n, "title": t, "required": r, "to_ai": a, "present": False, "lines": 0, "text": ""} for n, key, t, r, a in SECTIONS}}
        scored = score_context(parsed, now.date())
        with get_session() as session:
            row = session.scalar(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project_id))
            if row is None:
                row = ProjectContextSnapshot(id=str(uuid4()), project_id=project_id, created_at=now)
                session.add(row)
            row.source, row.path, row.sha, row.content = source, CONTEXT_PATH, sha, text or None
            row.meta = parsed["meta"]
            row.sections = {key: {name: value for name, value in section.items() if name != "text"} for key, section in parsed["sections"].items()}
            row.score, row.band, row.missing = int(scored["score"]), str(scored["band"]), list(scored["missing"])
            row.stale_days = scored["stale_days"]
            row.error = error
            row.fetched_at = now
            row.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="USER" if actor_id else "SYSTEM", actor_id=actor_id or "repo-reader",
                event_type="project.context.read", entity_type="project", entity_id=project_id,
                details={"source": source, "sha": sha, "score": row.score, "band": row.band, "missing": row.missing, "error": error}, created_at=now,
            ))
            session.commit()
            return self._dict(session, row)

    def record_error(self, project_id: str, error: str) -> dict[str, object] | None:
        """A read that failed: the last good pack stays, the error shows next to it."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.scalar(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project_id))
            if row is None:
                row = ProjectContextSnapshot(id=str(uuid4()), project_id=project_id, created_at=now, source="REPO", path=CONTEXT_PATH, score=0, band=BAND_MISSING, missing=[f"{n}. {t}" for n, _, t, r, _ in SECTIONS if r], sections={}, meta={})
                session.add(row)
            row.error, row.fetched_at, row.updated_at = error, now, now
            session.commit()
            return self._dict(session, row)

    def snapshot(self, project_id: str) -> dict[str, object] | None:
        with get_session() as session:
            row = session.scalar(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project_id))
            return self._dict(session, row) if row is not None else None

    def prompt_context(self, project_id: str) -> dict[str, object] | None:
        """What replaces the free brief in the normalization prompt (FR-CTX-05): sections 1 and 2 of the pack, but only
        when the CTO approved the version that is current and at least one of those sections is present. Otherwise None,
        and the brief field stays the source."""
        with get_session() as session:
            row = session.scalar(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project_id))
            if row is None or not row.content:
                return None
            if not row.approved_sha or row.approved_sha != (row.sha or row.content_hash()):
                return None
            parsed = parse_context(row.content)
            chosen = [section for section in parsed["sections"].values() if section["to_ai"] and section["present"]]
            if not chosen:
                return None
            text = "\n\n".join(f"{section['title']}:\n{section['text']}" for section in chosen)[:4000]
            return {"text": text, "sections": [str(section["title"]) for section in chosen], "approved_at": row.approved_at, "sha": row.sha}

    def sections_for_ai(self, project_id: str) -> str:
        """Sections 1 and 2 of the approved or latest pack, for the normalization prompt; nothing else leaves."""
        with get_session() as session:
            row = session.scalar(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project_id))
            if row is None or not row.content:
                return ""
            parsed = parse_context(row.content)
            parts = [f"{section['title']}:\n{section['text']}" for key, section in parsed["sections"].items() if section["to_ai"] and section["present"]]
            return "\n\n".join(parts)[:4000]

    def approve(self, project_id: str, actor_id: str) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.scalar(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project_id))
            if row is None or not row.content:
                raise KeyError(project_id)
            row.approved_sha, row.approved_by, row.approved_at, row.updated_at = row.sha or row.content_hash(), actor_id, now, now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="USER", actor_id=actor_id, event_type="project.context.approved",
                entity_type="project", entity_id=project_id, details={"sha": row.approved_sha, "score": row.score}, created_at=now,
            ))
            session.commit()
            return self._dict(session, row)

    def queue_read(self, project_id: str) -> bool:
        try:
            celery_app.send_task("intake.context.read", args=[project_id], queue="repo.read")
            return True
        except Exception:  # noqa: BLE001 - no broker: the page says so, nothing else breaks
            return False

    def bands(self, project_ids=None) -> dict[str, dict[str, object]]:
        """Band, score and missing sections per project, for the readiness score of a request and the morning board."""
        with get_session() as session:
            query = select(ProjectContextSnapshot)
            if project_ids is not None:
                query = query.where(ProjectContextSnapshot.project_id.in_([str(pid) for pid in project_ids]))
            return {
                str(row.project_id): {
                    "band": row.band, "score": row.score, "missing": list(row.missing or []),
                    "approved": bool(row.approved_sha) and row.approved_sha == (row.sha or row.content_hash()),
                }
                for row in session.scalars(query).all()
            }

    # --- suggestions: what agents and people found missing while working; the CTO changes the file, then decides here

    def add_suggestions(self, project_id: str, *, texts: list[str], intake_id: str | None = None, work_log_id: str | None = None,
                        actor_id: str | None = None, agent_name: str | None = None) -> int:
        cleaned = [" ".join(str(text).split())[:500] for text in texts if str(text).strip()][:SUGGESTION_LIMIT]
        if not cleaned:
            return 0
        now = datetime.now(timezone.utc)
        with get_session() as session:
            for text in cleaned:
                session.add(ProjectContextSuggestion(
                    id=str(uuid4()), project_id=project_id, intake_id=intake_id, work_log_id=work_log_id, text=text,
                    suggested_by=actor_id, agent_name=agent_name, status="PENDING", created_at=now,
                ))
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="AGENT" if agent_name else "USER", actor_id=actor_id or "agent",
                event_type="project.context.suggested", entity_type="project", entity_id=project_id,
                details={"count": len(cleaned), "intake_id": intake_id, "work_log_id": work_log_id, "agent": agent_name}, created_at=now,
            ))
            session.commit()
        return len(cleaned)

    def suggestions(self, project_id: str, status: str | None = None) -> list[dict[str, object]]:
        with get_session() as session:
            query = select(ProjectContextSuggestion).where(ProjectContextSuggestion.project_id == project_id)
            if status:
                query = query.where(ProjectContextSuggestion.status == status)
            rows = session.scalars(query.order_by(ProjectContextSuggestion.created_at.desc())).all()
            return [self._suggestion(session, row) for row in rows]

    def decide(self, project_id: str, suggestion_id: str, *, status: str, actor_id: str) -> dict[str, object]:
        if status not in ("APPLIED", "DISMISSED"):
            raise ContextError("DECISION_UNKNOWN", "Decision must be APPLIED or DISMISSED")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.get(ProjectContextSuggestion, suggestion_id)
            if row is None or str(row.project_id) != str(project_id):
                raise KeyError(suggestion_id)
            if row.status != "PENDING":
                raise ContextError("ALREADY_DECIDED", "This suggestion was already decided")
            row.status, row.decided_by, row.decided_at = status, actor_id, now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="USER", actor_id=actor_id, event_type="project.context.suggestion_decided",
                entity_type="project", entity_id=project_id, details={"suggestion_id": row.id, "status": status}, created_at=now,
            ))
            session.commit()
            return self._suggestion(session, row)

    def pending_count(self, project_id: str) -> int:
        with get_session() as session:
            return self._pending(session, project_id)

    @staticmethod
    def _pending(session, project_id: str) -> int:
        return int(session.scalar(select(func.count()).select_from(ProjectContextSuggestion).where(
            ProjectContextSuggestion.project_id == project_id, ProjectContextSuggestion.status == "PENDING")) or 0)

    @staticmethod
    def _suggestion(session, row: ProjectContextSuggestion) -> dict[str, object]:
        intake = session.get(IntakeItem, row.intake_id) if row.intake_id else None
        by = session.get(User, row.suggested_by) if row.suggested_by else None
        decided = session.get(User, row.decided_by) if row.decided_by else None
        return {
            "id": str(row.id), "project_id": str(row.project_id), "intake_id": str(row.intake_id) if row.intake_id else None,
            "intake_public_id": intake.public_id if intake else None, "work_log_id": str(row.work_log_id) if row.work_log_id else None,
            "text": row.text, "suggested_by": str(row.suggested_by) if row.suggested_by else None,
            "suggested_by_name": (by.display_name or by.auth_subject) if by else None, "agent_name": row.agent_name, "status": row.status,
            "decided_by": str(row.decided_by) if row.decided_by else None, "decided_by_name": (decided.display_name or decided.auth_subject) if decided else None,
            "decided_at": row.decided_at, "created_at": row.created_at,
        }

    def software_project_ids(self) -> list[str]:
        with get_session() as session:
            return [str(row) for row in session.scalars(select(Project.id).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE")).all()]

    @staticmethod
    def _dict(session, row: ProjectContextSnapshot) -> dict[str, object]:
        current = row.sha or row.content_hash()
        return {
            "project_id": str(row.project_id), "source": row.source, "path": row.path, "sha": row.sha, "fetched_at": row.fetched_at,
            "meta": row.meta or {}, "sections": row.sections or {}, "score": row.score, "band": row.band, "missing": row.missing or [],
            "stale_days": row.stale_days, "error": row.error, "has_content": bool(row.content),
            "approved": bool(row.approved_sha) and row.approved_sha == current, "approved_sha": row.approved_sha, "approved_at": row.approved_at,
            "content": row.content, "pending_suggestions": ProjectContextService._pending(session, str(row.project_id)),
        }


project_context_service = ProjectContextService()
