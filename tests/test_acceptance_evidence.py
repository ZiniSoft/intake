"""Evidence behind "done" (FR-PLAN-36, ADR-0065): what the worker, the agent, the work log, the report line and the
acceptor attach to an Issue; the fixed rule that says whether it is enough; accepting with nothing behind it needs a
line that says why, and the week counts those."""
import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import GitLabIssueSnapshot, IssueEvidenceLink, IssueVerification, PlanningAssignment, PlanningRun, Project, WorkforceMember
from app.modules.planning import evidence as ev
from app.modules.planning.gitlab_read_model import DONE_EVIDENCE_COMMIT, DONE_EVIDENCE_MR

cto = TestClient(app, headers={"X-User-Subject": "cto"})
ISSUE_URL = "https://gitlab.example.test/2026/orbit-platform/-/issues/9801"


def test_the_rule_says_what_is_enough_by_the_kind_of_work() -> None:
    nothing = ev.assess(DONE_EVIDENCE_COMMIT, {"commits": 0, "merge_requests": 0, "merged": 0, "pipeline": None}, [])
    assert nothing["status"] == "MISSING" and nothing["work"] == "UNKNOWN"
    doc = ev.assess(DONE_EVIDENCE_COMMIT, None, [{"kind": "LINK", "url": "https://drive.example.test/video"}])
    assert doc["status"] == "OK" and doc["work"] == "OTHER"
    traced = ev.assess(DONE_EVIDENCE_COMMIT, {"commits": 2, "merge_requests": 0, "merged": 0, "pipeline": None}, [])
    assert traced["status"] == "OK" and traced["work"] == "CODE"
    # A commit alone is not enough where the project asks for a merged MR; a pasted MR link is.
    weak = ev.assess(DONE_EVIDENCE_MR, {"commits": 2, "merge_requests": 0, "merged": 0, "pipeline": None}, [])
    assert weak["status"] == "WEAK" and weak["work"] == "CODE"
    assert ev.assess(DONE_EVIDENCE_MR, {"commits": 2, "merge_requests": 1, "merged": 1, "pipeline": "failed"}, [])["status"] == "WEAK"
    assert ev.assess(DONE_EVIDENCE_MR, None, [{"kind": "MR", "url": "https://gitlab.example.test/x/-/merge_requests/4"}])["status"] == "OK"
    # Code work with only a document link stays short.
    assert ev.assess(DONE_EVIDENCE_COMMIT, None, [{"kind": "COMMIT", "ref": "abc1234"}, {"kind": "LINK", "url": "https://d/x"}])["status"] == "OK"
    assert ev.assess(DONE_EVIDENCE_MR, None, [{"kind": "COMMIT", "ref": "abc1234"}, {"kind": "LINK", "url": "https://d/x"}])["status"] == "WEAK"
    # Shapes: a commit page, a merge request, a pull request, anything else.
    assert ev.kind_of_url("https://gitlab.example.test/g/p/-/commit/0123abcd") == "COMMIT"
    assert ev.kind_of_url("https://github.com/o/r/pull/12") == "MR" and ev.kind_of_url("https://gitlab.example.test/g/p/-/merge_requests/3") == "MR"
    assert ev.kind_of_url("https://youtu.be/abc") == "LINK"
    assert ev.repo_base(ISSUE_URL) == "https://gitlab.example.test/2026/orbit-platform"
    assert ev.commit_url(ISSUE_URL, "abc1234def") == "https://gitlab.example.test/2026/orbit-platform/-/commit/abc1234def"
    assert ev.commit_url("https://github.com/o/r/issues/5", "abc1234") == "https://github.com/o/r/commit/abc1234"
    # A pasted code link must point at the project's own repository.
    try:
        ev.clean_links([{"kind": "MR", "url": "https://gitlab.example.test/other/repo/-/merge_requests/1"}], issue_web_url=ISSUE_URL)
        raise AssertionError("another repository was taken")
    except ev.EvidenceError as error:
        assert error.code == "EVIDENCE_WRONG_REPO"
    try:
        ev.clean_links([{"url": "ftp://x"}])
        raise AssertionError("a non-http address was taken")
    except ev.EvidenceError as error:
        assert error.code == "EVIDENCE_URL_INVALID"


def _project_id() -> str:
    with get_session() as session:
        return str(session.scalar(select(Project).where(Project.code == "orbit")).id)


