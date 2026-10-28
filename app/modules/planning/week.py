"""The week in numbers: what the team planned, what it reported, what was really finished, and where the process
waited (FR-PLAN-29, ADR-0053).

Three levels of "done" stay side by side on purpose: a report saying done, the Issue closed in the tracker, and the
CTO having checked it. The gap between them is the point. Everything is read-only and counts only; no request
content and no customer name leaves here, so the text version can be pasted anywhere.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select

from app.db import get_session
from app.models import (
    ApprovalAction, AuditEvent, BoardDailySnapshot, EmailMessage, ExternalLink, GitLabIssueSnapshot, IntakeItem,
    IntakeWorkLog, IssueVerification, PlanningAssignment, PlanningRun, Project, ReportItem, WorkforceMember,
    WorkforceProjectMembership,
)
from app.modules.planning.cto import cto_member_ids
from app.modules.planning.overview import LOCAL_TZ, _hours_on, _sittings_minutes

REPORTED_STATUSES = ("DONE", "IN_PROGRESS", "PENDING_REVIEW")
DECIDE_WITHIN = timedelta(hours=24)


def monday_of(day: date) -> date:
    return day - timedelta(days=day.weekday())


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _bounds(week_start: date) -> tuple[datetime, datetime]:
    start = datetime.combine(week_start, time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    return start, start + timedelta(days=7)


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def week_summary(week_start: date, allowed_project_ids: frozenset[str] | None, cto_user_id: str | None = None) -> dict[str, object]:
    week_start = monday_of(week_start)
    week_end = week_start + timedelta(days=6)
    start, end = _bounds(week_start)
    today = datetime.now(LOCAL_TZ).date()
    past_days = [week_start + timedelta(days=offset) for offset in range(7) if week_start + timedelta(days=offset) <= today]
    with get_session() as session:
        query = select(Project).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE")
        if allowed_project_ids is not None:
            query = query.where(Project.id.in_(sorted(allowed_project_ids)))
        projects = session.scalars(query.order_by(Project.name)).all()
        project_ids = [str(project.id) for project in projects]
        names = {str(project.id): project.name for project in projects}

        memberships = session.execute(
            select(WorkforceProjectMembership.project_id, WorkforceMember)
            .join(WorkforceMember, WorkforceMember.id == WorkforceProjectMembership.member_id)
            .where(WorkforceProjectMembership.project_id.in_(project_ids), WorkforceProjectMembership.active.is_(True), WorkforceMember.status == "ACTIVE")
        ).all()
        members_by_project: dict[str, list[WorkforceMember]] = {pid: [] for pid in project_ids}
        members: dict[str, WorkforceMember] = {}
        for project_id, member in memberships:
            members_by_project[str(project_id)].append(member)
            members[str(member.id)] = member

        # --- hours each person had on the days of the week that have passed, and one report expected per such day
        # (none from the CTO's own record, FR-PLAN-37)
        cto_ids = cto_member_ids(session)
        available: dict[str, dict[date, float]] = {
            member_id: {day: _hours_on(session, member, day) for day in past_days} for member_id, member in members.items()
        }
        reports = session.execute(select(EmailMessage.member_id, EmailMessage.report_date, EmailMessage.is_late).where(
            EmailMessage.is_current.is_(True), EmailMessage.member_id.in_(list(members)), EmailMessage.report_date >= week_start, EmailMessage.report_date <= week_end,
        )).all()
        report_days: dict[str, dict[date, bool]] = {}
        for member_id, report_date, is_late in reports:
            report_days.setdefault(str(member_id), {})[report_date] = bool(is_late)

        def report_counts(member_ids: list[str]) -> dict[str, int]:
            expected = received = late = 0
            for member_id in member_ids:
                if member_id in cto_ids:
                    continue
                for day, hours in available.get(member_id, {}).items():
                    if hours <= 0:
                        continue
                    expected += 1
                    if day in report_days.get(member_id, {}):
                        received += 1
                        late += int(report_days[member_id][day])
            return {"expected": expected, "received": received, "missing": expected - received, "late": late}

        # --- plans and reports of the week
        assignments = session.execute(
            select(PlanningAssignment.project_id, PlanningAssignment.member_id, PlanningAssignment.planned_hours, PlanningRun.status)
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(PlanningRun.plan_date >= week_start, PlanningRun.plan_date <= week_end, PlanningRun.status != "SUPERSEDED", PlanningAssignment.project_id.in_(project_ids))
        ).all()
        items = session.execute(
            select(ReportItem.project_id, ReportItem.member_id, ReportItem.work_status, ReportItem.worked_hours, ReportItem.gitlab_issue_external_id, ReportItem.no_issue_reason)
            .join(EmailMessage, EmailMessage.id == ReportItem.email_message_id)
            .where(ReportItem.is_current.is_(True), EmailMessage.is_current.is_(True), EmailMessage.report_date >= week_start, EmailMessage.report_date <= week_end,
                   ReportItem.project_id.in_(project_ids))
        ).all()
        plans = session.execute(select(PlanningRun.project_scope, PlanningRun.status).where(
            PlanningRun.plan_date >= week_start, PlanningRun.plan_date <= week_end, PlanningRun.status != "SUPERSEDED",
        )).all()

        # --- really done: Issues closed, acceptance decided, work logs confirmed
        closed = session.execute(select(GitLabIssueSnapshot.project_id, func.count()).where(
            GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.project_id.in_(project_ids), GitLabIssueSnapshot.closed_at >= start, GitLabIssueSnapshot.closed_at < end,
        ).group_by(GitLabIssueSnapshot.project_id)).all()
        closed_by_project = {str(pid): int(count) for pid, count in closed}
        verified = session.execute(select(IssueVerification.project_id, IssueVerification.decision, func.count()).where(
            IssueVerification.project_id.in_(project_ids), IssueVerification.decided_at >= start, IssueVerification.decided_at < end,
        ).group_by(IssueVerification.project_id, IssueVerification.decision)).all()
        accepted_by_project: dict[str, int] = {}
        rejected_by_project: dict[str, int] = {}
        for pid, decision, count in verified:
            (accepted_by_project if decision == "ACCEPTED" else rejected_by_project if decision == "REJECTED" else {})[str(pid)] = int(count)
        no_evidence = session.execute(select(IssueVerification.project_id, func.count()).where(
            IssueVerification.project_id.in_(project_ids), IssueVerification.decision == "ACCEPTED", IssueVerification.evidence_missing_reason.is_not(None),
            IssueVerification.decided_at >= start, IssueVerification.decided_at < end,
        ).group_by(IssueVerification.project_id)).all()
        no_evidence_by_project = {str(pid): int(count) for pid, count in no_evidence}
        po_rows = session.execute(select(IssueVerification.project_id, func.count()).where(
            IssueVerification.project_id.in_(project_ids), IssueVerification.po_decision == "ACCEPTED", IssueVerification.po_decided_at >= start, IssueVerification.po_decided_at < end,
        ).group_by(IssueVerification.project_id)).all()
        po_by_project = {str(pid): int(count) for pid, count in po_rows}
        logs = session.execute(select(IntakeWorkLog.project_id, func.count()).where(
            IntakeWorkLog.project_id.in_(project_ids), IntakeWorkLog.review_decision == "CONFIRMED", IntakeWorkLog.reviewed_at >= start, IntakeWorkLog.reviewed_at < end,
        ).group_by(IntakeWorkLog.project_id)).all()
        logs_by_project = {str(pid): int(count) for pid, count in logs}

        # --- requests and decisions
        new_requests = session.execute(select(IntakeItem.project_id, func.count()).where(
            IntakeItem.project_id.in_(project_ids), IntakeItem.created_at >= start, IntakeItem.created_at < end,
        ).group_by(IntakeItem.project_id)).all()
        new_by_project = {str(pid): int(count) for pid, count in new_requests}
        approvals = session.execute(
            select(IntakeItem.project_id, IntakeItem.id, IntakeItem.created_at, ApprovalAction.created_at, ApprovalAction.source)
            .join(IntakeItem, IntakeItem.id == ApprovalAction.intake_id)
            .where(ApprovalAction.action == "APPROVE", ApprovalAction.created_at >= start, ApprovalAction.created_at < end, IntakeItem.project_id.in_(project_ids))
        ).all()
        links = session.execute(select(ExternalLink.project_id, ExternalLink.intake_id, ExternalLink.created_at).where(
            ExternalLink.project_id.in_(project_ids), ExternalLink.created_at >= start, ExternalLink.created_at < end,
        )).all()
        last_approve_before: dict[str, list[datetime]] = {}
        for _, intake_id, _, decided_at, _ in approvals:
            last_approve_before.setdefault(str(intake_id), []).append(_utc(decided_at))
        # Approvals before the week can still produce their Issue this week; fetch them for the linked requests.
        missing = [str(intake_id) for _, intake_id, _ in links if str(intake_id) not in last_approve_before]
        if missing:
            for intake_id, decided_at in session.execute(select(ApprovalAction.intake_id, ApprovalAction.created_at).where(
                ApprovalAction.action == "APPROVE", ApprovalAction.intake_id.in_(missing),
            )).all():
                last_approve_before.setdefault(str(intake_id), []).append(_utc(decided_at))

        # --- what each evening's board said
        snapshots = session.scalars(select(BoardDailySnapshot).where(
            BoardDailySnapshot.project_id.in_(project_ids), BoardDailySnapshot.snapshot_date >= week_start, BoardDailySnapshot.snapshot_date <= week_end,
        )).all()

        project_rows = []
        for project in projects:
            pid = str(project.id)
            member_ids = [str(member.id) for member in members_by_project[pid]]
            own_assignments = [row for row in assignments if str(row[0]) == pid]
            own_items = [row for row in items if str(row[0]) == pid]
            own_approvals = [row for row in approvals if str(row[0]) == pid]
            waits = [(_utc(decided) - _utc(created)).total_seconds() / 3600 for _, _, created, decided, _ in own_approvals]
            to_issue = []
            for link_pid, intake_id, linked_at in links:
                if str(link_pid) != pid:
                    continue
                before = [stamp for stamp in last_approve_before.get(str(intake_id), []) if stamp <= _utc(linked_at)]
                if before:
                    to_issue.append((_utc(linked_at) - max(before)).total_seconds() / 3600)
            own_snapshots = [row for row in snapshots if str(row.project_id) == pid]
            own_plans = [status for scope, status in plans if pid in [str(value) for value in (scope or [])]]
            project_rows.append({
                "id": pid, "code": project.code, "name": project.name, "people": len(member_ids),
                "hours": {
                    "available": round(sum(sum(available[member_id].values()) for member_id in member_ids if member_id in available), 1),
                    "planned": round(sum(float(row[2] or 0) for row in own_assignments), 1),
                    "reported": round(sum(float(row[3] or 0) for row in own_items), 1),
                },
                "plans": {"total": len(own_plans), "closed": sum(1 for status in own_plans if status not in ("DRAFT", "REVIEW_REQUIRED"))},
                "done": {
                    "reported": sum(1 for row in own_items if row[2] == "DONE"),
                    "issues_closed": closed_by_project.get(pid, 0),
                    "accepted": accepted_by_project.get(pid, 0), "rejected": rejected_by_project.get(pid, 0), "po_accepted": po_by_project.get(pid, 0),
                    "accepted_without_evidence": no_evidence_by_project.get(pid, 0),
                    "work_logs_confirmed": logs_by_project.get(pid, 0),
                },
                "items": {
                    "reported": sum(1 for row in own_items if row[2] in REPORTED_STATUSES),
                    "without_issue": sum(1 for row in own_items if row[2] in REPORTED_STATUSES and not row[4] and not row[5]),
                    "no_issue_needed": sum(1 for row in own_items if row[2] in REPORTED_STATUSES and not row[4] and row[5]),
                },
                "reports": report_counts(member_ids),
                "requests": {
                    "new": new_by_project.get(pid, 0), "approved": len(own_approvals),
                    "approved_within_24h": sum(1 for hours in waits if hours <= DECIDE_WITHIN.total_seconds() / 3600),
                    "from_planning": sum(1 for row in own_approvals if row[4] == "PLANNING"),
                    "avg_wait_hours": _avg(waits), "avg_to_issue_hours": _avg(to_issue),
                },
                "board": {
                    "days": len(own_snapshots),
                    "ready_days": sum(1 for row in own_snapshots if row.readiness_state == "READY"),
                    "no_work_days": sum(1 for row in own_snapshots if row.readiness_state == "NO_WORK"),
                    "overdue_days": sum(1 for row in own_snapshots if row.approvals_overdue + row.waiting_overdue + row.work_log_overdue + row.p0_open_overdue > 0),
                    "max_approvals_overdue": max((row.approvals_overdue for row in own_snapshots), default=0),
                    "max_stuck": max((row.stuck for row in own_snapshots), default=0),
                    "escalated_days": sum(1 for row in own_snapshots if row.approvals_overdue > 0),
                },
            })

        people_rows = []
        for member_id, member in sorted(members.items(), key=lambda pair: pair[1].display_name.casefold()):
            own_assignments = [row for row in assignments if str(row[1]) == member_id]
            own_items = [row for row in items if str(row[1]) == member_id]
            by_project: dict[str, float] = {}
            for row in own_assignments:
                by_project[str(row[0])] = by_project.get(str(row[0]), 0.0) + float(row[2] or 0)
            reported_by_project: dict[str, float] = {}
            for row in own_items:
                reported_by_project[str(row[0])] = reported_by_project.get(str(row[0]), 0.0) + float(row[3] or 0)
            people_rows.append({
                "member_id": member_id, "display_name": member.display_name,
                "hours": {
                    "available": round(sum(available.get(member_id, {}).values()), 1),
                    "planned": round(sum(by_project.values()), 1), "reported": round(sum(reported_by_project.values()), 1),
                },
                "done_reported": sum(1 for row in own_items if row[2] == "DONE"),
                "items": {
                    "reported": sum(1 for row in own_items if row[2] in REPORTED_STATUSES),
                    "without_issue": sum(1 for row in own_items if row[2] in REPORTED_STATUSES and not row[4] and not row[5]),
                    "no_issue_needed": sum(1 for row in own_items if row[2] in REPORTED_STATUSES and not row[4] and row[5]),
                },
                "reports": report_counts([member_id]),
                "projects": [
                    {"id": pid, "name": names.get(pid, pid), "planned": round(by_project.get(pid, 0.0), 1), "reported": round(reported_by_project.get(pid, 0.0), 1)}
                    for pid in sorted(set(by_project) | set(reported_by_project), key=lambda value: names.get(value, value).casefold())
                ],
            })

        all_waits = [(_utc(decided) - _utc(created)).total_seconds() / 3600 for _, _, created, decided, _ in approvals]
        process = {
            "requests_new": sum(new_by_project.values()), "approved": len(approvals),
            "approved_within_24h": sum(1 for hours in all_waits if hours <= 24), "avg_wait_hours": _avg(all_waits),
            "from_queue": sum(1 for row in approvals if row[4] != "PLANNING"), "from_planning": sum(1 for row in approvals if row[4] == "PLANNING"),
            "issues_created": len(links),
            "avg_to_issue_hours": _avg([value for row in project_rows for value in ([row["requests"]["avg_to_issue_hours"]] if row["requests"]["avg_to_issue_hours"] is not None else [])]),
            "board_days": len(snapshots),
            "ready_days": sum(1 for row in snapshots if row.readiness_state == "READY"),
            "overdue_project_days": sum(1 for row in snapshots if row.approvals_overdue + row.waiting_overdue + row.work_log_overdue + row.p0_open_overdue > 0),
            "escalated_project_days": sum(1 for row in snapshots if row.approvals_overdue > 0),
            "max_stuck": max((row.stuck for row in snapshots), default=0),
        }

        cto_days = None
        if cto_user_id:
            stamps = session.execute(select(AuditEvent.created_at).where(
                AuditEvent.actor_id == str(cto_user_id), AuditEvent.created_at >= start, AuditEvent.created_at < end,
            )).all()
            by_day: dict[date, list[datetime]] = {}
            for (stamp,) in stamps:
                by_day.setdefault(_utc(stamp).astimezone(LOCAL_TZ).date(), []).append(_utc(stamp))
            cto_days = [{"date": week_start + timedelta(days=offset), "minutes": _sittings_minutes(by_day.get(week_start + timedelta(days=offset), []))} for offset in range(7)]

        personal = None
        if cto_user_id:
            from app.modules.planning.personal import week_block
            personal = week_block(session, str(cto_user_id), week_start, week_end)

    result = {
        "week_start": week_start, "week_end": week_end, "days_passed": len(past_days), "generated_at": datetime.now(timezone.utc),
        "projects": project_rows, "people": people_rows, "process": process, "cto_days": cto_days, "personal": personal,
    }
    result["text"] = week_text(result)
    return result


def _h(value: float) -> str:
    return f"{value:g}"


def week_text(summary: dict[str, object]) -> str:
    """The week as plain lines to paste in a chat or a post: names of projects and people, counts, no content."""
    start, end = summary["week_start"], summary["week_end"]
    lines = [f"Tuần {start:%d/%m} - {end:%d/%m}"]
    for row in summary["projects"]:
        hours, done, items, reports, requests, board = row["hours"], row["done"], row["items"], row["reports"], row["requests"], row["board"]
        lines.append("")
        lines.append(f"{row['name']} ({row['people']} người)")
        lines.append(f"- Giờ: có {_h(hours['available'])}, xếp {_h(hours['planned'])}, báo cáo {_h(hours['reported'])}; kế hoạch chốt {row['plans']['closed']}/{row['plans']['total']}")
        lines.append(f"- Xong: báo cáo {done['reported']}, Issue đóng {done['issues_closed']}, Project Owner xác nhận {done.get('po_accepted', 0)}, CTO nghiệm thu {done['accepted']}" + (f" (trả lại {done['rejected']})" if done["rejected"] else "") + (f", {done['accepted_without_evidence']} nghiệm thu không bằng chứng" if done.get("accepted_without_evidence") else "") + f", lịch sử xử lý xác nhận {done['work_logs_confirmed']}")
        lines.append(f"- Việc trong báo cáo: {items['reported']}, chưa gắn Issue {items['without_issue']}" + (f", không cần Issue {items['no_issue_needed']}" if items.get("no_issue_needed") else "") + f"; báo cáo {reports['received']}/{reports['expected']}, trễ {reports['late']}")
        wait = f", chờ trung bình {_h(requests['avg_wait_hours'])} giờ" if requests["avg_wait_hours"] is not None else ""
        lines.append(f"- Yêu cầu: mới {requests['new']}, duyệt {requests['approved']} (trong 24 giờ: {requests['approved_within_24h']}){wait}")
        if board["days"]:
            lines.append(f"- Bảng đầu ngày: đủ cơ sở {board['ready_days']}/{board['days']} ngày, có việc quá hạn {board['overdue_days']} ngày")
    people = summary["people"]
    if people:
        lines.append("")
        lines.append("Theo nhân sự")
        for row in people:
            hours, reports = row["hours"], row["reports"]
            lines.append(f"- {row['display_name']}: xếp {_h(hours['planned'])}/{_h(hours['available'])} giờ, báo cáo {_h(hours['reported'])} giờ, xong {row['done_reported']}, không Issue {row['items']['without_issue']}, báo cáo {reports['received']}/{reports['expected']}" + (f", trễ {reports['late']}" if reports["late"] else ""))
    process = summary["process"]
    lines.append("")
    lines.append("Quy trình")
    lines.append(f"- Yêu cầu mới {process['requests_new']}, duyệt {process['approved']} (trong 24 giờ {process['approved_within_24h']}; từ Daily Planning {process['from_planning']}), Issue tạo {process['issues_created']}")
    if process["avg_wait_hours"] is not None:
        lines.append(f"- Chờ duyệt trung bình {_h(process['avg_wait_hours'])} giờ" + (f", từ duyệt đến Issue {_h(process['avg_to_issue_hours'])} giờ" if process["avg_to_issue_hours"] is not None else ""))
    if process["board_days"]:
        lines.append(f"- Bảng đầu ngày: đủ cơ sở {process['ready_days']}/{process['board_days']} dự án-ngày, quá hạn {process['overdue_project_days']}, leo thang lên CTO {process['escalated_project_days']}")
    if summary.get("cto_days"):
        total = sum(int(day["minutes"]) for day in summary["cto_days"])
        lines.append(f"- CTO điều hành {total} phút cả tuần, trung bình {round(total / max(summary['days_passed'], 1))} phút/ngày")
    personal = summary.get("personal")
    if personal and (personal["done_total"] or personal["delegated"]):
        q1 = next(x for x in personal["done"] if x["quadrant"] == 1)
        q2 = next(x for x in personal["done"] if x["quadrant"] == 2)
        lines.append(f"- Việc riêng của CTO: xong {personal['done_total']} ({personal['done_hours']:g}h), Làm ngay {q1['hours']:g}h, Lên lịch {q2['hours']:g}h, giao đi {personal['delegated']}, dời {personal['rollovers']} lần")
    return "\n".join(lines)
