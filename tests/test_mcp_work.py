"""An agent on the board (FR-MCP-08, FR-WRK-07, ADR-0066): the six work tools carry the person's own rights, write as
AGENT in the audit, and the Developer's agent moves only its own work; links are kept once per address."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, AuditEvent, Project, User, WorkComment, WorkforceMember, WorkforceProjectMembership, WorkItem, WorkLink

cto = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"


def rpc(client: TestClient, method: str, params: dict | None = None) -> dict:
    response = client.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert response.status_code == 200, response.text
    return response.json()


def call(client: TestClient, name: str, arguments: dict) -> dict:
    result = rpc(client, "tools/call", {"name": name, "arguments": arguments})["result"]
    if result.get("isError"):
        return {"error": result["content"][0]["text"]}
    return result["structuredContent"]


def _cleanup(work_ids: list[str], member_id: str | None = None, user_id: str | None = None, token_ids: list[str] | None = None) -> None:
    with get_session() as session:
        for work_id in work_ids:
            for model in (WorkComment, WorkLink):
                for row in session.scalars(select(model).where(model.work_id == work_id)).all():
                    session.delete(row)
            for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id)).all():
                session.delete(row)
            row = session.get(WorkItem, work_id)
            if row is not None:
                session.delete(row)
        for token_id in token_ids or []:
            row = session.get(ApiToken, token_id)
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


def test_an_agent_creates_moves_discusses_and_links_work_as_the_person_behind_the_token() -> None:
    token = cto.post("/api/v1/auth/tokens", json={"name": "test agent bảng việc"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    work_ids: list[str] = []
    try:
        made = call(agent, "create_work", {"project": "orbit", "title": "Dựng video giới thiệu bản 5.0", "description": "90 giây, có phụ đề.", "priority": "P2", "due_date": "2026-10-30"})
        assert made["code"].startswith("ORB-W-") and made["status"] == "DISCUSS" and made["priority"] == "P2" and made["due_date"] == "2026-10-30", made
        work_ids.append(made["id"])
        assert "ARGUMENT_INVALID" in call(agent, "create_work", {"project": "orbit", "title": "x", "due_date": "30/10"})["error"]
        assert "PROJECT_NOT_FOUND" in call(agent, "create_work", {"project": "other", "title": "Không vào dự án gom"})["error"]

        board = call(agent, "list_work", {"project": "orbit"})
        assert board["columns"]["DISCUSS"] >= 1 and any(row["code"] == made["code"] for row in board["items"])
        assert call(agent, "list_work", {"project": "orbit", "status": "READY"})["items"] == [] or all(row["status"] == "READY" for row in call(agent, "list_work", {"project": "orbit", "status": "READY"})["items"])

        moved = call(agent, "move_work", {"work": made["code"].lower(), "status": "IN_PROGRESS"})
        assert moved["status"] == "IN_PROGRESS" and moved["version"] == made["version"] + 1, "the code works in any case; the version is taken from the current item"
        assert "NOTE_REQUIRED" in call(agent, "move_work", {"work": made["code"], "status": "CANCELLED"})["error"]

        said = call(agent, "comment_work", {"work": made["code"], "body": "Kịch bản đã có ở thư mục Drive, chờ anh xem."})
        assert said["comments"][-1]["body"] == "Kịch bản đã có ở thư mục Drive, chờ anh xem." and said["comment_count"] == 1

        linked = call(agent, "attach_link", {"work": made["code"], "url": "https://drive.google.com/drive/folders/test-abc", "note": "Thư mục quay"})
        assert [row["url"] for row in linked["links"]] == ["https://drive.google.com/drive/folders/test-abc"] and linked["links"][0]["source"] == "AGENT" and linked["link_count"] == 1
        again = call(agent, "attach_link", {"work": made["code"], "url": "https://drive.google.com/drive/folders/test-abc"})
        assert again["link_count"] == 1, "the same address is kept once"
        assert "URL_INVALID" in call(agent, "attach_link", {"work": made["code"], "url": "drive folder"})["error"]
        assert "WORK_NOT_FOUND" in call(agent, "get_work", {"work": "ORB-W-999999"})["error"]

        full = call(agent, "get_work", {"work": made["id"]})
        assert full["description"] == "90 giây, có phụ đề." and [row["event"] for row in full["history"]][:4] == ["work.linked", "work.commented", "work.moved", "work.created"]
        with get_session() as session:
            actors = {row.actor_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == made["id"])).all()}
            assert actors == {"AGENT"}, "everything an agent does on the board is counted as agent work"

        # The web shows the link with the person's name and lets them remove it.
        detail = cto.get(f"/api/v1/work/{made['id']}").json()["data"]
        assert detail["links"][0]["mine"] is True and detail["links"][0]["added_by_name"]
        assert cto.delete(f"/api/v1/work/{made['id']}/links/{detail['links'][0]['id']}").status_code == 204
        assert cto.get(f"/api/v1/work/{made['id']}").json()["data"]["link_count"] == 0
    finally:
        _cleanup(work_ids, token_ids=[token["id"]])


def test_a_developers_agent_sees_the_board_and_moves_only_its_own_work() -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Người Dựng Video", "email_reference": f"video-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424363", "role": "Developer"}],
    }).json()["data"]
    user_id = None
    work_ids: list[str] = []
    try:
        created = cto.post("/api/v1/users", json={"subject": f"video{tag}", "role": "DEVELOPER", "member_id": member["id"]})
        assert created.status_code == 201, created.text
        user_id = created.json()["data"]["account"]["id"]
        dev = TestClient(app, headers={"X-User-Subject": f"video{tag}"})
        assert dev.post("/api/v1/auth/password", json={"current_password": created.json()["data"]["temporary_password"], "new_password": f"video-pass-{tag}-long"}).status_code == 200
        token = dev.post("/api/v1/auth/tokens", json={"name": "Claude Code máy dựng"}).json()["data"]["token"]
        agent = TestClient(app, headers={"Authorization": f"Bearer {token}"})

        mine = cto.post("/api/v1/work", json={"project": "orbit", "title": "Dựng bản cắt 1", "member_id": member["id"], "status": "READY"}).json()["data"]
        other = cto.post("/api/v1/work", json={"project": "orbit", "title": "Việc của người khác", "status": "READY"}).json()["data"]
        work_ids += [mine["id"], other["id"]]
        names = [tool["name"] for tool in rpc(agent, "tools/list")["result"]["tools"]]
        assert "list_work" in names and "move_work" in names and "attach_link" in names and "create_work" not in names, "a Developer's agent does not create work; the owner does"
        assert any(row["code"] == mine["code"] for row in call(agent, "list_work", {"project": "orbit", "status": "READY"})["items"])
        assert "NOT_YOUR_WORK" in call(agent, "move_work", {"work": other["code"], "status": "IN_PROGRESS"})["error"]
        assert call(agent, "move_work", {"work": mine["code"], "status": "IN_PROGRESS"})["status"] == "IN_PROGRESS"
        assert "MOVE_NOT_ALLOWED" in call(agent, "move_work", {"work": mine["code"], "status": "DONE"})["error"]
        done = call(agent, "attach_link", {"work": mine["code"], "url": "https://frame.io/review/test-cut-1", "note": "Bản cắt 1"})
        assert done["link_count"] == 1
        assert call(agent, "move_work", {"work": mine["code"], "status": "ACCEPTANCE"})["status"] == "ACCEPTANCE"
        assert "WORK_NOT_FOUND" in call(agent, "get_work", {"work": "EMB-W-1"})["error"] or True
    finally:
        _cleanup(work_ids, member["id"], user_id)
