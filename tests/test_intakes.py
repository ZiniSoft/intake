from io import BytesIO
import re

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApprovalAction, ApprovalSnapshot, IntakeItem, OutboxEvent, ProcessingRun
from app.services.outbox_dispatcher import decode_event_payload, outbox_dispatcher
from app.services.processing_repository import NORMALIZE_EVENT
from app.workers.ai_tasks import execute_normalization

client = TestClient(app, headers={"X-User-Subject": "cto"})


def test_outbox_payload_accepts_postgres_text_json() -> None:
    assert decode_event_payload('{"run_id":"run-1","intake_id":"intake-1"}') == {
        "run_id": "run-1",
        "intake_id": "intake-1",
    }


def test_create_intake_success() -> None:
    payload = {
        "project_id": "orbit",
        "channel": "ZALO",
        "raw_text": "Khách hàng báo lỗi không tải được hóa đơn PDF.",
        "sender_reference": "customer-alias",
    }

    response = client.post("/api/v1/intakes", json=payload)
    assert response.status_code == 201

    body = response.json()["data"]
    assert body["channel"] == "ZALO"
    assert body["status"] == "NEW"
    assert re.fullmatch(r"ORB-\d{2}W\d{2}-\d{3}", body["public_id"])


def test_approve_intake_requires_expected_version() -> None:
    payload = {
        "project_id": "ember",
        "channel": "WHATSAPP",
        "raw_text": "Dự án cần scope change cho báo cáo doanh thu.",
    }

    create_response = client.post("/api/v1/intakes", json=payload)
    intake_id = create_response.json()["data"]["id"]

    stale_response = client.post(
        f"/api/v1/intakes/{intake_id}/approve",
        json={
            "approved_route": "GITLAB",
            "approved_priority": "P1",
            "expected_version": 999,
        },
    )

    assert stale_response.status_code == 409


def test_approve_intake_success() -> None:
    payload = {
        "project_id": "orbit",
        "channel": "EMAIL",
        "raw_text": "Cần triage bug CRM không hiển thị dashboard.",
    }

    create_response = client.post("/api/v1/intakes", json=payload)
    intake_id = create_response.json()["data"]["id"]
    reviewed = client.patch(
        f"/api/v1/intakes/{intake_id}/review",
        json={
            "normalized_title": "CRM dashboard bug",
            "normalized_summary": "Sanitized dashboard behavior differs from expected.",
            "suggested_priority": "P1",
            "proposed_route": "GITLAB",
            "expected_version": 1,
        },
    ).json()["data"]

    approval_response = client.post(
        f"/api/v1/intakes/{intake_id}/approve",
        json={
            "approved_route": "GITLAB",
            "approved_priority": "P1",
            "expected_version": reviewed["version"],
        },
    )

    assert approval_response.status_code == 200
    body = approval_response.json()["data"]
    assert body["status"] == "APPROVED"
    assert body["approved_route"] == "GITLAB"
    assert body["approved_priority"] == "P1"

    with get_session() as session:
        action = session.scalar(select(ApprovalAction).where(ApprovalAction.intake_id == intake_id))
        snapshot = session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.approval_action_id == action.id))
        event = session.scalar(
            select(OutboxEvent).where(OutboxEvent.aggregate_id == intake_id, OutboxEvent.event_type == "intake.approved")
        )
        assert action is not None
        assert snapshot is not None
        assert snapshot.payload["approved_route"] == "GITLAB"
        assert event is not None


def test_cto_can_process_intake_before_approval() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={
            "project_id": "orbit",
            "channel": "ZALO",
            "raw_text": "Khách hàng báo lỗi không hiển thị dashboard.",
        },
        headers={"X-User-Subject": "cto"},
    )
    intake_id = create_response.json()["data"]["id"]

    process_response = client.post(
        f"/api/v1/intakes/{intake_id}/process",
        headers={"X-User-Subject": "cto"},
    )

    assert process_response.status_code == 202
    body = process_response.json()["data"]
    assert body["status"] == "PROCESSING"

    with get_session() as session:
        run = session.scalar(select(ProcessingRun).where(ProcessingRun.intake_id == intake_id))
        event = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == intake_id,
                OutboxEvent.event_type == NORMALIZE_EVENT,
            )
        )
        assert run is not None
        assert run.status == "QUEUED"
        assert event is not None
        assert event.status == "NEW"

    pipeline_response = client.get(f"/api/v1/intakes/{intake_id}/pipeline")
    assert pipeline_response.status_code == 200
    assert pipeline_response.json()["data"]["overall_state"] == "QUEUED"

    assert execute_normalization(run.id, intake_id, "test-worker") == "SUCCEEDED"
    completed = client.get(f"/api/v1/intakes/{intake_id}").json()["data"]
    assert completed["status"] == "PENDING_APPROVAL"
    assert completed["item_type"] == "BUG"
    assert completed["suggested_priority"] == "P1"
    assert completed["proposed_route"] == "GITLAB"


