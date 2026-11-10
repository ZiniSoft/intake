"""Acceptance as its own queue (FR-PLAN-31, ADR-0055).

The team's real signal that something is finished is the line "DONE" in a daily report, now carrying an Issue
number. Each such Issue, and each Issue closed on the tracker, becomes one acceptance to look at: the Project Owner
of the project confirms it, and the CTO looks at a daily sample of five chosen where a wrong "done" would hurt most
(P0/P1 first, then work without a code trace, then the project and the person looked at least recently). "Not done"
sends the work back to the open plan as rework. "Done" by the CTO writes a note on the Issue and closes it, the one
write beyond assignee, milestone and due date that the tracker allowlist now permits.
"""
from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import or_, select

from app.db import get_session
from app.models import (
    ApprovalSnapshot, AuditEvent, EmailMessage, ExternalLink, GitLabIssueSnapshot, IntakeItem, IntakeWorkLog, IssueVerification,
    PlanningCandidate, PlanningRun, PlanningWarning, Project, ProjectIntegration, ReportItem, SyncJob, User,
    WorkforceMember, WorkforceProjectMembership,
)
from app.modules.planning import evidence as ev
from app.modules.intake.decisions import latest_reopen_at, taken_back
from app.modules.planning.gitlab_read_model import LEVEL_ACCEPTED, LEVEL_NAMES, LEVEL_TRACED, done_level, evidence_summary
from app.modules.planning.overview import LOCAL_TZ
from app.modules.planning.service import MUTABLE_RUN_STATES, planning_service
from app.modules.reports.service import usable_for_planning
from app.modules.projects.delivery_switch import is_moved
from app.queue.celery_app import celery_app

SAMPLE_PER_DAY = 5
REPORT_WINDOW = timedelta(days=14)
CLOSED_WINDOW = timedelta(days=7)
DECIDED_WINDOW = timedelta(days=7)
ACCEPT_TASK = "intake.integrations.accept-issue"
# Per-project acceptance policy (FR-PLAN-41, ADR-0082): the CTO always closes, or the Project Owner closes low-risk work.
POLICY_CTO_ALWAYS = "CTO_ALWAYS"
POLICY_PO_FINAL = "PO_FINAL_LOW_RISK"
ACCEPTANCE_POLICIES = (POLICY_CTO_ALWAYS, POLICY_PO_FINAL)
# Only P0 counts as hard on its own; anything else is hard only when the CTO flagged it (FR-PLAN-39).
HARD_PRIORITIES = ("P0",)


def _today() -> date:
    return datetime.now(LOCAL_TZ).date()


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _snapshot(session, project_id: str, issue_id: str) -> GitLabIssueSnapshot | None:
    return session.scalar(select(GitLabIssueSnapshot).where(
        GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.issue_external_id == issue_id, GitLabIssueSnapshot.is_current.is_(True),
    ).order_by(GitLabIssueSnapshot.fetched_at.desc()))


