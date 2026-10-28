"""Reminders over Telegram (FR-NTF-01..05, ADR-0057): working days and holidays, the slots that are due, linking a
group and a person, what the messages say (never customer content), and sending each slot once."""
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import Holiday, Project, TelegramMessage, WorkforceMember
from app.modules.notify import linking, reminders
from app.modules.notify.telegram import TelegramClient, escape, mention
from app.modules.planning.overview import LOCAL_TZ

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def test_working_days_skip_weekends_and_holidays_and_slots_open_for_a_window() -> None:
    holidays = {date(2026, 10, 15)}
    assert reminders.is_working_day(date(2026, 10, 13), holidays)          # Tuesday
    assert not reminders.is_working_day(date(2026, 10, 17), holidays)      # Saturday
    assert not reminders.is_working_day(date(2026, 10, 15), holidays)      # a holiday
    assert reminders.next_working_day(date(2026, 10, 14), holidays) == date(2026, 10, 16)
    assert reminders.next_working_day(date(2026, 10, 16), holidays) == date(2026, 10, 19)
    assert reminders.previous_working_day(date(2026, 10, 19), holidays) == date(2026, 10, 16)
    at = lambda hour, minute, day=13: datetime(2026, 10, day, hour, minute, tzinfo=LOCAL_TZ)
    assert set(reminders.due_slots(at(8, 5), set())) == {"PLAN_TODAY", "REPORT_MISSING"}
    assert reminders.due_slots(at(8, 25), set()) == []
    assert set(reminders.due_slots(at(17, 31), set())) == {"PLAN_TOMORROW", "REPORT_TONIGHT"}
    assert set(reminders.due_slots(at(9, 45), set())) == {"PLAN_UNCLOSED_2", "OVERDUE"}
    assert reminders.due_slots(at(8, 5, day=17), set()) == []                # Saturday
    assert reminders.due_slots(at(8, 5), {date(2026, 10, 13)}) == []        # holiday


def test_the_bot_links_a_group_to_a_project_and_a_person_through_an_invite() -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        project_id = str(project.id)
    created = cto.post("/api/v1/planning/members", json={"display_name": "Telegram Test Person", "email_reference": f"tg-{uuid4().hex[:6]}@example.test"})
    assert created.status_code == 201, created.text
    member_id = created.json()["data"]["id"]
    try:
        # A wrong code, then the right one, from a group chat.
        reply = linking.handle_update({"update_id": 1, "message": {"chat": {"id": -100123, "type": "supergroup", "title": "Nhóm thử"}, "from": {"id": 5, "username": "someone"}, "text": "/lien-ket no-such-code"}})
        assert reply and "Không có dự án" in reply[1]
        reply = linking.handle_update({"update_id": 2, "message": {"chat": {"id": -100123, "type": "supergroup", "title": "Nhóm thử"}, "from": {"id": 5}, "text": "/lien-ket@intake_bot orbit"}})
        assert reply and reply[0] == "-100123" and "Orbit" in reply[1]
        with get_session() as session:
            project = session.get(Project, project_id)
            assert project.telegram_chat_id == "-100123" and project.telegram_chat_title == "Nhóm thử"
        # The same group cannot be claimed by a second project without unlinking.
        reply = linking.handle_update({"update_id": 3, "message": {"chat": {"id": -100123, "type": "supergroup"}, "from": {"id": 5}, "text": "/lien-ket ember"}})
        assert reply and "đang gắn với" in reply[1] and reply[2] is None
        # A topic inside the same group is another place: Ember takes topic 7, the reply goes to that topic.
        topic = {"chat": {"id": -100123, "type": "supergroup", "title": "Nhóm thử"}, "from": {"id": 5}, "is_topic_message": True, "message_thread_id": 7,
                 "reply_to_message": {"forum_topic_created": {"name": "Ember"}}, "text": "/lien-ket ember"}
        reply = linking.handle_update({"update_id": 30, "message": topic})
        assert reply and "Chủ đề này nhận nhắc việc" in reply[1] and reply[2] == 7
        with get_session() as session:
            ember = session.scalar(select(Project).where(Project.code == "ember"))
            assert ember.telegram_chat_id == "-100123" and ember.telegram_thread_id == 7 and ember.telegram_chat_title == "Nhóm thử › Ember"
            ember.telegram_chat_id, ember.telegram_thread_id, ember.telegram_chat_title, ember.telegram_linked_at = None, None, None, None
            session.commit()
        # A person: the CTO makes an invite, the person opens it (a /start with the code in a private chat).
        invite = cto.post(f"/api/v1/notify/telegram/members/{member_id}/invite")
        assert invite.status_code == 200, invite.text
        code = invite.json()["data"]["code"]
        assert owner.post(f"/api/v1/notify/telegram/members/{member_id}/invite").status_code == 403
        wrong = linking.handle_update({"update_id": 4, "message": {"chat": {"id": 777, "type": "private"}, "from": {"id": 777, "username": "tester"}, "text": "/start nope"}})
        assert wrong and "không đúng" in wrong[1]
        done = linking.handle_update({"update_id": 5, "message": {"chat": {"id": 777, "type": "private"}, "from": {"id": 777, "username": "tester"}, "text": "/start " + code}})
        assert done and done[0] == "777" and "Telegram Test Person" in done[1]
        with get_session() as session:
            member = session.get(WorkforceMember, member_id)
            assert member.telegram_chat_id == "777" and member.telegram_username == "tester" and member.telegram_invite_code is None
        # A code is used once.
        again = linking.handle_update({"update_id": 6, "message": {"chat": {"id": 778, "type": "private"}, "from": {"id": 778}, "text": "/start " + code}})
        assert again and "không đúng" in again[1]
        shown = cto.get("/api/v1/notify/telegram").json()["data"]
        assert any(row["id"] == member_id and row["linked"] for row in shown["members"])
        assert any(row["id"] == project_id and row["linked"] and row["chat_title"] == "Nhóm thử" for row in shown["projects"])
        # Chat text that is not a command is ignored: nothing people say becomes anything here.
        assert linking.handle_update({"update_id": 7, "message": {"chat": {"id": -100123, "type": "supergroup"}, "from": {"id": 5}, "text": "khách hỏi giá"}}) is None
        reply = linking.handle_update({"update_id": 8, "message": {"chat": {"id": -100123, "type": "supergroup"}, "from": {"id": 5}, "text": "/huy-lien-ket"}})
        assert reply and "bỏ gắn" in reply[1]
        assert cto.delete(f"/api/v1/notify/telegram/members/{member_id}/link").status_code == 204
    finally:
        with get_session() as session:
            project = session.get(Project, project_id)
            project.telegram_chat_id, project.telegram_chat_title, project.telegram_linked_at = None, None, None
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
            session.commit()


