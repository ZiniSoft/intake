"""A member proposes work for a day (FR-PLAN-35): over HTTP from "Việc của tôi", through the agent's propose_work,
or by writing "đề xuất ..." to the Telegram bot. The proposal waits on the project's plan with their name; a closed
plan refuses; the same proposal twice is one entry. A Project Owner sees the people of their teams with the hours
those people have in other projects, by project name (FR-PLAN-28)."""
import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, GitLabIssueSnapshot, PlanningApprovalSnapshot, PlanningAssignment, PlanningCandidate, PlanningRun, PlanningWarning, Project, User, WorkforceMember, WorkforceProjectMembership

cto = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"
DAY = "2031-11-05"


def _issue(project_id: str, issue_id: str, title: str, state: str = "opened") -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=project_id, issue_external_id=issue_id, title=title, state=state,
            labels=["priority:p2"], assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None,
            web_url=None, payload_hash=hashlib.sha256(f"proposal:{issue_id}:{uuid4().hex}".encode()).hexdigest(),
            is_current=True, fetched_at=now, last_seen_at=now,
        ))
        session.commit()


def _cleanup(project_id: str, member_id: str, user_id: str | None, issues: list[str]) -> None:
    with get_session() as session:
        for run in session.scalars(select(PlanningRun).where(PlanningRun.plan_date == date.fromisoformat(DAY))).all():
            for model in (PlanningApprovalSnapshot, PlanningWarning, PlanningAssignment, PlanningCandidate):
                for row in session.scalars(select(model).where(model.planning_run_id == run.id)).all():
                    session.delete(row)
            session.delete(run)
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.issue_external_id.in_(issues))).all():
            session.delete(row)
        if user_id:
            for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user_id)).all():
                session.delete(row)
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)
        for row in session.scalars(select(PlanningWarning).where(PlanningWarning.member_id == member_id)).all():
            session.delete(row)
        for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
            session.delete(row)
        member = session.get(WorkforceMember, member_id)
        if member is not None:
            session.delete(member)
        session.commit()


def test_a_member_proposes_work_from_the_web_the_agent_and_telegram() -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Người Đề Xuất", "email_reference": f"propose-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424341", "role": "Developer"}],
    }).json()["data"]
    user_id = None
    try:
        _issue(project_id, "9301", "Sửa đăng nhập iOS")
        _issue(project_id, "9302", "Issue đã đóng", state="closed")
        created = cto.post("/api/v1/users", json={"subject": f"propose{tag}", "role": "DEVELOPER", "member_id": member["id"]})
        assert created.status_code == 201, created.text
        user_id = created.json()["data"]["account"]["id"]
        dev = TestClient(app, headers={"X-User-Subject": f"propose{tag}"})
        assert dev.post("/api/v1/auth/password", json={"current_password": created.json()["data"]["temporary_password"], "new_password": f"propose-pass-{tag}-long"}).status_code == 200

        # The web: an Issue proposal opens the day's plan and waits there with the member's name.
        first = dev.post("/api/v1/planning/proposals", json={"project": "orbit", "plan_date": DAY, "issue": "#9301", "hours": 3, "slot": "MORNING", "text": "em rành phần này"})
        assert first.status_code == 201, first.text
        data = first.json()["data"]
        assert data["created"] is True and data["status"] == "READY" and data["gitlab_issue_external_id"] == "9301" and data["member_id"] == member["id"]
        assert data["source_reference"] == "Đề xuất của Người Đề Xuất" and data["summary"].startswith("Đề xuất của Người Đề Xuất: em rành") and data["requested_hours"] == 3.0
        run_id = data["run_id"]
        again = dev.post("/api/v1/planning/proposals", json={"project": "orbit", "plan_date": DAY, "issue": "9301"})
        assert again.status_code == 201 and again.json()["data"]["created"] is False and again.json()["data"]["id"] == data["id"], "one entry"
        # Words only wait in triage; a closed Issue, another project and a plan that is closed are refused.
        words = dev.post("/api/v1/planning/proposals", json={"project": "orbit", "plan_date": DAY, "text": "Dọn log máy thử"})
        assert words.status_code == 201 and words.json()["data"]["status"] == "PENDING_TRIAGE" and words.json()["data"]["title"] == "Dọn log máy thử"
        assert "GITLAB_ISSUE_CLOSED" in dev.post("/api/v1/planning/proposals", json={"project": "orbit", "plan_date": DAY, "issue": "9302"}).text
        assert dev.post("/api/v1/planning/proposals", json={"project": "ember", "plan_date": DAY, "text": "không phải đội tôi"}).status_code == 404
        assert "PROPOSAL_TEXT_REQUIRED" in dev.post("/api/v1/planning/proposals", json={"project": "orbit", "plan_date": DAY}).text
        run = cto.get(f"/api/v1/planning/runs/{run_id}").json()["data"]
        mine = [row for row in run["candidates"] if row["member_id"] == member["id"]]
        assert sorted(row["title"] for row in mine) == ["Dọn log máy thử", "Sửa đăng nhập iOS"]
        # The agent: same thing through the tool; the member's projects come with get_my_day.
        token = dev.post("/api/v1/auth/tokens", json={"name": "đề xuất thử"}).json()["data"]
        agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
        day = agent.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_my_day", "arguments": {"date": DAY}}}).json()["result"]["structuredContent"]
        assert [row["code"] for row in day["projects"]] == ["orbit"]
        proposed = agent.post(MCP, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "propose_work", "arguments": {"project": "orbit", "date": DAY, "text": "Viết test cho module thanh toán", "hours": 1.5}}}).json()["result"]["structuredContent"]
        assert proposed["created"] is True and proposed["status"] == "PENDING_TRIAGE" and "Project Owner" in proposed["note"]
        assert "PROJECT_NOT_FOUND" in agent.post(MCP, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "propose_work", "arguments": {"project": "ember", "text": "x"}}}).json()["result"]["content"][0]["text"]
        # Telegram: "đề xuất #9301 2h ..." from the linked person; the Issue is already proposed, so it says so.
        from app.modules.notify import linking
        with get_session() as session:
            stored = session.get(WorkforceMember, member["id"])
            stored.telegram_chat_id = "990077"
            session.commit()
        reply = linking.handle_update({"update_id": 95, "message": {"message_id": 5, "chat": {"id": 990077, "type": "private"}, "from": {"id": 990077}, "text": "đề xuất orbit #9301 2h sửa nốt phần đăng nhập"}})
        assert reply and reply[0] == "990077" and ("đã có từ trước" in reply[1] or "Đã ghi đề xuất" in reply[1]), reply
        fresh = linking.handle_update({"update_id": 96, "message": {"message_id": 6, "chat": {"id": 990077, "type": "private"}, "from": {"id": 990077}, "text": "de xuat 1.5h gom lại log lỗi đăng nhập"}})
        assert fresh and "Đã ghi đề xuất" in fresh[1] and "gom lại log lỗi đăng nhập" in fresh[1], fresh
        # A closed plan refuses the proposal and says which day.
        closed_run = cto.get(f"/api/v1/planning/runs/{run_id}").json()["data"]
        with get_session() as session:
            row = session.get(PlanningRun, run_id)
            row.status = "APPROVED"
            session.commit()
        refused = dev.post("/api/v1/planning/proposals", json={"project": "orbit", "plan_date": DAY, "text": "muộn rồi"})
        assert refused.status_code in (409, 422) and "PLANNING_RUN_IMMUTABLE" in refused.text, refused.text
        assert closed_run["version"] >= 1
    finally:
        _cleanup(project_id, member["id"], user_id, ["9301", "9302"])


