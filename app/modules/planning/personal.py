"""A person's own tasks for the day, outside any project (FR-PER-01..03, ADR-0060).

They belong to the login that made them. The staff record behind that login, when there is one, lends them its
hours: planning sees the person's free hours shrink, never the task. Reminders go only to the owner's Telegram.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from app.db import get_session
from app.models import AuditEvent, Holiday, PersonalTask, User, WorkforceMember

ARCHIVE_AFTER = timedelta(days=7)
ROLLOVER_WARN = 2

STATUSES = ("PLANNED", "DONE", "SKIPPED", "DELEGATED")
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
REPEAT = re.compile(r"^(WEEKLY:[0-6]|MONTHLY:(?:[1-9]|[12]\d|3[01]))$")
# The Eisenhower matrix (FR-PER-04): the quadrant number and what to do with what sits in it.
QUADRANTS = {1: "Làm ngay", 2: "Lên lịch", 3: "Ủy quyền", 4: "Bỏ"}


def _today() -> date:
    from app.modules.planning.overview import LOCAL_TZ
    return datetime.now(LOCAL_TZ).date()


def is_urgent(task: PersonalTask, today: date | None = None) -> bool:
    """Urgent when the person said so; otherwise when the day is today or tomorrow, or a reminder is set.
    A task with no date is not urgent until someone says so."""
    if task.urgent is not None:
        return bool(task.urgent)
    if task.task_date is None:
        return False
    today = today or _today()
    return (task.task_date - today).days <= 1 or bool(task.remind_at)


def quadrant_of(task: PersonalTask, today: date | None = None) -> int:
    urgent = is_urgent(task, today)
    if task.important:
        return 1 if urgent else 2
    return 3 if urgent else 4


def sort_key(task: PersonalTask, today: date | None = None) -> tuple:
    """Matrix order: quadrant first; inside it today's work, then by date (undated last), then start time."""
    today = today or _today()
    day = task.task_date
    return (quadrant_of(task, today), 0 if day == today else 1, day or date.max, task.start_time or "99:99", task.created_at)


def _working_days(session) -> set[date]:
    return {row.day for row in session.scalars(select(Holiday)).all()}


def next_working_day(day: date, holidays: set[date]) -> date:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5 or candidate in holidays:
        candidate += timedelta(days=1)
    return candidate


class PersonalTaskError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def member_for_user(session, user_id: str) -> WorkforceMember | None:
    """The staff record of a login: linked directly, or found by the login's email."""
    user = session.get(User, user_id)
    if user is None:
        return None
    if user.member_id:
        return session.get(WorkforceMember, user.member_id)
    return session.scalar(select(WorkforceMember).where(WorkforceMember.email_reference == user.email))


def reserved_hours(session, member_id: str | None, day: date) -> float:
    """Hours a person's own tasks take on a day; a task done or still planned both took them."""
    if not member_id:
        return 0.0
    total = session.scalar(select(func.coalesce(func.sum(PersonalTask.hours), 0)).where(
        PersonalTask.member_id == member_id, PersonalTask.task_date == day, PersonalTask.status.in_(("PLANNED", "DONE")), PersonalTask.archived_at.is_(None),
    ))
    return float(total or 0)


def _clock(value: str | None, field: str) -> str | None:
    text = (value or "").strip()
    if not text:
        return None
    if not CLOCK.match(text):
        raise PersonalTaskError("TIME_INVALID", f"'{field}' must be HH:MM")
    return text


def _repeat(value: str | None) -> str | None:
    text = (value or "").strip().upper()
    if not text:
        return None
    if not REPEAT.match(text):
        raise PersonalTaskError("REPEAT_INVALID", "repeat_rule must be WEEKLY:<0-6> or MONTHLY:<1-31>")
    return text