def _cleanup(project_id: str, member_id: str | None, run_id: str | None, user_id: str | None) -> None:
    from app.models import ApiToken, PlanningCandidate, PlanningWarning, User, WorkforceProjectMembership

    with get_session() as session:
        for model in (IssueEvidenceLink, IssueVerification, GitLabIssueSnapshot):
            for row in session.scalars(select(model).where(model.project_id == project_id, model.issue_external_id.in_(("9801", "9802")))).all():
                session.delete(row)
        if run_id:
            for model in (PlanningCandidate, PlanningWarning, PlanningAssignment):
                for row in session.scalars(select(model).where(model.planning_run_id == run_id)).all():
                    session.delete(row)
            run = session.get(PlanningRun, run_id)
            if run is not None:
                session.delete(run)
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


def test_evidence_arrives_from_the_worker_the_agent_and_the_acceptor_and_accepting_without_it_needs_a_reason() -> None:
    project_id = _project_id()
    now = datetime.now(timezone.utc)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Người Có Bằng Chứng", "email_reference": f"evidence-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424371", "role": "Developer"}],
    }).json()["data"]
    run_id = user_id = None
    try:
        with get_session() as session:
            for issue, title in (("9801", "Quay video hướng dẫn đăng ký"), ("9802", "Sửa lỗi lưu đơn hai lần")):
                session.add(GitLabIssueSnapshot(
                    id=str(uuid4()), project_id=project_id, issue_external_id=issue, title=title, state="opened", labels=["priority:p2"],
                    assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None,
                    web_url=ISSUE_URL.replace("9801", issue), payload_hash=hashlib.sha256(f"evidence:{issue}:{tag}".encode()).hexdigest(),
                    is_current=True, fetched_at=now, last_seen_at=now,
                ))
            session.commit()
        day = "2031-06-10"
        run = cto.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": [project_id], "timezone": "Asia/Ho_Chi_Minh"}).json()["data"]
        run_id = run["id"]
        placed = cto.post(f"/api/v1/planning/runs/{run_id}/assignments", json={
            "expected_run_version": run["version"], "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 2, "source_type": "GITLAB", "source_reference": "GL#9801", "gitlab_issue_external_id": "9801", "approved_priority": "P2",
        })
        assert placed.status_code in (200, 201), placed.text
        assignment_id = placed.json()["data"]["id"]
        # The worker marks the video done with the link; the acceptance card sees it as enough for non-code work.
        done = cto.patch(f"/api/v1/planning/runs/{run_id}/assignments/{assignment_id}/work-status", json={"status": "DONE", "evidence": [{"kind": "LINK", "url": "https://drive.example.test/video-dang-ky", "note": "bản dựng cuối"}]})
        assert done.status_code == 200, done.text
        assert done.json()["data"]["evidence_added"] == 1 and done.json()["data"]["acceptance_queued"] is True
        queue = cto.get(f"/api/v1/acceptance?project_id={project_id}").json()["data"]
        cards = {row["issue_external_id"]: row for row in queue["today"] + queue["more"]}
        video = cards["9801"]
        assert video["evidence_check"]["status"] == "OK" and video["evidence_check"]["work"] == "OTHER"
        assert [(link["kind"], link["source"], link["added_by_name"]) for link in video["evidence_links"]] == [("LINK", "WORKER", "Người Có Bằng Chứng")]
        accepted = cto.post(f"/api/v1/acceptance/{video['id']}/accept", json={})
        assert accepted.status_code == 200 and accepted.json()["data"]["evidence_missing_reason"] is None

        # The bug: offered without anything behind it; accepting needs a reason; a wrong-repo link is refused; the acceptor pastes the commit.
        with get_session() as session:
            session.add(IssueVerification(id=str(uuid4()), project_id=project_id, issue_external_id="9802", evidence_level=0, decision="PENDING", source="CLOSED", member_id=member["id"], created_at=now))
            session.commit()
        queue = cto.get(f"/api/v1/acceptance?project_id={project_id}").json()["data"]
        bug = {row["issue_external_id"]: row for row in queue["today"] + queue["more"]}["9802"]
        assert bug["evidence_check"]["status"] == "MISSING"
        refused = cto.post(f"/api/v1/acceptance/{bug['id']}/accept", json={})
        assert refused.status_code == 422 and "EVIDENCE_REASON_REQUIRED" in refused.text
        wrong = cto.post(f"/api/v1/acceptance/{bug['id']}/evidence", json={"links": [{"kind": "COMMIT", "url": "https://gitlab.example.test/other/repo/-/commit/0123abcd"}]})
        assert wrong.status_code == 422 and "EVIDENCE_WRONG_REPO" in wrong.text
        pasted = cto.post(f"/api/v1/acceptance/{bug['id']}/evidence", json={"links": [{"url": "https://gitlab.example.test/2026/orbit-platform/-/commit/0123abcd"}]})
        assert pasted.status_code == 200, pasted.text
        card = pasted.json()["data"]
        assert card["evidence_check"]["status"] == "OK" and card["evidence_check"]["work"] == "CODE"
        assert card["evidence_links"][0]["kind"] == "COMMIT" and card["evidence_links"][0]["source"] == "ACCEPTOR"
        # The same address twice is one line.
        again = cto.post(f"/api/v1/acceptance/{bug['id']}/evidence", json={"links": [{"url": "https://gitlab.example.test/2026/orbit-platform/-/commit/0123abcd"}]})
        assert len(again.json()["data"]["evidence_links"]) == 1
    finally:
        _cleanup(project_id, member["id"], run_id, user_id)


