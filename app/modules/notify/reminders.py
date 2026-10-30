"""What to say, to whom, when (FR-NTF-04, FR-NTF-05, ADR-0057).

Working days are Monday to Friday minus the holidays the CTO listed. On a working day:
- 17:30 to each project group: tomorrow's (next working day's) plan when it is not closed, tagging the Project Owner;
  and a private note to each person with hours today who has not sent today's report.
- 08:00 to each person: their plan for the day, item by item; and a private nudge when yesterday's report is missing,
  with a count in the project group.
- 08:30 and 09:30 to the group: today's plan still not closed (09:30 tags the CTO as well).
- 09:30 to the CTO, privately: what is overdue on the board.
Groups get counts and links; private messages carry work titles and Issue numbers; customer content never travels.
Every (kind, chat, date, slot) is sent once.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import (
    EmailMessage, GitLabIssueSnapshot, Holiday, PersonalTask, PlanningAssignment, PlanningCandidate, PlanningRun, Project, TelegramMessage, User, WorkforceMember,
    WorkforceProjectMembership,
)
from app.modules.notify.telegram import TelegramClient, TelegramError, escape, mention
from app.modules.planning import personal as personal_tasks
from app.modules.planning.cto import cto_member, cto_member_ids
from app.modules.planning.overview import LOCAL_TZ, _hours_on, day_overview
from app.modules.planning.service import MUTABLE_RUN_STATES, _canonical_hash, planning_service

logger = logging.getLogger(__name__)

SLOTS = {"PLAN_TOMORROW": "17:30", "REPORT_TONIGHT": "17:30", "PLAN_TODAY": "08:00", "REPORT_MISSING": "08:00", "PLAN_UNCLOSED_1": "08:30", "PLAN_UNCLOSED_2": "09:30", "OVERDUE": "09:30"}
WINDOW_MINUTES = 20   # a slot missed (bot down) is still sent within this window, not hours later


@dataclass
class Message:
    kind: str
    chat_id: str
    text: str
    for_date: date
    slot: str
    project_id: str | None = None
    member_id: str | None = None
    thread_id: int | None = None
    tags: list[str] = field(default_factory=list)


def app_link(path: str) -> str:
    base = (get_settings().app_public_url or "").rstrip("/")
    return f"{base}{path}" if base else path


def is_working_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def next_working_day(day: date, holidays: set[date]) -> date:
    candidate = day + timedelta(days=1)
    while not is_working_day(candidate, holidays):
        candidate += timedelta(days=1)
    return candidate


def previous_working_day(day: date, holidays: set[date]) -> date:
    candidate = day - timedelta(days=1)
    while not is_working_day(candidate, holidays):
        candidate -= timedelta(days=1)
    return candidate


def due_slots(now_local: datetime, holidays: set[date]) -> list[str]:
    """The slots whose time has come within the window, on a working day."""
    if not is_working_day(now_local.date(), holidays):
        return []
    due = []
    for slot, clock in SLOTS.items():
        hour, minute = (int(part) for part in clock.split(":"))
        at = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= now_local < at + timedelta(minutes=WINDOW_MINUTES):
            due.append(slot)
    return due


def _holidays(session) -> set[date]:
    return {row.day for row in session.scalars(select(Holiday)).all()}


def _plan_of(session, project: Project, day: date) -> PlanningRun | None:
    run = session.scalar(select(PlanningRun).where(
        PlanningRun.plan_date == day, PlanningRun.scope_hash == _canonical_hash([str(project.id)]), PlanningRun.status != "SUPERSEDED",
    ).order_by(PlanningRun.revision.desc()))
    if run is not None:
        return run
    for candidate in session.scalars(select(PlanningRun).where(PlanningRun.plan_date == day, PlanningRun.status != "SUPERSEDED")).all():
        if str(project.id) in [str(value) for value in (candidate.project_scope or [])]:
            return candidate
    return None


def _owner(session, project: Project) -> WorkforceMember | None:
    return session.get(WorkforceMember, project.owner_member_id) if project.owner_member_id else None


def _cto_member(session) -> WorkforceMember | None:
    return cto_member(session)


def _members_of(session, project: Project) -> list[WorkforceMember]:
    return session.scalars(
        select(WorkforceMember).join(WorkforceProjectMembership, WorkforceProjectMembership.member_id == WorkforceMember.id)
        .where(WorkforceProjectMembership.project_id == project.id, WorkforceProjectMembership.active.is_(True), WorkforceMember.status == "ACTIVE")
        .order_by(WorkforceMember.display_name)
    ).all()


def _report_of(session, member: WorkforceMember, day: date) -> EmailMessage | None:
    return session.scalar(select(EmailMessage).where(EmailMessage.member_id == member.id, EmailMessage.report_date == day, EmailMessage.is_current.is_(True)))


def plan_group_message(session, project: Project, day: date, label: str, tag_cto: bool) -> str | None:
    """The group's line about a plan that is not closed yet; None when it is closed."""
    run = _plan_of(session, project, day)
    if run is not None and run.status not in MUTABLE_RUN_STATES:
        return None
    owner = _owner(session, project)
    tags = [mention(owner.telegram_chat_id, owner.display_name, owner.telegram_username)] if owner else []
    if tag_cto:
        cto = _cto_member(session)
        if cto is not None and (not owner or str(cto.id) != str(owner.id)):
            tags.append(mention(cto.telegram_chat_id, cto.display_name, cto.telegram_username))
    if run is None:
        body = f"Chưa có kế hoạch {label} cho <b>{escape(project.name)}</b>."
    else:
        waiting = session.scalar(select(PlanningCandidate).where(PlanningCandidate.planning_run_id == run.id, PlanningCandidate.status.in_(("PENDING_TRIAGE", "READY"))).limit(1))
        waiting_count = len(session.scalars(select(PlanningCandidate.id).where(PlanningCandidate.planning_run_id == run.id, PlanningCandidate.status.in_(("PENDING_TRIAGE", "READY")))).all()) if waiting else 0
        assigned = {str(row.member_id) for row in session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id, PlanningAssignment.project_id == project.id)).all()}
        free = [m.display_name for m in _members_of(session, project) if _hours_on(session, m, day) > 0 and str(m.id) not in assigned]
        parts = [f"Kế hoạch {label} của <b>{escape(project.name)}</b> chưa chốt"]
        if waiting_count:
            parts.append(f"{waiting_count} việc chờ phân công")
        if free:
            parts.append(f"{len(free)} người có giờ chưa có việc")
        body = " · ".join(parts) + "."
    link = app_link(f"/planning?project={project.id}&date={day.isoformat()}")
    tagline = " ".join(tags)
    return f"{body}\n{tagline + ' ' if tagline else ''}Mở Daily Planning: {escape(link)}"