def test_holidays_are_a_list_the_cto_replaces() -> None:
    saved = cto.put("/api/v1/notify/holidays", json={"days": [{"day": "2031-04-30", "note": "Giải phóng"}, {"day": "2031-05-01", "note": None}, {"day": "2031-04-30", "note": "trùng"}]})
    assert saved.status_code == 200, saved.text
    try:
        assert [row["day"] for row in saved.json()["data"]] == ["2031-04-30", "2031-05-01"]
        assert owner.get("/api/v1/notify/holidays").status_code == 403
        with get_session() as session:
            assert reminders._holidays(session) >= {date(2031, 4, 30), date(2031, 5, 1)}
    finally:
        with get_session() as session:
            for row in session.scalars(select(Holiday).where(Holiday.day.in_([date(2031, 4, 30), date(2031, 5, 1)]))).all():
                session.delete(row)
            session.commit()


class _FakeClient(TelegramClient):
    def __init__(self) -> None:
        super().__init__(token="test")
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str, *, thread_id: int | None = None) -> dict:
        self.sent.append((chat_id, text))
        self.threads = getattr(self, "threads", []) + [thread_id]
        return {"message_id": len(self.sent)}


def test_messages_carry_counts_in_the_group_and_titles_in_private_and_go_out_once() -> None:
    assert mention("42", "Đoàn <x>") == '<a href="tg://user?id=42">Đoàn &lt;x&gt;</a>'
    assert mention(None, "Ai đó", "ai_do") == "@ai_do"
    assert escape("<b>") == "&lt;b&gt;"
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        project.telegram_chat_id, project.telegram_thread_id = "-100999", 5
        other = session.scalar(select(Project).where(Project.code == "ember"))
        other.telegram_chat_id, other.telegram_thread_id = "-100999", 6
        session.commit()
        project_id, other_id = str(project.id), str(other.id)
    client = _FakeClient()
    day = date(2031, 6, 3)   # a Tuesday with no plan at all
    at = datetime(2031, 6, 3, 8, 31, tzinfo=LOCAL_TZ)
    try:
        first = reminders.send_due(at, client)
        assert first["sent"] >= 1 and first["failed"] == 0
        group = [text for chat, text in client.sent if chat == "-100999"]
        orbit = next(text for text in group if "Orbit" in text)
        assert "Chưa có kế hoạch hôm nay 03/06" in orbit and "/planning?project=" in orbit
        # Two projects in one group, each in its own topic: both lines go out, each into its topic.
        assert len(group) == 2 and any("Ember" in text for text in group) and sorted(t for t in client.threads if t) == [5, 6]
        # The same minute again: nothing goes twice.
        again = reminders.send_due(at, client)
        assert again["sent"] == 0 and again["skipped"] >= 1
        with get_session() as session:
            rows = session.scalars(select(TelegramMessage).where(TelegramMessage.chat_id == "-100999", TelegramMessage.for_date == day)).all()
            assert len(rows) == 2 and {row.status for row in rows} == {"SENT"} and {row.kind for row in rows} == {"PLAN_UNCLOSED_1"} and {row.thread_id for row in rows} == {5, 6}
        log = cto.get("/api/v1/notify/telegram/messages?days=60").status_code
        assert log == 200
    finally:
        with get_session() as session:
            for row in session.scalars(select(TelegramMessage).where(TelegramMessage.chat_id == "-100999")).all():
                session.delete(row)
            for pid in (project_id, other_id):
                project = session.get(Project, pid)
                project.telegram_chat_id, project.telegram_thread_id = None, None
            session.commit()


