"""After a decision is taken back: the request leaves the day plan, its old Issue shows as superseded, a new decision for
the same tracker takes the old Issue over again (reopened when closed), and the AI keeps the delivery route (FR-APR-10,
FR-APR-11, FR-AI-13)."""
import asyncio
import hashlib
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApprovalSnapshot, ExternalLink, GitLabIssueSnapshot, IntakeItem, PlanningCandidate, PlanningRun, SyncJob, User
from app.modules.integrations import adapters as adapter_module
from app.modules.integrations.service import ExternalSyncContext, integration_service
from app.services.ai_processor import build_intake_message, keep_delivery_route
from app.services.intake_service import intake_store
from app.workers.integration_tasks import _sync_gitlab
from tests.test_intake_reopen import _approved, _mark_synced

client = TestClient(app, headers={"X-User-Subject": "cto"})


def _waiting_in_a_plan(intake_id: str) -> str:
    """What "Thêm việc" from the waiting list leaves behind: a READY candidate in an open day plan."""
    day = (date.today() + timedelta(days=40)).isoformat()
    run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
    with get_session() as session:
        item = session.get(IntakeItem, intake_id)
        session.add(PlanningCandidate(
            id=str(uuid4()), planning_run_id=run["id"], project_id=item.project_id, intake_id=item.id, source_type="INTAKE",
            source_reference=item.public_id, title=item.normalized_title or item.public_id, status="READY", proposed_priority="P2",
            created_by=session.scalar(select(User.id).where(User.auth_subject == "cto")),
        ))
        session.commit()
    return run["id"]


def test_reopen_leaves_the_plan_and_a_new_decision_takes_the_old_issue_over(monkeypatch) -> None:
    intake = _approved("GITLAB")
    base = f"/api/v1/intakes/{intake['id']}"
    _mark_synced(intake["id"], "GITLAB", "6")
    # The read model knows Issue #6 (made from this request) and #7 (someone else's): only #7 is a possible duplicate.
    with get_session() as session:
        item = session.get(IntakeItem, intake["id"])
        now = datetime.now(timezone.utc)
        for number in ("6", "7"):
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=item.project_id, issue_external_id=number, title=f"Reuse test issue {number}", state="opened",
                labels=[], assignee_external_ids=[], payload_hash=hashlib.sha256(f"reuse-test:{number}:{intake['id']}".encode()).hexdigest(),
                is_current=True, fetched_at=now, last_seen_at=now, external_updated_at=now,
            ))
        session.commit()
    source = intake_store.normalization_source(intake["id"])
    assert source["existing_issue"] == {"system": "GITLAB", "external_id": "6"}
    listed = {row["id"] for row in source["open_issues"]}
    assert "7" in listed and "6" not in listed
    run_id = _waiting_in_a_plan(intake["id"])
    synced = client.get(base).json()["data"]
    assert synced["sync_targets"][0]["superseded"] is False

    reopened = client.post(f"{base}/reopen", json={"reason": "Nội dung cần sửa lại trước khi làm", "expected_version": synced["version"]})
    assert reopened.status_code == 200, reopened.text
    with get_session() as session:
        candidate = session.scalar(select(PlanningCandidate).where(PlanningCandidate.intake_id == intake["id"], PlanningCandidate.planning_run_id == run_id))
        assert candidate.status == "REJECTED" and "rút lại" in (candidate.summary or "")
        assert session.get(PlanningRun, run_id).status == "REVIEW_REQUIRED"
    after = client.get(base).json()["data"]
    assert after["sync_targets"][0]["superseded"] is True and after["sync_targets"][0]["external_id"] == "6"
    assert client.get(f"{base}/journey").json()["data"]["issue"] is None

    # The same tracker again: allowed, and the sync finds Issue #6 by its marker, updates it and reopens it.
    again = client.post(f"{base}/approve", json={"approved_route": "GITLAB", "approved_priority": "P1", "expected_version": after["version"]})
    assert again.status_code == 200, again.text
    calls: list[dict] = []

    async def fake_find(self, project_path, public_id):
        return {"iid": 6, "id": 601, "web_url": "https://gitlab.test/p/-/issues/6", "state": "closed"}

    async def fake_refresh(self, project_path, issue_iid, approved, idempotency_key, *, reopen=False):
        calls.append({"iid": issue_iid, "reopen": reopen, "title": approved["title"], "key": idempotency_key})
        return {"iid": 6, "web_url": "https://gitlab.test/p/-/issues/6", "state": "opened"}

    monkeypatch.setattr(adapter_module.GitLabAdapter, "find_issue", fake_find)
    monkeypatch.setattr(adapter_module.GitLabAdapter, "refresh_issue", fake_refresh)
    with get_session() as session:
        item = session.get(IntakeItem, intake["id"])
        snapshot = session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.intake_id == intake["id"], ApprovalSnapshot.invalidated_at.is_(None)))
        approved = {"approved": True, "title": item.normalized_title, "summary": item.normalized_summary, "approved_priority": "P1", "item_type": item.item_type or "TASK", "intake_public_id": item.public_id}
        job = SyncJob(
            id=str(uuid4()), approval_snapshot_id=snapshot.id, intake_id=item.id, project_id=item.project_id, target_system="GITLAB",
            idempotency_key=f"reuse-test-{uuid4().hex}", status="RUNNING", attempt=1, max_attempts=5, request_payload_hash=snapshot.payload_hash,
        )
        session.add(job)
        session.commit()
        context = ExternalSyncContext(
            job_id=job.id, intake_id=item.id, intake_public_id=item.public_id, target_system="GITLAB", workspace_slug=None,
            project_external_id="group/project", project_base_url="https://gitlab.test", project_config={}, idempotency_key=job.idempotency_key,
            approved=approved, attempt=1, max_attempts=5,
        )
        job_id = job.id
    result, found_existing = asyncio.run(_sync_gitlab(context))
    assert found_existing and result["id"] == "6" and result["reopened"] is True
    assert calls == [{"iid": "6", "reopen": True, "title": intake["normalized_title"], "key": context.idempotency_key}]
    integration_service.complete(job_id, result, found_existing)

    final = client.get(base).json()["data"]
    assert final["status"] == "SYNCED"
    assert [(row["external_id"], row["superseded"]) for row in final["sync_targets"]] == [("6", False)]
    journey = client.get(f"{base}/journey").json()["data"]
    assert journey["issue"]["external_id"] == "6" and journey["previous_targets"] == []
    with get_session() as session:
        assert session.scalar(select(SyncJob).where(SyncJob.id == job_id)).response_metadata["reopened"] is True
        for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == intake["id"])).all():
            link.target_system = "PLANE"
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.title.like("Reuse test issue %"))).all():
            session.delete(row)
        session.commit()


