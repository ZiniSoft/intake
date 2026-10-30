"""What was done about a request, logged by a person or an agent, and checked by the CTO (FR-MCP-03)."""
import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.modules.planning import acceptance
from app.models import (
    ApiToken,
    AuditEvent,
    ExternalLink,
    GitLabIssueSnapshot,
    IssueVerification,
    PlanningApprovalSnapshot,
    PlanningAssignment,
    PlanningCandidate,
    PlanningRun,
    PlanningWarning,
    Project,
    User,
    WorkforceMember,
    WorkforceProjectMembership,
)
from tests.test_intake_reopen import _approved, _mark_synced

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
MCP = "/api/v1/mcp-server"


def _call(agent: TestClient, name: str, arguments: dict) -> dict:
    answer = agent.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).json()
    assert "result" in answer, answer
    return answer["result"]


def test_work_is_logged_reviewed_and_read_back_by_issue_number() -> None:
    request = _approved("GITLAB")
    issue = str(90000 + uuid4().int % 900)
    _mark_synced(request["id"], "GITLAB", issue)
    worked_on = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date().isoformat()
    with get_session() as session:
        project_id = str(session.scalar(select(Project.id).where(Project.code == "orbit")))
        now = datetime.now(timezone.utc)
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=project_id, issue_external_id=issue, title=request.get("normalized_title") or request["public_id"], state="opened",
            labels=[], assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None,
            web_url=f"https://gitlab.example.test/issues/{issue}", evidence={
                "commits": [{"id": "abc1234"}], "merge_requests": [{"iid": 42, "state": "merged", "web_url": "https://gitlab.example.test/mr/42"}],
            }, payload_hash=hashlib.sha256(f"work-log:{issue}".encode()).hexdigest(), is_current=True, fetched_at=now, last_seen_at=now,
        ))
        session.commit()
    token = cto.post("/api/v1/auth/tokens", json={"name": "work-log test"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    try:
        # The CTO leaves hints for whoever fixes it; they travel with the request.
        hinted = cto.patch(f"/api/v1/intakes/{request['id']}/fix-hints", json={"fix_hints": "  Xem _list_summary; đừng đụng phân trang.  "})
        assert hinted.status_code == 200 and hinted.json()["data"]["fix_hints"] == "Xem _list_summary; đừng đụng phân trang."

        # The agent finds the request by the Issue number the team uses, with the project because numbers repeat.
        found = _call(agent, "get_intake", {"ref": f"#{issue}", "project": "orbit"})["structuredContent"]
        assert found["public_id"] == request["public_id"] and found["fix_hints"].startswith("Xem _list_summary") and found["issue"]["external_id"] == issue
        assert found["work_log"] == []
        evidence_gap = cto.get(f"/api/v1/intakes/{request['id']}/journey").json()["data"]["unlogged_evidence"]
        assert evidence_gap == {"commits": 1, "merge_requests": 1, "links": 1}, "tracker evidence warns; it never auto-accepts"
        assert _call(agent, "get_intake", {"ref": f"gitlab:{issue}"})["structuredContent"]["id"] == request["id"], "one project: no need to say which"
        missing = _call(agent, "get_intake", {"ref": "#9999999"})
        assert missing["isError"] and "INTAKE_NOT_FOUND" in missing["content"][0]["text"]

        # The agent logs what it did; nothing is merged or deployed by that.
        logged = _call(agent, "log_work", {
            "ref": f"#{issue}", "project": "orbit", "summary": "Sửa counter P0/P1 luôn 0", "cause": "Bộ lọc dự án bị áp hai lần",
            "changes": ["app/services/intake_service.py", "tests/test_intake_list.py"], "tests": "test_counter_counts_p0 đỏ trước, xanh sau; 196 passed",
            "branch": f"fix/{issue}-counter", "commit": "abc1234", "verify_steps": ["Mở /intakes, tạo 2 yêu cầu P0, counter phải là 2"],
            "deploy_steps": ["Dựng lại api và web"], "worked_on": worked_on, "actual_minutes": 95, "deployed": True,
            "agent": "claude-code",
        })["structuredContent"]
        assert logged["review_decision"] == "PENDING" and logged["public_id"] == request["public_id"]
        rows = cto.get(f"/api/v1/intakes/{request['id']}/work-log").json()["data"]
        assert len(rows) == 1 and rows[0]["agent_name"] == "claude-code" and rows[0]["details"]["commit"] == "abc1234" and rows[0]["details"]["changes"][0].endswith("intake_service.py")
        assert rows[0]["details"]["worked_on"] == worked_on and rows[0]["details"]["actual_minutes"] == 95 and rows[0]["details"]["deployed"] is True
        assert cto.get(f"/api/v1/intakes/{request['id']}/journey").json()["data"]["work"] == {
            "entries": 1, "latest_id": rows[0]["id"], "latest_decision": "PENDING", "latest_at": rows[0]["created_at"],
            "latest_by": "claude-code", "off_plan": True, "worked_on": worked_on, "actual_minutes": 95, "deployed": True,
        }
        day = cto.get(f"/api/v1/planning/day-plans/{worked_on}")
        assert day.status_code == 200, day.text
        project = next(block for block in day.json()["data"]["projects"] if block["id"] == project_id)
        actual = next(item for item in project["off_plan"] if item["intake_id"] == request["id"])
        assert actual["actual_minutes"] == 95 and actual["deployed"] is True and actual["accepted_at"] is None
        acceptance_queue = cto.get("/api/v1/acceptance")
        assert acceptance_queue.status_code == 200, acceptance_queue.text
        acceptance_data = acceptance_queue.json()["data"]
        queued_log = next(item for item in acceptance_data["work_logs_pending"] if item["id"] == rows[0]["id"])
        assert acceptance_data["work_log_pending_total"] >= 1
        assert queued_log["intake_public_id"] == request["public_id"] and queued_log["summary"] == rows[0]["summary"]

        # Sent back with a note: the next attempt reads it first; only the CTO decides; once.
        assert cto.post(f"/api/v1/intakes/{request['id']}/work-log/{rows[0]['id']}/review", json={"decision": "RETURNED"}).status_code == 422, "a return needs a note"
        assert owner.post(f"/api/v1/intakes/{request['id']}/work-log/{rows[0]['id']}/review", json={"decision": "CONFIRMED"}).status_code in (401, 403, 404)
        returned = cto.post(f"/api/v1/intakes/{request['id']}/work-log/{rows[0]['id']}/review", json={"decision": "RETURNED", "note": "Vẫn 0 khi lọc theo dự án"})
        assert returned.status_code == 200 and returned.json()["data"]["review_decision"] == "RETURNED" and returned.json()["data"]["reviewed_by_name"]
        assert cto.post(f"/api/v1/intakes/{request['id']}/work-log/{rows[0]['id']}/review", json={"decision": "CONFIRMED"}).status_code == 409
        acceptance_data = cto.get("/api/v1/acceptance").json()["data"]
        assert all(item["id"] != rows[0]["id"] for item in acceptance_data["work_logs_pending"])
        decided_log = next(item for item in acceptance_data["work_logs_decided"] if item["id"] == rows[0]["id"])
        assert decided_log["review_decision"] == "RETURNED" and decided_log["review_note"] == "Vẫn 0 khi lọc theo dự án"
        seen = _call(agent, "get_intake", {"ref": request["public_id"]})["structuredContent"]["work_log"]
        assert seen[0]["review_decision"] == "RETURNED" and seen[0]["review_note"] == "Vẫn 0 khi lọc theo dự án"

        # A person logs by hand through the API; the CTO confirms it.
        manual = cto.post(f"/api/v1/intakes/{request['id']}/work-log", json={"summary": "Sửa lại bộ lọc dự án", "details": {"commit": "def5678"}})
        assert manual.status_code == 201 and manual.json()["data"]["agent_name"] is None and manual.json()["data"]["actor_name"]
        confirmed = cto.post(f"/api/v1/intakes/{request['id']}/work-log/{manual.json()['data']['id']}/review", json={"decision": "CONFIRMED", "note": "Đã deploy 10/10"})
        assert confirmed.json()["data"]["review_decision"] == "CONFIRMED"
        journey = cto.get(f"/api/v1/intakes/{request['id']}/journey").json()["data"]["work"]
        assert journey["entries"] == 2 and journey["latest_decision"] == "CONFIRMED"
        assert cto.post(f"/api/v1/intakes/{request['id']}/work-log", json={"summary": "x"}).status_code == 422
        with get_session() as session:
            kinds = {row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_id == request["id"])).all()}
        assert {"intake.fix_hints_updated", "intake.work_logged", "intake.work_reviewed"} <= kinds
    finally:
        cto.delete(f"/api/v1/auth/tokens/{token['id']}")
        with get_session() as session:
            for snapshot in session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.issue_external_id == issue,
            )).all():
                session.delete(snapshot)
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == request["id"])).all():
                link.target_system = "PLANE"
            session.commit()