def plan_private_message(session, member: WorkforceMember, day: date) -> str:
    """The person's own day: each piece of work with its Issue, slot and hours; or that there is none yet."""
    rows = session.execute(
        select(PlanningAssignment, PlanningRun, Project)
        .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
        .join(Project, Project.id == PlanningAssignment.project_id)
        .where(PlanningRun.plan_date == day, PlanningRun.status != "SUPERSEDED", PlanningAssignment.member_id == member.id)
        .order_by(Project.name, PlanningAssignment.slot)
    ).all()
    if not rows:
        personal = _personal_lines(session, member, day)
        if not personal:
            return f"Hôm nay {day:%d/%m} chưa có việc nào xếp cho bạn. Nếu thấy thiếu, nhắn Project Owner của dự án."
        return "\n".join([f"<b>Việc hôm nay {day:%d/%m}</b>", "Chưa có việc dự án nào xếp cho bạn."] + personal + [f"Chi tiết: {escape(app_link('/viec-rieng'))} · Trong Claude Code: /in-today"])
    lines = [f"<b>Việc hôm nay {day:%d/%m}</b>"]
    accepted = planning_service.accepted_at_by_issue(session, sorted({str(project.id) for _, _, project in rows}))
    for assignment, run, project in rows:
        title = None
        candidate = session.scalar(select(PlanningCandidate).where(PlanningCandidate.assignment_id == assignment.id))
        if candidate is not None:
            title = candidate.title
        if not title and assignment.gitlab_issue_external_id:
            snapshot = session.scalar(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == project.id, GitLabIssueSnapshot.issue_external_id == assignment.gitlab_issue_external_id, GitLabIssueSnapshot.is_current.is_(True),
            ))
            title = snapshot.title if snapshot is not None else None
        slot = "Sáng" if assignment.slot == "MORNING" else "Chiều"
        issue = f"#{escape(assignment.gitlab_issue_external_id)} " if assignment.gitlab_issue_external_id else ""
        draft = " (kế hoạch chưa chốt)" if run.status in MUTABLE_RUN_STATES else ""
        done = " ✅ đã nghiệm thu" if assignment.gitlab_issue_external_id and (str(project.id), assignment.gitlab_issue_external_id) in accepted else ""
        lines.append(f"• {slot} · {float(assignment.planned_hours):g}h · [{escape(project.name)}] {issue}{escape(title or 'việc chưa có tên')}{draft}{done}")
    lines.extend(_personal_lines(session, member, day))
    lines.append(f"Chi tiết: {escape(app_link('/planning'))} · Trong Claude Code: /in-today")
    return "\n".join(lines)


