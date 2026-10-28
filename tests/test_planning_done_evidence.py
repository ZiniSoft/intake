"""Done is a ladder, not a word: closed, traced in code, looked at by the CTO (FR-PLAN-22)."""
import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ExternalLink, GitLabIssueSnapshot, IntakeItem, IssueVerification, PlanningCandidate, PlanningWarning, Project
from app.modules.integrations import adapters as adapter_module
from app.modules.integrations.adapters import GitLabAdapter
from app.modules.integrations.github import as_read_model_issue
from app.modules.planning.gitlab_read_model import done_level, gitlab_read_model_service, normalize_gitlab_issue
from tests.test_intake_reopen import _approved, _mark_synced

client = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "owner.orbit"})


def _project_id() -> str:
    with get_session() as session:
        return str(session.scalar(select(Project).where(Project.code == "orbit")).id)


def _closed_issue(issue_id: str, *, days_ago: float = 1, evidence: dict | None = None, title: str = "Việc đã đóng", assignees: list | None = None) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=_project_id(), issue_external_id=issue_id, title=title, state="closed",
            labels=["priority:p2"], assignee_external_ids=assignees or [], milestone_external_id=None, milestone_title=None, due_date=None,
            web_url=f"https://gitlab.test/i/{issue_id}", payload_hash=hashlib.sha256(f"done:{issue_id}".encode()).hexdigest(),
            is_current=True, fetched_at=now, last_seen_at=now, closed_at=now - timedelta(days=days_ago), closed_by_external_id="88",
            evidence=evidence, evidence_fetched_at=now if evidence is not None else None,
        ))
        session.commit()


def _cleanup(issue_ids: list[str]) -> None:
    with get_session() as session:
        for row in session.scalars(select(IssueVerification).where(IssueVerification.issue_external_id.in_(issue_ids))).all():
            session.delete(row)
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id.in_(issue_ids))).all():
            session.delete(row)
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        project.project_settings = {k: v for k, v in (project.project_settings or {}).items() if k != "done_evidence"}
        session.commit()


def test_closed_fields_and_the_ladder() -> None:
    row = normalize_gitlab_issue({"iid": 7, "title": "x", "state": "closed", "closed_at": "2026-10-07T09:00:00Z", "closed_by": {"id": 88, "name": "Dev"}})
    assert row["closed_at"] == datetime(2026, 10, 7, 9, tzinfo=timezone.utc) and row["closed_by_external_id"] == "88"
    assert normalize_gitlab_issue({"iid": 8, "title": "y", "state": "opened"})["closed_at"] is None
    github = as_read_model_issue({"number": 5, "title": "gh", "state": "closed", "closed_at": "2026-10-07T09:00:00Z", "closed_by": {"id": 9}, "labels": [], "assignees": []})
    assert github["closed_at"] == "2026-10-07T09:00:00Z" and github["closed_by"] == {"id": 9}

    traced = {"merge_requests": [], "commits": [{"sha": "abc1234"}], "pipeline": None}
    merged = {"merge_requests": [{"iid": "3", "state": "merged"}], "commits": [], "pipeline": {"status": "success"}}
    failed = {"merge_requests": [{"iid": "3", "state": "merged"}], "commits": [], "pipeline": {"status": "failed"}}
    assert done_level("opened", merged) == 0, "open is self-reported whatever is behind it"
    assert done_level("closed", None) == 1 and done_level("closed", {}) == 1
    assert done_level("closed", traced) == 2 and done_level("closed", traced, "MR") == 1, "a commit mention is not enough under the MR rule"
    assert done_level("closed", merged, "MR") == 2 and done_level("closed", failed, "MR") == 1, "a failed pipeline keeps it at closed"
    assert done_level("closed", None, accepted=True) == 5