def test_confirming_a_work_log_accepts_its_issue_and_marks_the_planned_card() -> None:
    """INT-26W43-004 follow-up: the detail journey and Daily Planning must share one acceptance state."""
    request = _approved("GITLAB")
    issue = str(93000 + uuid4().int % 900)
    _mark_synced(request["id"], "GITLAB", issue)
    plan_date = date(2031, 10, 21)
    with get_session() as session:
        project_id = str(session.scalar(select(Project.id).where(Project.code == "orbit")))
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Work log accepted", "email_reference": f"work-accepted-{uuid4().hex[:8]}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "930001", "role": "Developer"}],
    }).json()["data"]
    subject = f"work-accepted-{uuid4().hex[:8]}"
    created_user = cto.post("/api/v1/users", json={"subject": subject, "role": "DEVELOPER", "member_id": member["id"]})
    assert created_user.status_code == 201, created_user.text
    user_id = created_user.json()["data"]["account"]["id"]
    developer = TestClient(app, headers={"X-User-Subject": subject})
    assert developer.post("/api/v1/auth/password", json={
        "current_password": created_user.json()["data"]["temporary_password"], "new_password": f"accepted-{uuid4().hex}-pass",
    }).status_code == 200
    run = cto.post("/api/v1/planning/runs", json={"plan_date": plan_date.isoformat(), "project_ids": [project_id]}).json()["data"]
    placed = cto.post(f"/api/v1/planning/runs/{run['id']}/assignments", json={
        "expected_run_version": run["version"], "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
        "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 4, "source_type": "GITLAB",
        "source_reference": f"GL#{issue}", "gitlab_issue_external_id": issue, "approved_priority": "P2",
    })
    assert placed.status_code == 201, placed.text
    try:
        # A human developer reports done through the plan, without any AI-agent work log.  The Intake journey must
        # expose the exact assignment and pending acceptance so the CTO can finish the same flow on the detail page.
        assignment_id = placed.json()["data"]["id"]
        done = cto.patch(f"/api/v1/planning/runs/{run['id']}/assignments/{assignment_id}/work-status", json={"status": "DONE"})
        assert done.status_code == 200 and done.json()["data"]["acceptance_queued"] is True
        human_journey = cto.get(f"/api/v1/intakes/{request['id']}/journey").json()["data"]
        assert human_journey["plans"][0]["assignment_id"] == assignment_id
        assert human_journey["verification"]["decision"] == "PENDING"
        assert human_journey["verification"]["source"] == "PLAN"

        logged = cto.post(f"/api/v1/intakes/{request['id']}/work-log", json={
            "summary": "Đã sửa và kiểm tra chức năng", "details": {"commit": "abcdef1", "tests": "regression xanh"},
        }).json()["data"]
        confirmed = cto.post(f"/api/v1/intakes/{request['id']}/work-log/{logged['id']}/review", json={
            "decision": "CONFIRMED", "note": "Đã kiểm và triển khai",
        })
        assert confirmed.status_code == 200, confirmed.text

        with get_session() as session:
            verification = session.scalar(select(IssueVerification).where(
                IssueVerification.project_id == project_id,
                IssueVerification.issue_external_id == issue,
            ).order_by(IssueVerification.created_at.desc()))
            assert verification is not None and verification.decision == "ACCEPTED"
            assert verification.sync_status in ("PENDING", "QUEUE_FAILED"), "the tracker close is queued"
            # Simulate INT-26W43-004 as it exists on live: the work log was confirmed by the old release, before an
            # official acceptance row was created.  The regular collector must repair it after deployment.
            session.delete(verification)
            session.commit()
        reconciled = acceptance.collect()
        assert reconciled["from_work_logs"] == 1

        detail = cto.get(f"/api/v1/intakes/{request['id']}").json()["data"]
        assert detail["lifecycle_stage"] == "ACCEPTED"
        accepted_page = cto.get("/api/v1/intakes", params={"stage": "ACCEPTED", "search": request["public_id"]})
        assert accepted_page.status_code == 200, accepted_page.text
        assert [row["id"] for row in accepted_page.json()["data"]["items"]] == [request["id"]]

        planned = cto.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]
        card = next(row for row in planned["assignments"] if row["gitlab_issue_external_id"] == issue)
        assert card["accepted_at"] is not None
        my_day = developer.get(f"/api/v1/planning/my-day/{plan_date.isoformat()}")
        assert my_day.status_code == 200, my_day.text
        my_card = next(row for row in my_day.json()["data"]["items"] if row["issue"] == issue)
        assert my_card["accepted_at"] is not None, "Việc của tôi must show Đã nghiệm thu instead of Chưa bắt đầu"
        assert my_card["issue_url"] == f"https://plane.test/{issue}", "Việc của tôi must keep the Issue link from the Intake sync"
        journey = cto.get(f"/api/v1/intakes/{request['id']}/journey").json()["data"]
        assert journey["intake_public_id"] == request["public_id"] and journey["project_id"] == project_id
        assert journey["plans"][0]["accepted_at"] is not None
    finally:
        with get_session() as session:
            for row in session.scalars(select(IssueVerification).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id == issue)).all():
                session.delete(row)
            stored_run = session.get(PlanningRun, run["id"])
            if stored_run is not None:
                for model in (PlanningApprovalSnapshot, PlanningWarning, PlanningAssignment, PlanningCandidate):
                    for row in session.scalars(select(model).where(model.planning_run_id == stored_run.id)).all():
                        session.delete(row)
                session.delete(stored_run)
            for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user_id)).all():
                session.delete(row)
            stored_user = session.get(User, user_id)
            if stored_user is not None:
                session.delete(stored_user)
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member["id"])).all():
                session.delete(row)
            stored_member = session.get(WorkforceMember, member["id"])
            if stored_member is not None:
                session.delete(stored_member)
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == request["id"])).all():
                link.target_system = "PLANE"
            session.commit()