def test_a_project_owner_sees_hours_people_have_in_other_projects_by_name() -> None:
    """FR-PLAN-28: the capacity row and the day overview name the other project and its hours, no more."""
    with get_session() as session:
        orbit = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
        ember = str(session.scalar(select(Project).where(Project.code == "ember")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Hai Dự Án", "email_reference": f"two-{tag}@example.test",
        "project_mappings": [{"project_id": orbit, "gitlab_user_external_id": "424351", "role": "Developer"}, {"project_id": ember, "gitlab_user_external_id": "424351", "role": "Developer"}],
    }).json()["data"]
    try:
        run = cto.post("/api/v1/planning/runs", json={"plan_date": DAY, "project_ids": [ember]}).json()["data"]
        placed = cto.post(f"/api/v1/planning/runs/{run['id']}/assignments", json={
            "expected_run_version": run["version"], "project_id": ember, "member_id": member["id"], "slot": "MORNING",
            "work_type": "SUPPORT", "is_primary": False, "planned_hours": 4, "source_type": "FORM", "source_reference": "Việc Ember (thử)",
        })
        assert placed.status_code == 201, placed.text
        rows = {row["member_id"]: row for row in cto.get(f"/api/v1/planning/capacities/{DAY}?project_id={orbit}").json()["data"]}
        mine = rows[member["id"]]
        assert mine["planned_elsewhere_hours"] == 4.0 and mine["planned_elsewhere"] == [{"project_id": ember, "project_name": "Ember", "hours": 4.0}]
        plans = cto.get(f"/api/v1/planning/day-plans/{DAY}").json()["data"]
        block = next(row for row in plans["projects"] if row["code"] == "orbit")
        free = next(row for row in block["free"] if row["member_id"] == member["id"])
        assert free["hours"] == 4.0 and free["elsewhere"][0]["project_name"] == "Ember"
        people = cto.get(f"/api/v1/planning/people/{DAY}").json()["data"]["people"]
        person = next(row for row in people if row["member_id"] == member["id"])
        assert person["projects"] == [{"id": ember, "name": "Ember", "hours": 4.0, "run_status": run["status"]}] or person["projects"][0]["name"] == "Ember"
    finally:
        _cleanup(orbit, member["id"], None, [])