def collect() -> dict[str, int]:
    """Turn every recent "done" into one acceptance, including CTO-confirmed work logs from older releases."""
    now = datetime.now(timezone.utc)
    today = _today()
    created_report = created_closed = created_work_log = 0
    queue_ids: list[str] = []
    with get_session() as session:
        existing = {(str(row.project_id), str(row.issue_external_id)) for row in session.scalars(select(IssueVerification)).all()}
        rows = session.execute(
            select(ReportItem, EmailMessage).join(EmailMessage, EmailMessage.id == ReportItem.email_message_id)
            .where(ReportItem.is_current.is_(True), EmailMessage.is_current.is_(True), ReportItem.work_status == "DONE",
                   ReportItem.gitlab_issue_external_id.is_not(None), ReportItem.project_id.is_not(None),
                   EmailMessage.report_date >= today - REPORT_WINDOW)
            .order_by(EmailMessage.report_date.desc())
        ).all()
        for item, email in rows:
            key = (str(item.project_id), str(item.gitlab_issue_external_id))
            if key in existing or not usable_for_planning(email):
                continue
            snapshot = _snapshot(session, key[0], key[1])
            rule = planning_service._done_evidence_of(session, key[0])
            level = done_level(snapshot.state, snapshot.evidence, rule) if snapshot is not None else 0
            session.add(IssueVerification(
                id=str(uuid4()), project_id=item.project_id, issue_external_id=key[1], planning_run_id=None, evidence_level=level,
                decision="PENDING", source="REPORT", report_item_id=item.id, member_id=item.member_id, reported_on=email.report_date, created_at=now,
            ))
            try:
                ev.add_links(session, key[0], key[1], ev.links_from_text(f"{item.title} {item.summary}", snapshot.web_url if snapshot else None),
                             source="REPORT", member_id=str(item.member_id) if item.member_id else None, issue_web_url=snapshot.web_url if snapshot else None)
            except ev.EvidenceError:
                pass
            existing.add(key)
            created_report += 1
        closed = session.scalars(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.state == "closed", GitLabIssueSnapshot.closed_at.is_not(None),
            GitLabIssueSnapshot.closed_at >= now - CLOSED_WINDOW,
        )).all()
        for snapshot in closed:
            key = (str(snapshot.project_id), str(snapshot.issue_external_id))
            if key in existing:
                continue
            project = session.get(Project, snapshot.project_id)
            if project is None or project.status != "ACTIVE" or project.kind != "SOFTWARE":
                continue
            rule = planning_service._done_evidence_of(session, key[0])
            member_id = None
            for external in (snapshot.assignee_external_ids or []):
                member_id = session.scalar(select(WorkforceProjectMembership.member_id).where(
                    WorkforceProjectMembership.project_id == snapshot.project_id, WorkforceProjectMembership.gitlab_user_external_id == str(external),
                ))
                if member_id:
                    break
            session.add(IssueVerification(
                id=str(uuid4()), project_id=snapshot.project_id, issue_external_id=key[1], planning_run_id=None,
                evidence_level=done_level(snapshot.state, snapshot.evidence, rule), decision="PENDING", source="CLOSED", member_id=member_id, created_at=now,
            ))
            existing.add(key)
            created_closed += 1
        # INT-26W43-004: before work-log confirmation and Issue acceptance shared one state, CONFIRMED rows could
        # exist without an IssueVerification.  Reconcile the newest confirmation of each Intake on every collector
        # run; the helper is idempotent, so this also makes rolling deployments safe.
        seen_intakes: set[str] = set()
        confirmed_logs = session.scalars(select(IntakeWorkLog).where(
            IntakeWorkLog.review_decision == "CONFIRMED", IntakeWorkLog.reviewed_by.is_not(None),
        ).order_by(IntakeWorkLog.reviewed_at.desc(), IntakeWorkLog.created_at.desc())).all()
        for work_log in confirmed_logs:
            intake_id = str(work_log.intake_id)
            if intake_id in seen_intakes:
                continue
            seen_intakes.add(intake_id)
            verification_id, accepted = accept_intake_work(
                session, intake_id, actor_id=str(work_log.reviewed_by), note=work_log.review_note,
                now=_utc(work_log.reviewed_at) or _utc(work_log.created_at) or now,
            )
            if verification_id and accepted:
                queue_ids.append(verification_id)
                created_work_log += 1
        session.commit()
    for verification_id in queue_ids:
        queue_acceptance(verification_id)
    return {"from_reports": created_report, "from_closed": created_closed, "from_work_logs": created_work_log}


def _priority_of(session, row: IssueVerification) -> str:
    snapshot = _snapshot(session, str(row.project_id), row.issue_external_id)
    return planning_service._priority_from_labels(list(snapshot.labels or [])) if snapshot is not None else "P3"


def acceptance_policy_of(session, project_id: str) -> str:
    project = session.get(Project, project_id)
    value = str(((project.project_settings if project else None) or {}).get("acceptance_policy") or POLICY_CTO_ALWAYS)
    return value if value in ACCEPTANCE_POLICIES else POLICY_CTO_ALWAYS


def _intake_of(session, row: IssueVerification) -> IntakeItem | None:
    link = session.scalar(select(ExternalLink).where(
        ExternalLink.project_id == row.project_id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")), ExternalLink.external_id == row.issue_external_id,
    ).order_by(ExternalLink.created_at.desc()))
    return session.get(IntakeItem, link.intake_id) if link is not None else None


def _assignee_of(session, row: IssueVerification, issue: GitLabIssueSnapshot | None) -> str | None:
    for external in ((issue.assignee_external_ids or []) if issue is not None else []):
        member_id = session.scalar(select(WorkforceProjectMembership.member_id).where(
            WorkforceProjectMembership.project_id == row.project_id, WorkforceProjectMembership.gitlab_user_external_id == str(external),
        ))
        if member_id:
            return str(member_id)
    return None


