"""Telegram around a post's hour (FR-MKT-15): the morning schedule, an hour-before nudge to the person who posts by
hand, a nudge to the owner when an auto-publish version is not approved, a late note to both, nothing once the version
is out, each once; and never on the words of the post."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.db import get_session
from app.models import TelegramMessage, WorkforceMember
from app.modules.notify import reminders
from app.modules.notify.posts import post_messages
from app.modules.planning.overview import LOCAL_TZ
from tests.test_watch_topics import cto, mkt  # noqa: F401  (the fixture)


class FakeClient:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str, *, thread_id=None) -> dict:
        self.sent.append((chat_id, text))
        return {}


def test_the_hour_of_a_post_is_announced_nudged_and_chased_once(mkt) -> None:  # noqa: F811
    po, code, project_id = mkt["po"], mkt["code"], mkt["project_id"]
    writer_id = mkt["writer_member_id"]
    today = datetime.now(LOCAL_TZ).date()
    with get_session() as session:
        writer = session.get(WorkforceMember, writer_id)
        writer.telegram_chat_id = "tg-writer-thu"
        owner = session.scalar(select(WorkforceMember).where(WorkforceMember.email_reference.like("po%@example.test")).order_by(WorkforceMember.created_at.desc()))
        owner.telegram_chat_id = "tg-owner-thu"
        session.commit()
    at = lambda hour, minute: datetime.combine(today, datetime.min.time(), tzinfo=LOCAL_TZ).replace(hour=hour, minute=minute)  # noqa: E731
    stamp = at(11, 30).astimezone(timezone.utc).isoformat()
    post = po.post("/api/v1/work", json={"project": code, "title": "Bài nhắc giờ (thử)", "status": "IN_PROGRESS", "member_id": writer_id, "channels": [{"channel": "FACEBOOK_PAGE", "publish_at": stamp}, {"channel": "THREADS", "publish_at": at(19, 0).astimezone(timezone.utc).isoformat()}]}).json()["data"]
    fb = next(row for row in post["channels"] if row["channel"] == "FACEBOOK_PAGE")
    assert po.patch(f"/api/v1/work/{post['id']}/channels/{fb['id']}", json={"text": "Chữ bản Facebook thử dài vừa đủ."}).status_code == 200
    original_auto = next(row["auto_publish"] for row in cto.get("/api/v1/channel-rules").json()["data"] if row["code"] == "FACEBOOK_PAGE")
    try:
        with get_session() as session:
            # Morning: the day's schedule to the owner privately (no group linked), both versions, with the writer's name.
            morning = post_messages(session, at(8, 5))
            digest = [m for m in morning if m.kind == "POSTS_TODAY" and m.project_id == project_id]
            assert len(digest) == 1 and digest[0].chat_id == "tg-owner-thu" and "11:30 Facebook trang công ty" in digest[0].text and "19:00 Threads" in digest[0].text and "Viết" in digest[0].text
            assert "Chữ bản Facebook" not in digest[0].text, "the words of the post never travel"
            assert not [m for m in post_messages(session, at(8, 30)) if m.kind == "POSTS_TODAY" and m.project_id == project_id], "outside the window"

            # An hour before: the writer, by hand, with the state of the words and the card.
            due = [m for m in post_messages(session, at(10, 35)) if m.kind == "POST_DUE" and m.project_id == project_id]
            assert len(due) == 1 and due[0].chat_id == "tg-writer-thu" and "Sắp đến giờ đăng 11:30" in due[0].text and "đã có" in due[0].text and post["code"] in due[0].text and f"work={post['id']}" in due[0].text
            assert not [m for m in post_messages(session, at(11, 0)) if m.kind == "POST_DUE" and m.project_id == project_id]

            # Half an hour after, still not out: the writer and the owner.
            late = [m for m in post_messages(session, at(12, 5)) if m.kind == "POST_LATE" and m.project_id == project_id]
            assert sorted(m.chat_id for m in late) == ["tg-owner-thu", "tg-writer-thu"] and all("Quá giờ đăng 11:30" in m.text for m in late)

        # On an auto-publish channel the hour-before note goes to the owner, and only while the post is not approved.
        assert cto.put("/api/v1/channel-rules/FACEBOOK_PAGE", json={"auto_publish": True}).status_code == 200
        with get_session() as session:
            need = [m for m in post_messages(session, at(10, 35)) if m.project_id == project_id and m.kind in ("POST_DUE", "POST_NEED_OK")]
            assert [(m.kind, m.chat_id) for m in need] == [("POST_NEED_OK", "tg-owner-thu")] and "Đang làm" in need[0].text
        version = po.get(f"/api/v1/work/{post['id']}").json()["data"]["version"]
        assert po.post(f"/api/v1/work/{post['id']}/move", json={"status": "ACCEPTANCE", "expected_version": version}).status_code == 200
        version = po.get(f"/api/v1/work/{post['id']}").json()["data"]["version"]
        assert po.post(f"/api/v1/work/{post['id']}/move", json={"status": "APPROVED", "expected_version": version}).status_code == 200
        with get_session() as session:
            assert not [m for m in post_messages(session, at(10, 35)) if m.project_id == project_id and m.kind in ("POST_DUE", "POST_NEED_OK")], "approved on an auto channel: the flow posts, nobody is nudged"
            late = [m for m in post_messages(session, at(12, 5)) if m.kind == "POST_LATE" and m.project_id == project_id]
            assert len(late) == 2 and "Luồng đăng chưa báo về" in late[0].text

        # Sent once through the usual door, then the version is out and nothing more is said.
        client = FakeClient()
        with get_session() as session:
            session.execute(delete(TelegramMessage).where(TelegramMessage.project_id == project_id))
            session.commit()
        first = reminders.send_due(at(12, 5), client)
        again = reminders.send_due(at(12, 6), client)
        mine = [row for row in client.sent if post["code"] in row[1]]
        assert len(mine) == 2 and first["sent"] >= 2 and again["skipped"] >= 2
        assert po.patch(f"/api/v1/work/{post['id']}/channels/{fb['id']}", json={"status": "PUBLISHED", "published_url": "https://www.facebook.com/acme/posts/thu"}).status_code == 200
        with get_session() as session:
            assert not [m for m in post_messages(session, at(12, 5)) if m.project_id == project_id and m.kind in ("POST_LATE", "POST_DUE")]
            after = [m for m in post_messages(session, at(8, 5)) if m.kind == "POSTS_TODAY" and m.project_id == project_id]
            assert "đã đăng" in after[0].text
    finally:
        cto.put("/api/v1/channel-rules/FACEBOOK_PAGE", json={"auto_publish": original_auto})
        with get_session() as session:
            session.execute(delete(TelegramMessage).where(TelegramMessage.project_id == project_id))
            session.commit()
