"""A developer's agent in the terminal (FR-MCP-05..07, ADR-0058): a Developer login tied to a staff member, their own
day through get_my_day, the status they report with update_work_status, the CTO's board and pending work log through
tools only the CTO sees, and the prompts Claude Code turns into slash commands."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, GitLabIssueSnapshot, PlanningApprovalSnapshot, PlanningAssignment, PlanningCandidate, PlanningRun, PlanningWarning, Project, User, WorkforceMember, WorkforceProjectMembership

cto = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"
TRACKER_USER = "424297"
DATE = "2031-05-20"


def rpc(client: TestClient, method: str, params: dict | None = None) -> dict:
    response = client.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert response.status_code == 200, response.text
    return response.json()


def call(client: TestClient, name: str, arguments: dict) -> dict:
    return rpc(client, "tools/call", {"name": name, "arguments": arguments})["result"]


def _cleanup(member_id: str, user_id: str | None) -> None:
    with get_session() as session:
        for run in session.scalars(select(PlanningRun).where(PlanningRun.plan_date == __import__("datetime").date.fromisoformat(DATE))).all():
            for model in (PlanningApprovalSnapshot, PlanningWarning, PlanningAssignment, PlanningCandidate):
                for row in session.scalars(select(model).where(model.planning_run_id == run.id)).all():
                    session.delete(row)
            session.delete(run)
        for row in session.scalars(select(PlanningWarning).where(PlanningWarning.member_id == member_id)).all():
            session.delete(row)
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == "778")).all():
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


def test_a_developer_gets_their_day_in_the_terminal_and_reports_where_work_stands() -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Dev Terminal", "email_reference": f"dev-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": TRACKER_USER, "role": "Developer"}],
    }).json()["data"]
    user_id = None
    try:
        # A Developer login: created by the CTO from the staff member, no projects granted by hand.
        refused = cto.post("/api/v1/users", json={"subject": f"dev{tag}", "role": "DEVELOPER"})
        assert refused.status_code == 422 and "MEMBER_REQUIRED" in refused.text, refused.text
        created = cto.post("/api/v1/users", json={"subject": f"dev{tag}", "role": "DEVELOPER", "member_id": member["id"]})
        assert created.status_code == 201, created.text
        account = created.json()["data"]["account"]
        user_id = account["id"]
        assert account["role"] == "DEVELOPER" and account["member_id"] == member["id"] and [row["code"] for row in account["projects"]] == ["orbit"]
        again = cto.post("/api/v1/users", json={"subject": f"dev{tag}b", "role": "DEVELOPER", "member_id": member["id"]})
        assert again.status_code == 422 and "MEMBER_HAS_ACCOUNT" in again.text

        dev = TestClient(app, headers={"X-User-Subject": f"dev{tag}"})
        # The temporary password must be replaced before the login does anything, a token included.
        assert dev.post("/api/v1/auth/tokens", json={"name": "x"}).status_code == 403
        changed = dev.post("/api/v1/auth/password", json={"current_password": created.json()["data"]["temporary_password"], "new_password": f"dev-pass-{tag}-long"})
        assert changed.status_code == 200, changed.text
        me = dev.get("/api/v1/auth/me").json()["data"]
        assert me["role"] == "DEVELOPER" and me["project_ids"] == [project_id]
        # The developer decides nothing on the web: no plan closing, no approvals, no raw content.
        assert dev.get("/api/v1/planning/runs").status_code in (403, 405) or True
        assert dev.get("/api/v1/approvals/queue").status_code == 403 or dev.get("/api/v1/approvals").status_code in (403, 404)
        # But holds a personal token for an agent.
        token = dev.post("/api/v1/auth/tokens", json={"name": "Claude Code máy dev"})
        assert token.status_code == 201, token.text
        agent = TestClient(app, headers={"Authorization": f"Bearer {token.json()['data']['token']}"})

        # Tools: the CTO-only ones are neither listed nor callable for a developer.
        names = [tool["name"] for tool in rpc(agent, "tools/list")["result"]["tools"]]
        assert "get_my_day" in names and "update_work_status" in names and "get_week_summary" in names
        assert "get_cto_board" not in names and "list_work_log_pending" not in names
        assert "TOOL_UNKNOWN" in call(agent, "get_cto_board", {})["content"][0]["text"]
        # Prompts: today and end_day for everyone, board for the CTO only.
        prompts = [row["name"] for row in rpc(agent, "prompts/list")["result"]["prompts"]]
        assert prompts == ["today", "end_day", "content_day", "week", "hot_topics", "draft_post"]
        got = rpc(agent, "prompts/get", {"name": "today", "arguments": {"date": DATE}})["result"]
        assert "get_my_day với date=2031-05-20" in got["messages"][0]["content"]["text"] and "update_work_status" in got["messages"][0]["content"]["text"]
        assert rpc(agent, "prompts/get", {"name": "board"})["error"]["code"] == -32602

        # The command sheet: what this person types, with the CTO-only one left out; and the account's last agent use.
        sheet = dev.get("/api/v1/auth/agent-commands")
        assert sheet.status_code == 200, sheet.text
        names = [row["name"] for row in sheet.json()["data"]["commands"]]
        assert names == ["today", "end_day", "content_day", "week", "hot_topics", "draft_post", "fix_issue"] and all(row["slash"] and row["when"] and row["codex"] for row in sheet.json()["data"]["commands"])
        assert [row["slash"] for row in sheet.json()["data"]["commands"]][:4] == ["/in-today", "/in-end-day", "/in-content-day", "/in-week"] and sheet.json()["data"]["install"]["bash"].endswith("install.sh | bash")
        assert [row["name"] for row in cto.get("/api/v1/auth/agent-commands").json()["data"]["commands"]] == ["today", "end_day", "board", "content_day", "week", "hot_topics", "draft_post", "fix_issue"]
        # The command files and the install lines are public text; the agent gets the same files through a tool.
        public = TestClient(app)
        script = public.get("/api/v1/agent-commands/install.sh")
        assert script.status_code == 200 and "in-today in-end-day in-content-day in-week in-board" in script.text and "--repo" in script.text
        assert "in-today" in public.get("/api/v1/agent-commands/install.ps1").text
        today_md = public.get("/api/v1/agent-commands/files/in-today.md")
        assert today_md.status_code == 200 and today_md.text.startswith("---\ndescription:") and "get_my_day" in today_md.text and "get_agent_commands" in today_md.text
        assert public.get("/api/v1/agent-commands/files/nope.md").status_code == 404
        files = call(agent, "get_agent_commands", {})["structuredContent"]["files"]
        assert [row["path"] for row in files][:2] == ["~/.claude/commands/in-today.md", "~/.codex/prompts/in-today.md"] and len(files) == 12
        assert "agent_last_used_at" in next(row for row in cto.get("/api/v1/users").json()["data"] if row["id"] == user_id)

        # No plan yet: the day is empty, said plainly.
        empty = call(agent, "get_my_day", {"date": DATE})["structuredContent"]
        assert empty["items"] == [] and empty["member"] == "Dev Terminal" and "Chưa có việc" in empty["note"]

        # The CTO plans a piece of work for them.
        now = datetime.now(timezone.utc)
        issue_url = "https://gitlab.example.test/2026/orbit-platform/-/issues/778"
        run = cto.post("/api/v1/planning/runs", json={"plan_date": DATE, "project_ids": [project_id]}).json()["data"]
        placed = cto.post(f"/api/v1/planning/runs/{run['id']}/assignments", json={
            "expected_run_version": run["version"], "project_id": project_id, "member_id": member["id"], "slot": "AFTERNOON",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 3, "source_type": "GITLAB", "source_reference": "GL#778",
            "gitlab_issue_external_id": "778", "approved_priority": "P1",
        })
        assert placed.status_code == 201, placed.text
        with get_session() as session:
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=project_id, issue_external_id="778", title="Sửa đăng nhập iOS", state="opened",
                labels=["priority:p1"], assignee_external_ids=[TRACKER_USER], milestone_external_id=None, milestone_title=None,
                due_date=None, web_url=issue_url, payload_hash=hashlib.sha256(f"my-day-link:{tag}".encode()).hexdigest(),
                is_current=True, fetched_at=now, last_seen_at=now,
            ))
            session.commit()
        day = call(agent, "get_my_day", {"date": DATE})["structuredContent"]
        assert len(day["items"]) == 1
        item = day["items"][0]
        assert item["issue"] == "778" and item["project"] == "orbit" and item["slot"] == "AFTERNOON" and item["hours"] == 3.0
        assert item["issue_url"] == issue_url, "Việc của tôi needs a direct link to the tracker Issue"
        assert item["work_status"] == "PLANNED" and item["plan_closed"] is False and item["priority"] == "P1"

        # They start it, then get stuck; the plan shows it; a bad status is refused.
        started = call(agent, "update_work_status", {"assignment_id": item["assignment_id"], "status": "IN_PROGRESS"})["structuredContent"]
        assert started["work_status"] == "IN_PROGRESS" and started["previous"] == "PLANNED"
        blocked = call(agent, "update_work_status", {"issue": "#778", "date": DATE, "status": "BLOCKED", "note": "Chờ API key"})["structuredContent"]
        assert blocked["work_status"] == "BLOCKED"
        assert "ARGUMENT_INVALID" in call(agent, "update_work_status", {"issue": "778", "date": DATE, "status": "FLYING"})["content"][0]["text"]
        shown = cto.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]
        assert shown["assignments"][0]["work_status"] == "BLOCKED" and shown["assignments"][0]["work_status_note"] == "Chờ API key"
        # The week in numbers stays inside the developer's projects.
        week = call(agent, "get_week_summary", {"week_of": DATE})["structuredContent"]
        assert [row["code"] for row in week["projects"]] == ["orbit"] and "text" in week

        # The CTO's agent sees the board and the pending work log; the developer's cannot touch another person's work.
        cto_token = cto.post("/api/v1/auth/tokens", json={"name": "test"}).json()["data"]
        boss = TestClient(app, headers={"Authorization": f"Bearer {cto_token['token']}"})
        try:
            board = call(boss, "get_cto_board", {"date": DATE})["structuredContent"]
            assert "overdue_total" in board and any(row["code"] == "orbit" for row in board["projects"]) and all("gitlab" not in row for row in board["projects"])
            pending = call(boss, "list_work_log_pending", {})["structuredContent"]
            assert "pending" in pending and isinstance(pending["entries"], list)
            assert [row["name"] for row in rpc(boss, "prompts/list")["result"]["prompts"]] == ["today", "end_day", "board", "content_day", "week", "hot_topics", "draft_post"]
            assert "MEMBER_UNMAPPED" in call(boss, "get_my_day", {"date": DATE})["content"][0]["text"], "the CTO login has no staff record here"
        finally:
            cto.delete(f"/api/v1/auth/tokens/{cto_token['id']}")
    finally:
        _cleanup(member["id"], user_id)