def test_a_test_line_reaches_every_linked_place_and_is_logged(capsys) -> None:
    from app.workers.telegram_bot import main
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "ember"))
        project.telegram_chat_id, project.telegram_thread_id, project.telegram_chat_title = "-100555", 9, "Acme › Ember"
        session.commit()
        project_id = str(project.id)
    client = _FakeClient()
    try:
        results = reminders.send_test(client)
        assert any(row["target"].startswith("Ember") and row["status"] == "SENT" for row in results)
        assert ("-100555", 9) in [(chat, thread) for (chat, _), thread in zip(client.sent, client.threads)]
        with get_session() as session:
            logged = session.scalars(select(TelegramMessage).where(TelegramMessage.chat_id == "-100555", TelegramMessage.kind == "TEST")).all()
            assert len(logged) == 1 and logged[0].thread_id == 9
        # preview prints and sends nothing
        main(["preview", "--at", "2031-06-03 08:31"])
        out = capsys.readouterr().out
        assert "tin sẽ gửi" in out and "Ember" in out and "chủ đề 9" in out
        assert len(client.sent) == 1
    finally:
        with get_session() as session:
            for row in session.scalars(select(TelegramMessage).where(TelegramMessage.chat_id == "-100555")).all():
                session.delete(row)
            project = session.get(Project, project_id)
            project.telegram_chat_id, project.telegram_thread_id, project.telegram_chat_title = None, None, None
            session.commit()


def test_a_private_plan_lists_the_persons_work_or_says_there_is_none() -> None:
    created = cto.post("/api/v1/planning/members", json={"display_name": "Telegram Plan Person", "email_reference": f"tg-plan-{uuid4().hex[:6]}@example.test"})
    assert created.status_code == 201, created.text
    member_id = created.json()["data"]["id"]
    try:
        with get_session() as session:
            member = session.get(WorkforceMember, member_id)
            text = reminders.plan_private_message(session, member, date(2031, 6, 3))
        assert "chưa có việc nào xếp cho bạn" in text
    finally:
        with get_session() as session:
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
            session.commit()