def next_occurrence(rule: str, after: date) -> date:
    """The first day after `after` that the rule names: that weekday, or that day of the month (clipped to the month)."""
    kind, _, value = rule.partition(":")
    number = int(value)
    if kind == "WEEKLY":
        delta = (number - after.weekday()) % 7 or 7
        return after + timedelta(days=delta)
    month_start = date(after.year, after.month, 1)
    for _ in range(3):
        month_start = date(month_start.year + (month_start.month // 12), month_start.month % 12 + 1, 1)
        last = (date(month_start.year + (month_start.month // 12), month_start.month % 12 + 1, 1) - timedelta(days=1)).day
        candidate = month_start.replace(day=min(number, last))
        if candidate > after:
            return candidate
    return after + timedelta(days=30)


def repeat_label(rule: str | None) -> str | None:
    if not rule:
        return None
    kind, _, value = rule.partition(":")
    if kind == "WEEKLY":
        return "lặp tuần " + ["T2", "T3", "T4", "T5", "T6", "T7", "CN"][int(value)]
    return f"lặp tháng ngày {int(value)}"


def _spawn_next(session, row: PersonalTask, now: datetime) -> PersonalTask | None:
    """When a repeating task is finished, the next one is made once, from the finished task's own date (or today)."""
    if not row.repeat_rule:
        return None
    root = row.repeat_parent_id or row.id
    after = row.task_date or now.astimezone(__import__("app.modules.planning.overview", fromlist=["LOCAL_TZ"]).LOCAL_TZ).date()
    day = next_occurrence(row.repeat_rule, after)
    exists = session.scalar(select(PersonalTask.id).where(
        (PersonalTask.repeat_parent_id == root) | (PersonalTask.id == root), PersonalTask.task_date == day, PersonalTask.status == "PLANNED",
    ))
    if exists:
        return None
    following = PersonalTask(
        id=str(uuid4()), user_id=row.user_id, member_id=row.member_id, task_date=day, title=row.title, note=row.note, hours=row.hours,
        start_time=row.start_time, remind_at=row.remind_at, status="PLANNED", important=row.important, urgent=row.urgent,
        repeat_rule=row.repeat_rule, repeat_parent_id=root, created_at=now, updated_at=now,
    )
    session.add(following)
    return following


def _dict(row: PersonalTask, today: date | None = None) -> dict[str, object]:
    quadrant = quadrant_of(row, today)
    delegate = None
    if row.delegated_member_id:
        from sqlalchemy.orm import object_session
        session = object_session(row)
        member = session.get(WorkforceMember, row.delegated_member_id) if session is not None else None
        delegate = member.display_name if member is not None else None
    return {
        "delegated_member_id": str(row.delegated_member_id) if row.delegated_member_id else None, "delegated_member_name": delegate,
        "delegated_assignment_id": str(row.delegated_assignment_id) if row.delegated_assignment_id else None,
        "repeat_rule": row.repeat_rule, "repeat_label": repeat_label(row.repeat_rule), "done_quadrant": row.done_quadrant,
        "id": str(row.id), "task_date": row.task_date, "title": row.title, "note": row.note, "hours": float(row.hours or 0),
        "start_time": row.start_time, "remind_at": row.remind_at, "status": row.status, "done_at": row.done_at,
        "important": bool(row.important), "urgent": row.urgent, "urgent_effective": is_urgent(row, today),
        "quadrant": quadrant, "quadrant_label": QUADRANTS[quadrant],
        "rollover_count": int(row.rollover_count or 0), "archived_at": row.archived_at,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _live(query):
    return query.where(PersonalTask.archived_at.is_(None))


def list_tasks(user_id: str, start: date, end: date) -> list[dict[str, object]]:
    with get_session() as session:
        today = _today()
        rows = session.scalars(_live(select(PersonalTask).where(
            PersonalTask.user_id == user_id, PersonalTask.task_date >= start, PersonalTask.task_date <= end,
        ))).all()
        rows.sort(key=lambda row: (row.task_date, sort_key(row, today)))
        return [_dict(row, today) for row in rows]


def list_archived(user_id: str) -> list[dict[str, object]]:
    with get_session() as session:
        rows = session.scalars(select(PersonalTask).where(PersonalTask.user_id == user_id, PersonalTask.archived_at.is_not(None))
                               .order_by(PersonalTask.archived_at.desc()).limit(200)).all()
        return [_dict(row) for row in rows]


def tasks_on(session, user_id: str, day: date) -> list[PersonalTask]:
    """The person's tasks of a day, the matrix order: do first, then schedule, delegate, drop."""
    rows = session.scalars(_live(select(PersonalTask).where(PersonalTask.user_id == user_id, PersonalTask.task_date == day))).all()
    rows.sort(key=lambda row: sort_key(row))
    return rows


def matrix(user_id: str, week_of: date | None = None) -> dict[str, object]:
    """The week's matrix (FR-PER-05): the tasks dated in that week, plus the ones with no date yet and the ones left
    over from before, each with its quadrant; the numbers for the strip above it."""
    today = _today()
    week_of = week_of or today
    week_start = week_of - timedelta(days=week_of.weekday())
    week_end = week_start + timedelta(days=6)
    with get_session() as session:
        rows = session.scalars(_live(select(PersonalTask).where(PersonalTask.user_id == user_id))).all()
        chosen = [
            row for row in rows
            if row.task_date is None
            or (week_start <= row.task_date <= week_end)
            or (row.task_date < week_start and row.status == "PLANNED" and week_start <= today <= week_end)
        ]
        chosen.sort(key=lambda row: sort_key(row, today))
        open_today = [row for row in rows if row.task_date == today and row.status == "PLANNED"]
        week_open = [row for row in chosen if row.status == "PLANNED"]
        by_quadrant = {q: [row for row in week_open if quadrant_of(row, today) == q] for q in QUADRANTS}
        return {
            "week_start": week_start, "week_end": week_end, "today": today,
            "tasks": [_dict(row, today) for row in chosen],
            "summary": {
                "today_open": len(open_today), "today_hours": round(sum(float(r.hours or 0) for r in open_today), 2),
                "quadrants": [{"quadrant": q, "label": QUADRANTS[q], "open": len(items), "hours": round(sum(float(r.hours or 0) for r in items), 2)} for q, items in by_quadrant.items()],
                "rolled_over": len([row for row in week_open if int(row.rollover_count or 0) > ROLLOVER_WARN]),
                "undated": len([row for row in week_open if row.task_date is None]),
                "overdue": len([row for row in week_open if row.task_date is not None and row.task_date < today]),
            },
        }


def nightly(now: datetime | None = None) -> dict[str, int]:
    """After the day: unfinished dated tasks roll to the next working day (counted), and tasks the drop quadrant has
    held untouched for a week are archived."""
    now = now or datetime.now(timezone.utc)
    from app.modules.planning.overview import LOCAL_TZ
    today = now.astimezone(LOCAL_TZ).date()
    rolled = archived = 0
    with get_session() as session:
        holidays = _working_days(session)
        # The job runs at the end of `today`: whatever is still planned for today or earlier moves to the next working day.
        target = next_working_day(today, holidays)
        for row in session.scalars(_live(select(PersonalTask).where(PersonalTask.status == "PLANNED", PersonalTask.task_date.is_not(None), PersonalTask.task_date <= today))).all():
            row.task_date = target
            row.rollover_count = int(row.rollover_count or 0) + 1
            row.updated_at = now
            rolled += 1
        for row in session.scalars(_live(select(PersonalTask).where(PersonalTask.status == "PLANNED", PersonalTask.updated_at <= now - ARCHIVE_AFTER))).all():
            if quadrant_of(row, today) == 4:
                row.archived_at = now
                archived += 1
        session.commit()
    return {"rolled": rolled, "archived": archived}


def create_task(
    user_id: str, *, title: str, task_date: date | None, hours: float = 0, start_time: str | None = None, remind_at: str | None = None, note: str | None = None,
    important: bool = False, urgent: bool | None = None, repeat_rule: str | None = None,
) -> dict[str, object]:
    title = " ".join((title or "").split())[:200]
    if not title:
        raise PersonalTaskError("TITLE_REQUIRED", "A task needs a title")
    if hours < 0 or hours > 24:
        raise PersonalTaskError("HOURS_INVALID", "hours must be between 0 and 24")
    now = datetime.now(timezone.utc)
    with get_session() as session:
        member = member_for_user(session, user_id)
        row = PersonalTask(
            id=str(uuid4()), user_id=user_id, member_id=member.id if member is not None else None, task_date=task_date, title=title,
            note=(note or "").strip()[:2000] or None, hours=Decimal(str(round(float(hours), 2))), start_time=_clock(start_time, "start_time"),
            remind_at=_clock(remind_at, "remind_at"), status="PLANNED", important=bool(important), urgent=urgent, repeat_rule=_repeat(repeat_rule),
            created_at=now, updated_at=now,
        )
        session.add(row)
        session.add(AuditEvent(
            id=str(uuid4()), project_id=None, actor_type="USER", actor_id=user_id, event_type="personal_task.created",
            entity_type="personal_task", entity_id=row.id, details={"task_date": task_date.isoformat() if task_date else None, "hours": float(row.hours)}, created_at=now,
        ))
        session.commit()
        return _dict(row)


def update_task(user_id: str, task_id: str, **changes: object) -> dict[str, object] | None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(PersonalTask, task_id)
        if row is None or str(row.user_id) != str(user_id):
            return None
        if "title" in changes and changes["title"] is not None:
            title = " ".join(str(changes["title"]).split())[:200]
            if not title:
                raise PersonalTaskError("TITLE_REQUIRED", "A task needs a title")
            row.title = title
        if "note" in changes:
            row.note = (str(changes["note"] or "")).strip()[:2000] or None
        if "task_date" in changes:
            # None takes the date away: the task goes back to the matrix to be scheduled.
            row.task_date = changes["task_date"]  # type: ignore[assignment]
            if changes["task_date"] is not None:
                row.rollover_count = 0
        if "archived" in changes and changes["archived"] is not None:
            row.archived_at = None if not changes["archived"] else (row.archived_at or now)
        if "hours" in changes and changes["hours"] is not None:
            hours = float(changes["hours"])  # type: ignore[arg-type]
            if hours < 0 or hours > 24:
                raise PersonalTaskError("HOURS_INVALID", "hours must be between 0 and 24")
            row.hours = Decimal(str(round(hours, 2)))
        if "start_time" in changes:
            row.start_time = _clock(changes["start_time"], "start_time")  # type: ignore[arg-type]
        if "remind_at" in changes:
            row.remind_at = _clock(changes["remind_at"], "remind_at")  # type: ignore[arg-type]
        if "important" in changes and changes["important"] is not None:
            row.important = bool(changes["important"])
        if "urgent" in changes:
            # None puts the date back in charge.
            row.urgent = None if changes["urgent"] is None else bool(changes["urgent"])
        if "repeat_rule" in changes:
            row.repeat_rule = _repeat(changes["repeat_rule"])  # type: ignore[arg-type]
        if "status" in changes and changes["status"] is not None:
            status = str(changes["status"]).upper()
            if status not in STATUSES or status == "DELEGATED":
                raise PersonalTaskError("STATUS_INVALID", "status must be one of PLANNED, DONE, SKIPPED")
            if status in ("DONE", "SKIPPED") and row.status == "PLANNED":
                row.done_quadrant = quadrant_of(row)
                _spawn_next(session, row, now)
            if status == "PLANNED":
                row.done_quadrant = None
            row.status = status
            row.done_at = now if status == "DONE" else None
        row.updated_at = now
        session.commit()
        return _dict(row)


def delete_task(user_id: str, task_id: str) -> bool:
    with get_session() as session:
        row = session.get(PersonalTask, task_id)
        if row is None or str(row.user_id) != str(user_id):
            return False
        session.delete(row)
        session.commit()
        return True


def delegate(user_id: str, task_id: str, *, member_id: str, project_id: str, task_date: date, hours: float | None, actor_name: str) -> dict[str, object]:
    """Hand a task to a staff member: it becomes support work in that person's plan for the day (no Issue), and the
    task is marked as given away, with a link to the plan (FR-PER-06)."""
    from app.modules.planning.service import PlanningValidationError, planning_service
    from app.schemas import PlanningAssignmentCreate, PlanningRunCreate

    now = datetime.now(timezone.utc)
    with get_session() as session:
        row = session.get(PersonalTask, task_id)
        if row is None or str(row.user_id) != str(user_id):
            return {}
        if row.status != "PLANNED":
            raise PersonalTaskError("TASK_NOT_OPEN", "Chỉ giao được việc chưa làm")
        member = session.get(WorkforceMember, member_id)
        if member is None or member.status != "ACTIVE":
            raise PersonalTaskError("MEMBER_REQUIRED", "Chọn một nhân sự đang hoạt động")
        title, planned = row.title, float(hours if hours is not None else (row.hours or 1)) or 1.0
    try:
        run = planning_service.create_run(PlanningRunCreate(plan_date=task_date, project_ids=[project_id]), user_id)
        made = planning_service.add_assignment(run["id"], PlanningAssignmentCreate(
            expected_run_version=run["version"], project_id=run["project_scope"][0] if run.get("project_scope") else project_id, member_id=member_id, slot="MORNING",
            work_type="SUPPORT", is_primary=False, planned_hours=planned, source_type="FORM", source_reference=f"Việc riêng của {actor_name}: {title}"[:512],
        ), user_id)
    except PlanningValidationError as error:
        raise PersonalTaskError(error.code, error.message) from error
    with get_session() as session:
        row = session.get(PersonalTask, task_id)
        row.status, row.delegated_member_id, row.delegated_assignment_id = "DELEGATED", member_id, made["id"]
        row.done_quadrant = quadrant_of(row)
        row.updated_at = now
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project_id, actor_type="USER", actor_id=user_id, event_type="personal_task.delegated",
            entity_type="personal_task", entity_id=row.id, details={"member_id": member_id, "run_id": run["id"], "assignment_id": made["id"], "task_date": task_date.isoformat()}, created_at=now,
        ))
        session.commit()
        out = _dict(row)
    out["plan"] = {"run_id": run["id"], "project_id": project_id, "plan_date": task_date.isoformat()}
    return out


def week_block(session, user_id: str, week_start: date, week_end: date) -> dict[str, object]:
    """The person's own week in numbers (FR-PER-06): what was finished by quadrant (as it stood when finished), what
    is still open by quadrant, how much was handed on, how many nights work rolled over."""
    start_dt = datetime.combine(week_start, datetime.min.time(), tzinfo=timezone.utc) - timedelta(hours=7)
    end_dt = start_dt + timedelta(days=7)
    rows = session.scalars(select(PersonalTask).where(PersonalTask.user_id == user_id, PersonalTask.archived_at.is_(None))).all()
    done = [row for row in rows if row.status == "DONE" and row.done_at and start_dt <= row.done_at.replace(tzinfo=row.done_at.tzinfo or timezone.utc) < end_dt]
    delegated = [row for row in rows if row.status == "DELEGATED" and start_dt <= row.updated_at.replace(tzinfo=row.updated_at.tzinfo or timezone.utc) < end_dt]
    open_rows = [row for row in rows if row.status == "PLANNED" and row.task_date is not None and week_start <= row.task_date <= week_end]
    by_done = {q: [row for row in done if (row.done_quadrant or 4) == q] for q in QUADRANTS}
    by_open = {q: [row for row in open_rows if quadrant_of(row) == q] for q in QUADRANTS}
    hours = lambda items: round(sum(float(r.hours or 0) for r in items), 2)
    focus_total = hours(by_done[1]) + hours(by_done[2])
    return {
        "done": [{"quadrant": q, "label": QUADRANTS[q], "count": len(items), "hours": hours(items)} for q, items in by_done.items()],
        "open": [{"quadrant": q, "label": QUADRANTS[q], "count": len(items), "hours": hours(items)} for q, items in by_open.items()],
        "done_total": len(done), "done_hours": hours(done), "delegated": len(delegated),
        "rollovers": sum(int(row.rollover_count or 0) for row in open_rows + done),
        "schedule_share": round(hours(by_done[2]) / focus_total, 2) if focus_total else None,
    }


def weekly_review_message(session, user_id: str, today: date, link: str) -> str | None:
    """Sunday evening: what to tidy before the week starts; None when there is nothing to say."""
    rows = session.scalars(select(PersonalTask).where(PersonalTask.user_id == user_id, PersonalTask.archived_at.is_(None), PersonalTask.status == "PLANNED")).all()
    undated = [row for row in rows if row.task_date is None]
    lingering = [row for row in rows if row.task_date is not None and row.task_date < today]
    rolled = [row for row in rows if int(row.rollover_count or 0) > ROLLOVER_WARN]
    dropping = [row for row in rows if quadrant_of(row, today) == 4 and row.updated_at.replace(tzinfo=row.updated_at.tzinfo or timezone.utc) <= datetime.now(timezone.utc) - timedelta(days=5)]
    last = week_block(session, user_id, today - timedelta(days=today.weekday()), today - timedelta(days=today.weekday()) + timedelta(days=6))
    parts = []
    if undated:
        parts.append(f"{len(undated)} việc chưa có ngày")
    if lingering or rolled:
        parts.append(f"{len(lingering)} việc tồn, {len(rolled)} việc dời quá {ROLLOVER_WARN} lần")
    if dropping:
        parts.append(f"{len(dropping)} việc ở ô Bỏ sắp lưu trữ")
    done_line = ""
    if last["done_total"]:
        q1 = next(x for x in last["done"] if x["quadrant"] == 1)
        q2 = next(x for x in last["done"] if x["quadrant"] == 2)
        done_line = f"Tuần qua xong {last['done_total']} việc ({last['done_hours']:g}h): Làm ngay {q1['hours']:g}h, Lên lịch {q2['hours']:g}h" + (f", giao đi {last['delegated']}" if last["delegated"] else "") + "."
    if not parts and not done_line:
        return None
    lines = ["<b>Dọn việc riêng cho tuần tới</b>"]
    if parts:
        lines.append("Cần xếp: " + "; ".join(parts) + ".")
    if done_line:
        lines.append(done_line)
    lines.append(f"Ma trận tuần tới: {link}")
    return "\n".join(lines)
