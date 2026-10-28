"""Suggestions from members who are not Project Owners (FR-FBK-01..03, ADR-0064): a Developer, their agent or the
person on Telegram says a project needs a request; it waits without an Intake code; the owner accepts (an Intake on
channel FEEDBACK with the pictures, AI reading it) or rejects with a line the person hears on Telegram."""
import base64
from datetime import datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, Attachment, FeedbackItem, IntakeItem, ProcessingRun, Project, SourceMessage, User, WorkforceMember, WorkforceProjectMembership
from app.modules.notify import linking, reminders
from app.modules.planning.overview import LOCAL_TZ

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
MCP = "/api/v1/mcp-server"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _cleanup(member_id: str, user_id: str | None) -> None:
    with get_session() as session:
        for row in session.scalars(select(FeedbackItem).where(FeedbackItem.member_id == member_id)).all():
            if row.intake_id:
                for model in (Attachment, SourceMessage, ProcessingRun):
                    for child in session.scalars(select(model).where(model.intake_id == row.intake_id)).all():
                        session.delete(child)
                intake = session.get(IntakeItem, row.intake_id)
                row.intake_id = None
                if intake is not None:
                    session.delete(intake)
            session.delete(row)
        if user_id:
            for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user_id)).all():
                session.delete(row)
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)
        for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
            session.delete(row)
        member = session.get(WorkforceMember, member_id)
        if member is not None:
            session.delete(member)
        session.commit()


