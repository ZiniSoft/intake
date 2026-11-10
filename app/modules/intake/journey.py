"""Where one request stands on its way from Intake to an approved day plan."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.db import get_session
from app.modules.intake.decisions import latest_reopen_at, taken_back
from app.models import (
    ApprovalAction,
    ApprovalSnapshot,
    ExternalLink,
    GitLabIssueSnapshot,
    IntakeItem,
    IntakeWorkLog,
    IssueEvidenceLink,
    IssueVerification,
    PlanningAssignment,
    PlanningCandidate,
    PlanningRun,
    SyncJob,
    User,
    WorkforceMember,
    WorkItem,
)
from app.modules.planning.gitlab_read_model import evidence_summary

DELIVERY_SYSTEMS = ("GITLAB", "GITHUB")
# A plan that was approved keeps its assignments for good.
SETTLED_RUNS = ("APPROVED", "SYNCING", "SYNCED", "PARTIAL", "SYNC_FAILED")


def intake_journey(intake_id: str) -> dict[str, object] | None:
    with get_session() as session:
        item = session.get(IntakeItem, intake_id)
        if item is None:
            return None
        decision = session.scalar(
            select(ApprovalAction).where(ApprovalAction.intake_id == item.id).order_by(ApprovalAction.created_at.desc())
        )
        decided_by = session.get(User, decision.actor_id) if decision is not None and decision.actor_id else None
        # A link belongs to the decision it was created under. After that decision is reopened, the work item is still
        # out there, but it no longer is where this request lives.
        linked = session.execute(
            select(ExternalLink, ApprovalSnapshot.created_at, ApprovalSnapshot.invalidated_at)
            .join(SyncJob, SyncJob.id == ExternalLink.sync_job_id)
            .join(ApprovalSnapshot, ApprovalSnapshot.id == SyncJob.approval_snapshot_id)
            .where(ExternalLink.intake_id == item.id).order_by(ExternalLink.created_at.desc())
        ).all()
        reopened_at = latest_reopen_at(session, [str(item.id)]).get(str(item.id))
        current = [row[0] for row in linked if not taken_back(row[1], row[2], reopened_at)]
        current_keys = {(entry.target_system, entry.external_id) for entry in current}
        # The item of an earlier decision that the new decision took over again is not "previous" (FR-APR-10).
        previous = [row[0] for row in linked if taken_back(row[1], row[2], reopened_at) and (row[0].target_system, row[0].external_id) not in current_keys]
        link = next((entry for entry in current if entry.target_system in DELIVERY_SYSTEMS), None)
        other_link = None if link is not None else next(iter(current), None)
        job = session.scalar(select(SyncJob).where(SyncJob.intake_id == item.id).order_by(SyncJob.created_at.desc()))

        plans: list[dict[str, object]] = []
        accepted_at = None
        accepted_by = None
        verification = None
        if link is not None:
            accepted = session.scalar(select(IssueVerification).where(
                IssueVerification.project_id == item.project_id,
                IssueVerification.issue_external_id == link.external_id,
                IssueVerification.decision == "ACCEPTED",
            ).order_by(IssueVerification.decided_at.desc()))
            accepted_at = accepted.decided_at if accepted is not None else None
            accepted_by = session.get(User, accepted.decided_by) if accepted is not None and accepted.decided_by else None
            latest_verification = session.scalar(select(IssueVerification).where(
                IssueVerification.project_id == item.project_id,
                IssueVerification.issue_external_id == link.external_id,
            ).order_by(IssueVerification.created_at.desc()))
            if latest_verification is not None:
                po_by = session.get(User, latest_verification.po_decided_by) if latest_verification.po_decided_by else None
                final_by = latest_verification.final_by or ("CTO" if latest_verification.decision != "PENDING" else None)
                verification = {
                    "id": str(latest_verification.id), "decision": latest_verification.decision,
                    "source": latest_verification.source or "CLOSED", "created_at": latest_verification.created_at,
                    "reason": latest_verification.reason,
                    # The Project Owner's word, and whose word closed it (FR-PLAN-41).
                    "po_decision": latest_verification.po_decision, "po_decided_at": latest_verification.po_decided_at,
                    "po_decided_by_name": (po_by.display_name or po_by.auth_subject) if po_by else None,
                    "final_by": final_by,
                    "accepted_by_name": (accepted_by.display_name or accepted_by.auth_subject) if accepted_by else None,
                }
            rows = session.execute(
                select(PlanningAssignment, PlanningRun, WorkforceMember)
                .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
                .join(WorkforceMember, WorkforceMember.id == PlanningAssignment.member_id)
                .where(
                    PlanningAssignment.project_id == item.project_id,
                    PlanningAssignment.gitlab_issue_external_id == link.external_id,
                    PlanningRun.status != "SUPERSEDED",
                )
                .order_by(PlanningRun.plan_date.desc(), PlanningAssignment.slot)
            ).all()
            for assignment, run, member in rows[:6]:
                plans.append({
                    "plan_date": run.plan_date, "run_id": str(run.id), "assignment_id": str(assignment.id), "member_name": member.display_name,
                    "slot": assignment.slot, "planned_hours": float(assignment.planned_hours),
                    "settled": run.status in SETTLED_RUNS,
                    "work_status": assignment.work_status or "PLANNED", "work_status_at": assignment.work_status_at,
                    "accepted_at": accepted_at,
                })
        waiting = session.execute(
            select(PlanningCandidate, PlanningRun).join(PlanningRun, PlanningRun.id == PlanningCandidate.planning_run_id)
            .where(
                PlanningCandidate.intake_id == item.id, PlanningCandidate.status.in_(("PENDING_TRIAGE", "READY")),
                PlanningRun.status != "SUPERSEDED",
            ).order_by(PlanningRun.plan_date.desc())
        ).first()

        board = session.scalars(select(WorkItem).where(WorkItem.intake_id == item.id).order_by(WorkItem.created_at.desc())).first()
        logs = session.scalars(select(IntakeWorkLog).where(IntakeWorkLog.intake_id == item.id).order_by(IntakeWorkLog.created_at.desc())).all()
        latest_log = logs[0] if logs else None
        latest_actor = session.get(User, latest_log.actor_id) if latest_log is not None and latest_log.actor_id else None
        unlogged_evidence = None
        if link is not None and latest_log is None:
            snapshot = session.scalar(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == item.project_id,
                GitLabIssueSnapshot.issue_external_id == link.external_id,
                GitLabIssueSnapshot.is_current.is_(True),
            ).order_by(GitLabIssueSnapshot.fetched_at.desc()))
            summary = evidence_summary(snapshot.evidence if snapshot is not None else None)
            attached = session.scalars(select(IssueEvidenceLink).where(
                IssueEvidenceLink.project_id == item.project_id,
                IssueEvidenceLink.issue_external_id == link.external_id,
                IssueEvidenceLink.kind.in_(("COMMIT", "MR")),
            )).all()
            attached_commits = sum(1 for row in attached if row.kind == "COMMIT")
            attached_mrs = sum(1 for row in attached if row.kind == "MR")
            commits = int(summary["commits"]) + attached_commits
            merge_requests = int(summary["merge_requests"]) + attached_mrs
            if commits or merge_requests:
                unlogged_evidence = {"commits": commits, "merge_requests": merge_requests, "links": len(summary["links"])}

        latest_details = (latest_log.details or {}) if latest_log is not None else {}
        worked_on = None
        if latest_details.get("worked_on"):
            try:
                worked_on = date.fromisoformat(str(latest_details["worked_on"]))
            except ValueError:
                worked_on = None
        off_plan = not any(plan["plan_date"] == worked_on for plan in plans) if worked_on is not None else not bool(plans)

        return {
            "intake_id": str(item.id), "intake_public_id": item.public_id, "project_id": str(item.project_id), "status": item.status,
            "received_at": item.created_at, "channel": item.channel,
            "decision": {
                "action": decision.action, "at": decision.created_at,
                "by": (decided_by.display_name or decided_by.auth_subject) if decided_by else None,
                "route": item.approved_route, "priority": item.approved_priority,
            } if decision is not None else None,
            "issue": {"system": link.target_system, "external_id": link.external_id, "url": link.url} if link is not None else None,
            # A historical non-delivery decision, or a direct response, never becomes a delivery Issue.
            "other_target": other_link.target_system if other_link is not None else None,
            # The work item it became on the board (ADR-0066), whatever column it is in now.
            "work_item": {"id": str(board.id), "code": board.code, "status": board.status, "project_id": str(board.project_id)} if board is not None else None,
            "previous_targets": [{"system": entry.target_system, "external_id": entry.external_id, "url": entry.url} for entry in previous],
            # The sync that counts is the one of the standing decision; after a reopen there is none yet.
            "sync_status": job.status if job is not None and item.status != "PENDING_APPROVAL" else None,
            "accepted_at": accepted_at,
            "verification": verification,
            "plans": plans,
            "waiting_in_plan": {"plan_date": waiting[1].plan_date, "run_id": str(waiting[1].id), "plan_closed": waiting[1].status in SETTLED_RUNS} if waiting else None,
            "work": {
                "entries": len(logs), "latest_id": str(latest_log.id), "latest_decision": latest_log.review_decision, "latest_at": latest_log.created_at,
                "latest_by": latest_log.agent_name or (latest_actor.display_name if latest_actor else None),
                "off_plan": off_plan, "worked_on": worked_on,
                "actual_minutes": latest_details.get("actual_minutes"), "deployed": latest_details.get("deployed"),
            } if latest_log is not None else None,
            "unlogged_evidence": unlogged_evidence,
        }