def _personal_lines(session, member: WorkforceMember, day: date) -> list[str]:
    """The person's own tasks for the day, in their private chat only (FR-PER-03)."""
    user = session.scalar(select(User).where(User.member_id == member.id)) or (
        session.scalar(select(User).where(User.email == member.email_reference)) if member.email_reference else None
    )
    if user is None:
        return []
    rows = [row for row in personal_tasks.tasks_on(session, str(user.id), day) if row.status == "PLANNED" and personal_tasks.quadrant_of(row) != 4]
    if not rows:
        return []
    lines = ["<b>Việc riêng</b>"]
    for row in rows:
        when = f"{row.start_time} · " if row.start_time else ""
        hours = f"{float(row.hours):g}h · " if float(row.hours or 0) > 0 else ""
        lines.append(f"• [{personal_tasks.QUADRANTS[personal_tasks.quadrant_of(row)]}] {when}{hours}{escape(row.title)}")
    return lines


def weekly_review_messages(session, now_local: datetime) -> list[Message]:
    """Sunday 20:00: the CTO's own tasks tidied for the week ahead, one note, only when there is something to tidy."""
    if now_local.weekday() != 6 or not (now_local.replace(hour=20, minute=0, second=0, microsecond=0) <= now_local < now_local.replace(hour=20, minute=WINDOW_MINUTES, second=0, microsecond=0)):
        return []
    cto = _cto_member(session)
    if cto is None or not cto.telegram_chat_id:
        return []
    user = session.scalar(select(User).where(User.member_id == cto.id)) or session.scalar(select(User).where(User.role == "CTO", User.is_active.is_(True)).order_by(User.created_at))
    if user is None:
        return []
    text = personal_tasks.weekly_review_message(session, str(user.id), now_local.date(), escape(app_link("/viec-rieng")))
    if not text:
        return []
    return [Message("CTO_WEEKLY", cto.telegram_chat_id, text, now_local.date(), "20:00", member_id=str(cto.id))]