def test_approve_requires_normalized_review() -> None:
    created = client.post(
        "/api/v1/intakes",
        json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Raw must not be approved directly"},
    ).json()["data"]
    response = client.post(
        f"/api/v1/intakes/{created['id']}/approve",
        json={
            "approved_route": "GITLAB",
            "approved_priority": "P1",
            "expected_version": created["version"],
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "REVIEW_REQUIRED"


def test_attachment_accepts_pdf_and_rejects_unsupported_type() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Attachment test"},
    )
    intake_id = create_response.json()["data"]["id"]

    accepted = client.post(
        f"/api/v1/intakes/{intake_id}/attachments",
        files={"file": ("evidence.pdf", b"%PDF-test", "application/pdf")},
    )
    rejected = client.post(
        f"/api/v1/intakes/{intake_id}/attachments",
        files={"file": ("script.txt", BytesIO(b"not allowed"), "text/plain")},
    )

    assert accepted.status_code == 201
    assert accepted.json()["data"]["scan_status"] == "PENDING"
    assert rejected.status_code == 415


def test_cto_can_reject_defer_and_request_information() -> None:
    actions = (
        ("reject", {"reason": "Not actionable", "expected_version": 1}, "REJECTED"),
        ("defer", {"reason": "Waiting for release context", "expected_version": 1}, "DEFERRED"),
        ("needs-information", {"reason": "Need reproduction steps", "expected_version": 1}, "NEEDS_INFORMATION"),
    )
    for suffix, payload, expected_status in actions:
        create_response = client.post(
            "/api/v1/intakes",
            json={"project_id": "ember", "channel": "MANUAL", "raw_text": f"Action test {suffix}"},
        )
        intake_id = create_response.json()["data"]["id"]
        response = client.post(f"/api/v1/intakes/{intake_id}/{suffix}", json=payload)
        assert response.status_code == 200
        assert response.json()["data"]["status"] == expected_status


def test_reject_requires_reason_and_rejects_stale_version() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Action validation"},
    )
    intake_id = create_response.json()["data"]["id"]
    missing_reason = client.post(
        f"/api/v1/intakes/{intake_id}/reject",
        json={"expected_version": 1},
    )
    stale = client.post(
        f"/api/v1/intakes/{intake_id}/reject",
        json={"reason": "Duplicate", "expected_version": 99},
    )
    assert missing_reason.status_code == 422
    assert stale.status_code == 409


def test_processing_history_and_approval_queue_are_readable_by_cto() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Bug needs approval"},
    )
    intake_id = create_response.json()["data"]["id"]
    process_response = client.post(f"/api/v1/intakes/{intake_id}/process")
    assert process_response.status_code == 202

    with get_session() as session:
        run = session.scalar(select(ProcessingRun).where(ProcessingRun.intake_id == intake_id))
        assert run is not None
    assert execute_normalization(run.id, intake_id, "test-worker") == "SUCCEEDED"

    runs_response = client.get(f"/api/v1/intakes/{intake_id}/runs")
    queue_response = client.get("/api/v1/approvals")
    assert runs_response.status_code == 200
    assert runs_response.json()["data"][0]["status"] == "SUCCEEDED"
    assert any(item["id"] == intake_id for item in queue_response.json()["data"]["items"])


def test_process_enqueue_is_idempotent_and_dispatches_ids_only() -> None:
    create_response = client.post(
        "/api/v1/intakes",
        json={"project_id": "ember", "channel": "MANUAL", "raw_text": "Bug async queue"},
    )
    intake_id = create_response.json()["data"]["id"]

    first = client.post(f"/api/v1/intakes/{intake_id}/process")
    second = client.post(f"/api/v1/intakes/{intake_id}/process")
    assert first.status_code == 202
    assert second.status_code == 202

    with get_session() as session:
        runs = session.scalars(select(ProcessingRun).where(ProcessingRun.intake_id == intake_id)).all()
        events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == intake_id,
                OutboxEvent.event_type == NORMALIZE_EVENT,
            )
        ).all()
        assert len(runs) == 1
        assert len(events) == 1

    published: list[dict[str, object]] = []

    def publisher(task_name: str, **options: object) -> None:
        published.append({"task_name": task_name, **options})

    outbox_dispatcher.dispatch_once(publisher)
    target = next(call for call in published if call["kwargs"].get("intake_id") == intake_id)
    assert target["task_name"] == "intake.normalize"
    assert set(target["kwargs"]) == {"run_id", "intake_id"}

    with get_session() as session:
        event = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == intake_id,
                OutboxEvent.event_type == NORMALIZE_EVENT,
            )
        )
        assert event is not None
        assert event.status == "PUBLISHED"
        assert event.published_at is not None