def po_final_blockers(session, row: IssueVerification, actor_id: str | None, check: dict | None = None) -> list[str]:
    """Why a Project Owner's "done" on this row would still go to the CTO; empty means the Owner's word is final.

    Codes: POLICY (the project keeps the CTO on every acceptance), HARD (flagged by the CTO), P0, EVIDENCE (the
    project's evidence rule is not met), SELF (the Owner did or reported the work), REJECTED_BEFORE (someone already
    said "not done" once), NOT_OWNER (the person is not this project's Owner)."""
    reasons: list[str] = []
    project_id = str(row.project_id)
    if acceptance_policy_of(session, project_id) != POLICY_PO_FINAL:
        reasons.append("POLICY")
    intake = _intake_of(session, row)
    if intake is not None and intake.needs_cto_acceptance:
        reasons.append("HARD")
    issue = _snapshot(session, project_id, row.issue_external_id)
    priority = (intake.approved_priority if intake is not None and intake.approved_priority else None) or _priority_of(session, row)
    if priority in HARD_PRIORITIES:
        reasons.append("P0")
    if check is None:
        check = ev.assess(planning_service._done_evidence_of(session, project_id), evidence_summary(issue.evidence if issue else None),
                          ev.links_for(session, project_id, row.issue_external_id))
    if check["status"] != "OK":
        reasons.append("EVIDENCE")
    project = session.get(Project, project_id)
    user = session.get(User, actor_id) if actor_id else None
    member_id = str(user.member_id) if user is not None and user.member_id else None
    if actor_id is not None and (project is None or not project.owner_member_id or member_id != str(project.owner_member_id)):
        reasons.append("NOT_OWNER")
    workers = {value for value in (str(row.member_id) if row.member_id else None, _assignee_of(session, row, issue)) if value}
    if member_id and member_id in workers:
        reasons.append("SELF")
    rejected = session.scalar(select(IssueVerification.id).where(
        IssueVerification.project_id == row.project_id, IssueVerification.issue_external_id == row.issue_external_id,
        or_(IssueVerification.decision == "REJECTED", IssueVerification.po_decision == "REJECTED"),
    ).limit(1))
    if rejected is None and intake is not None:
        rejected = session.scalar(select(IntakeWorkLog.id).where(
            IntakeWorkLog.intake_id == intake.id, IntakeWorkLog.review_decision == "RETURNED",
        ).limit(1))
    if rejected is not None:
        reasons.append("REJECTED_BEFORE")
    return reasons


def sample(day: date | None = None, extra: int = 0) -> int:
    """Put up to five pending acceptances into the CTO's sample for the day (more when the CTO asks for more)."""
    day = day or _today()
    with get_session() as session:
        picked_today = session.scalar(select(IssueVerification.id).where(IssueVerification.picked_on == day).limit(1)) is not None
        already = len(session.scalars(select(IssueVerification.id).where(IssueVerification.picked_on == day)).all())
        room = (SAMPLE_PER_DAY - already if not extra else 0) + extra
        if room <= 0:
            return 0
        pending = session.scalars(select(IssueVerification).where(
            IssueVerification.decision == "PENDING", IssueVerification.picked_on.is_(None),
        )).all()
        if not pending:
            return 0
        last_project: dict[str, datetime] = {}
        last_member: dict[str, datetime] = {}
        for row in session.scalars(select(IssueVerification).where(IssueVerification.decided_at.is_not(None))).all():
            stamp = _utc(row.decided_at)
            last_project[str(row.project_id)] = max(last_project.get(str(row.project_id), stamp), stamp)
            if row.member_id:
                last_member[str(row.member_id)] = max(last_member.get(str(row.member_id), stamp), stamp)
        never = datetime(1970, 1, 1, tzinfo=timezone.utc)

        def key(row: IssueVerification) -> tuple:
            priority = _priority_of(session, row)
            return (
                0 if priority in ("P0", "P1") else 1,
                0 if row.evidence_level < LEVEL_TRACED else 1,
                last_project.get(str(row.project_id), never),
                last_member.get(str(row.member_id), never) if row.member_id else never,
                _utc(row.created_at),
            )

        chosen = sorted(pending, key=key)[:room]
        for row in chosen:
            row.picked_on = day
        session.commit()
        return len(chosen)