def test_the_cto_gets_one_digest_after_a_round_only_when_something_is_off() -> None:
    """A CTO login linked to a staff member with Telegram gets the 17:30 round-up: plans not closed with the owner to
    call, people without a report. Sent once; nothing goes out when all is well."""
    from app.models import User
    from app.modules.notify.reminders import LOCAL_TZ as TZ
    member = cto.post("/api/v1/planning/members", json={"display_name": "CTO Digest Member", "email_reference": f"cto-digest-{uuid4().hex[:6]}@example.test"}).json()["data"]
    with get_session() as session:
        stored = session.get(WorkforceMember, member["id"])
        stored.telegram_chat_id = "880011"
        boss = User(id=str(uuid4()), auth_subject=f"cto-digest-{uuid4().hex[:6]}", email=f"{uuid4().hex[:8]}@example.test", display_name="CTO Digest", role="CTO",
                    password_hash="x:y", mfa_enabled=False, is_active=True, member_id=stored.id, created_at=datetime(2020, 1, 1, tzinfo=timezone.utc), updated_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
        session.add(boss)
        session.commit()
        boss_id = str(boss.id)
    client = _FakeClient()
    try:
        # Linking the account to the member through the API is what the settings page does.
        shown = cto.get("/api/v1/users").json()["data"]
        row = next(r for r in shown if r["id"] == boss_id)
        assert row["member_name"] == "CTO Digest Member"
        first = reminders.send_due(datetime(2031, 6, 10, 17, 31, tzinfo=TZ), client)   # a Tuesday with no plans anywhere
        digests = [text for chat, text in client.sent if chat == "880011" and "Tổng hợp" in text]
        assert len(digests) == 1 and "Tổng hợp 17:30" in digests[0] and "Kế hoạch ngày 11/06 chưa chốt" in digests[0] and "Orbit" in digests[0], digests
        assert first["sent"] >= 1
        again = reminders.send_due(datetime(2031, 6, 10, 17, 35, tzinfo=TZ), client)
        assert [text for chat, text in client.sent if chat == "880011" and "Tổng hợp" in text] == digests, "once per round"
        assert again["sent"] == 0
    finally:
        with get_session() as session:
            for row in session.scalars(select(TelegramMessage).where(TelegramMessage.chat_id == "880011")).all():
                session.delete(row)
            for row in session.scalars(select(TelegramMessage).where(TelegramMessage.for_date == date(2031, 6, 10))).all():
                session.delete(row)
            user = session.get(User, boss_id)
            if user is not None:
                session.delete(user)
            stored = session.get(WorkforceMember, member["id"])
            if stored is not None:
                session.delete(stored)
            session.commit()


def test_a_picture_sent_to_the_bot_becomes_a_suggestion_with_the_file(monkeypatch) -> None:
    """FR-AI-14, FR-FBK-01: a linked person who is not the CTO or a Project Owner sends a photo in a private chat; a
    suggestion of their project is made with the file, the caption as text, waiting for the owner; the same message
    twice makes one suggestion; an unknown chat is told to link."""
    import base64

    from sqlalchemy import func

    from app.models import FeedbackFile, FeedbackItem, WorkforceProjectMembership
    from app.modules.notify import linking

    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")
    monkeypatch.setattr(linking, "download_telegram_file", lambda file_id: png)
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Người Gửi Ảnh", "email_reference": f"photo-{uuid4().hex[:6]}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424331", "role": "Developer"}],
    }).json()["data"]
    try:
        with get_session() as session:
            stored = session.get(WorkforceMember, member["id"])
            stored.telegram_chat_id = "990011"
            session.commit()
        stranger = linking.handle_update({"update_id": 90, "message": {"message_id": 1, "chat": {"id": 990099, "type": "private"}, "from": {"id": 990099}, "photo": [{"file_id": "f1", "file_size": 100}]}})
        assert stranger and "link mời" in stranger[1]
        sent = linking.handle_update({"update_id": 91, "message": {"message_id": 2, "chat": {"id": 990011, "type": "private"}, "from": {"id": 990011},
                                                                    "caption": "Khách báo nút Lưu không bấm được", "photo": [{"file_id": "small", "file_size": 100}, {"file_id": "big", "file_size": 900}]}})
        assert sent and sent[0] == "990011" and "Đã ghi góp ý kèm ảnh" in sent[1], sent
        with get_session() as session:
            item = session.scalar(select(FeedbackItem).where(FeedbackItem.member_id == member["id"]).order_by(FeedbackItem.created_at.desc()))
            assert item is not None and item.transport == "TELEGRAM" and str(item.project_id) == project_id and item.status == "PENDING"
            files = session.scalars(select(FeedbackFile).where(FeedbackFile.feedback_id == item.id)).all()
            assert len(files) == 1 and files[0].mime_type == "image/png"
        again = linking.handle_update({"update_id": 92, "message": {"message_id": 2, "chat": {"id": 990011, "type": "private"}, "from": {"id": 990011},
                                                                     "caption": "Khách báo nút Lưu không bấm được", "photo": [{"file_id": "big", "file_size": 900}]}})
        assert again and "đã được nhận rồi" in again[1]
        with get_session() as session:
            assert session.scalar(select(func.count(FeedbackItem.id)).where(FeedbackItem.member_id == member["id"])) == 1
        # A group chat never makes anything out of a picture.
        assert linking.handle_update({"update_id": 93, "message": {"message_id": 3, "chat": {"id": -100123, "type": "supergroup"}, "from": {"id": 5}, "photo": [{"file_id": "x", "file_size": 10}]}}) is None
    finally:
        with get_session() as session:
            for row in session.scalars(select(FeedbackItem).where(FeedbackItem.member_id == member["id"])).all():
                session.delete(row)
            session.commit()
        with get_session() as session:
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member["id"])).all():
                session.delete(row)
            stored = session.get(WorkforceMember, member["id"])
            if stored is not None:
                session.delete(stored)
            session.commit()
