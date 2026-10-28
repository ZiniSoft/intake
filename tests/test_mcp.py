"""An agent calls Intake as the person whose token it carries: tokens, the MCP endpoint, the tools (FR-MCP-01/02)."""
import hashlib
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app

cto = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"


def rpc(client: TestClient, method: str, params: dict | None = None, message_id: int = 1) -> dict:
    response = client.post(MCP, json={"jsonrpc": "2.0", "id": message_id, "method": method, "params": params or {}})
    assert response.status_code == 200, response.text
    return response.json()


def call(client: TestClient, name: str, arguments: dict) -> dict:
    answer = rpc(client, "tools/call", {"name": name, "arguments": arguments})
    assert "result" in answer, answer
    return answer["result"]


def test_tokens_are_minted_once_shown_once_and_revocable() -> None:
    issued = cto.post("/api/v1/auth/tokens", json={"name": "  Codex   máy làm việc "})
    assert issued.status_code == 201, issued.text
    token = issued.json()["data"]
    assert token["token"].startswith("itk_") and token["prefix"] == token["token"][:12] and token["name"] == "Codex máy làm việc"
    listed = cto.get("/api/v1/auth/tokens").json()["data"]
    assert any(row["id"] == token["id"] and "token" not in row for row in listed), "the secret is shown once"

    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    me = agent.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["data"]["role"] == "CTO", "the token carries the person's own rights"
    assert agent.get("/api/v1/auth/tokens").status_code == 403 and agent.post("/api/v1/auth/tokens", json={"name": "x"}).status_code == 403, "a token cannot manage tokens"
    assert TestClient(app, headers={"Authorization": "Bearer itk_not-a-real-token"}).get("/api/v1/auth/me").status_code == 401

    assert cto.delete(f"/api/v1/auth/tokens/{token['id']}").status_code == 204
    assert agent.get("/api/v1/auth/me").status_code == 401, "revoked"
    assert cto.delete(f"/api/v1/auth/tokens/{token['id']}").status_code == 404