def _dict(session, row: IssueVerification, names: dict[str, str], projects: dict[str, str], users: dict[str, str]) -> dict[str, object]:
    issue = _snapshot(session, str(row.project_id), row.issue_external_id)
    rule = planning_service._done_evidence_of(session, str(row.project_id))
    intake = _intake_of(session, row)
    acceptance = [str(item) for item in ((intake.normalized_details or {}).get("acceptance") or []) if str(item).strip()] if intake else []
    accepted = row.decision == "ACCEPTED"
    auto = evidence_summary(issue.evidence if issue is not None else None)
    links = ev.links_for(session, str(row.project_id), row.issue_external_id)
    check = ev.assess(rule, auto, links)
    # The CTO's word is the top of the ladder whatever the tracker says; the tracker catches up when the write lands.
    level = LEVEL_ACCEPTED if accepted else (done_level(issue.state, issue.evidence, rule) if issue is not None else row.evidence_level)
    item = session.get(ReportItem, row.report_item_id) if row.report_item_id else None
    assignee = _assignee_of(session, row, issue)
    pending_for_po = row.decision == "PENDING" and row.po_decision is None
    return {
        "id": str(row.id), "source": row.source or "CLOSED", "project_id": str(row.project_id), "project_name": projects.get(str(row.project_id)),
        "issue_external_id": row.issue_external_id, "title": issue.title if issue is not None else (item.title if item else f"Issue #{row.issue_external_id}"),
        "web_url": issue.web_url if issue is not None else None, "state": issue.state if issue is not None else None,
        "closed_at": issue.closed_at if issue is not None else None,
        "assignee_member_id": str(assignee) if assignee else None, "assignee_name": names.get(str(assignee)) if assignee else None,
        "reporter_member_id": str(row.member_id) if row.member_id else None, "reporter_name": names.get(str(row.member_id)) if row.member_id else None,
        "reported_on": row.reported_on, "reported_hours": float(item.worked_hours) if item is not None and item.worked_hours is not None else None,
        "report_item_title": item.title if item else None,
        "priority": _priority_of(session, row), "level": level, "level_name": LEVEL_NAMES.get(level, str(level)), "done_evidence": rule,
        "evidence": auto, "evidence_fetched_at": issue.evidence_fetched_at if issue is not None else None,
        "evidence_links": links, "evidence_check": check, "evidence_missing_reason": row.evidence_missing_reason,
        "intake_id": str(intake.id) if intake else None, "intake_public_id": intake.public_id if intake else None, "acceptance": acceptance[:12],
        "picked_on": row.picked_on, "decision": row.decision, "reason": row.reason, "decided_at": row.decided_at,
        "decided_by_name": users.get(str(row.decided_by)) if row.decided_by else None,
        "po_decision": row.po_decision, "po_reason": row.po_reason, "po_decided_at": row.po_decided_at,
        "po_decided_by_name": users.get(str(row.po_decided_by)) if row.po_decided_by else None,
        "final_by": row.final_by or ("CTO" if accepted or row.decision == "REJECTED" else None),
        "acceptance_policy": acceptance_policy_of(session, str(row.project_id)),
        "needs_cto_acceptance": bool(intake.needs_cto_acceptance) if intake is not None else False,
        # Why a Project Owner's "done" would still wait for the CTO (actor-independent reasons only).
        "po_final_blockers": po_final_blockers(session, row, None, check) if pending_for_po else [],
        "sync_status": row.sync_status, "sync_error": row.sync_error, "synced_at": row.synced_at, "created_at": row.created_at,
        "source_note": row.source_note,
    }


def _work_log_dict(session, row: IntakeWorkLog, users: dict[str, str], projects: dict[str, str]) -> dict[str, object]:
    item = session.get(IntakeItem, row.intake_id)
    link = session.scalar(select(ExternalLink).where(
        ExternalLink.intake_id == row.intake_id,
        ExternalLink.target_system.in_(("GITLAB", "GITHUB")),
    ).order_by(ExternalLink.created_at.desc()))
    accepted = None
    if link is not None:
        accepted = session.scalar(select(IssueVerification).where(
            IssueVerification.project_id == link.project_id,
            IssueVerification.issue_external_id == link.external_id,
            IssueVerification.decision == "ACCEPTED",
        ).order_by(IssueVerification.decided_at.desc()))
    actor = users.get(str(row.actor_id)) if row.actor_id else None
    return {
        "id": str(row.id), "intake_id": str(row.intake_id),
        "intake_public_id": item.public_id if item is not None else str(row.intake_id),
        "project_id": str(row.project_id), "project_name": projects.get(str(row.project_id)),
        "title": (item.normalized_title if item is not None else None) or row.summary,
        "summary": row.summary, "issue_external_id": link.external_id if link is not None else None,
        "web_url": link.url if link is not None else None,
        "executor": row.agent_name or actor or "Không rõ", "details": row.details or {},
        "review_decision": row.review_decision, "review_note": row.review_note,
        "reviewed_by_name": users.get(str(row.reviewed_by)) if row.reviewed_by else None,
        "reviewed_at": row.reviewed_at, "accepted_at": accepted.decided_at if accepted is not None else None,
        "created_at": row.created_at,
    }