def test_gitlab_traces_of_one_issue(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    calls: list[str] = []

    def client_factory(**kwargs):
        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path.endswith("/related_merge_requests"):
                return httpx.Response(200, json=[{"iid": 41, "state": "merged", "title": "Fix", "merged_at": "2026-10-07T10:00:00Z", "web_url": "https://gitlab.test/mr/41", "sha": "deadbeef1"}])
            if request.url.path.endswith("/notes"):
                return httpx.Response(200, json=[
                    {"system": True, "body": "mentioned in commit 0123456789abcdef", "created_at": "2026-10-07T09:00:00Z"},
                    {"system": False, "body": "mentioned in commit ffffffff is only a comment"},
                    {"system": True, "body": "changed the description"},
                ])
            if "/repository/commits/" in request.url.path:
                return httpx.Response(200, json={"id": "deadbeef1", "last_pipeline": {"status": "success", "web_url": "https://gitlab.test/p/9"}})
            return httpx.Response(404, json={})

        return real_client(base_url=kwargs["base_url"], timeout=kwargs["timeout"], transport=httpx.MockTransport(handler))

    monkeypatch.setattr(adapter_module.httpx, "AsyncClient", client_factory)
    adapter = GitLabAdapter()
    adapter.settings = SimpleNamespace(gitlab_base_url="https://gitlab.test", gitlab_token="secret")
    evidence = asyncio.run(adapter.issue_evidence("2026/orbit-platform", "12"))
    assert evidence["merge_requests"][0]["iid"] == "41" and evidence["commits"] == [{"sha": "0123456789abcdef", "at": "2026-10-07T09:00:00Z"}]
    assert evidence["pipeline"] == {"status": "success", "sha": "deadbeef1", "web_url": "https://gitlab.test/p/9"}, "the merged MR's head pipeline"
    assert len(calls) == 3 and "/issues/12/" in calls[0]


def test_recently_closed_issues_get_their_traces_looked_up() -> None:
    project_id = _project_id()
    fresh, old, done = str(81000 + uuid4().int % 900), str(82000 + uuid4().int % 900), str(83000 + uuid4().int % 900)
    _closed_issue(fresh, days_ago=1)
    _closed_issue(old, days_ago=40)
    _closed_issue(done, days_ago=2, evidence={"commits": []})
    try:
        targets = gitlab_read_model_service.evidence_targets(project_id)
        assert fresh in targets and old not in targets and done not in targets, "two weeks back, and only when missing or old"
        gitlab_read_model_service.store_evidence(project_id, fresh, {"merge_requests": [], "commits": [{"sha": "a1b2c3d"}], "pipeline": None})
        assert fresh not in gitlab_read_model_service.evidence_targets(project_id)
        with get_session() as session:
            row = session.scalar(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == fresh, GitLabIssueSnapshot.is_current.is_(True)))
            assert row.evidence["commits"][0]["sha"] == "a1b2c3d" and row.evidence_fetched_at is not None
    finally:
        _cleanup([fresh, old, done])


