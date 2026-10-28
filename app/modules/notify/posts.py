"""Telegram reminders around a post's hour (FR-MKT-15, ADR-0067): the day's schedule in the morning, a private nudge
an hour before a version is due to the person who posts it by hand, a nudge to the owner when a version on an
auto-publish channel is still not approved, and a late note half an hour after the hour when nothing was marked
posted. Posts go out on any day of the week, so none of this waits for a working day. Messages carry titles, hours
and links into the app, never the words of the post."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

from app.models import ChannelRule, Project, WorkChannel, WorkforceMember, WorkItem
from app.modules.notify.reminders import WINDOW_MINUTES, Message, app_link
from app.modules.notify.telegram import escape
from app.modules.planning.overview import LOCAL_TZ
from app.modules.work.links import links_of

DUE_LEAD_MINUTES = 60
LATE_AFTER_MINUTES = 30
DIGEST_CLOCK = "08:00"


def _aware(value: datetime | None) -> datetime | None:
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _in_window(at: datetime, now_local: datetime) -> bool:
    return at <= now_local < at + timedelta(minutes=WINDOW_MINUTES)


def _versions_around(session, projects: list[Project], now_local: datetime) -> list[tuple[WorkChannel, WorkItem, Project]]:
    """Every dated, unpublished version of an open post of these projects within a day either side of now."""
    if not projects:
        return []
    start = (now_local - timedelta(hours=26)).astimezone(timezone.utc)
    end = (now_local + timedelta(hours=26)).astimezone(timezone.utc)
    by_id = {str(project.id): project for project in projects}
    rows = session.execute(
        select(WorkChannel, WorkItem).join(WorkItem, WorkItem.id == WorkChannel.work_id)
        .where(WorkItem.project_id.in_(list(by_id)), WorkItem.status.not_in(("CANCELLED",)), WorkItem.parent_id.is_(None),
               WorkChannel.publish_at.is_not(None), WorkChannel.publish_at >= start, WorkChannel.publish_at < end)
        .order_by(WorkChannel.publish_at)
    ).all()
    return [(version, work, by_id[str(work.project_id)]) for version, work in rows]


def _people(session, work: WorkItem, project: Project) -> tuple[WorkforceMember | None, WorkforceMember | None]:
    member = session.get(WorkforceMember, work.member_id) if work.member_id else None
    owner = session.get(WorkforceMember, project.owner_member_id) if project.owner_member_id else None
    return member, owner


def _card(project: Project, work: WorkItem) -> str:
    return escape(app_link(f"/viec?project={project.id}&work={work.id}"))


def due_message(label: str, clock: str, work: WorkItem, project: Project, version: WorkChannel, short_link: str | None) -> str:
    words = f"đã có {len(version.text):,} ký tự".replace(",", ".") if version.text else "chưa có trong thẻ"
    link = f"Link rút gọn để dán vào bài: {escape(short_link)}" if short_link else "Chưa có link rút gọn; bấm Lấy link trong thẻ nếu bài dẫn về trang nào."
    return "\n".join([
        f"<b>Sắp đến giờ đăng {clock}</b> · {escape(label)}",
        f"{escape(work.title)} ({escape(work.code)}) · chữ bản kênh: {words}",
        link,
        f"Đăng xong thì dán link bài và bấm Đã đăng trong thẻ: {_card(project, work)}",
    ])


def need_ok_message(label: str, clock: str, work: WorkItem, project: Project, status_word: str) -> str:
    return "\n".join([
        f"<b>Bài sẽ tự đăng lúc {clock}</b> · {escape(label)} · nhưng còn ở {escape(status_word)}",
        f"{escape(work.title)} ({escape(work.code)}): luồng đăng chỉ lấy bài Đã duyệt. Duyệt ở {escape(app_link('/duyet'))} hoặc đổi giờ trong thẻ: {_card(project, work)}",
    ])


def late_message(label: str, clock: str, work: WorkItem, project: Project, auto: bool) -> str:
    why = "Luồng đăng chưa báo về; kiểm tra luồng hoặc đăng tay rồi dán link." if auto else "Đăng rồi thì dán link và bấm Đã đăng; chưa đăng thì đổi giờ trong thẻ."
    return f"<b>Quá giờ đăng {clock}</b> · {escape(label)} · {escape(work.title)} ({escape(work.code)}) chưa đánh dấu Đã đăng.\n{why} {_card(project, work)}"


def digest_message(project: Project, day: date, rows: list[tuple[str, str, str, str | None, bool, str]]) -> str:
    lines = [f"<b>Lịch đăng hôm nay {day:%d/%m}</b> · {escape(project.name)}"]
    for clock, label, title, person, auto, state in rows:
        lines.append(f"• {clock} {escape(label)} · {escape(title)}" + (f" · {escape(person)}" if person else "") + (" · tự đăng" if auto else "") + (f" · {state}" if state else ""))
    lines.append(f"Tuần này: {escape(app_link(f'/tuan-nay?project={project.id}'))}")
    return "\n".join(lines)


POST_STATUS_WORDS = {"DISCUSS": "Ý tưởng", "READY": "Ý tưởng", "IN_PROGRESS": "Đang làm", "ACCEPTANCE": "Chờ duyệt", "APPROVED": "Đã duyệt", "DONE": "Đã đăng"}


def post_messages(session, now_local: datetime) -> list[Message]:
    """Everything a post's hour asks for at this moment, on any day."""
    today = now_local.date()
    projects = session.scalars(select(Project).where(Project.status == "ACTIVE", Project.kind == "NON_CODE").order_by(Project.name)).all()
    if not projects:
        return []
    rules = {row.code: row for row in session.scalars(select(ChannelRule)).all()}
    rows = _versions_around(session, projects, now_local)
    links = links_of(session, [str(version.id) for version, _, _ in rows]) if rows else {}
    out: list[Message] = []
    digest: dict[str, list[tuple[str, str, str, str | None, bool, str]]] = {}
    for version, work, project in rows:
        when = _aware(version.publish_at).astimezone(LOCAL_TZ)
        rule = rules.get(version.channel)
        label = rule.label if rule is not None else version.channel
        auto = bool(rule is not None and rule.auto_publish and rule.enabled)
        clock = when.strftime("%H:%M")
        member, owner = _people(session, work, project)
        slot = str(version.id)[:8]
        published = version.status == "PUBLISHED"
        if when.date() == today:
            state = "đã đăng" if published else ("chưa duyệt" if work.status != "APPROVED" else "")
            digest.setdefault(str(project.id), []).append((clock, label, work.title, member.display_name if member else None, auto, state))
        if published:
            continue
        if _in_window(when - timedelta(minutes=DUE_LEAD_MINUTES), now_local):
            if auto:
                if work.status != "APPROVED" and owner is not None and owner.telegram_chat_id:
                    out.append(Message("POST_NEED_OK", owner.telegram_chat_id, need_ok_message(label, clock, work, project, POST_STATUS_WORDS.get(work.status, work.status)), today, slot, project_id=str(project.id), member_id=str(owner.id)))
            else:
                who = member if member is not None and member.telegram_chat_id else owner
                if who is not None and who.telegram_chat_id:
                    out.append(Message("POST_DUE", who.telegram_chat_id, due_message(label, clock, work, project, version, (links.get(str(version.id)) or {}).get("url")), today, slot, project_id=str(project.id), member_id=str(who.id)))
        if _in_window(when + timedelta(minutes=LATE_AFTER_MINUTES), now_local):
            seen: set[str] = set()
            for who in (member, owner):
                if who is None or not who.telegram_chat_id or who.telegram_chat_id in seen:
                    continue
                seen.add(who.telegram_chat_id)
                out.append(Message("POST_LATE", who.telegram_chat_id, late_message(label, clock, work, project, auto), today, slot, project_id=str(project.id), member_id=str(who.id)))
    # The day's schedule, once in the morning: to the project's group when linked, else privately to the owner.
    hour, minute = (int(part) for part in DIGEST_CLOCK.split(":"))
    if _in_window(now_local.replace(hour=hour, minute=minute, second=0, microsecond=0), now_local):
        for project in projects:
            items = sorted(digest.get(str(project.id)) or [])
            if not items:
                continue
            text = digest_message(project, today, items)
            if project.telegram_chat_id:
                out.append(Message("POSTS_TODAY", project.telegram_chat_id, text, today, DIGEST_CLOCK, project_id=str(project.id), thread_id=project.telegram_thread_id))
            else:
                owner = session.get(WorkforceMember, project.owner_member_id) if project.owner_member_id else None
                if owner is not None and owner.telegram_chat_id:
                    out.append(Message("POSTS_TODAY", owner.telegram_chat_id, text, today, DIGEST_CLOCK, project_id=str(project.id), member_id=str(owner.id)))
    return out
