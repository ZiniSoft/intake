"""Where a planned piece of work stands (FR-PLAN-34): said by the person doing it, by the Project Owner or by the
CTO, from the web or from an agent in the terminal. "Done" with an Issue behind it is a claim: it joins the acceptance
queue for the CTO to check, the same way "done" in a daily report does."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.models import AuditEvent, IssueVerification, PlanningAssignment, PlanningRun
from app.modules.planning import acceptance
from app.modules.planning.gitlab_read_model import done_level
from app.modules.planning.service import WORK_STATUSES, planning_service


class WorkStatusError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def set_work_status(session, assignment: PlanningAssignment, status_value: str, note: str | None, actor_id: str, evidence: list[dict] | None = None) -> dict[str, object]:
    """Record the status on the assignment (the plan may be closed: the work goes on after the plan is settled) and
    keep the acceptance queue in step: "done" offers the Issue for checking, taking "done" back withdraws the offer
    nobody has looked at yet."""
    status_value = (status_value or "").upper()
    if status_value not in WORK_STATUSES:
        raise WorkStatusError("ARGUMENT_INVALID", f"status must be one of {', '.join(WORK_STATUSES)}")
    now = datetime.now(timezone.utc)
    previous = assignment.work_status or "PLANNED"
    assignment.work_status, assignment.work_status_at, assignment.work_status_note = status_value, now, (note or None)
    assignment.updated_at = now
    queued = False
    evidence_added = 0
    if assignment.gitlab_issue_external_id:
        if evidence:
            # What the person says stands behind the work goes on the Issue, whatever the status (FR-PLAN-36).
            from app.modules.planning import evidence as ev

            evidence_added = ev.add_links(session, str(assignment.project_id), assignment.gitlab_issue_external_id, evidence, source="WORKER",
                                          actor_id=actor_id, member_id=str(assignment.member_id) if assignment.member_id else None,
                                          issue_web_url=ev.snapshot_url(session, str(assignment.project_id), assignment.gitlab_issue_external_id))
        if status_value == "DONE":
            queued = _offer_acceptance(session, assignment, now)
        elif previous == "DONE":
            _withdraw_acceptance(session, assignment)
    session.add(AuditEvent(
        id=str(uuid4()), project_id=assignment.project_id, actor_type="USER", actor_id=actor_id, event_type="planning.assignment.work-status",
        entity_type="planning_assignment", entity_id=assignment.id,
        details={"from": previous, "to": status_value, "issue": assignment.gitlab_issue_external_id, "acceptance_queued": queued}, created_at=now,
    ))
    return {
        "assignment_id": str(assignment.id), "issue": assignment.gitlab_issue_external_id, "work_status": status_value, "previous": previous,
        "at": now.isoformat(), "work_status_note": assignment.work_status_note, "acceptance_queued": queued, "evidence_added": evidence_added,
    }


def _offer_acceptance(session, assignment: PlanningAssignment, now: datetime) -> bool:
    run = session.get(PlanningRun, assignment.planning_run_id)
    return offer_issue(session, str(assignment.project_id), assignment.gitlab_issue_external_id, str(assignment.member_id), run.plan_date if run else None, now)


def offer_issue(session, project_id: str, issue_id: str, member_id: str | None, reported_on, now: datetime, note: str | None = None) -> bool:
    """Put an Issue said to be done in front of the CTO, once: an Issue already waiting is not offered again, but a
    note that comes with the claim is kept on it so the CTO reads it and the Issue gets it when closed."""
    pending = session.scalar(select(IssueVerification).where(
        IssueVerification.project_id == project_id, IssueVerification.issue_external_id == issue_id, IssueVerification.decision == "PENDING",
    ))
    if pending is not None:
        if note and not pending.source_note:
            pending.source_note = note
        return False
    snapshot = acceptance._snapshot(session, project_id, issue_id)
    rule = planning_service._done_evidence_of(session, project_id)
    session.add(IssueVerification(
        id=str(uuid4()), project_id=project_id, issue_external_id=issue_id, planning_run_id=None,
        evidence_level=done_level(snapshot.state, snapshot.evidence, rule) if snapshot is not None else 0,
        decision="PENDING", source="PLAN", member_id=member_id, reported_on=reported_on, created_at=now, source_note=note,
    ))
    return True


def _withdraw_acceptance(session, assignment: PlanningAssignment) -> None:
    for row in session.scalars(select(IssueVerification).where(
        IssueVerification.project_id == assignment.project_id, IssueVerification.issue_external_id == assignment.gitlab_issue_external_id,
        IssueVerification.source == "PLAN", IssueVerification.decision == "PENDING", IssueVerification.po_decision.is_(None),
    )).all():
        session.delete(row)