def feedback_decisions(session, now_local: datetime) -> list[Message]:
    """The owner's yes or no on a suggestion, told to the person who wrote it, once (FR-FBK-03)."""
    from app.modules.intake.feedback import feedback_service

    since = (now_local - timedelta(days=2)).astimezone(timezone.utc)
    out: list[Message] = []
    for row in feedback_service.decided_recently(session, since):
        chat_id = row.get("member_chat_id")
        if not chat_id:
            continue
        project = row.get("project_name") or row.get("project_code") or ""
        head = str(row.get("text") or "").strip().replace("\n", " ")
        head = head[:80] + ("…" if len(head) > 80 else "")
        if row["status"] == "ACCEPTED":
            link = app_link(f"/intakes/{row['intake_id']}") if row.get("intake_id") else ""
            text = (f"Góp ý của bạn cho <b>{escape(project)}</b> đã được nhận: \"{escape(head)}\" thành yêu cầu <b>{escape(row.get('intake_public_id') or '')}</b>"
                    + (f" ({escape(row['decision_note'])})" if row.get("decision_note") else "") + (f". {escape(link)}" if link else "."))
        else:
            text = f"Góp ý của bạn cho <b>{escape(project)}</b> chưa được nhận: \"{escape(head)}\". Lý do: {escape(row.get('decision_note') or '')}"
        decided_at = row.get("decided_at")
        day = decided_at.astimezone(LOCAL_TZ).date() if isinstance(decided_at, datetime) else now_local.date()
        out.append(Message("FEEDBACK_DECIDED", str(chat_id), text, day, str(row["id"])[:8], project_id=row.get("project_id"), member_id=row.get("member_id")))
    return out


def personal_reminders(session, now_local: datetime) -> list[Message]:
    """Each person's own tasks whose reminder time falls in the window, grouped by minute; any day of the week."""
    today = now_local.date()
    out: list[Message] = []
    rows = session.execute(
        select(PersonalTask, WorkforceMember).join(WorkforceMember, WorkforceMember.id == PersonalTask.member_id)
        .where(PersonalTask.task_date == today, PersonalTask.status == "PLANNED", PersonalTask.remind_at.is_not(None), WorkforceMember.telegram_chat_id.is_not(None))
        .order_by(PersonalTask.remind_at, PersonalTask.created_at)
    ).all()
    grouped: dict[tuple[str, str], list[tuple[PersonalTask, WorkforceMember]]] = {}
    for task, member in rows:
        if personal_tasks.quadrant_of(task, today) == 4:
            continue
        hour, minute = (int(part) for part in str(task.remind_at).split(":"))
        at = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if at <= now_local < at + timedelta(minutes=WINDOW_MINUTES):
            grouped.setdefault((member.telegram_chat_id, str(task.remind_at)), []).append((task, member))
    for (chat_id, clock), pairs in grouped.items():
        member = pairs[0][1]
        lines = [f"<b>Nhắc {clock}</b>"] + [f"• {escape(task.title)}" + (f": {escape(task.note)}" if task.note else "") for task, _ in pairs]
        out.append(Message("PERSONAL_REMIND", chat_id, "\n".join(lines), today, clock, member_id=str(member.id)))
    return out


def report_tonight_message(member: WorkforceMember, day: date) -> str:
    return f"Nhớ gửi báo cáo ngày {day:%d/%m} trước 18:00 nhé. Mỗi việc một dòng, có số Issue, số giờ và tiến độ. Trong Claude Code: /in-end-day"


def report_missing_message(member: WorkforceMember, day: date) -> str:
    return f"Chưa thấy báo cáo ngày {day:%d/%m} của bạn. Gửi sớm để kế hoạch hôm nay có cơ sở."


def report_missing_group_message(project: Project, day: date, names: list[str]) -> str:
    return f"<b>{escape(project.name)}</b>: {len(names)} người chưa gửi báo cáo ngày {day:%d/%m}. Xem: {escape(app_link('/reports'))}"