def test_an_issue_number_shared_by_two_projects_needs_the_project() -> None:
    first, second = _approved("GITLAB"), _approved("GITLAB")
    issue = str(91000 + uuid4().int % 900)
    _mark_synced(first["id"], "GITLAB", issue)
    # The same number cannot be filed twice in one project; it is moved to the other project below.
    _mark_synced(second["id"], "GITLAB", f"{issue}-tmp")
    token = cto.post("/api/v1/auth/tokens", json={"name": "work-log test 2"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    try:
        with get_session() as session:
            # Move the second link to another project so the same number lives in two places.
            from app.models import Project
            other = session.scalar(select(Project).where(Project.code == "ember"))
            link = session.scalar(select(ExternalLink).where(ExternalLink.intake_id == second["id"]))
            link.project_id = other.id
            link.external_id = issue
            session.commit()
        clash = _call(agent, "get_intake", {"ref": f"#{issue}"})
        assert clash["isError"] and "ISSUE_AMBIGUOUS" in clash["content"][0]["text"]
        assert _call(agent, "get_intake", {"ref": f"#{issue}", "project": "orbit"})["structuredContent"]["id"] == first["id"]
    finally:
        cto.delete(f"/api/v1/auth/tokens/{token['id']}")
        with get_session() as session:
            for intake_id in (first["id"], second["id"]):
                for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == intake_id)).all():
                    link.target_system = "PLANE"
            session.commit()
