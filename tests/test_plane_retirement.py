from pathlib import Path

from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApprovalSnapshot, IntakeItem
from app.modules.integrations.service import integration_service
from app.schemas import ProjectCreate


client = TestClient(app, headers={"X-User-Subject": "cto"})


def test_retiring_plane_keeps_tracker_worker_egress() -> None:
    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    worker = compose.split("  integration-worker:\n", 1)[1].split("\n  # Reads docs/agent/CONTEXT.md", 1)[0]
    networks = compose.split("\nnetworks:\n", 1)[1].split("\nvolumes:\n", 1)[0]

    assert "networks: [backend, integration-egress]" in worker
    assert "  integration-egress:\n" in networks


def _reviewed_intake() -> dict:
    created = client.post(
        "/api/v1/intakes",
        json={
            "project_id": "orbit",
            "channel": "MANUAL",
            "raw_text": "Plane retirement contract test",
        },
    ).json()["data"]
    return client.patch(
        f"/api/v1/intakes/{created['id']}/review",
        json={
            "normalized_title": "Plane retirement contract",
            "normalized_summary": "New work must no longer be sent to Plane.",
            "suggested_priority": "P2",
            "proposed_route": "GITLAB",
            "expected_version": created["version"],
        },
    ).json()["data"]


def test_plane_is_not_an_operational_project_integration() -> None:
    projects = client.get("/api/v1/projects").json()["data"]
    assert projects
    assert all(not any(key.startswith("plane_") for key in project) for project in projects)

    probe = client.post(
        "/api/v1/projects/integration-probes",
        json={"system": "PLANE", "action": "LIST"},
    )
    assert probe.status_code == 422


def test_project_payload_rejects_retired_plane_configuration() -> None:
    try:
        ProjectCreate.model_validate(
            {
                "name": "No Plane",
                "code": "no-plane",
                "intake_key": "NOP",
                "kind": "IDEA",
                "plane_project_id": "727e8b1d-8a4e-4fe3-adad-149c77164c62",
            }
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("retired Plane configuration must not be silently accepted")


def test_new_intake_cannot_be_approved_for_plane() -> None:
    reviewed = _reviewed_intake()
    response = client.post(
        f"/api/v1/intakes/{reviewed['id']}/approve",
        json={
            "approved_route": "PLANE",
            "approved_priority": "P2",
            "expected_version": reviewed["version"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "ROUTE_RETIRED"


def test_historical_plane_decision_is_read_only_but_still_visible() -> None:
    reviewed = _reviewed_intake()
    approved = client.post(
        f"/api/v1/intakes/{reviewed['id']}/approve",
        json={
            "approved_route": "GITLAB",
            "approved_priority": "P2",
            "expected_version": reviewed["version"],
        },
    ).json()["data"]
    with get_session() as session:
        item = session.get(IntakeItem, approved["id"])
        snapshot = session.scalar(
            select(ApprovalSnapshot)
            .where(ApprovalSnapshot.intake_id == approved["id"])
            .order_by(ApprovalSnapshot.created_at.desc())
        )
        assert item is not None and snapshot is not None
        item.approved_route = "PLANE"
        snapshot.approved_route = "PLANE"
        snapshot.payload = {**snapshot.payload, "approved_route": "PLANE"}
        session.commit()

    status = integration_service.status_for_intake(approved["id"])
    assert status["target_system"] == "PLANE"
    assert status["sync_available"] is False
    assert status["reason"] == "ROUTE_RETIRED"