def queue(allowed_project_ids: frozenset[str] | None, *, is_cto: bool, project_id: str | None = None) -> dict[str, object]:
    """What waits for acceptance. The CTO gets today's sample apart from the rest; a Project Owner gets their projects."""
    today = _today()
    if is_cto:
        sample(today)
    with get_session() as session:
        query = select(IssueVerification)
        if allowed_project_ids is not None:
            query = query.where(IssueVerification.project_id.in_(sorted(allowed_project_ids)))
        if project_id:
            query = query.where(IssueVerification.project_id == project_id)
        rows = session.scalars(query.order_by(IssueVerification.created_at.desc())).all()
        names = {str(member.id): member.display_name for member in session.scalars(select(WorkforceMember)).all()}
        projects = {str(project.id): project.name for project in session.scalars(select(Project)).all()}
        users = {str(user.id): (user.display_name or user.auth_subject) for user in session.scalars(select(User)).all()}
        since = datetime.now(timezone.utc) - DECIDED_WINDOW
        pending = [row for row in rows if row.decision == "PENDING"]
        if not is_cto:
            pending = [row for row in pending if row.po_decision is None]
        decided = [row for row in rows if row.decision != "PENDING" and _utc(row.decided_at) and _utc(row.decided_at) >= since]
        if not is_cto:
            decided = [row for row in rows if row.decision != "PENDING" or row.po_decision is not None][:30]
        today_rows = [row for row in pending if row.picked_on == today] if is_cto else pending
        rest = [row for row in pending if row.picked_on != today] if is_cto else []
        work_logs_pending: list[IntakeWorkLog] = []
        work_logs_decided: list[IntakeWorkLog] = []
        if is_cto:
            work_log_query = select(IntakeWorkLog).where(or_(
                IntakeWorkLog.review_decision == "PENDING",
                IntakeWorkLog.reviewed_at >= since,
            ))
            if allowed_project_ids is not None:
                work_log_query = work_log_query.where(IntakeWorkLog.project_id.in_(sorted(allowed_project_ids)))
            if project_id:
                work_log_query = work_log_query.where(IntakeWorkLog.project_id == project_id)
            work_logs = session.scalars(work_log_query.order_by(IntakeWorkLog.created_at.desc())).all()
            work_logs_pending = [row for row in work_logs if row.review_decision == "PENDING"]
            work_logs_decided = [
                row for row in work_logs
                if row.review_decision != "PENDING" and _utc(row.reviewed_at) and _utc(row.reviewed_at) >= since
            ][:30]
        order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
        as_dicts = lambda items: sorted((_dict(session, row, names, projects, users) for row in items), key=lambda item: (order.get(str(item["priority"]), 9), int(item["level"]), str(item["created_at"])))
        return {
            "today": today_rows and as_dicts(today_rows) or [], "more": as_dicts(rest), "decided": [_dict(session, row, names, projects, users) for row in decided],
            "pending_total": len(pending), "sample_size": SAMPLE_PER_DAY, "plan_date": today,
            "work_log_pending_total": len(work_logs_pending),
            "work_logs_pending": [_work_log_dict(session, row, users, projects) for row in work_logs_pending],
            "work_logs_decided": [_work_log_dict(session, row, users, projects) for row in work_logs_decided],
        }


class AcceptanceError(ValueError):
    pass


