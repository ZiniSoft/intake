"""What was done about a request, and what the CTO made of it (FR-MCP-03).

A person or an agent logs one entry per piece of work: cause, what changed, tests, branch and commit, how to check,
how to deploy. The CTO confirms ("checked and deployed") or returns it with a note; a returned entry is what the
next attempt reads first. The hints the CTO leaves for whoever fixes the request live next to it.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, IntakeItem, IntakeWorkLog, User
from app.modules.projects.context import project_context_service

DECISIONS = ("CONFIRMED", "RETURNED")
DETAIL_LISTS = ("changes", "verify_steps", "deploy_steps", "context_suggestions")
DETAIL_TEXTS = ("cause", "tests", "branch", "commit")
FIX_HINTS_LIMIT = 2000


class WorkLogError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _clean_details(details: dict | None) -> dict:
    """Only the fields the screen shows, trimmed; nothing else rides along."""
    details = details if isinstance(details, dict) else {}
    out: dict = {}
    for key in DETAIL_TEXTS:
        value = " ".join(str(details.get(key) or "").split())
        if value:
            out[key] = value[:500]
    for key in DETAIL_LISTS:
        items = details.get(key)
        if isinstance(items, list):
            cleaned = [" ".join(str(item).split())[:300] for item in items if str(item).strip()]
            if cleaned:
                out[key] = cleaned[:20]
    worked_on = str(details.get("worked_on") or "").strip()
    if worked_on:
        try:
            out["worked_on"] = date.fromisoformat(worked_on).isoformat()
        except ValueError as error:
            raise WorkLogError("WORKED_ON_INVALID", "worked_on must be YYYY-MM-DD") from error
    actual_minutes = details.get("actual_minutes")
    if actual_minutes is not None:
        if isinstance(actual_minutes, bool) or not isinstance(actual_minutes, int) or not 0 <= actual_minutes <= 1440:
            raise WorkLogError("ACTUAL_MINUTES_INVALID", "actual_minutes must be from 0 to 1440")
        out["actual_minutes"] = actual_minutes
    if isinstance(details.get("deployed"), bool):
        out["deployed"] = details["deployed"]
    return out


class WorkLogService:
    @staticmethod
    def _dict(session, row: IntakeWorkLog) -> dict[str, object]:
        actor = session.get(User, row.actor_id) if row.actor_id else None
        reviewer = session.get(User, row.reviewed_by) if row.reviewed_by else None
        return {
            "id": str(row.id), "intake_id": str(row.intake_id), "project_id": str(row.project_id),
            "actor_id": str(row.actor_id) if row.actor_id else None, "actor_name": actor.display_name if actor else None,
            "agent_name": row.agent_name, "summary": row.summary, "details": row.details or {},
            "review_decision": row.review_decision, "review_note": row.review_note,
            "reviewed_by_name": reviewer.display_name if reviewer else None, "reviewed_at": row.reviewed_at,
            "created_at": row.created_at,
        }

    def list(self, intake_id: str) -> list[dict[str, object]]:
        with get_session() as session:
            rows = session.scalars(select(IntakeWorkLog).where(IntakeWorkLog.intake_id == intake_id).order_by(IntakeWorkLog.created_at.desc())).all()
            return [self._dict(session, row) for row in rows]

    def add(self, intake_id: str, *, summary: str, details: dict | None, actor_id: str, agent_name: str | None) -> dict[str, object]:
        text = " ".join(summary.split())
        if len(text) < 5:
            raise WorkLogError("SUMMARY_REQUIRED", "Say in one line what was done")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            row = IntakeWorkLog(
                id=str(uuid4()), intake_id=item.id, project_id=item.project_id, actor_id=actor_id,
                agent_name=(" ".join(agent_name.split())[:80] or None) if agent_name else None,
                summary=text[:1000], details=_clean_details(details), review_decision="PENDING", created_at=now,
            )
            session.add(row)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="AGENT" if agent_name else "USER", actor_id=actor_id,
                event_type="intake.work_logged", entity_type="intake", entity_id=item.id,
                details={"work_log_id": row.id, "agent": row.agent_name, "commit": (row.details or {}).get("commit")}, created_at=now,
            ))
            session.commit()
            out = self._dict(session, row)
            project_id, work_log_id, agent = str(item.project_id), str(row.id), row.agent_name
        # What the pack lacked, as the worker saw it: kept for the CTO to decide on, never written to the repo (FR-CTX-04).
        suggestions = (out.get("details") or {}).get("context_suggestions") or []
        if suggestions:
            project_context_service.add_suggestions(project_id, texts=list(suggestions), intake_id=intake_id, work_log_id=work_log_id, actor_id=actor_id, agent_name=agent)
        self._attach_evidence(intake_id, out.get("details") or {}, actor_id)
        return out

    @staticmethod
    def _attach_evidence(intake_id: str, details: dict, actor_id: str) -> None:
        """The commit an agent names in its entry stands behind the request's Issue on the acceptance card (FR-PLAN-36)."""
        from app.models import ExternalLink
        from app.modules.planning import evidence as ev

        commit = str(details.get("commit") or "").strip()
        if not commit:
            return
        with get_session() as session:
            links = session.scalars(select(ExternalLink).where(ExternalLink.intake_id == intake_id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")))).all()
            for link in links:
                issue_url = ev.snapshot_url(session, str(link.project_id), link.external_id)
                try:
                    ev.add_links(session, str(link.project_id), link.external_id, [{"kind": "COMMIT", "ref": commit, "url": ev.commit_url(issue_url, commit)}],
                                 source="WORK_LOG", actor_id=actor_id, issue_web_url=issue_url)
                except ev.EvidenceError:
                    continue
            session.commit()

    def review(self, intake_id: str, log_id: str, *, decision: str, note: str | None, actor_id: str) -> dict[str, object]:
        if decision not in DECISIONS:
            raise WorkLogError("DECISION_UNKNOWN", "Decision must be CONFIRMED or RETURNED")
        text = " ".join((note or "").split())
        if decision == "RETURNED" and len(text) < 3:
            raise WorkLogError("NOTE_REQUIRED", "Say what is still wrong")
        now = datetime.now(timezone.utc)
        verification_id = None
        should_queue = False
        with get_session() as session:
            row = session.get(IntakeWorkLog, log_id)
            if row is None or str(row.intake_id) != str(intake_id):
                raise KeyError(log_id)
            if row.review_decision != "PENDING":
                raise WorkLogError("ALREADY_REVIEWED", "This entry was already reviewed")
            row.review_decision, row.review_note, row.reviewed_by, row.reviewed_at = decision, text[:1000] or None, actor_id, now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id,
                event_type="intake.work_reviewed", entity_type="intake", entity_id=row.intake_id,
                details={"work_log_id": row.id, "decision": decision, "note": row.review_note}, created_at=now,
            ))
            if decision == "CONFIRMED":
                from app.modules.planning.acceptance import accept_intake_work

                verification_id, should_queue = accept_intake_work(
                    session, str(row.intake_id), actor_id=actor_id, note=row.review_note, now=now,
                )
            session.commit()
            out = self._dict(session, row)
        if verification_id and should_queue:
            from app.modules.planning.acceptance import queue_acceptance

            queue_acceptance(verification_id)
        return out

    def set_fix_hints(self, intake_id: str, text: str | None, actor_id: str) -> str | None:
        cleaned = (text or "").strip()[:FIX_HINTS_LIMIT] or None
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            item.fix_hints = cleaned
            item.updated_at = datetime.now(timezone.utc)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id,
                event_type="intake.fix_hints_updated", entity_type="intake", entity_id=item.id,
                details={"chars": len(cleaned or "")}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            return cleaned


    def set_hard_flag(self, intake_id: str, value: bool, actor_id: str) -> bool:
        """The CTO's mark that acceptance of this work always comes back to the CTO (FR-PLAN-39)."""
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise KeyError(intake_id)
            before = bool(item.needs_cto_acceptance)
            if before != value:
                item.needs_cto_acceptance = value
                item.updated_at = datetime.now(timezone.utc)
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id,
                    event_type="intake.hard_flag_changed", entity_type="intake", entity_id=item.id,
                    details={"needs_cto_acceptance": value, "was": before, "at": "detail"}, created_at=datetime.now(timezone.utc),
                ))
                session.commit()
            return value


work_log_service = WorkLogService()
