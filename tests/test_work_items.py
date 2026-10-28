"""Work tracked inside Intake (FR-WRK-01..04, ADR-0066): numbered per project, seen by the people of the project,
moved across six columns with a reason when dropped, discussed in comments."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, AuditEvent, Project, User, WorkComment, WorkforceMember, WorkforceProjectMembership, WorkItem

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def _cleanup(work_ids: list[str], member_id: str | None = None, user_id: str | None = None) -> None:
    with get_session() as session:
        for work_id in work_ids:
            for row in session.scalars(select(WorkComment).where(WorkComment.work_id == work_id)).all():
                session.delete(row)
            for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id)).all():
                session.delete(row)
            row = session.get(WorkItem, work_id)
            if row is not None:
                session.delete(row)
        if user_id:
            for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user_id)).all():
                session.delete(row)
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)
        if member_id:
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
                session.delete(row)
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
        session.commit()


def _developer(tag: str, project_id: str) -> tuple[TestClient, dict, str]:
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Người Làm Việc", "email_reference": f"work-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424362", "role": "Developer"}],
    }).json()["data"]
    created = cto.post("/api/v1/users", json={"subject": f"work{tag}", "role": "DEVELOPER", "member_id": member["id"]})
    assert created.status_code == 201, created.text
    dev = TestClient(app, headers={"X-User-Subject": f"work{tag}"})
    assert dev.post("/api/v1/auth/password", json={"current_password": created.json()["data"]["temporary_password"], "new_password": f"work-pass-{tag}-long"}).status_code == 200
    return dev, member, created.json()["data"]["account"]["id"]


def test_work_is_numbered_per_project_and_moves_across_the_board_with_rules() -> None:
    ids: list[str] = []
    try:
        first = cto.post("/api/v1/work", json={"project": "orbit", "title": "  Viết   bài giới thiệu  bản 5.0 ", "description": "Ba đoạn, có ảnh màn hình.", "priority": "P2"})
        assert first.status_code == 201, first.text
        one = first.json()["data"]
        ids.append(one["id"])
        assert one["code"].startswith("ORB-W-") and one["status"] == "DISCUSS" and one["title"] == "Viết bài giới thiệu bản 5.0"
        assert one["description"] == "Ba đoạn, có ảnh màn hình." and one["priority"] == "P2" and one["project_code"] == "orbit"
        second = cto.post("/api/v1/work", json={"project": "orbit", "title": "Chụp ảnh màn hình", "status": "READY"}).json()["data"]
        ids.append(second["id"])
        assert int(second["code"].rsplit("-", 1)[1]) == int(one["code"].rsplit("-", 1)[1]) + 1 and second["status"] == "READY"
        with get_session() as session:
            assert session.get(WorkItem, one["id"]).description_ciphertext != "Ba đoạn, có ảnh màn hình.", "the description is stored encrypted"

        board = cto.get("/api/v1/work", params={"project": "orbit"}).json()["data"]
        assert {row["id"] for row in board} >= set(ids)

        # Columns: a reason is required to drop; the version guards against a stale board.
        assert "NOTE_REQUIRED" in cto.post(f"/api/v1/work/{one['id']}/move", json={"status": "CANCELLED", "expected_version": one["version"]}).text
        stale = cto.post(f"/api/v1/work/{one['id']}/move", json={"status": "IN_PROGRESS", "expected_version": one["version"] + 5})
        assert stale.status_code == 409 and "STALE_VERSION" in stale.text
        moved = cto.post(f"/api/v1/work/{one['id']}/move", json={"status": "IN_PROGRESS", "expected_version": one["version"]}).json()["data"]
        assert moved["status"] == "IN_PROGRESS" and moved["version"] == one["version"] + 1 and moved["closed_at"] is None
        done = cto.post(f"/api/v1/work/{one['id']}/move", json={"status": "DONE", "expected_version": moved["version"], "note": "Đã đăng lên trang chủ"}).json()["data"]
        assert done["status"] == "DONE" and done["closed_at"] and done["closed_note"] == "Đã đăng lên trang chủ"
        assert "WORK_CLOSED" in cto.patch(f"/api/v1/work/{one['id']}", json={"expected_version": done["version"], "title": "Đổi tên"}).text
        back = cto.post(f"/api/v1/work/{one['id']}/move", json={"status": "READY", "expected_version": done["version"]}).json()["data"]
        assert back["status"] == "READY" and back["closed_at"] is None and back["closed_note"] is None

        # Edits: title, priority, due date; each one is a history line.
        edited = cto.patch(f"/api/v1/work/{one['id']}", json={"expected_version": back["version"], "title": "Viết bài giới thiệu", "priority": "P1", "due_date": "2026-10-30"})
        assert edited.status_code == 200, edited.text
        assert edited.json()["data"]["title"] == "Viết bài giới thiệu" and edited.json()["data"]["priority"] == "P1" and edited.json()["data"]["due_date"] == "2026-10-30"
        detail = cto.get(f"/api/v1/work/{one['id']}").json()["data"]
        assert [row["event_type"] for row in detail["history"]][:5] == ["work.updated", "work.moved", "work.moved", "work.moved", "work.created"]
        assert detail["history"][-1]["actor_name"]
        dropped = cto.post(f"/api/v1/work/{second['id']}/move", json={"status": "CANCELLED", "expected_version": second["version"], "note": "Không cần nữa"}).json()["data"]
        assert dropped["status"] == "CANCELLED" and dropped["closed_note"] == "Không cần nữa"
        # Dropped and done work stays on the board for a while; the caller can ask for the closed ones too.
        assert any(row["id"] == second["id"] for row in cto.get("/api/v1/work", params={"project": "orbit", "include_closed": "true"}).json()["data"])
    finally:
        _cleanup(ids)


def test_the_people_of_the_project_see_and_discuss_the_work_but_only_deciders_shape_it() -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    ids: list[str] = []
    dev, member, user_id = _developer(tag, project_id)
    try:
        work = cto.post("/api/v1/work", json={"project": "orbit", "title": "Soạn bộ câu hỏi thường gặp", "member_id": member["id"], "status": "READY"}).json()["data"]
        ids.append(work["id"])
        assert work["member_name"] == "Người Làm Việc"
        assert "MEMBER_NOT_IN_PROJECT" in cto.post("/api/v1/work", json={"project": "ember", "title": "Sai dự án", "member_id": member["id"]}).text

        # The owner of other projects sees nothing here; the Developer on the project sees the board.
        assert owner.get("/api/v1/work", params={"project": "orbit"}).status_code == 404
        assert owner.get(f"/api/v1/work/{work['id']}").status_code == 404
        seen = dev.get("/api/v1/work", params={"project": "orbit"})
        assert seen.status_code == 200 and any(row["id"] == work["id"] for row in seen.json()["data"]), seen.text
        assert dev.get("/api/v1/work", params={"project": "ember"}).status_code == 404
        assert dev.post("/api/v1/work", json={"project": "orbit", "title": "Dev không tạo được"}).status_code == 403
        assert dev.patch(f"/api/v1/work/{work['id']}", json={"expected_version": work["version"], "title": "Dev không sửa được"}).status_code == 403

        # The Developer moves their own work between the doing columns, and no further.
        doing = dev.post(f"/api/v1/work/{work['id']}/move", json={"status": "IN_PROGRESS", "expected_version": work["version"]})
        assert doing.status_code == 200, doing.text
        refused = dev.post(f"/api/v1/work/{work['id']}/move", json={"status": "DONE", "expected_version": doing.json()["data"]["version"]})
        assert refused.status_code == 422 and "MOVE_NOT_ALLOWED" in refused.text
        other = cto.post("/api/v1/work", json={"project": "orbit", "title": "Việc của người khác", "status": "READY"}).json()["data"]
        ids.append(other["id"])
        assert "NOT_YOUR_WORK" in dev.post(f"/api/v1/work/{other['id']}/move", json={"status": "IN_PROGRESS", "expected_version": other["version"]}).text

        # Discussion: anyone who sees the work writes; a line is removed by its author or the CTO.
        said = dev.post(f"/api/v1/work/{work['id']}/comments", json={"body": "Em gom câu hỏi từ nhóm Zalo, mai gửi bản đầu."})
        assert said.status_code == 201, said.text
        comment = said.json()["data"]["comments"][0]
        assert comment["body"] == "Em gom câu hỏi từ nhóm Zalo, mai gửi bản đầu." and comment["user_name"] and said.json()["data"]["comment_count"] == 1
        with get_session() as session:
            assert session.get(WorkComment, comment["id"]).body_ciphertext != comment["body"], "comments are stored encrypted"
        reply = cto.post(f"/api/v1/work/{work['id']}/comments", json={"body": "Nhớ bỏ tên khách trước khi gửi."}).json()["data"]
        assert [row["body"] for row in reply["comments"]] == [comment["body"], "Nhớ bỏ tên khách trước khi gửi."]
        assert dev.delete(f"/api/v1/work/{work['id']}/comments/{reply['comments'][1]['id']}").status_code == 403
        assert dev.delete(f"/api/v1/work/{work['id']}/comments/{comment['id']}").status_code == 204
        assert cto.delete(f"/api/v1/work/{work['id']}/comments/{reply['comments'][1]['id']}").status_code == 204
        assert cto.get(f"/api/v1/work/{work['id']}").json()["data"]["comments"] == []
    finally:
        _cleanup(ids, member["id"], user_id)