def test_a_synced_request_edited_or_clarified_can_be_approved_for_its_tracker_again() -> None:
    """Back in review without a reopen (an edit after sync, or answers plus a new analysis): the Issue is still the
    request's Issue, and deciding for GitLab again is how it gets updated, not refused."""
    intake = _approved("GITLAB")
    base = f"/api/v1/intakes/{intake['id']}"
    _mark_synced(intake["id"], "GITLAB", "8")
    synced = client.get(base).json()["data"]
    edited = client.patch(f"{base}/review", json={
        "normalized_title": "Yêu cầu thử, sửa sau khi đồng bộ", "normalized_summary": "Nội dung đã sửa",
        "suggested_priority": "P2", "proposed_route": "GITLAB", "expected_version": synced["version"],
    })
    assert edited.status_code == 200, edited.text
    shown = client.get(base).json()["data"]
    assert shown["status"] == "PENDING_APPROVAL" and shown["sync_targets"][0]["superseded"] is False, "edited, not taken back"
    again = client.post(f"{base}/approve", json={"approved_route": "GITLAB", "approved_priority": "P2", "expected_version": shown["version"]})
    assert again.status_code == 200, again.text
    assert client.get(f"{base}/sync-status").json()["data"]["target_system"] == "GITLAB"
    with get_session() as session:
        for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == intake["id"])).all():
            link.target_system = "PLANE"
        session.commit()


def test_the_ai_is_told_about_the_existing_issue_and_keeps_the_delivery_route() -> None:
    message = build_intake_message("Nút chốt task không bấm được", routes=["NEEDS_INFO", "RESPONSE", "PLANE", "GITLAB"], existing_issue={"system": "GITLAB", "external_id": "6"})
    assert "Existing issue: this request already has Issue #6" in message and "Keep proposed_route = GITLAB" in message
    assert "Existing issue" not in build_intake_message("x", routes=["NEEDS_INFO", "RESPONSE"], existing_issue=None)
    routes = ["NEEDS_INFO", "RESPONSE", "PLANE", "GITLAB"]
    assert keep_delivery_route("PLANE", routes, {"system": "GITLAB", "external_id": "6"}) == "GITLAB"
    assert keep_delivery_route("PLANE", routes, None) == "PLANE"
    assert keep_delivery_route("PLANE", ["NEEDS_INFO", "RESPONSE", "PLANE"], {"external_id": "6"}) == "PLANE", "a project with no delivery tracker any more cannot be routed there"
