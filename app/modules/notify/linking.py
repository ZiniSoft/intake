"""Who the bot talks to (FR-NTF-02, FR-NTF-03): a project's group, joined by typing `/lien-ket <mã dự án>` in it, and
each person's private chat, joined by opening a one-time invite link. Holidays switch the reminders off.

Only linking is read from Telegram; nothing people write there becomes an Intake in this slice.
"""
from __future__ import annotations

import re
import secrets
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import AuditEvent, Holiday, Project, TelegramState, User, WorkforceMember
from app.modules.planning.overview import LOCAL_TZ
from app.modules.planning.personal import next_working_day
from app.modules.notify.telegram import TelegramClient, TelegramError, escape

# A picture or a PDF the bot is sent in a private chat becomes a request with that file (FR-AI-14, ADR-0061).
PICTURE_MIME = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
PICTURE_MAX_BYTES = 5 * 1024 * 1024

LINK_COMMANDS = ("/lien-ket", "/lienket", "/link")
UNLINK_COMMANDS = ("/huy-lien-ket", "/huylienket", "/unlink")
INVITE_TTL_DAYS = 7


def invite_link(code: str) -> str | None:
    username = (get_settings().telegram_bot_username or "").lstrip("@")
    return f"https://t.me/{username}?start={code}" if username else None