def cto_digest_message(session, projects: list[Project], plan_day: date, report_day: date, clock: str) -> str | None:
    """What the CTO should nudge after a reminder round: plans not closed (with the Project Owner to call) and people
    who have not reported. One note, nothing when all is well (FR-NTF-06)."""
    unclosed: list[str] = []
    for project in projects:
        run = _plan_of(session, project, plan_day)
        if run is not None and run.status not in MUTABLE_RUN_STATES:
            continue
        owner = _owner(session, project)
        unclosed.append(f"{escape(project.name)} ({escape(owner.display_name) if owner else 'chưa có Project Owner'})")
    missing: list[str] = []
    for project in projects:
        names = [m.display_name for m in _members_of(session, project) if _hours_on(session, m, report_day) > 0 and _report_of(session, m, report_day) is None]
        if names:
            missing.append(f"{escape(project.name)}: {escape(', '.join(names))}")
    if not unclosed and not missing:
        return None
    lines = [f"<b>Tổng hợp {clock}</b>"]
    if unclosed:
        lines.append(f"Kế hoạch ngày {plan_day:%d/%m} chưa chốt: " + "; ".join(unclosed))
    if missing:
        lines.append(f"Chưa gửi báo cáo ngày {report_day:%d/%m}: " + " · ".join(missing))
    lines.append(f"Daily Planning: {escape(app_link('/planning'))}")
    return "\n".join(lines)


def overdue_message(board: dict[str, object]) -> str | None:
    rows = [row for row in board["projects"] if sum(int(v) for v in row["overdue"].values()) > 0]
    if not rows:
        return None
    lines = ["<b>Việc chờ quá hạn sáng nay</b>"]
    for row in rows:
        over = row["overdue"]
        parts = []
        if over["approvals"]:
            parts.append(f"{over['approvals']} chờ duyệt quá 24h")
        if over["waiting"]:
            parts.append(f"{over['waiting']} chờ phân công quá 2 ngày")
        if over["work_log"]:
            parts.append(f"{over['work_log']} lịch sử chờ xác nhận")
        if over["p0_open"]:
            parts.append(f"{over['p0_open']} Issue P0 mở quá 1 ngày")
        lines.append(f"• {escape(row['name'])}: " + ", ".join(parts))
    lines.append(f"Bảng đầu ngày: {escape(app_link('/'))}")
    return "\n".join(lines)


