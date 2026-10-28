from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

client = TestClient(app)


def test_root_endpoint() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["project"] == get_settings().project_name


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["status"] == "ok"
    assert body["app_name"] == "Private Feedback Intake"


def test_live_and_ready_health_endpoints() -> None:
    assert client.get("/api/v1/health/live").json()["data"] == {"status": "ok"}
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    assert response.json()["data"]["dependencies"]["database"] == "ok"


def test_request_id_is_propagated() -> None:
    response = client.get("/api/v1/health", headers={"X-Request-ID": "req_review_001"})
    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req_review_001"
    assert response.json()["success"] is True
    assert response.json()["request_id"] == "req_review_001"


def test_auth_requires_subject_header() -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_cto_can_access_identity_context() -> None:
    response = client.get("/api/v1/auth/me", headers={"X-User-Subject": "cto"})
    assert response.status_code == 200
    body = response.json()["data"]
    assert body["subject"] == "cto"
    assert body["role"] == "CTO"
    assert body["can_approve"] is True


def test_login_returns_bearer_token() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"subject": "cto", "password": "dev-cto-password"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["token_type"] == "bearer"
    assert response.json()["data"]["access_token"]
    assert response.cookies.get("intake_session")
    assert response.cookies.get("intake_csrf")


def test_login_rejects_invalid_password() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"subject": "cto", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_bearer_token_can_access_identity_context() -> None:
    login_response = client.post(
        "/api/v1/auth/login",
        json={"subject": "project-owner", "password": "dev-owner-password"},
    )

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {login_response.json()['data']['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["role"] == "PROJECT_OWNER"


def test_project_owner_cannot_approve_intake() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={
            "project_id": "orbit",
            "channel": "ZALO",
            "raw_text": "Project owner should not be able to approve this request.",
        },
        headers={"X-User-Subject": "cto"},
    )
    intake_id = create_response.json()["data"]["id"]

    response = client.post(
        f"/api/v1/intakes/{intake_id}/approve",
        json={
            "approved_route": "GITLAB",
            "approved_priority": "P1",
            "expected_version": 1,
        },
        headers={"X-User-Subject": "project-owner"},
    )

    assert response.status_code == 404


def test_cto_can_read_raw_content() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={
            "project_id": "orbit",
            "channel": "EMAIL",
            "raw_text": "This raw content is strictly reserved for CTO access.",
        },
        headers={"X-User-Subject": "cto"},
    )
    intake_id = create_response.json()["data"]["id"]

    response = client.get(f"/api/v1/intakes/{intake_id}/raw", headers={"X-User-Subject": "cto"})

    assert response.status_code == 200
    assert response.json()["data"]["raw_text"] == "This raw content is strictly reserved for CTO access."


def test_project_owner_cannot_read_raw_content() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={
            "project_id": "ember",
            "channel": "WHATSAPP",
            "raw_text": "This message should remain hidden from project owner.",
        },
        headers={"X-User-Subject": "cto"},
    )
    intake_id = create_response.json()["data"]["id"]

    response = client.get(f"/api/v1/intakes/{intake_id}/raw", headers={"X-User-Subject": "project-owner"})

    assert response.status_code == 404


def test_project_owner_cannot_access_pilot_business_routes() -> None:
    headers = {"X-User-Subject": "project-owner"}
    # With no project granted, a Project Owner reaches the scoped lists but they are empty.
    assert client.get("/api/v1/projects", headers=headers).json()["data"] == []
    intakes = client.get("/api/v1/intakes", headers=headers).json()["data"]
    assert intakes["items"] == [] and intakes["summary"]["total_items"] == 0 and intakes["summary"]["pending_approval"] == 0
    assert client.get("/api/v1/approvals", headers=headers).json()["data"]["items"] == []
    assert client.get("/api/v1/reports/daily", headers=headers).json()["data"] == []
    assert client.get("/api/v1/planning/members", headers=headers).json()["data"] == []
    assert client.get("/api/v1/reports/mailbox", headers=headers).status_code == 403
    assert client.get("/api/v1/operations/status", headers=headers).status_code == 403