def test_a_member_suggests_from_the_web_the_agent_and_telegram_and_the_owner_decides(monkeypatch) -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Người Góp Ý", "email_reference": f"feedback-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424361", "role": "Developer"}],
    }).json()["data"]
    user_id = None
    try:
        created = cto.post("/api/v1/users", json={"subject": f"feedback{tag}", "role": "DEVELOPER", "member_id": member["id"]})
        assert created.status_code == 201, created.text
        user_id = created.json()["data"]["account"]["id"]
        dev = TestClient(app, headers={"X-User-Subject": f"feedback{tag}"})
        assert dev.post("/api/v1/auth/password", json={"current_password": created.json()["data"]["temporary_password"], "new_password": f"feedback-pass-{tag}-long"}).status_code == 200

        # The web: a suggestion with a picture, in the member's own project only.
        first = dev.post("/api/v1/feedback", json={"project": "orbit", "text": "Màn đăng nhập báo sai mật khẩu dù gõ đúng, thử trên iOS 17"})
        assert first.status_code == 201, first.text
        one = first.json()["data"]
        assert one["status"] == "PENDING" and one["transport"] == "WEB" and one["member_name"] == "Người Góp Ý" and one["project_code"] == "orbit"
        with_file = dev.post(f"/api/v1/feedback/{one['id']}/files", files={"file": ("loi.png", PNG, "image/png")})
        assert with_file.status_code == 201 and len(with_file.json()["data"]["files"]) == 1, with_file.text
        assert dev.post("/api/v1/feedback", json={"project": "ember", "text": "không phải đội tôi, nhưng vẫn muốn góp"}).status_code == 404
        assert "TEXT_REQUIRED" in dev.post("/api/v1/feedback", json={"project": "orbit", "text": "ngắn"}).text or dev.post("/api/v1/feedback", json={"project": "orbit", "text": "ngắn"}).status_code == 422
        mine = dev.get("/api/v1/feedback").json()["data"]
        assert [row["id"] for row in mine] == [one["id"]]
        picture = dev.get(f"/api/v1/feedback/{one['id']}/files/{with_file.json()['data']['files'][0]['id']}")
        assert picture.status_code == 200 and picture.content == PNG and picture.headers["content-type"].startswith("image/png")
        # No Intake exists yet: the list of requests does not know it.
        assert all(row["channel"] != "FEEDBACK" for row in cto.get("/api/v1/intakes?project_id=orbit&limit=50").json()["data"]["items"])
        # Only the CTO or the Project Owner decides.
        assert dev.post(f"/api/v1/feedback/{one['id']}/accept", json={}).status_code == 403
        # An owner of another project who is also a member here suggests here (ADR-0064), and sees their own anywhere.
        second_member = cto.post("/api/v1/planning/members", json={
            "display_name": "Người Góp Ý Hai", "email_reference": f"feedback2-{tag}@example.test",
            "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424362", "role": "Developer"}],
        }).json()["data"]
        with get_session() as session:
            po_user = session.scalar(select(User).where(User.auth_subject == "project-owner"))
            po_user_id, previous_member = str(po_user.id), po_user.member_id
            po_user.member_id = second_member["id"]
            session.commit()
        try:
            assert owner.get("/api/v1/auth/me").json()["data"]["member_id"] == second_member["id"]
            theirs = owner.post("/api/v1/feedback", json={"project": "orbit", "text": "Góp ý từ PO dự án khác nhưng có mặt ở đây"})
            assert theirs.status_code == 201, theirs.text
            assert theirs.json()["data"]["member_name"] == "Người Góp Ý Hai"
            assert owner.get(f"/api/v1/feedback/{theirs.json()['data']['id']}").status_code == 200
            assert any(row["id"] == theirs.json()["data"]["id"] for row in owner.get("/api/v1/feedback?mine=true").json()["data"])
            assert owner.get("/api/v1/feedback?status=PENDING").status_code == 200 and all(row["project_code"] != "orbit" for row in owner.get("/api/v1/feedback?status=PENDING").json()["data"]), "not theirs to decide"
            assert owner.post(f"/api/v1/feedback/{theirs.json()['data']['id']}/accept", json={}).status_code == 404, "orbit is not a project they manage"
            with get_session() as session:
                po_user = session.get(User, po_user_id)
                po_user.member_id = None
                session.commit()
            assert owner.post("/api/v1/feedback", json={"project": "orbit", "text": "không ở dự án, không quản dự án"}).status_code == 404
        finally:
            with get_session() as session:
                po_user = session.get(User, po_user_id)
                po_user.member_id = previous_member
                for row in session.scalars(select(FeedbackItem).where(FeedbackItem.member_id == second_member["id"])).all():
                    session.delete(row)
                for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == second_member["id"])).all():
                    session.delete(row)
                extra = session.get(WorkforceMember, second_member["id"])
                if extra is not None:
                    session.delete(extra)
                session.commit()

        # The agent: suggest_intake is there, create_intake is not, for a Developer token.
        token = dev.post("/api/v1/auth/tokens", json={"name": "góp ý thử"}).json()["data"]
        agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
        names = [tool["name"] for tool in agent.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]]
        assert "suggest_intake" in names and "create_intake" not in names
        suggested = agent.post(MCP, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "suggest_intake", "arguments": {
            "project": "orbit", "text": "Nút Lưu bấm hai lần tạo hai đơn; cần chặn ở client và server", "idempotency_key": f"gopy-{tag}-1",
            "attachments": [{"name": "don.png", "mime_type": "image/png", "data_base64": base64.b64encode(PNG).decode("ascii")}],
        }}}).json()["result"]
        assert not suggested.get("isError"), suggested
        second = suggested["structuredContent"]
        assert second["status"] == "PENDING" and second["created"] is True and second["files"] == 1
        again = agent.post(MCP, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "suggest_intake", "arguments": {"project": "orbit", "text": "Nút Lưu bấm hai lần tạo hai đơn; cần chặn ở client và server", "idempotency_key": f"gopy-{tag}-1"}}}).json()["result"]["structuredContent"]
        assert again["created"] is False and again["feedback_id"] == second["feedback_id"]

        # Telegram: "góp ý ..." and a picture from the linked person wait the same way; the CTO's picture still makes a request.
        with get_session() as session:
            stored = session.get(WorkforceMember, member["id"])
            stored.telegram_chat_id = "990088"
            session.commit()
        reply = linking.handle_update({"update_id": 101, "message": {"message_id": 11, "chat": {"id": 990088, "type": "private"}, "from": {"id": 990088}, "text": "góp ý orbit báo cáo tuần thiếu cột giờ làm"}})
        assert reply and reply[0] == "990088" and "Đã ghi góp ý" in reply[1], reply
        monkeypatch.setattr(linking, "download_telegram_file", lambda file_id: PNG)
        photo = linking.handle_update({"update_id": 102, "message": {"message_id": 12, "chat": {"id": 990088, "type": "private"}, "from": {"id": 990088}, "caption": "orbit màn này lệch", "photo": [{"file_id": "f1", "file_size": 70}]}})
        assert photo and "Đã ghi góp ý kèm ảnh" in photo[1], photo
        waiting = cto.get("/api/v1/feedback?status=PENDING&project_id=orbit").json()["data"]
        by_transport = sorted((row["transport"], len(row["files"])) for row in waiting if row["member_id"] == member["id"])
        assert by_transport == [("AGENT", 1), ("TELEGRAM", 0), ("TELEGRAM", 1), ("WEB", 1)]

        # The owner's yes: an Intake on channel FEEDBACK with the picture; the owner's no: a line the person reads.
        accepted = cto.post(f"/api/v1/feedback/{one['id']}/accept", json={"note": "làm trong tuần"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["status"] == "ACCEPTED" and accepted.json()["data"]["intake_public_id"]
        intake = cto.get(f"/api/v1/intakes/{accepted.json()['data']['intake_id']}").json()["data"]
        assert intake["channel"] == "FEEDBACK" and intake["project_id"] == project_id
        assert len(cto.get(f"/api/v1/intakes/{intake['id']}/attachments").json()["data"]) == 1
        assert cto.post(f"/api/v1/feedback/{one['id']}/accept", json={}).status_code == 409
        assert cto.post(f"/api/v1/feedback/{second['feedback_id']}/reject", json={"note": ""}).status_code == 422
        rejected = cto.post(f"/api/v1/feedback/{second['feedback_id']}/reject", json={"note": "Đã có chặn ở server từ tuần trước, kiểm lại bản mới"})
        assert rejected.status_code == 200 and rejected.json()["data"]["status"] == "REJECTED"
        shown = dev.get("/api/v1/feedback?mine=true").json()["data"]
        assert {row["status"] for row in shown} == {"ACCEPTED", "REJECTED", "PENDING"}
        # Telegram hears both decisions, once each (the once-only rule is the TelegramMessage row in send_due).
        notices = [m for m in reminders.build_messages(datetime.now(LOCAL_TZ)) if m.kind == "FEEDBACK_DECIDED" and m.chat_id == "990088"]
        assert len(notices) == 2 and any("đã được nhận" in m.text and intake["public_id"] in m.text for m in notices) and any("chưa được nhận" in m.text and "kiểm lại bản mới" in m.text for m in notices)
        assert len({m.slot for m in notices}) == 2
        old = [m for m in reminders.build_messages(datetime.now(LOCAL_TZ) + timedelta(days=5)) if m.kind == "FEEDBACK_DECIDED" and m.chat_id == "990088"]
        assert old == [], "decisions older than two days are not told again"
    finally:
        _cleanup(member["id"], user_id)
