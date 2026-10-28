"""The morning picture: one row per project, and whether the data behind it is complete enough to review (FR-PLAN-23).

Each row also says who the waiting approvals belong to (CTO or Project Owner, FR-APR-14), how much waiting has gone
on too long (FR-PLAN-27), and, for the CTO alone, how many minutes they spent clicking today (FR-UI-15).

Everything here is read-only and rule-based. "Enough to review" means: everyone who worked yesterday sent a
report the machine could read (and the CTO confirmed when AI read it), the Issue list was refreshed today, the
meetings of yesterday have their note and their action items became requests, and no request is stuck with AI.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from app.db import get_session
from app.modules.planning.personal import reserved_hours
from app.models import (
    AuditEvent, DailyCapacity, EmailMessage, GitLabIssueSnapshot, IntakeItem, IntakeWorkLog, IssueVerification, Meeting,
    MeetingNoteItem, PlanningAssignment, PlanningCandidate, PlanningRun, PlanningWarning, Project, ReportItem, User,
    WorkforceMember, WorkforceProjectMembership,
)
from app.modules.intake.routing import OVERDUE, approval_owner, projects_with_owner
from app.modules.meetings.service import INTAKE_KINDS
from app.modules.planning.service import REPORT_CARRY_OVER_STATUSES, _canonical_hash, planning_service
from app.modules.projects.context import project_context_service
from app.modules.reports.service import usable_for_planning

LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SYNC_ROUTES = ("GITLAB", "GITHUB")
WAITING = ("PENDING_TRIAGE", "READY")
STUCK_AFTER = timedelta(minutes=15)
SNAPSHOT_DUE = time(6, 0)   # the Issue list is refreshed at 06:45; before 06:00 yesterday's is the latest there can be
SESSION_GAP = timedelta(minutes=10)   # two CTO actions closer than this belong to one sitting
LONE_ACTION_MINUTES = 2               # a sitting with one action still took a moment


def _hours_on(session, member: WorkforceMember, day: date) -> float:
    """The person's free hours for the day: capacity, minus what their own tasks take (FR-PER-02)."""
    capacity = session.scalar(select(DailyCapacity).where(DailyCapacity.member_id == member.id, DailyCapacity.work_date == day))
    hours = float(capacity.available_hours) if capacity is not None else (float(member.default_weekday_hours) if day.weekday() < 5 else 0.0)
    return max(hours - reserved_hours(session, str(member.id), day), 0.0)


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    return start, start + timedelta(days=1)