def build_messages(now_local: datetime) -> list[Message]:
    """Everything due at this moment, computed from the database; sending and the once-only rule happen in `send_due`."""
    from app.modules.notify.posts import post_messages

    with get_session() as session:
        holidays = _holidays(session)
        cto_ids = cto_member_ids(session)  # the CTO's own record owes no Daily Report (FR-PLAN-37)
        out: list[Message] = personal_reminders(session, now_local)
        out.extend(weekly_review_messages(session, now_local))
        out.extend(feedback_decisions(session, now_local))
        # Posts go out on any day: their reminders do not wait for a working day (FR-MKT-15).
        out.extend(post_messages(session, now_local))
        slots = due_slots(now_local, holidays)
        if not slots:
            return out
        today = now_local.date()
        projects = session.scalars(select(Project).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE").order_by(Project.name)).all()
        linked_projects = [p for p in projects if p.telegram_chat_id]
        if "PLAN_TOMORROW" in slots:
            tomorrow = next_working_day(today, holidays)
            for project in linked_projects:
                text = plan_group_message(session, project, tomorrow, f"ngày mai {tomorrow:%d/%m}" if tomorrow == today + timedelta(days=1) else f"ngày {tomorrow:%d/%m}", tag_cto=False)
                if text:
                    out.append(Message("PLAN_TOMORROW", project.telegram_chat_id, text, tomorrow, "17:30", project_id=str(project.id), thread_id=project.telegram_thread_id))
        if "REPORT_TONIGHT" in slots:
            for member in session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE", WorkforceMember.telegram_chat_id.is_not(None))).all():
                if str(member.id) not in cto_ids and _hours_on(session, member, today) > 0 and _report_of(session, member, today) is None:
                    out.append(Message("REPORT_TONIGHT", member.telegram_chat_id, report_tonight_message(member, today), today, "17:30", member_id=str(member.id)))
        if "PLAN_TODAY" in slots:
            for member in session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE", WorkforceMember.telegram_chat_id.is_not(None))).all():
                if _hours_on(session, member, today) > 0:
                    out.append(Message("PLAN_TODAY", member.telegram_chat_id, plan_private_message(session, member, today), today, "08:00", member_id=str(member.id)))
        if "REPORT_MISSING" in slots:
            yesterday = previous_working_day(today, holidays)
            missing_by_project: dict[str, list[str]] = {}
            seen_members: set[str] = set()
            for project in linked_projects:
                names = []
                for member in _members_of(session, project):
                    if str(member.id) in cto_ids or _hours_on(session, member, yesterday) <= 0 or _report_of(session, member, yesterday) is not None:
                        continue
                    names.append(member.display_name)
                    if member.telegram_chat_id and str(member.id) not in seen_members:
                        seen_members.add(str(member.id))
                        out.append(Message("REPORT_MISSING", member.telegram_chat_id, report_missing_message(member, yesterday), yesterday, "08:00", member_id=str(member.id)))
                if names:
                    missing_by_project[str(project.id)] = names
                    out.append(Message("REPORT_MISSING_GROUP", project.telegram_chat_id, report_missing_group_message(project, yesterday, names), yesterday, "08:00", project_id=str(project.id), thread_id=project.telegram_thread_id))
        for slot_name, clock, tag_cto in (("PLAN_UNCLOSED_1", "08:30", False), ("PLAN_UNCLOSED_2", "09:30", True)):
            if slot_name in slots:
                for project in linked_projects:
                    text = plan_group_message(session, project, today, f"hôm nay {today:%d/%m}", tag_cto=tag_cto)
                    if text:
                        out.append(Message(slot_name, project.telegram_chat_id, text, today, clock, project_id=str(project.id), thread_id=project.telegram_thread_id))
        if "OVERDUE" in slots:
            cto = _cto_member(session)
            if cto is not None and cto.telegram_chat_id:
                text = overdue_message(day_overview(today, None))
                if text:
                    out.append(Message("OVERDUE", cto.telegram_chat_id, text, today, "09:30", member_id=str(cto.id)))
        # The CTO's own round-up, twice a day at most and only when something needs a nudge: after the 17:30 round
        # (tomorrow's plans, today's reports) and after the 08:30 one (today's plans, yesterday's reports).
        cto = _cto_member(session)
        if cto is not None and cto.telegram_chat_id:
            for slot_name, clock, plan_day, report_day in (
                ("PLAN_TOMORROW", "17:30", next_working_day(today, holidays), today),
                ("PLAN_UNCLOSED_1", "08:30", today, previous_working_day(today, holidays)),
            ):
                if slot_name in slots:
                    text = cto_digest_message(session, projects, plan_day, report_day, clock)
                    if text:
                        out.append(Message("CTO_DIGEST", cto.telegram_chat_id, text, today, clock, member_id=str(cto.id)))
        return out


def send_due(now_local: datetime | None = None, client: TelegramClient | None = None) -> dict[str, int]:
    """Send what is due and not yet sent. Safe to call every minute."""
    now_local = now_local or datetime.now(LOCAL_TZ)
    client = client or TelegramClient()
    sent = skipped = failed = 0
    for message in build_messages(now_local):
        with get_session() as session:
            already = session.scalar(select(TelegramMessage).where(
                TelegramMessage.kind == message.kind, TelegramMessage.chat_id == message.chat_id, TelegramMessage.thread_id == (message.thread_id or 0),
                TelegramMessage.for_date == message.for_date, TelegramMessage.slot == message.slot,
            ))
            if already is not None:
                skipped += 1
                continue
            row = TelegramMessage(
                id=str(uuid4()), kind=message.kind, chat_id=message.chat_id, thread_id=message.thread_id or 0, project_id=message.project_id, member_id=message.member_id,
                for_date=message.for_date, slot=message.slot, status="PENDING", created_at=datetime.now(timezone.utc),
            )
            session.add(row)
            session.commit()
            row_id = str(row.id)
        try:
            client.send_message(message.chat_id, message.text, thread_id=message.thread_id)
            status, error = "SENT", None
            sent += 1
        except TelegramError as exc:
            status, error = "FAILED", exc.safe_summary[:300]
            failed += 1
            logger.warning("telegram %s to %s failed: %s", message.kind, message.chat_id, exc.safe_summary)
        with get_session() as session:
            row = session.get(TelegramMessage, row_id)
            if row is not None:
                row.status, row.error, row.sent_at = status, error, datetime.now(timezone.utc) if status == "SENT" else None
                session.commit()
    return {"sent": sent, "skipped": skipped, "failed": failed}


def send_test(client: TelegramClient | None = None) -> list[dict[str, object]]:
    """One short line to every linked group or topic and every linked person, so a new setup can be checked at once.
    Each attempt is logged under kind TEST; nothing about plans or reports is read."""
    client = client or TelegramClient()
    now = datetime.now(timezone.utc)
    stamp = datetime.now(LOCAL_TZ).strftime("%H:%M:%S")
    results: list[dict[str, object]] = []
    with get_session() as session:
        targets: list[tuple[str, str, int | None, str | None, str | None]] = []
        for project in session.scalars(select(Project).where(Project.status == "ACTIVE", Project.telegram_chat_id.is_not(None)).order_by(Project.name)).all():
            targets.append((f"{project.name} ({project.telegram_chat_title or project.telegram_chat_id})", project.telegram_chat_id, project.telegram_thread_id, str(project.id), None))
        for member in session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE", WorkforceMember.telegram_chat_id.is_not(None)).order_by(WorkforceMember.display_name)).all():
            targets.append((f"{member.display_name} (@{member.telegram_username or '?'})", member.telegram_chat_id, None, None, str(member.id)))
    for label, chat_id, thread_id, project_id, member_id in targets:
        text = f"Tin thử từ Intake lúc {stamp}: bot gửi được tới đây. Lịch nhắc thật: 17:30, 08:00, 08:30, 09:30 các ngày làm việc."
        try:
            client.send_message(chat_id, escape(text), thread_id=thread_id)
            status, error = "SENT", None
        except TelegramError as exc:
            status, error = "FAILED", exc.safe_summary[:300]
        with get_session() as session:
            session.add(TelegramMessage(
                id=str(uuid4()), kind="TEST", chat_id=chat_id, thread_id=thread_id or 0, project_id=project_id, member_id=member_id,
                for_date=now.date(), slot=stamp, status=status, error=error, sent_at=now if status == "SENT" else None, created_at=now,
            ))
            session.commit()
        results.append({"target": label, "status": status, "error": error})
    return results


def recent_messages(days: int = 7) -> list[dict[str, object]]:
    since = datetime.now(LOCAL_TZ).date() - timedelta(days=days)
    with get_session() as session:
        rows = session.scalars(select(TelegramMessage).where(TelegramMessage.for_date >= since).order_by(TelegramMessage.created_at.desc()).limit(200)).all()
        projects = {str(p.id): p.name for p in session.scalars(select(Project)).all()}
        members = {str(m.id): m.display_name for m in session.scalars(select(WorkforceMember)).all()}
        return [{
            "id": str(row.id), "kind": row.kind, "for_date": row.for_date, "slot": row.slot, "status": row.status, "error": row.error,
            "sent_at": row.sent_at, "project_name": projects.get(str(row.project_id)) if row.project_id else None,
            "member_name": members.get(str(row.member_id)) if row.member_id else None,
        } for row in rows]