def test_the_mcp_endpoint_opens_only_to_a_personal_token() -> None:
    assert cto.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "ping"}).status_code == 401, "a session, dev header or cookie is not enough"
    token = cto.post("/api/v1/auth/tokens", json={"name": "test"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    try:
        hello = rpc(agent, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "codex"}})
        assert hello["result"]["protocolVersion"] == "2025-06-18" and hello["result"]["serverInfo"]["name"] == "intake" and "tools" in hello["result"]["capabilities"]
        assert agent.post(MCP, json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
        assert rpc(agent, "ping")["result"] == {}
        tools = rpc(agent, "tools/list")["result"]["tools"]
        assert [tool["name"] for tool in tools] == ["list_projects", "get_project_context", "suggest_intake", "create_intake", "get_intake", "log_work", "list_intakes", "answer_questions", "get_day_plan", "submit_daily_report", "get_my_day", "propose_work", "update_work_status", "add_personal_task", "update_personal_task", "get_agent_commands", "get_cto_board", "get_week_summary", "list_work_log_pending", "list_work", "get_work", "create_work", "move_work", "comment_work", "attach_link",
                                                   "hot_topics", "trending", "get_pillars", "week_plan", "review_queue", "topic_to_post", "dismiss_topic", "refresh_topics", "set_channel_text", "get_short_link", "add_signals"]
        assert all("inputSchema" in tool and tool["description"] for tool in tools)
        assert rpc(agent, "no/such")["error"]["code"] == -32601
        assert agent.post(MCP, content=b"{not json", headers={"Content-Type": "application/json"}).status_code == 400
        batch = agent.post(MCP, json=[{"jsonrpc": "2.0", "id": 1, "method": "ping"}, {"jsonrpc": "2.0", "id": 2, "method": "ping"}]).json()
        assert [row["id"] for row in batch] == [1, 2]
        unknown = call(agent, "nothing", {})
        assert unknown["isError"] and "TOOL_UNKNOWN" in unknown["content"][0]["text"]
    finally:
        cto.delete(f"/api/v1/auth/tokens/{token['id']}")


def test_an_agent_files_a_request_reads_it_back_normalized_and_answers_questions() -> None:
    token = cto.post("/api/v1/auth/tokens", json={"name": "test"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    try:
        projects = call(agent, "list_projects", {})["structuredContent"]["projects"]
        assert any(row["code"] == "orbit" and row["delivery_system"] for row in projects)
        assert all(row["code"] != "other" for row in projects), "the catch-all project is not offered to an agent"

        raw = "KHACH-NOI: đơn tạo trùng khi bấm Lưu hai lần; mong sửa trước thứ Sáu."
        key = hashlib.sha256(raw.encode()).hexdigest()
        first = call(agent, "create_intake", {"project": "orbit", "text": raw, "idempotency_key": key, "sender_reference": "chị Lan"})["structuredContent"]
        assert first["created"] and first["public_id"].startswith("ORB-") and first["status"] == "PROCESSING"
        again = call(agent, "create_intake", {"project": "orbit", "text": raw, "idempotency_key": key, "sender_reference": "chị Lan"})["structuredContent"]
        assert again["public_id"] == first["public_id"] and not again["created"], "a retry files nothing twice"
        other = call(agent, "create_intake", {"project": "orbit", "text": "khác", "idempotency_key": key})
        assert other["isError"] and "IDEMPOTENCY_KEY_REUSED" in other["content"][0]["text"]
        assert "PROJECT_NOT_FOUND" in call(agent, "create_intake", {"project": "nope", "text": raw, "idempotency_key": key})["content"][0]["text"]

        shown = call(agent, "get_intake", {"ref": first["public_id"].lower()})
        view = shown["structuredContent"]
        assert view["public_id"] == first["public_id"] and view["channel"] == "AGENT" and "KHACH-NOI" not in shown["content"][0]["text"], "the source text never leaves"
        assert set(view) >= {"title", "summary", "open_questions", "acceptance", "status", "sync_targets"} and "raw_text" not in view

        listed = call(agent, "list_intakes", {"project": "orbit", "limit": 5})["structuredContent"]["items"]
        assert any(row["public_id"] == first["public_id"] for row in listed) and all("summary" not in row for row in listed)
        assert "ARGUMENT_INVALID" in call(agent, "list_intakes", {"limit": 500})["content"][0]["text"]

        answered = call(agent, "answer_questions", {"ref": first["id"], "answers": [{"question": "Lưu ở màn nào?", "answer": "Màn tạo đơn POS"}, {"question": "Có log không?", "skipped": True}]})["structuredContent"]
        assert answered["clarifications"] == [{"question": "Lưu ở màn nào?", "answer": "Màn tạo đơn POS", "skipped": False}, {"question": "Có log không?", "answer": None, "skipped": True}]
        assert answered["version"] == view["version"] + 1
        detail = cto.get(f"/api/v1/intakes/{first['id']}").json()["data"]
        assert detail["channel"] == "AGENT" and detail["details"]["clarifications"][0]["answer"] == "Màn tạo đơn POS"
    finally:
        cto.delete(f"/api/v1/auth/tokens/{token['id']}")


def test_an_agent_reads_the_day_and_files_a_structured_report() -> None:
    token = cto.post("/api/v1/auth/tokens", json={"name": "test"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    me = cto.get("/api/v1/auth/me").json()["data"]
    member_email = f"agent-{uuid4().hex[:6]}@example.test"
    member = cto.post("/api/v1/planning/members", json={"display_name": "Người báo cáo qua agent", "email_reference": member_email, "project_mappings": []}).json()["data"]
    try:
        day = call(agent, "get_day_plan", {"date": "2027-03-01"})["structuredContent"]
        assert day["date"] == "2027-03-01" and day["status"] is None and "assignments" not in day, "no plan that day; nothing is opened"
        assert "ARGUMENT_INVALID" in call(agent, "get_day_plan", {"date": "tomorrow"})["content"][0]["text"]
        run = cto.post("/api/v1/planning/runs", json={"plan_date": "2027-03-02", "project_ids": ["orbit"]}).json()["data"]
        opened = call(agent, "get_day_plan", {"date": "2027-03-02", "project": "orbit"})["structuredContent"]
        assert opened["status"] == run["status"] and isinstance(opened["assignments"], list) and isinstance(opened["waiting"], list) and "verifications_pending" in opened

        # The report goes in under the member the account is linked to; here the account has none, so under its email.
        bad = call(agent, "submit_daily_report", {"project": "orbit", "items": [{"status": "FLYING", "title": "x"}]})
        assert bad["isError"] and "ARGUMENT_INVALID" in bad["content"][0]["text"]
        filed = call(agent, "submit_daily_report", {"project": "orbit", "report_date": "2027-03-02", "items": [
            {"status": "DONE", "title": "Sửa lỗi tạo đơn trùng", "gitlab_issue": "#4411", "hours": 3.5, "next_step": "Chờ review"},
            {"status": "IN_PROGRESS", "title": "Bộ lọc theo ngày", "gitlab_issue": "4412", "hours": 2, "progress_percent": 40},
            {"status": "PLANNED", "title": "Dọn log", "hours": 1},
            {"status": "BLOCKED", "title": "Đồng bộ CRM", "blocker": "Chờ API key của khách"},
        ]})["structuredContent"]
        assert filed["report_id"] and filed["items"] == 4 and filed["report_date"] == "2027-03-02"
        codes = {row["code"] for row in filed["parse_errors"]}
        assert "REPORT_ITEMS_MISSING" not in codes and "INVALID_SUBJECT" not in codes and "TOTAL_HOURS_MISSING" not in codes
        # Whether the sending account maps to a team member decides the status; either way the report says which.
        assert filed["status"] in ("VALID", "WARNING", "MALFORMED") and (filed["status"] != "MALFORMED") == ("REPORT_MEMBER_UNMAPPED" not in codes)
        report = cto.get(f"/api/v1/reports/daily/{filed['report_id']}").json()["data"]
        titles = {row["title"]: row for row in report["items"]}
        assert titles["Sửa lỗi tạo đơn trùng"]["work_status"] == "DONE" and titles["Sửa lỗi tạo đơn trùng"]["worked_hours"] == 3.5
        assert titles["Bộ lọc theo ngày"]["work_status"] == "IN_PROGRESS" and titles["Dọn log"]["work_status"] == "PLANNED" and titles["Dọn log"]["planned_hours"] == 1
        assert titles["Đồng bộ CRM"]["work_status"] == "BLOCKED" and report["item_count"] == 4
        assert me["email"] and member["id"]
    finally:
        cto.delete(f"/api/v1/auth/tokens/{token['id']}")