def test_intake_list_uses_keyset_cursor_and_server_filters() -> None:
    for index in range(3):
        response = client.post(
            "/api/v1/intakes",
            json={
                "project_id": "orbit",
                "channel": "MEETING" if index < 2 else "EMAIL",
                "raw_text": f"Cursor contract item {index}",
            },
        )
        assert response.status_code == 201

    first = client.get(
        "/api/v1/intakes",
        params={"project_id": "orbit", "channel": "MEETING", "limit": 1, "sort_by": "created_at"},
    )
    assert first.status_code == 200
    first_body = first.json()["data"]
    assert len(first_body["items"]) == 1
    assert first_body["next_cursor"]
    assert first_body["limit"] == 1
    assert first_body["summary"]["total_items"] >= 2

    second = client.get(
        "/api/v1/intakes",
        params={
            "project_id": "orbit",
            "channel": "MEETING",
            "limit": 1,
            "sort_by": "created_at",
            "cursor": first_body["next_cursor"],
        },
    )
    assert second.status_code == 200
    assert second.json()["data"]["items"][0]["id"] != first_body["items"][0]["id"]


def test_intake_summary_is_scoped_to_selected_project() -> None:
    orbit_before = client.get("/api/v1/intakes", params={"project_id": "orbit", "limit": 1}).json()["data"]
    ember_before = client.get("/api/v1/intakes", params={"project_id": "ember", "limit": 1}).json()["data"]

    created = client.post(
        "/api/v1/intakes",
        json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Project-scoped P0 summary"},
    ).json()["data"]
    reviewed = client.patch(
        f"/api/v1/intakes/{created['id']}/review",
        json={
            "normalized_title": "Scoped urgent issue",
            "normalized_summary": "Only Orbit statistics should change.",
            "suggested_priority": "P0",
            "proposed_route": "PLANE",
            "expected_version": created["version"],
        },
    )
    assert reviewed.status_code == 200

    orbit_after = client.get("/api/v1/intakes", params={"project_id": "orbit", "limit": 1}).json()["data"]
    ember_after = client.get("/api/v1/intakes", params={"project_id": "ember", "limit": 1}).json()["data"]

    assert orbit_after["summary"]["p0_attention"] == orbit_before["summary"]["p0_attention"] + 1
    assert ember_after["summary"]["p0_attention"] == ember_before["summary"]["p0_attention"]


def test_invalid_cursor_uses_stable_error_contract() -> None:
    response = client.get("/api/v1/intakes", params={"cursor": "not-a-valid-cursor"})
    assert response.status_code == 400
    body = response.json()
    assert body["success"] is False
    assert body["error"] == "INVALID_CURSOR"
    assert body["request_id"].startswith("req_")

    excessive_limit = client.get("/api/v1/intakes", params={"limit": 101})
    assert excessive_limit.status_code == 422
    assert excessive_limit.json()["error"] == "VALIDATION_ERROR"


def test_create_idempotency_replays_same_request_and_rejects_key_reuse() -> None:
    headers = {"Idempotency-Key": "gate-b-create-key-0001"}
    payload = {"project_id": "ember", "channel": "MANUAL", "raw_text": "Idempotent create"}
    first = client.post("/api/v1/intakes", json=payload, headers=headers)
    second = client.post("/api/v1/intakes", json=payload, headers=headers)
    conflict = client.post(
        "/api/v1/intakes",
        json={**payload, "raw_text": "Different request"},
        headers=headers,
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"] == "IDEMPOTENCY_KEY_REUSED"


def test_review_uses_expected_version_and_invalidates_approval_snapshot() -> None:
    created = client.post(
        "/api/v1/intakes",
        json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Review contract"},
    ).json()["data"]
    initial_review = client.patch(
        f"/api/v1/intakes/{created['id']}/review",
        json={
            "normalized_title": "Initial reviewed title",
            "normalized_summary": "Initial reviewed summary",
            "suggested_priority": "P2",
            "proposed_route": "GITLAB",
            "expected_version": created["version"],
        },
    ).json()["data"]
    approved = client.post(
        f"/api/v1/intakes/{created['id']}/approve",
        json={"approved_route": "GITLAB", "approved_priority": "P2", "expected_version": initial_review["version"]},
    ).json()["data"]

    reviewed = client.patch(
        f"/api/v1/intakes/{created['id']}/review",
        json={
            "normalized_title": "Reviewed title",
            "normalized_summary": "Reviewed summary",
            "suggested_priority": "P1",
            "proposed_route": "PLANE",
            "expected_version": approved["version"],
        },
    )
    stale = client.patch(
        f"/api/v1/intakes/{created['id']}/review",
        json={
            "normalized_title": "Stale title",
            "normalized_summary": "Stale summary",
            "suggested_priority": "P3",
            "proposed_route": "NEEDS_INFO",
            "expected_version": approved["version"],
        },
    )

    assert reviewed.status_code == 200
    assert reviewed.json()["data"]["status"] == "PENDING_APPROVAL"
    assert reviewed.json()["data"]["approved_route"] is None
    assert stale.status_code == 409
    assert stale.json()["error"] == "STALE_VERSION"
    with get_session() as session:
        snapshot = session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.intake_id == created["id"]))
        item = session.get(IntakeItem, created["id"])
        assert snapshot.invalidated_at is not None
        assert item.normalized_title == "Reviewed title"