def accept_intake_work(session, intake_id: str, *, actor_id: str, note: str | None, now: datetime) -> tuple[str | None, bool]:
    """Make a CTO-confirmed work log the official acceptance of its current delivery Issue.

    The caller owns the transaction so the work-log review and the acceptance cannot drift apart.  The tracker
    write is queued only after that transaction commits.  Repeating the operation is harmless: an already accepted
    Issue remains the one official result and is not queued twice.
    """
    item = session.get(IntakeItem, intake_id)
    if item is None:
        raise KeyError(intake_id)
    linked = session.execute(
        select(ExternalLink, ApprovalSnapshot.created_at, ApprovalSnapshot.invalidated_at)
        .join(SyncJob, SyncJob.id == ExternalLink.sync_job_id)
        .join(ApprovalSnapshot, ApprovalSnapshot.id == SyncJob.approval_snapshot_id)
        .where(ExternalLink.intake_id == item.id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")))
        .order_by(ExternalLink.created_at.desc())
    ).all()
    reopened_at = latest_reopen_at(session, [str(item.id)]).get(str(item.id))
    link = next((row[0] for row in linked if not taken_back(row[1], row[2], reopened_at)), None)
    if link is None:
        return None, False

    row = session.scalar(select(IssueVerification).where(
        IssueVerification.project_id == link.project_id,
        IssueVerification.issue_external_id == link.external_id,
    ).order_by(IssueVerification.created_at.desc()))
    if row is not None and row.decision == "ACCEPTED":
        return str(row.id), False
    snapshot = _snapshot(session, str(link.project_id), link.external_id)
    if row is None or row.decision != "PENDING":
        rule = planning_service._done_evidence_of(session, str(link.project_id))
        row = IssueVerification(
            id=str(uuid4()), project_id=link.project_id, issue_external_id=link.external_id,
            planning_run_id=None,
            evidence_level=done_level(snapshot.state, snapshot.evidence, rule) if snapshot is not None else 0,
            decision="PENDING", source="WORK_LOG", created_at=now,
        )
        session.add(row)
    row.decision, row.decided_by, row.decided_at, row.final_by = "ACCEPTED", actor_id, now, "CTO"
    row.reason = " ".join((note or "").split())[:1000] or None
    row.source_note = row.reason
    row.picked_on = now.astimezone(LOCAL_TZ).date()
    row.sync_status, row.sync_error = "PENDING", None
    # A work-log confirmation is direct CTO verification.  Preserve that explicit reason when automated evidence is
    # incomplete instead of making the same confirmation happen a second time in the acceptance queue.
    check = ev.assess(
        planning_service._done_evidence_of(session, str(link.project_id)),
        evidence_summary(snapshot.evidence if snapshot else None),
        ev.links_for(session, str(link.project_id), link.external_id),
    )
    if check["status"] != "OK" and not row.evidence_missing_reason:
        row.evidence_missing_reason = row.reason or "CTO đã kiểm trực tiếp và xác nhận đã triển khai"
    session.add(AuditEvent(
        id=str(uuid4()), project_id=link.project_id, actor_type="USER", actor_id=actor_id,
        event_type="planning.issue.verified", entity_type="issue_verification", entity_id=row.id,
        details={"issue": row.issue_external_id, "decision": "ACCEPTED", "level_at_pick": row.evidence_level,
                 "reason": row.reason, "source": "WORK_LOG", "intake_id": str(item.id)},
        created_at=now,
    ))
    return str(row.id), True


def queue_acceptance(verification_id: str) -> bool:
    """Queue the tracker close after an acceptance transaction has committed."""
    try:
        celery_app.send_task(ACCEPT_TASK, args=[verification_id], queue="integration.sync")
        return True
    except Exception:  # noqa: BLE001 - the decision stands even while the broker is unavailable
        with get_session() as session:
            row = session.get(IssueVerification, verification_id)
            if row is not None and row.sync_status == "PENDING":
                row.sync_status, row.sync_error = "QUEUE_FAILED", "Không gửi được lệnh ghi lên tracker"
                session.commit()
        return False


def decide(verification_id: str, *, decision: str, reason: str | None, actor_id: str, role: str, allowed_project_ids: frozenset[str] | None,
           evidence_missing_reason: str | None = None) -> dict[str, object]:
    """A person looked at the work: done, or not done (with a reason). The CTO's word closes the Issue; the Project
    Owner's word closes it too when the project's policy allows and nothing marks the work as risky (ADR-0082),
    otherwise it is recorded beside the CTO's. "Not done" from either sends the work back to the open plan as rework.
    "Done" with nothing behind it needs a line that says why (FR-PLAN-36)."""
    now = datetime.now(timezone.utc)
    reason = (reason or "").strip() or None
    missing_reason = " ".join((evidence_missing_reason or "").split())[:500] or None
    if decision == "REJECTED" and not reason:
        raise AcceptanceError("REASON_REQUIRED")
    with get_session() as session:
        row = session.get(IssueVerification, verification_id)
        if row is None or (allowed_project_ids is not None and str(row.project_id) not in allowed_project_ids):
            raise KeyError("verification")
        if (row.decision != "PENDING") if role == "CTO" else (row.po_decision is not None or row.decision != "PENDING"):
            raise AcceptanceError("VERIFICATION_DECIDED")
        check = None
        if decision == "ACCEPTED":
            snapshot = _snapshot(session, str(row.project_id), row.issue_external_id)
            check = ev.assess(planning_service._done_evidence_of(session, str(row.project_id)), evidence_summary(snapshot.evidence if snapshot else None),
                              ev.links_for(session, str(row.project_id), row.issue_external_id))
            if check["status"] != "OK" and not missing_reason:
                raise AcceptanceError("EVIDENCE_REASON_REQUIRED")
            if check["status"] != "OK" and not row.evidence_missing_reason:
                row.evidence_missing_reason = missing_reason
        po_final, blockers = False, []
        if role == "CTO":
            if row.decision != "PENDING":
                raise AcceptanceError("VERIFICATION_DECIDED")
            row.decision, row.reason, row.decided_by, row.decided_at = decision, reason, actor_id, now
            row.final_by = "CTO"
            if row.picked_on is None:
                row.picked_on = _today()
        else:
            if row.po_decision is not None or row.decision != "PENDING":
                raise AcceptanceError("VERIFICATION_DECIDED")
            blockers = po_final_blockers(session, row, actor_id, check) if decision == "ACCEPTED" else []
            row.po_decision, row.po_reason, row.po_decided_by, row.po_decided_at = decision, reason, actor_id, now
            po_final = decision == "ACCEPTED" and not blockers
            if po_final:
                # ADR-0082: low-risk work the Owner accepts is accepted; the CTO is not asked again.
                row.decision, row.reason, row.decided_by, row.decided_at, row.final_by = "ACCEPTED", reason, actor_id, now, "PO"
        issue = _snapshot(session, str(row.project_id), row.issue_external_id)
        if decision == "REJECTED":
            _send_back(session, row, issue, reason or "", actor_id, now)
        closes = decision == "ACCEPTED" and (role == "CTO" or po_final)
        if closes:
            row.sync_status, row.sync_error = "PENDING", None
        details = {"issue": row.issue_external_id, "decision": decision, "level_at_pick": row.evidence_level, "reason": reason, "source": row.source}
        if role != "CTO" and decision == "ACCEPTED":
            details.update({"final": po_final, "blockers": blockers})
        session.add(AuditEvent(
            id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id,
            event_type="planning.issue.verified" if role == "CTO" else "planning.issue.po-verified", entity_type="issue_verification", entity_id=row.id,
            details=details, created_at=now,
        ))
        session.commit()
        row_id = str(row.id)
        queued = None
        if closes:
            queued = queue_acceptance(row_id)
            session.expire(row)
        names = {str(member.id): member.display_name for member in session.scalars(select(WorkforceMember)).all()}
        projects = {str(project.id): project.name for project in session.scalars(select(Project)).all()}
        users = {str(user.id): (user.display_name or user.auth_subject) for user in session.scalars(select(User)).all()}
        result = _dict(session, row, names, projects, users)
        result["sync_queued"] = queued
        result["po_final_blockers"] = blockers
        return result


def add_evidence(verification_id: str, links: list[dict], *, actor_id: str, allowed_project_ids: frozenset[str] | None) -> dict[str, object]:
    """The acceptor pastes what the worker did not: a commit, a merge request, a link (FR-PLAN-36)."""
    with get_session() as session:
        row = session.get(IssueVerification, verification_id)
        if row is None or (allowed_project_ids is not None and str(row.project_id) not in allowed_project_ids):
            raise KeyError("verification")
        issue = _snapshot(session, str(row.project_id), row.issue_external_id)
        added = ev.add_links(session, str(row.project_id), row.issue_external_id, links, source="ACCEPTOR", actor_id=actor_id,
                             issue_web_url=issue.web_url if issue is not None else None)
        session.add(AuditEvent(
            id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id, event_type="planning.issue.evidence-added",
            entity_type="issue_verification", entity_id=row.id, details={"issue": row.issue_external_id, "added": added}, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
        names = {str(member.id): member.display_name for member in session.scalars(select(WorkforceMember)).all()}
        projects = {str(project.id): project.name for project in session.scalars(select(Project)).all()}
        users = {str(user.id): (user.display_name or user.auth_subject) for user in session.scalars(select(User)).all()}
        return _dict(session, row, names, projects, users)


def _send_back(session, row: IssueVerification, issue: GitLabIssueSnapshot | None, reason: str, actor_id: str, now: datetime) -> None:
    """Rework: the Issue goes to the waiting list of the project's open plan (today's or a later one), with a warning."""
    run = None
    for candidate in session.scalars(select(PlanningRun).where(
        PlanningRun.plan_date >= _today(), PlanningRun.status.in_(sorted(MUTABLE_RUN_STATES)),
    ).order_by(PlanningRun.plan_date, PlanningRun.revision.desc())).all():
        if str(row.project_id) in [str(value) for value in (candidate.project_scope or [])]:
            run = candidate
            break
    if run is None:
        return
    key_hash = hashlib.sha256(f"verification:{row.id}".encode("utf-8")).hexdigest()
    title = issue.title if issue is not None else f"Issue #{row.issue_external_id}"
    if not session.scalar(select(PlanningCandidate.id).where(PlanningCandidate.idempotency_key_hash == key_hash)):
        session.add(PlanningCandidate(
            id=str(uuid4()), planning_run_id=run.id, project_id=row.project_id, member_id=row.member_id,
            intake_id=None, assignment_id=None, source_type="VERIFICATION", source_reference=f"Issue #{row.issue_external_id}",
            gitlab_issue_external_id=row.issue_external_id,
            title=f"Làm lại: {title}"[:255], summary=f"Nghiệm thu ngày {now.astimezone(LOCAL_TZ).date().isoformat()}: chưa xong. {reason}".strip(),
            status="READY", proposed_priority=planning_service._priority_from_labels(list(issue.labels or [])) if issue is not None else "P2",
            requested_hours=None, target_slot=None, idempotency_key_hash=key_hash, request_hash=None,
            created_by=actor_id, created_at=now, updated_at=now,
        ))
    session.add(PlanningWarning(
        id=str(uuid4()), planning_run_id=run.id, assignment_id=None, member_id=row.member_id, project_id=row.project_id,
        code="ISSUE_NOT_DONE_AFTER_CLOSE", severity="WARNING",
        source_values={"issue": row.issue_external_id, "reason": reason},
        message=f"Issue #{row.issue_external_id} was reported done but found not done: {reason}", created_at=now,
    ))
    run.status = "REVIEW_REQUIRED"
    run.version += 1
    run.updated_at = now


def sync_target(verification_id: str) -> dict[str, object] | None:
    """What the worker needs to write the acceptance on the tracker: system, where, which Issue, what to say."""
    with get_session() as session:
        row = session.get(IssueVerification, verification_id)
        if row is None or row.decision != "ACCEPTED" or row.sync_status not in ("PENDING", "QUEUE_FAILED", "RETRY"):
            return None
        mapping = session.scalar(select(ProjectIntegration).where(
            ProjectIntegration.project_id == row.project_id, ProjectIntegration.enabled.is_(True),
            ProjectIntegration.system.in_(("GITLAB", "GITHUB")), ProjectIntegration.project_external_id.is_not(None),
        ))
        if mapping is None:
            row.sync_status, row.sync_error, row.synced_at = "SKIPPED", "Dự án không có tracker đang bật", datetime.now(timezone.utc)
            session.commit()
            return None
        if is_moved(row.issue_external_id):
            # An Issue of the GitLab project the project left (FR-PRJ-13): accepted here, never written to GitHub.
            row.sync_status, row.sync_error, row.synced_at = "SKIPPED", "Issue thuộc GitLab cũ, đã ngừng đồng bộ khi chuyển sang GitHub", datetime.now(timezone.utc)
            session.commit()
            return None
        issue = _snapshot(session, str(row.project_id), row.issue_external_id)
        decided = _utc(row.decided_at) or datetime.now(timezone.utc)
        who = "Project Owner" if row.final_by == "PO" else "CTO"
        note = f"Intake: {who} đã nghiệm thu ngày {decided.astimezone(LOCAL_TZ):%d/%m/%Y}: đúng là xong."
        if row.reason:
            note += f" {row.reason}"
        if row.source_note:
            # What was written when the work was set aside as done already (FR-PLAN-34): the Issue tells the same story.
            note += f"\nĐã làm xong ngoài kế hoạch: {row.source_note}"
        return {
            "verification_id": str(row.id), "system": mapping.system, "target": str(mapping.project_external_id),
            "token_ref": str(mapping.credential_ref or ""), "issue": row.issue_external_id, "note": note,
            "close": issue is None or issue.state != "closed",
        }


def record_sync(verification_id: str, status: str, error: str | None = None) -> None:
    with get_session() as session:
        row = session.get(IssueVerification, verification_id)
        if row is None:
            return
        row.sync_status, row.sync_error, row.synced_at = status, error, datetime.now(timezone.utc)
        if status == "DONE":
            for snapshot in session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == row.project_id, GitLabIssueSnapshot.issue_external_id == row.issue_external_id, GitLabIssueSnapshot.is_current.is_(True),
            )).all():
                if snapshot.state != "closed":
                    snapshot.state, snapshot.closed_at = "closed", datetime.now(timezone.utc)
        session.commit()