def create_invite(member_id: str, actor_id: str) -> dict[str, object] | None:
    """A fresh one-time code for a member; the link opens the bot with that code."""
    with get_session() as session:
        member = session.get(WorkforceMember, member_id)
        if member is None:
            return None
        code = secrets.token_urlsafe(12).replace("-", "x").replace("_", "y")[:16]
        member.telegram_invite_code = code
        member.updated_at = datetime.now(timezone.utc)
        session.add(AuditEvent(
            id=str(uuid4()), project_id=None, actor_type="USER", actor_id=actor_id, event_type="notify.telegram.invite-created",
            entity_type="workforce_member", entity_id=member.id, details=None, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
        return {"member_id": str(member.id), "code": code, "link": invite_link(code), "linked": bool(member.telegram_chat_id)}


def unlink_member(member_id: str, actor_id: str) -> bool:
    with get_session() as session:
        member = session.get(WorkforceMember, member_id)
        if member is None:
            return False
        member.telegram_chat_id, member.telegram_username, member.telegram_invite_code, member.telegram_linked_at = None, None, None, None
        session.add(AuditEvent(
            id=str(uuid4()), project_id=None, actor_type="USER", actor_id=actor_id, event_type="notify.telegram.member-unlinked",
            entity_type="workforce_member", entity_id=member.id, details=None, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
        return True


def unlink_project(project_id: str, actor_id: str) -> bool:
    with get_session() as session:
        project = session.get(Project, project_id)
        if project is None:
            return False
        project.telegram_chat_id, project.telegram_thread_id, project.telegram_chat_title, project.telegram_linked_at = None, None, None, None
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id, event_type="notify.telegram.project-unlinked",
            entity_type="project", entity_id=project.id, details=None, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
        return True


def _topic_of(message: dict) -> tuple[int | None, str | None]:
    """The topic a group message was posted in (None in a plain group or in General), and its name when Telegram says."""
    if not message.get("is_topic_message"):
        return None, None
    try:
        thread_id = int(message.get("message_thread_id") or 0) or None
    except (TypeError, ValueError):
        thread_id = None
    replied = message.get("reply_to_message") if isinstance(message.get("reply_to_message"), dict) else {}
    created = replied.get("forum_topic_created") if isinstance(replied.get("forum_topic_created"), dict) else {}
    name = str(created.get("name") or "").strip() or None
    return thread_id, name


def handle_update(update: dict) -> tuple[str, str, int | None] | None:
    """One Telegram update in, maybe one reply out: (chat_id, html text, topic to answer in). Everything else is ignored."""
    message = update.get("message") if isinstance(update, dict) else None
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    chat_id = str(chat.get("id") or "")
    text = str(message.get("text") or "").strip()
    if chat_id and chat.get("type") == "private" and (message.get("photo") or message.get("document")):
        return chat_id, _picture(chat_id, message, datetime.now(timezone.utc)), None
    if chat_id and chat.get("type") == "private" and PROPOSAL_PREFIX.match(text):
        return chat_id, _proposal(chat_id, PROPOSAL_PREFIX.sub("", text, count=1).strip()), None
    if chat_id and chat.get("type") == "private" and FEEDBACK_PREFIX.match(text):
        return chat_id, _feedback_text(chat_id, FEEDBACK_PREFIX.sub("", text, count=1).strip(), message), None
    if not chat_id or not text.startswith("/"):
        return None
    command, _, argument = text.partition(" ")
    command = command.split("@", 1)[0].lower()
    argument = argument.strip()
    now = datetime.now(timezone.utc)
    if command == "/start":
        return chat_id, _start(chat_id, chat, sender, argument, now), None
    if chat.get("type") in ("group", "supergroup"):
        thread_id, topic_name = _topic_of(message)
        if command in LINK_COMMANDS:
            return chat_id, _link_project(chat_id, chat, argument, now, thread_id, topic_name), thread_id
        if command in UNLINK_COMMANDS:
            return chat_id, _unlink_project_here(chat_id, thread_id, now), thread_id
        return None
    if command in LINK_COMMANDS:
        return chat_id, "Lệnh này dùng trong nhóm của dự án: thêm bot vào nhóm rồi gõ /lien-ket &lt;mã dự án&gt;.", None
    return None


def _start(chat_id: str, chat: dict, sender: dict, code: str, now: datetime) -> str:
    if chat.get("type") != "private":
        return "Bấm link mời của mình trong tin nhắn riêng với bot nhé."
    if not code:
        return "Chào bạn. Để nhận nhắc việc, bấm link mời do CTO gửi (Cài đặt &gt; Nhân sự &gt; Link mời Telegram)."
    with get_session() as session:
        member = session.scalar(select(WorkforceMember).where(WorkforceMember.telegram_invite_code == code))
        if member is None:
            return "Mã mời không đúng hoặc đã dùng. Nhờ CTO tạo link mời mới."
        member.telegram_chat_id = chat_id
        member.telegram_username = str(sender.get("username") or "") or None
        member.telegram_invite_code = None
        member.telegram_linked_at = now
        member.updated_at = now
        session.add(AuditEvent(
            id=str(uuid4()), project_id=None, actor_type="SYSTEM", actor_id="telegram-bot", event_type="notify.telegram.member-linked",
            entity_type="workforce_member", entity_id=member.id, details={"username": member.telegram_username}, created_at=now,
        ))
        session.commit()
        return f"Đã gắn Telegram với <b>{escape(member.display_name)}</b>. Từ nay bạn nhận kế hoạch ngày lúc 08:00 và nhắc báo cáo ở đây."


PROPOSAL_PREFIX = re.compile(r"^\s*/?(đề\s*xuất|de\s*xuat|de-xuat)\b[:\s]*", re.IGNORECASE)
FEEDBACK_PREFIX = re.compile(r"^\s*/?(góp\s*ý|gop\s*y|gop-y)\b[:\s]*", re.IGNORECASE)
PROPOSAL_HOURS = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*(h|giờ|gio)\b", re.IGNORECASE)
PROPOSAL_ISSUE = re.compile(r"#(\d{1,12})\b")
PROPOSAL_INTAKE = re.compile(r"\b([A-Z]{2,6}-\d{2}W\d{2}-\d{3})\b")


def _proposal(chat_id: str, body: str) -> str:
    """"đề xuất [mã dự án] [#Issue | mã Intake] [Xh] [mai] lời việc" from a linked person: the work waits on the day's
    plan of that project with their name (FR-PLAN-35). One project needs no code; "mai" means the next working day."""
    from app.modules.planning.add_work import add_work_service
    from app.modules.planning.service import PlanningValidationError
    from app.models import WorkforceProjectMembership

    with get_session() as session:
        member = session.scalar(select(WorkforceMember).where(WorkforceMember.telegram_chat_id == chat_id, WorkforceMember.status == "ACTIVE"))
        if member is None:
            return "Bot chưa biết bạn là ai. Bấm link mời do CTO gửi (Cài đặt &gt; Nhân sự &gt; Link mời Telegram) rồi gửi lại."
        projects = session.scalars(
            select(Project).join(WorkforceProjectMembership, WorkforceProjectMembership.project_id == Project.id)
            .where(WorkforceProjectMembership.member_id == member.id, WorkforceProjectMembership.active.is_(True), Project.status == "ACTIVE", Project.kind == "SOFTWARE")
            .order_by(Project.code)
        ).all()
        choices = [(project.code, project.name, str(project.id)) for project in projects]
        member_id, member_user = str(member.id), None
        user = session.scalar(select(User).where(User.member_id == member.id, User.is_active.is_(True)))
        member_user = str(user.id) if user is not None else None
    if not choices:
        return "Bạn chưa thuộc dự án phần mềm nào; nhờ CTO thêm bạn ở Cài đặt &gt; Nhân sự."
    words = body.split()
    picked = None
    if words and any(words[0].lower() == code.lower() for code, _, _ in choices):
        picked = next(row for row in choices if row[0].lower() == words[0].lower())
        body = " ".join(words[1:])
    elif len(choices) == 1:
        picked = choices[0]
    else:
        codes = ", ".join(code for code, _, _ in choices)
        return f"Bạn ở nhiều dự án: bắt đầu bằng mã dự án ({escape(codes)}), ví dụ \"đề xuất {escape(choices[0][0])} #12 2h\"."
    today = datetime.now(LOCAL_TZ).date()
    day = today
    if re.search(r"\b(mai|ngày mai|ngay mai)\b", body, re.IGNORECASE):
        day = next_working_day(today, _holidays())
        body = re.sub(r"\b(ngày mai|ngay mai|mai)\b", "", body, flags=re.IGNORECASE)
    hours = None
    hours_match = PROPOSAL_HOURS.search(body)
    if hours_match:
        hours = float(hours_match.group(1).replace(",", "."))
        body = PROPOSAL_HOURS.sub("", body, count=1)
    issue = None
    issue_match = PROPOSAL_ISSUE.search(body)
    if issue_match:
        issue = issue_match.group(1)
        body = PROPOSAL_ISSUE.sub("", body, count=1)
    intake = None
    intake_match = PROPOSAL_INTAKE.search(body)
    if intake_match:
        intake = intake_match.group(1)
        body = PROPOSAL_INTAKE.sub("", body, count=1)
    text = re.sub(r"\s+", " ", body).strip(" ,.;:")
    code, project_name, project_id = picked
    try:
        result = add_work_service.propose_work(
            project_id, member_id, day, actor_id=member_user or member_id, text=text or None, issue=issue, intake_ref=intake, hours=hours, slot=None, channel="Telegram",
        )
    except PlanningValidationError as error:
        if error.code == "PLANNING_RUN_IMMUTABLE":
            return f"Kế hoạch {day:%d/%m} của {escape(project_name)} đã chốt; thêm chữ \"mai\" để đề xuất cho ngày làm việc kế tiếp."
        if error.code == "PROPOSAL_TEXT_REQUIRED":
            return "Ghi việc muốn làm, hoặc số Issue (#12), hoặc mã Intake, ví dụ \"đề xuất #12 2h sửa đăng nhập\"."
        return f"Không ghi được đề xuất: {escape(str(error))}"
    what = f"#{result['gitlab_issue_external_id']} " if result.get("gitlab_issue_external_id") else ""
    if not result.get("created"):
        return f"Đề xuất {what}{escape(str(result['title']))} cho {day:%d/%m} đã có từ trước."
    return f"Đã ghi đề xuất {what}<b>{escape(str(result['title']))}</b> vào kế hoạch {day:%d/%m} của {escape(project_name)}{f' ({hours:g}h)' if hours else ''}. Project Owner sẽ xếp hoặc bỏ qua."


def _member_choices(session, chat_id: str):
    """The linked person and their software projects, or the line to answer when there is none."""
    from app.models import WorkforceProjectMembership

    member = session.scalar(select(WorkforceMember).where(WorkforceMember.telegram_chat_id == chat_id, WorkforceMember.status == "ACTIVE"))
    if member is None:
        return None, [], None
    projects = session.scalars(
        select(Project).join(WorkforceProjectMembership, WorkforceProjectMembership.project_id == Project.id)
        .where(WorkforceProjectMembership.member_id == member.id, WorkforceProjectMembership.active.is_(True), Project.status == "ACTIVE", Project.kind == "SOFTWARE")
        .order_by(Project.code)
    ).all()
    user = session.scalar(select(User).where(User.member_id == member.id, User.is_active.is_(True)))
    return member, [(project.code, project.name, str(project.id)) for project in projects], user


def _decides(user) -> bool:
    """The CTO and Project Owners create requests directly; everyone else suggests (FR-FBK-01)."""
    return user is not None and user.role in ("CTO", "PROJECT_OWNER")


def _feedback_text(chat_id: str, body: str, message: dict) -> str:
    """"góp ý [mã dự án] lời góp ý" from a linked person: a suggestion waiting for the Project Owner."""
    from app.modules.intake.feedback import FeedbackError, feedback_service

    with get_session() as session:
        member, choices, user = _member_choices(session, chat_id)
        member_id, user_id = (str(member.id), str(user.id) if user else None) if member else (None, None)
    if member is None:
        return "Bot chưa biết bạn là ai. Bấm link mời do CTO gửi (Cài đặt &gt; Nhân sự &gt; Link mời Telegram) rồi gửi lại."
    if not choices:
        return "Bạn chưa thuộc dự án phần mềm nào; nhờ CTO thêm bạn ở Cài đặt &gt; Nhân sự."
    words = body.split()
    picked = None
    if words and any(words[0].lower() == code.lower() for code, _, _ in choices):
        picked = next(row for row in choices if row[0].lower() == words[0].lower())
        body = " ".join(words[1:])
    elif len(choices) == 1:
        picked = choices[0]
    else:
        codes = ", ".join(code for code, _, _ in choices)
        return f"Bạn ở nhiều dự án: bắt đầu bằng mã dự án ({escape(codes)}), ví dụ \"góp ý {escape(choices[0][0])} màn đăng nhập báo sai mật khẩu dù đúng\"."
    code, project_name, project_id = picked
    try:
        row = feedback_service.create(project_id=project_id, text=body, transport="TELEGRAM", user_id=user_id, member_id=member_id,
                                      idempotency_key=f"telegram:{chat_id}:{message.get('message_id')}")
    except FeedbackError as error:
        if error.code == "TEXT_REQUIRED":
            return "Ghi điều nên làm sau chữ \"góp ý\", ví dụ \"góp ý màn đăng nhập báo sai mật khẩu dù đúng\"."
        return f"Không ghi được góp ý: {escape(str(error))}"
    if not row.get("created"):
        return "Góp ý này đã được nhận rồi."
    return f"Đã ghi góp ý cho <b>{escape(project_name)}</b>; Project Owner sẽ nhận hoặc trả lời. Gửi thêm ảnh trong vài phút tới nếu cần."


def _holidays() -> set[date]:
    with get_session() as session:
        return {row.day for row in session.scalars(select(Holiday)).all()}


def download_telegram_file(file_id: str) -> bytes:
    """The bytes behind a Telegram file id; tests replace this."""
    client = TelegramClient()
    path = str(client.get_file(file_id).get("file_path") or "")
    if not path:
        raise TelegramError("TELEGRAM_REJECTED", error_type="TelegramAPIError")
    return client.download(path)


def _picture(chat_id: str, message: dict, now: datetime) -> str:
    """A linked person sends a picture (a chat screenshot, a photo of a page) or a PDF: it becomes a request of one
    of their projects, the file attached, and the AI reads both. The caption may start with the project code and
    goes in as the text; without a code the person's only software project is taken."""
    from app.schemas import IntakeCreate
    from app.services.attachment_service import store_attachment
    from app.services.attachment_reader import AttachmentCheckError
    from app.services.intake_service import intake_store
    from app.services.processing_repository import processing_repository
    from app.models import WorkforceProjectMembership

    with get_session() as session:
        member = session.scalar(select(WorkforceMember).where(WorkforceMember.telegram_chat_id == chat_id, WorkforceMember.status == "ACTIVE"))
        if member is None:
            return "Bot chưa biết bạn là ai. Bấm link mời do CTO gửi (Cài đặt &gt; Nhân sự &gt; Link mời Telegram) rồi gửi lại ảnh."
        projects = session.scalars(
            select(Project).join(WorkforceProjectMembership, WorkforceProjectMembership.project_id == Project.id)
            .where(WorkforceProjectMembership.member_id == member.id, WorkforceProjectMembership.active.is_(True), Project.status == "ACTIVE", Project.kind == "SOFTWARE")
            .order_by(Project.code)
        ).all()
        choices = [(project.code, project.name, project.id) for project in projects]
        member_name = member.display_name
    if not choices:
        return "Bạn chưa thuộc dự án phần mềm nào nên chưa gửi yêu cầu được; nhờ CTO thêm bạn ở Cài đặt &gt; Nhân sự."
    caption = str(message.get("caption") or "").strip()
    head, _, rest = caption.partition(" ")
    picked = next((row for row in choices if head.lower() == row[0].lower()), None)
    text = rest.strip() if picked else caption
    if picked is None:
        if len(choices) != 1:
            codes = ", ".join(code for code, _, _ in choices)
            return f"Bạn ở nhiều dự án: gửi lại ảnh với chú thích bắt đầu bằng mã dự án ({escape(codes)}), ví dụ \"{escape(choices[0][0])} khách báo lỗi đăng nhập\"."
        picked = choices[0]
    code, project_name, project_id = picked
    with get_session() as session:
        member_row, _, user_row = _member_choices(session, chat_id)
        decides = _decides(user_row)
        member_id, user_id = (str(member_row.id), str(user_row.id) if user_row else None) if member_row else (None, None)
    # The file: the largest rendering of a photo, or a document of an allowed type within the limit.
    if message.get("document"):
        document = message["document"] if isinstance(message["document"], dict) else {}
        mime = str(document.get("mime_type") or "").lower()
        if mime not in PICTURE_MIME:
            return "Bot chỉ nhận ảnh (JPG, PNG, WebP) hoặc PDF."
        if int(document.get("file_size") or 0) > PICTURE_MAX_BYTES:
            return "Tệp quá 5 MB; gửi ảnh nhỏ hơn hoặc chụp lại."
        file_id, name = str(document.get("file_id") or ""), str(document.get("file_name") or "tep-telegram")
    else:
        photos = [row for row in message.get("photo") or [] if isinstance(row, dict)]
        if not photos:
            return "Không đọc được ảnh này; gửi lại giúp."
        largest = max(photos, key=lambda row: int(row.get("file_size") or 0))
        if int(largest.get("file_size") or 0) > PICTURE_MAX_BYTES:
            return "Ảnh quá 5 MB; gửi ảnh nhỏ hơn."
        file_id, name, mime = str(largest.get("file_id") or ""), f"telegram-{message.get('message_id') or 'anh'}.jpg", "image/jpeg"
    try:
        content = download_telegram_file(file_id)
    except TelegramError:
        return "Không tải được ảnh từ Telegram; gửi lại sau ít phút."
    if not message.get("document"):
        # Telegram re-encodes photos as JPEG, but the bytes decide: the stored type must match them (FR-AI-09).
        from app.services.attachment_reader import detect_mime

        mime = detect_mime(content) or "image/jpeg"
        name = f"telegram-{message.get('message_id') or 'anh'}.{ 'png' if mime == 'image/png' else 'webp' if mime == 'image/webp' else 'jpg' }"
    if not decides:
        # A member's picture waits for the Project Owner as a suggestion (FR-FBK-01); the owner's and the CTO's go straight in.
        from app.modules.intake.feedback import FeedbackError, feedback_service

        try:
            row = feedback_service.create(
                project_id=project_id, text=text or f"Ảnh {member_name} gửi qua Telegram {now.astimezone().strftime('%d/%m %H:%M')}",
                transport="TELEGRAM", user_id=user_id, member_id=member_id, files=[(name, mime, content)],
                idempotency_key=f"telegram:{chat_id}:{message.get('message_id')}",
            )
        except AttachmentCheckError as error:
            return f"Tệp không đúng loại ({escape(error.code)}); gửi lại ảnh JPG, PNG, WebP hoặc PDF."
        except FeedbackError as error:
            return f"Không ghi được góp ý: {escape(str(error))}"
        if not row.get("created"):
            return "Ảnh này đã được nhận rồi."
        return f"Đã ghi góp ý kèm ảnh cho <b>{escape(project_name)}</b>; Project Owner sẽ nhận hoặc trả lời. Muốn thêm chữ thì gửi \"góp ý ...\" trước ảnh lần sau."
    payload = IntakeCreate(
        project_id=code, channel="TELEGRAM", sender_reference=member_name,
        raw_text=text or f"Ảnh {member_name} gửi qua Telegram {now.astimezone().strftime('%d/%m %H:%M')}",
    )
    try:
        item = intake_store.create(payload, idempotency_key=f"telegram:{chat_id}:{message.get('message_id')}")
    except RuntimeError:
        return "Ảnh này đã được nhận rồi."
    if not processing_repository.list_runs(item.id):
        try:
            store_attachment(item.id, name, mime, content, read_now=False)
        except AttachmentCheckError as error:
            return f"Tệp không đúng loại ({escape(error.code)}); yêu cầu {escape(item.public_id)} đã tạo nhưng không có ảnh."
        processing_repository.enqueue_normalization(item.id)
    base = (get_settings().app_public_url or "").rstrip("/")
    link = f"{base}/intakes/{item.id}" if base else item.public_id
    return f"Đã tạo <b>{escape(item.public_id)}</b> cho {escape(project_name)}; AI đang đọc ảnh và chuẩn hóa. {escape(link)}"


def _same_place(chat_id: str, thread_id: int | None):
    """The filter for "this group, this topic": a plain group and its General topic are the same place."""
    return (Project.telegram_chat_id == chat_id, Project.telegram_thread_id.is_(None) if thread_id is None else Project.telegram_thread_id == thread_id)


def _link_project(chat_id: str, chat: dict, code: str, now: datetime, thread_id: int | None = None, topic_name: str | None = None) -> str:
    code = code.strip().strip("<>").lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,63}", code):
        return "Gõ /lien-ket &lt;mã dự án&gt;, với mã là mã dự án của bạn."
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == code, Project.status == "ACTIVE"))
        if project is None:
            return f"Không có dự án mã <code>{escape(code)}</code> đang hoạt động."
        other = session.scalar(select(Project).where(*_same_place(chat_id, thread_id), Project.id != project.id))
        if other is not None:
            where = "Chủ đề này" if thread_id else "Nhóm này"
            return f"{where} đang gắn với <b>{escape(other.name)}</b>. Gõ /huy-lien-ket trước nếu muốn đổi."
        title = str(chat.get("title") or "")[:200]
        if thread_id:
            title = f"{title} › {topic_name or f'chủ đề {thread_id}'}"
        project.telegram_chat_id = chat_id
        project.telegram_thread_id = thread_id
        project.telegram_chat_title = title[:255] or None
        project.telegram_linked_at = now
        project.updated_at = now
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project.id, actor_type="SYSTEM", actor_id="telegram-bot", event_type="notify.telegram.project-linked",
            entity_type="project", entity_id=project.id, details={"chat_title": project.telegram_chat_title}, created_at=now,
        ))
        session.commit()
        where = "Chủ đề này" if thread_id else "Nhóm này"
        return f"{where} nhận nhắc việc của dự án <b>{escape(project.name)}</b>: kế hoạch ngày mai lúc 17:30, nhắc lại 08:30 và 09:30, báo cáo lúc 17:30 và 08:00."


