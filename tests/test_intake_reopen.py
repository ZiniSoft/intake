"""Taking back an approval so a request can be decided again (FR-APR-08)."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApprovalAction, ApprovalSnapshot, AuditEvent, ExternalLink, IntakeItem, SyncJob


client = TestClient(app, headers={"X-User-Subject": "cto"})


def _approved(route: str = "GITLAB") -> dict:
    created = client.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "MANUAL", "raw_text": f"Yêu cầu thử chuyển hướng {uuid4().hex[:6]}"})
    assert created.status_code == 201, created.text
    intake = created.json()["data"]
    reviewed = client.patch(f"/api/v1/intakes/{intake['id']}/review", json={
        "normalized_title": "Yêu cầu thử chuyển hướng", "normalized_summary": "Nội dung đã chuẩn hóa",
        "suggested_priority": "P2", "proposed_route": route, "expected_version": intake["version"],
    })
    assert reviewed.status_code == 200, reviewed.text
    approved = client.post(f"/api/v1/intakes/{intake['id']}/approve", json={
        "approved_route": route, "approved_priority": "P2", "expected_version": reviewed.json()["data"]["version"],
    })
    assert approved.status_code == 200, approved.text
    return approved.json()["data"]


def _historical_plane() -> dict:
    """Seed a decision made before ADR-0066 without reopening the retired write path."""
    approved = _approved("GITLAB")
    with get_session() as session:
        item = session.get(IntakeItem, approved["id"])
        snapshot = session.scalar(select(ApprovalSnapshot).where(
            ApprovalSnapshot.intake_id == approved["id"], ApprovalSnapshot.invalidated_at.is_(None),
        ))
        assert item is not None and snapshot is not None
        item.approved_route = "PLANE"
        snapshot.approved_route = "PLANE"
        snapshot.payload = {**snapshot.payload, "approved_route": "PLANE"}
        session.commit()
    return {**approved, "approved_route": "PLANE"}


def _mark_synced(intake_id: str, system: str, external_id: str) -> None:
    """What a successful sync leaves behind, without calling the outside system."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        item = session.get(IntakeItem, intake_id)
        snapshot = session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.intake_id == intake_id, ApprovalSnapshot.invalidated_at.is_(None)))
        job = SyncJob(
            id=str(uuid4()), approval_snapshot_id=snapshot.id, intake_id=item.id, project_id=item.project_id, target_system=system,
            idempotency_key=f"reopen-test-{uuid4().hex}", status="SUCCEEDED", attempt=1, max_attempts=5, request_payload_hash=snapshot.payload_hash, created_at=now, updated_at=now,
        )
        session.add(job)
        session.flush()
        session.add(ExternalLink(
            id=str(uuid4()), sync_job_id=job.id, intake_id=item.id, project_id=item.project_id, target_system=system,
            external_id=external_id, url=f"https://plane.test/{external_id}", payload_hash=snapshot.payload_hash, created_at=now,
        ))
        item.status = "SYNCED"
        session.commit()


def test_a_synced_request_can_be_reopened_and_sent_elsewhere() -> None:
    intake = _historical_plane()
    external = f"wi-{uuid4().hex[:8]}"
    _mark_synced(intake["id"], "PLANE", external)
    base = f"/api/v1/intakes/{intake['id']}"
    synced = client.get(base).json()["data"]
    assert synced["status"] == "SYNCED"

    # A reason is required, and the version must be the current one.
    assert client.post(f"{base}/reopen", json={"reason": "x", "expected_version": synced["version"]}).status_code == 422
    assert client.post(f"{base}/reopen", json={"reason": "Bấm nhầm sang Plane", "expected_version": synced["version"] + 5}).status_code == 409

    reopened = client.post(f"{base}/reopen", json={"reason": "Bấm nhầm sang Plane", "expected_version": synced["version"]})
    assert reopened.status_code == 200, reopened.text
    data = reopened.json()["data"]
    assert (data["status"], data["approved_route"], data["approved_priority"]) == ("PENDING_APPROVAL", None, None)
    assert client.get(f"{base}/sync-status").json()["data"]["reason"] == "NOT_APPROVED"

    # The work item made by mistake is still out there, shown as no longer in use; nothing was deleted.
    journey = client.get(f"{base}/journey").json()["data"]
    assert journey["issue"] is None and journey["other_target"] is None and journey["sync_status"] is None
    assert journey["previous_targets"] == [{"system": "PLANE", "external_id": external, "url": f"https://plane.test/{external}"}]
    with get_session() as session:
        assert session.scalar(select(ExternalLink).where(ExternalLink.external_id == external)) is not None
        assert session.scalar(select(ApprovalAction).where(ApprovalAction.intake_id == intake["id"], ApprovalAction.action == "REOPEN")).reason == "Bấm nhầm sang Plane"
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "intake.reopen", AuditEvent.entity_id == intake["id"])) is not None

    # Decided again, for the delivery system this time. (Sending it back to Plane would reuse the item there: FR-APR-10.)
    rerouted = client.post(f"{base}/approve", json={"approved_route": "GITLAB", "approved_priority": "P1", "expected_version": data["version"]})
    assert rerouted.status_code == 200, rerouted.text
    assert (rerouted.json()["data"]["status"], rerouted.json()["data"]["approved_route"]) == ("APPROVED", "GITLAB")
    assert client.get(f"{base}/sync-status").json()["data"]["target_system"] == "GITLAB"


def test_reopen_before_sync_and_refusals() -> None:
    intake = _historical_plane()
    base = f"/api/v1/intakes/{intake['id']}"
    reopened = client.post(f"{base}/reopen", json={"reason": "Chọn nhầm tuyến", "expected_version": intake["version"]})
    assert reopened.status_code == 200 and reopened.json()["data"]["status"] == "PENDING_APPROVAL"
    # Nothing left to take back.
    again = client.post(f"{base}/reopen", json={"reason": "Chọn nhầm tuyến", "expected_version": reopened.json()["data"]["version"]})
    assert again.status_code == 409 and again.json()["error"] == "NOT_DECIDED"

    # While a sync is under way the decision cannot be pulled from under it.
    busy = _historical_plane()
    with get_session() as session:
        session.get(IntakeItem, busy["id"]).status = "SYNC_PENDING"
        session.commit()
    locked = client.post(f"/api/v1/intakes/{busy['id']}/reopen", json={"reason": "Chọn nhầm tuyến", "expected_version": busy["version"]})
    assert locked.status_code == 409 and locked.json()["error"] == "SYNC_LOCKED"

    # A Project Owner of another project cannot see it, let alone reopen it.
    stranger = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert stranger.post(f"/api/v1/intakes/{busy['id']}/reopen", json={"reason": "Chọn nhầm tuyến", "expected_version": busy["version"]}).status_code == 404