def day_overview(plan_date: date, allowed_project_ids: frozenset[str] | None, cto_user_id: str | None = None) -> dict[str, object]:
    """The board. `cto_user_id` is set only when the CTO asks; it switches on the time meter."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        query = select(Project).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE")
        if allowed_project_ids is not None:
            query = query.where(Project.id.in_(sorted(allowed_project_ids)))
        projects = session.scalars(query).all()
        owned = projects_with_owner(session)
        rows = [_project_row(session, project, plan_date, now, owned) for project in projects]
        rows.sort(key=lambda row: (not row["p0"], -int(row["attention"]), str(row["name"]).casefold()))
        snapshot_at = max((row["gitlab"]["snapshot_at"] for row in rows if row["gitlab"]["snapshot_at"]), default=None)
        return {
            "plan_date": plan_date, "generated_at": now, "gitlab_snapshot_at": snapshot_at,
            "missing_projects": sum(1 for row in rows if row["readiness"]["state"] == "MISSING"),
            "overdue_total": sum(sum(int(value) for value in row["overdue"].values()) for row in rows),
            "projects": rows,
            "cto_time": _cto_time(session, cto_user_id, now) if cto_user_id else None,
        }


def _sittings_minutes(stamps: list[datetime]) -> int:
    """Minutes across sittings: actions closer than SESSION_GAP merge; a lone action counts LONE_ACTION_MINUTES."""
    total = 0.0
    start = last = None
    for stamp in sorted(stamps):
        if last is not None and stamp - last <= SESSION_GAP:
            last = stamp
            continue
        if start is not None:
            total += max((last - start).total_seconds() / 60, LONE_ACTION_MINUTES)
        start = last = stamp
    if start is not None:
        total += max((last - start).total_seconds() / 60, LONE_ACTION_MINUTES)
    return int(round(total))


def _cto_time(session, user_id: str, now: datetime) -> dict[str, object]:
    """How long the CTO spent acting in the app: today and the average of the last seven days, from the audit trail.

    It measures clicks that left a trace, not reading; the board says so. Only the CTO sees it (ADR-0052)."""
    today_local = now.astimezone(LOCAL_TZ).date()
    week_start, _ = _day_bounds(today_local - timedelta(days=6))
    _, today_end = _day_bounds(today_local)
    rows = session.execute(select(AuditEvent.created_at).where(
        AuditEvent.actor_id == str(user_id), AuditEvent.created_at >= week_start, AuditEvent.created_at < today_end,
    )).all()
    by_day: dict[date, list[datetime]] = {}
    for (stamp,) in rows:
        aware = stamp if stamp.tzinfo else stamp.replace(tzinfo=timezone.utc)
        by_day.setdefault(aware.astimezone(LOCAL_TZ).date(), []).append(aware)
    minutes_by_day = {day: _sittings_minutes(stamps) for day, stamps in by_day.items()}
    today_minutes = minutes_by_day.get(today_local, 0)
    week = [minutes_by_day.get(today_local - timedelta(days=offset), 0) for offset in range(7)]
    return {
        "today_minutes": today_minutes, "actions_today": len(by_day.get(today_local, [])),
        "avg7_minutes": int(round(sum(week) / 7)), "days": [{"date": today_local - timedelta(days=offset), "minutes": week[offset]} for offset in range(7)],
    }


def _project_row(session, project: Project, plan_date: date, now: datetime, owned: set[str] | None = None) -> dict[str, object]:
    pid = str(project.id)
    has_owner = pid in (owned if owned is not None else projects_with_owner(session))
    members = session.scalars(
        select(WorkforceMember).join(WorkforceProjectMembership, WorkforceProjectMembership.member_id == WorkforceMember.id)
        .where(WorkforceProjectMembership.project_id == project.id, WorkforceProjectMembership.active.is_(True), WorkforceMember.status == "ACTIVE")
    ).all()

    # --- yesterday's reports, one per person who had hours on their last working day
    expected: list[tuple[WorkforceMember, date]] = []
    for member in members:
        expected_date = planning_service._expected_report_date(session, member, plan_date)
        if expected_date is not None:
            expected.append((member, expected_date))
    report_date = max((day for _, day in expected), default=None)
    missing_names: list[str] = []
    unmapped_names: list[str] = []
    received = late = malformed = unreviewed = 0
    report_ids: list[str] = []
    usable_ids: list[str] = []
    for member, expected_date in expected:
        if not member.email_reference:
            unmapped_names.append(member.display_name)
            continue
        report = session.scalar(select(EmailMessage).where(
            EmailMessage.member_id == member.id, EmailMessage.report_date == expected_date, EmailMessage.is_current.is_(True),
        ).order_by(EmailMessage.revision.desc()))
        if report is None:
            missing_names.append(member.display_name)
            continue
        received += 1
        report_ids.append(str(report.id))
        late += int(bool(report.is_late))
        if not usable_for_planning(report):
            unreviewed += 1
        else:
            usable_ids.append(str(report.id))
        if report.status == "MALFORMED":
            malformed += 1
    items_without_issue = 0
    if report_ids:
        items_without_issue = session.scalar(select(func.count()).select_from(ReportItem).where(
            ReportItem.email_message_id.in_(report_ids), ReportItem.is_current.is_(True),
            ReportItem.work_status.in_(("DONE", "IN_PROGRESS", "PENDING_REVIEW")), ReportItem.gitlab_issue_external_id.is_(None),
            ReportItem.no_issue_reason.is_(None),
        )) or 0

    # Work the latest reports say is not finished: what tomorrow's plan will have to carry over.
    carry_over = 0
    if usable_ids:
        carry_over = session.scalar(select(func.count()).select_from(ReportItem).where(
            ReportItem.email_message_id.in_(usable_ids), ReportItem.is_current.is_(True),
            ReportItem.work_status.in_(sorted(REPORT_CARRY_OVER_STATUSES)),
        )) or 0

    # --- requests
    pending_rows = session.execute(select(IntakeItem.suggested_priority, IntakeItem.updated_at).where(
        IntakeItem.project_id == project.id, IntakeItem.status == "PENDING_APPROVAL",
    )).all()
    pending = len(pending_rows)
    urgent = sum(1 for (priority, _) in pending_rows if priority in ("P0", "P1"))
    pending_p0 = any(priority == "P0" for (priority, _) in pending_rows)
    routed = [approval_owner(project_has_owner=has_owner, priority=priority, waiting_since=since, now=now) for priority, since in pending_rows]
    approvals_cto = sum(1 for who, _ in routed if who == "CTO")
    approvals_overdue = sum(1 for _, late_ in routed if late_)
    unsynced = session.scalar(select(func.count()).select_from(IntakeItem).where(
        IntakeItem.project_id == project.id, IntakeItem.status == "APPROVED", IntakeItem.approved_route.in_(SYNC_ROUTES),
    )) or 0
    stuck = session.scalar(select(func.count()).select_from(IntakeItem).where(
        IntakeItem.project_id == project.id,
        ((IntakeItem.status == "PROCESSING") & (IntakeItem.updated_at <= now - STUCK_AFTER)) | (IntakeItem.status == "PROCESSING_FAILED"),
    )) or 0

    # --- meetings of yesterday
    yesterday_start, yesterday_end = _day_bounds(plan_date - timedelta(days=1))
    meetings = session.scalars(select(Meeting).where(
        Meeting.project_id == project.id, Meeting.kind == "MEETING", Meeting.started_at >= yesterday_start, Meeting.started_at < yesterday_end,
    )).all()
    notes_pending = sum(1 for meeting in meetings if meeting.status == "FINISHED" and meeting.note_status not in ("DONE", "SKIPPED"))
    items_unconverted = 0
    if meetings:
        items_unconverted = session.scalar(select(func.count()).select_from(MeetingNoteItem).where(
            MeetingNoteItem.meeting_id.in_([str(meeting.id) for meeting in meetings]), MeetingNoteItem.kind.in_(sorted(INTAKE_KINDS)),
            MeetingNoteItem.intake_id.is_(None),
        )) or 0

    # --- the Issue list
    snapshot_at = session.scalar(select(func.max(GitLabIssueSnapshot.fetched_at)).where(
        GitLabIssueSnapshot.project_id == project.id, GitLabIssueSnapshot.is_current.is_(True),
    ))
    due = datetime.combine(plan_date, SNAPSHOT_DUE, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    snapshot_fresh = snapshot_at is not None and (snapshot_at if snapshot_at.tzinfo else snapshot_at.replace(tzinfo=timezone.utc)) >= due
    open_issues = session.scalars(select(GitLabIssueSnapshot.labels).where(
        GitLabIssueSnapshot.project_id == project.id, GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.state == "opened",
    )).all()
    open_p0 = sum(1 for labels in open_issues if "priority:p0" in [str(label).lower() for label in (labels or [])])
    p0_open_overdue = 0
    if open_p0:
        for external_id, labels in session.execute(select(GitLabIssueSnapshot.issue_external_id, GitLabIssueSnapshot.labels).where(
            GitLabIssueSnapshot.project_id == project.id, GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.state == "opened",
        )).all():
            if "priority:p0" not in [str(label).lower() for label in (labels or [])]:
                continue
            first_seen = session.scalar(select(func.min(GitLabIssueSnapshot.created_at)).where(
                GitLabIssueSnapshot.project_id == project.id, GitLabIssueSnapshot.issue_external_id == external_id,
            ))
            if first_seen is not None and (first_seen if first_seen.tzinfo else first_seen.replace(tzinfo=timezone.utc)) <= now - OVERDUE["p0_open"]:
                p0_open_overdue += 1
    has_tracker = session.scalar(select(func.count()).select_from(GitLabIssueSnapshot).where(GitLabIssueSnapshot.project_id == project.id)) or 0

    # --- the plan of the day: the project's own plan first, else the old all-projects plan that holds it
    run = session.scalar(select(PlanningRun).where(
        PlanningRun.plan_date == plan_date, PlanningRun.scope_hash == _canonical_hash([pid]), PlanningRun.status != "SUPERSEDED",
    ).order_by(PlanningRun.revision.desc()))
    scope = "PROJECT"
    if run is None:
        for candidate in session.scalars(select(PlanningRun).where(PlanningRun.plan_date == plan_date, PlanningRun.status != "SUPERSEDED")).all():
            if pid in [str(value) for value in (candidate.project_scope or [])]:
                run, scope = candidate, "ALL"
                break
    plan: dict[str, object] = {
        "run_id": None, "status": None, "scope": None, "assigned_people": 0, "assigned_hours": 0.0, "waiting": 0, "warnings": 0,
        "made_by": None, "updated_at": None,
    }
    assigned_member_ids: set[str] = set()
    waiting_overdue = 0
    if run is not None:
        assignments = session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id, PlanningAssignment.project_id == project.id)).all()
        waiting = session.scalar(select(func.count()).select_from(PlanningCandidate).where(
            PlanningCandidate.planning_run_id == run.id, PlanningCandidate.project_id == project.id, PlanningCandidate.status.in_(WAITING),
        )) or 0
        waiting_overdue = session.scalar(select(func.count()).select_from(PlanningCandidate).where(
            PlanningCandidate.planning_run_id == run.id, PlanningCandidate.project_id == project.id, PlanningCandidate.status.in_(WAITING),
            PlanningCandidate.created_at <= now - OVERDUE["waiting"],
        )) or 0
        warnings = session.scalar(select(func.count()).select_from(PlanningWarning).where(
            PlanningWarning.planning_run_id == run.id, (PlanningWarning.project_id == project.id) | (PlanningWarning.project_id.is_(None)),
        )) or 0
        assigned_member_ids = {str(row.member_id) for row in assignments}
        maker = session.get(User, run.created_by) if run.created_by else None
        plan = {
            "run_id": str(run.id), "status": run.status, "scope": scope,
            "assigned_people": len(assigned_member_ids),
            "assigned_hours": round(sum(float(row.planned_hours or 0) for row in assignments), 2),
            "waiting": int(waiting), "warnings": int(warnings),
            "made_by": (maker.display_name or maker.auth_subject) if maker else None, "updated_at": run.updated_at,
        }
    hours_by_member = {str(member.id): _hours_on(session, member, plan_date) for member in members}
    available_hours = round(sum(hours_by_member.values()), 2)
    people_today = sum(1 for value in hours_by_member.values() if value > 0)
    people_off = [member.display_name for member in members if hours_by_member[str(member.id)] <= 0]
    unassigned = [member.display_name for member in members if hours_by_member[str(member.id)] > 0 and str(member.id) not in assigned_member_ids] if run is not None else []

    # --- acceptance waiting for the CTO
    verifications_pending = session.scalar(select(func.count()).select_from(IssueVerification).where(
        IssueVerification.project_id == project.id, IssueVerification.decision == "PENDING",
    )) or 0
    work_log_pending = session.scalar(select(func.count()).select_from(IntakeWorkLog).where(
        IntakeWorkLog.project_id == project.id, IntakeWorkLog.review_decision == "PENDING",
    )) or 0
    work_log_overdue = session.scalar(select(func.count()).select_from(IntakeWorkLog).where(
        IntakeWorkLog.project_id == project.id, IntakeWorkLog.review_decision == "PENDING", IntakeWorkLog.created_at <= now - OVERDUE["work_log"],
    )) or 0

    # --- the gate
    reasons: list[str] = []
    if missing_names:
        reasons.append(f"thiếu báo cáo hôm {report_date:%d/%m}: {', '.join(missing_names)}" if report_date else f"thiếu báo cáo: {', '.join(missing_names)}")
    if unmapped_names:
        reasons.append(f"chưa gắn email báo cáo: {', '.join(unmapped_names)}")
    if unreviewed:
        reasons.append(f"{unreviewed} báo cáo AI đọc chưa được xác nhận")
    if malformed:
        reasons.append(f"{malformed} báo cáo máy không đọc được")
    if has_tracker and not snapshot_fresh:
        reasons.append("danh sách Issue chưa cập nhật hôm nay" if snapshot_at is None else f"danh sách Issue cập nhật lúc {snapshot_at.astimezone(LOCAL_TZ):%H:%M %d/%m}")
    if notes_pending:
        reasons.append(f"{notes_pending} cuộc họp hôm qua chưa có note")
    if items_unconverted:
        reasons.append(f"{items_unconverted} mục hành động trong họp hôm qua chưa thành Intake")
    if stuck:
        reasons.append(f"{stuck} yêu cầu kẹt ở bước AI")
    if not expected and not meetings:
        state = "NO_WORK"
        reasons = [reason for reason in reasons if not reason.startswith("danh sách Issue")] or ["không ai có giờ làm hôm qua"]
    else:
        state = "MISSING" if reasons else "READY"

    return {
        "id": pid, "code": project.code, "name": project.name,
        "p0": pending_p0 or open_p0 > 0,
        "readiness": {"state": state, "reasons": reasons},
        # The project's context pack as scored (FR-CTX-04): what an agent would find when it opens the repo.
        "context": project_context_service.bands([pid]).get(pid) or {"band": "MISSING", "score": 0, "missing": [], "approved": False},
        "reports": {
            "report_date": report_date, "expected": len(expected), "received": received, "missing": missing_names, "late": late,
            "malformed": malformed, "unreviewed": unreviewed, "items_without_issue": int(items_without_issue),
        },
        "approvals": {"pending": pending, "urgent": urgent, "cto": approvals_cto, "po": pending - approvals_cto, "overdue": approvals_overdue, "has_owner": has_owner},
        "overdue": {"approvals": approvals_overdue, "waiting": int(waiting_overdue), "work_log": int(work_log_overdue), "p0_open": p0_open_overdue},
        "unsynced": int(unsynced), "stuck": int(stuck),
        "meetings": {"yesterday": len(meetings), "notes_pending": notes_pending, "items_unconverted": int(items_unconverted)},
        "plan": {**plan, "available_hours": available_hours, "people_today": people_today},
        "people_off": people_off, "unassigned": unassigned, "carry_over": int(carry_over),
        "acceptance": {"verifications_pending": int(verifications_pending), "work_log_pending": int(work_log_pending)},
        "gitlab": {"snapshot_at": snapshot_at, "fresh": bool(snapshot_fresh), "open_p0": open_p0},
        "attention": pending + int(unsynced) + int(plan["waiting"]) + int(verifications_pending) + int(work_log_pending),
    }