def test_the_day_offers_the_least_proven_closed_issues_and_the_cto_decides() -> None:
    day = "2027-02-03"
    bare, traced, merged, stale = (str(84000 + uuid4().int % 900) for _ in range(4))
    _closed_issue(bare, days_ago=1, title="Đóng tay, không dấu vết", assignees=["88"])
    _closed_issue(traced, days_ago=2, title="Có commit nhắc", evidence={"merge_requests": [], "commits": [{"sha": "abc1234"}], "pipeline": None})
    _closed_issue(merged, days_ago=3, title="MR đã merge", evidence={"merge_requests": [{"iid": "5", "state": "merged", "web_url": "https://gitlab.test/mr/5"}], "commits": [], "pipeline": {"status": "success"}})
    _closed_issue(stale, days_ago=12, title="Đóng lâu rồi")
    # The bare one came from a request with acceptance criteria: they are shown next to the decision.
    request = _approved("GITLAB")
    _mark_synced(request["id"], "GITLAB", bare)
    with get_session() as session:
        intake = session.get(IntakeItem, request["id"])
        intake.normalized_details = {**(intake.normalized_details or {}), "acceptance": ["Khách thấy đơn trong 1 phút", "Không tạo đơn trùng"]}
        session.commit()
    try:
        run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
        picks = {row["issue_external_id"]: row for row in run["verifications"]}
        assert set(picks) == {bare, traced}, "two a day, the least proven first; the one closed twelve days ago is out of the window"
        assert picks[bare]["level"] == 1 and picks[bare]["level_name"] == "CLOSED" and picks[traced]["level"] == 2
        assert picks[bare]["acceptance"] == ["Khách thấy đơn trong 1 phút", "Không tạo đơn trùng"] and picks[bare]["intake_public_id"] == request["public_id"]
        assert picks[traced]["evidence"]["commits"] == 1 and picks[bare]["web_url"].endswith(bare)
        again = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
        assert {row["issue_external_id"] for row in again["verifications"]} == {bare, traced}, "opening the day again keeps the same picks"

        # Not done: back to the waiting list as rework, a warning for the person who had it; GitLab untouched.
        no_reason = client.post(f"/api/v1/planning/runs/{run['id']}/verifications/{picks[bare]['id']}/reject", json={"expected_version": again["version"]})
        assert no_reason.status_code == 422
        rejected = client.post(f"/api/v1/planning/runs/{run['id']}/verifications/{picks[bare]['id']}/reject", json={"expected_version": again["version"], "reason": "Đơn vẫn tạo trùng khi khách bấm hai lần"})
        assert rejected.status_code == 200, rejected.text
        data = rejected.json()["data"]
        assert data["version"] == again["version"] + 1 and data["status"] == "REVIEW_REQUIRED"
        decided = next(row for row in data["verifications"] if row["issue_external_id"] == bare)
        assert decided["decision"] == "REJECTED" and decided["reason"].startswith("Đơn vẫn") and decided["level"] == 1
        rework = [row for row in data["candidates"] if row["source_type"] == "VERIFICATION"]
        assert len(rework) == 1 and rework[0]["gitlab_issue_external_id"] == bare and rework[0]["title"].startswith("Làm lại:") and rework[0]["status"] == "READY"
        assert any(w["code"] == "ISSUE_NOT_DONE_AFTER_CLOSE" and w["project_id"] == picks[bare]["project_id"] for w in data["warnings"])
        twice = client.post(f"/api/v1/planning/runs/{run['id']}/verifications/{picks[bare]['id']}/reject", json={"expected_version": data["version"], "reason": "lại"})
        assert twice.status_code == 409

        # Done: the ladder's top. A stale version is refused; a project owner may not decide.
        assert owner.post(f"/api/v1/planning/runs/{run['id']}/verifications/{picks[traced]['id']}/accept", json={"expected_version": data["version"]}).status_code in (401, 403)
        assert client.post(f"/api/v1/planning/runs/{run['id']}/verifications/{picks[traced]['id']}/accept", json={"expected_version": 1}).status_code == 409
        accepted = client.post(f"/api/v1/planning/runs/{run['id']}/verifications/{picks[traced]['id']}/accept", json={"expected_version": data["version"]}).json()["data"]
        assert next(row for row in accepted["verifications"] if row["issue_external_id"] == traced)["level"] == 5

        # The project's rule: under "MR", a commit mention no longer counts as a trace.
        assert client.put("/api/v1/planning/projects/orbit/done-evidence", json={"done_evidence": "MR"}).json()["data"]["done_evidence"] == "MR"
        assert next(row for row in client.get("/api/v1/projects").json()["data"] if row["code"] == "orbit")["done_evidence"] == "MR"
        next_day = client.post("/api/v1/planning/runs", json={"plan_date": "2027-02-04", "project_ids": ["orbit"]}).json()["data"]
        levels = {row["issue_external_id"]: row["level"] for row in next_day["verifications"]}
        assert levels == {merged: 2}, "the merged one is the only one left to offer, and it is traced under the MR rule"
        assert client.put("/api/v1/planning/projects/orbit/done-evidence", json={"done_evidence": "WORD"}).status_code == 422
    finally:
        with get_session() as session:
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == request["id"])).all():
                link.target_system = "PLANE"
            for row in session.scalars(select(PlanningCandidate).where(PlanningCandidate.source_type == "VERIFICATION")).all():
                session.delete(row)
            for row in session.scalars(select(PlanningWarning).where(PlanningWarning.code == "ISSUE_NOT_DONE_AFTER_CLOSE")).all():
                session.delete(row)
            session.commit()
        _cleanup([bare, traced, merged, stale])