def test_accepting_with_nothing_behind_it_is_recorded_and_the_agent_attaches_evidence() -> None:
    project_id = _project_id()
    now = datetime.now(timezone.utc)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Người Không Link", "email_reference": f"nolink-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424372", "role": "Developer"}],
    }).json()["data"]
    run_id = user_id = None
    try:
        with get_session() as session:
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=project_id, issue_external_id="9801", title="Cấu hình máy khách", state="opened", labels=["priority:p3"],
                assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None, web_url=ISSUE_URL,
                payload_hash=hashlib.sha256(f"nolink:{tag}".encode()).hexdigest(), is_current=True, fetched_at=now, last_seen_at=now,
            ))
            session.add(IssueVerification(id=str(uuid4()), project_id=project_id, issue_external_id="9801", evidence_level=0, decision="PENDING", source="CLOSED", member_id=member["id"], created_at=now))
            session.commit()
        queue = cto.get(f"/api/v1/acceptance?project_id={project_id}").json()["data"]
        card = {row["issue_external_id"]: row for row in queue["today"] + queue["more"]}["9801"]
        accepted = cto.post(f"/api/v1/acceptance/{card['id']}/accept", json={"evidence_missing_reason": "đã xem trực tiếp trên máy khách, không có gì để link"})
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["data"]["evidence_missing_reason"].startswith("đã xem trực tiếp") and accepted.json()["data"]["decision"] == "ACCEPTED"
        week = cto.get(f"/api/v1/planning/week/{date.today().isoformat()}").json()["data"]
        mine = next(row for row in week["projects"] if row["id"] == project_id)
        assert mine["done"]["accepted_without_evidence"] >= 1 and "nghiệm thu không bằng chứng" in week["text"]

        # The agent: update_work_status carries evidence; a Developer's token, their own work.
        created = cto.post("/api/v1/users", json={"subject": f"nolink{tag}", "role": "DEVELOPER", "member_id": member["id"]})
        assert created.status_code == 201, created.text
        user_id = created.json()["data"]["account"]["id"]
        dev = TestClient(app, headers={"X-User-Subject": f"nolink{tag}"})
        assert dev.post("/api/v1/auth/password", json={"current_password": created.json()["data"]["temporary_password"], "new_password": f"nolink-pass-{tag}-long"}).status_code == 200
        day = "2031-06-11"
        run = cto.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": [project_id], "timezone": "Asia/Ho_Chi_Minh"}).json()["data"]
        run_id = run["id"]
        placed = cto.post(f"/api/v1/planning/runs/{run_id}/assignments", json={
            "expected_run_version": run["version"], "project_id": project_id, "member_id": member["id"], "slot": "AFTERNOON",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 2, "source_type": "GITLAB", "source_reference": "GL#9802", "gitlab_issue_external_id": "9802", "approved_priority": "P2",
        })
        assert placed.status_code in (200, 201), placed.text
        with get_session() as session:
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=project_id, issue_external_id="9802", title="Sửa lỗi lưu đơn", state="opened", labels=["priority:p2"],
                assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None, web_url=ISSUE_URL.replace("9801", "9802"),
                payload_hash=hashlib.sha256(f"nolink2:{tag}".encode()).hexdigest(), is_current=True, fetched_at=now, last_seen_at=now,
            ))
            session.commit()
        token = dev.post("/api/v1/auth/tokens", json={"name": "bằng chứng thử"}).json()["data"]
        agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
        told = agent.post("/api/v1/mcp-server", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "update_work_status", "arguments": {
            "assignment_id": placed.json()["data"]["id"], "status": "DONE", "evidence": [{"kind": "MR", "url": "https://gitlab.example.test/2026/orbit-platform/-/merge_requests/44"}],
        }}}).json()["result"]
        assert not told.get("isError"), told
        assert told["structuredContent"]["evidence_added"] == 1
        with get_session() as session:
            rows = session.scalars(select(IssueEvidenceLink).where(IssueEvidenceLink.project_id == project_id, IssueEvidenceLink.issue_external_id == "9802")).all()
            assert [(row.kind, row.source) for row in rows] == [("MR", "WORKER")]
    finally:
        _cleanup(project_id, member["id"], run_id, user_id)