def _unlink_project_here(chat_id: str, thread_id: int | None, now: datetime) -> str:
    with get_session() as session:
        project = session.scalar(select(Project).where(*_same_place(chat_id, thread_id)))
        if project is None:
            return ("Chủ đề này" if thread_id else "Nhóm này") + " chưa gắn với dự án nào."
        name = project.name
        project.telegram_chat_id, project.telegram_thread_id, project.telegram_chat_title, project.telegram_linked_at = None, None, None, None
        project.updated_at = now
        session.commit()
        return f"Đã bỏ gắn nhóm khỏi dự án <b>{escape(name)}</b>."


# --- holidays and the bot's own state -----------------------------------------------------------------------------

def holidays() -> list[dict[str, object]]:
    with get_session() as session:
        return [{"day": row.day, "note": row.note} for row in session.scalars(select(Holiday).order_by(Holiday.day)).all()]


def set_holidays(days: list[tuple[date, str | None]], actor_id: str) -> list[dict[str, object]]:
    """Replace the holiday list with the one given."""
    with get_session() as session:
        for row in session.scalars(select(Holiday)).all():
            session.delete(row)
        session.flush()
        seen: set[date] = set()
        for day, note in days:
            if day in seen:
                continue
            seen.add(day)
            session.add(Holiday(day=day, note=(note or "").strip()[:200] or None, created_at=datetime.now(timezone.utc)))
        session.add(AuditEvent(
            id=str(uuid4()), project_id=None, actor_type="USER", actor_id=actor_id, event_type="notify.holidays-set",
            entity_type="holidays", entity_id=None, details={"count": len(seen)}, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
    return holidays()


def get_state(key: str) -> str | None:
    with get_session() as session:
        row = session.get(TelegramState, key)
        return row.value if row is not None else None


def set_state(key: str, value: str | None) -> None:
    with get_session() as session:
        row = session.get(TelegramState, key)
        if row is None:
            session.add(TelegramState(key=key, value=value, updated_at=datetime.now(timezone.utc)))
        else:
            row.value, row.updated_at = value, datetime.now(timezone.utc)
        session.commit()


def status() -> dict[str, object]:
    """What the settings page shows: is the bot configured, which projects and people are linked."""
    settings = get_settings()
    with get_session() as session:
        projects = session.scalars(select(Project).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE").order_by(Project.name)).all()
        members = session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE").order_by(WorkforceMember.display_name)).all()
        return {
            "bot_username": (settings.telegram_bot_username or get_state("bot_username") or "").lstrip("@") or None,
            "bot_seen_at": get_state("bot_seen_at"),
            "projects": [{"id": str(p.id), "code": p.code, "name": p.name, "chat_title": p.telegram_chat_title, "linked": bool(p.telegram_chat_id), "linked_at": p.telegram_linked_at} for p in projects],
            "members": [{"id": str(m.id), "display_name": m.display_name, "username": m.telegram_username, "linked": bool(m.telegram_chat_id), "linked_at": m.telegram_linked_at, "invite_pending": bool(m.telegram_invite_code)} for m in members],
            "holidays": holidays(),
        }
