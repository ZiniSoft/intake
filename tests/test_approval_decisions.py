"""FR-APR-15: the decisions taken on requests stay findable after they leave the queue. One list under the queue,
newest first, in the caller's projects: who decided, when, what, why, and what the request is now."""
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app
from tests.test_intake_context import _retire
from tests.test_intake_reopen import _approved

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def _pending(text: str) -> dict:
    created = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "MANUAL", "raw_text": text})
    assert created.status_code == 201, created.text
    intake = created.json()["data"]
    reviewed = cto.patch(f"/api/v1/intakes/{intake['id']}/review", json={
        "normalized_title": text[:60], "normalized_summary": text, "suggested_priority": "P3", "proposed_route": "WORK", "expected_version": intake["version"],
    })
    assert reviewed.status_code == 200, reviewed.text
    return reviewed.json()["data"]


def test_decisions_are_listed_newest_first_with_who_why_and_now() -> None:
    marker = uuid4().hex[:6]
    approved = _approved("WORK")
    rejected = _pending(f"Yêu cầu thử bị từ chối {marker}")
    deferred = _pending(f"Yêu cầu thử bị hoãn {marker}")
    try:
        assert cto.post(f"/api/v1/intakes/{rejected['id']}/reject", json={"reason": "Trùng với việc đã làm (thử)", "expected_version": rejected["version"]}).status_code == 200
        assert cto.post(f"/api/v1/intakes/{deferred['id']}/defer", json={"reason": "Để sang tuần (thử)", "expected_version": deferred["version"]}).status_code == 200
        current = cto.get(f"/api/v1/intakes/{approved['id']}").json()["data"]
        assert cto.post(f"/api/v1/intakes/{approved['id']}/reopen", json={"reason": "Bấm nhầm nơi nhận (thử)", "expected_version": current["version"]}).status_code == 200

        page = cto.get("/api/v1/approvals/decisions?days=1&limit=100")
        assert page.status_code == 200, page.text
        data = page.json()["data"]
        ours = [row for row in data["items"] if row["intake_id"] in {approved["id"], rejected["id"], deferred["id"]}]
        assert [row["action"] for row in ours] == ["REOPENED", "DEFERRED", "REJECTED", "APPROVED"], ours
        by_action = {row["action"]: row for row in ours}
        assert by_action["APPROVED"]["approved_route"] == "WORK" and by_action["APPROVED"]["approved_priority"] == "P2"
        assert by_action["APPROVED"]["source"] == "QUEUE" and by_action["APPROVED"]["actor_name"]
        assert by_action["REJECTED"]["reason"] == "Trùng với việc đã làm (thử)" and by_action["REJECTED"]["status"] == "REJECTED"
        assert by_action["DEFERRED"]["status"] == "DEFERRED" and by_action["DEFERRED"]["public_id"].startswith("ORB-")
        assert by_action["REOPENED"]["reason"] == "Bấm nhầm nơi nhận (thử)" and by_action["REOPENED"]["status"] == "PENDING_APPROVAL"
        assert data["since"] is not None and data["next_before"] is None
        assert all(row["project_code"] == "orbit" and row["title"] for row in ours)

        # Filtering by project code works, and the window can be walked back with `before`.
        scoped = cto.get("/api/v1/approvals/decisions?project_id=orbit&days=1&limit=2").json()["data"]
        assert len(scoped["items"]) == 2 and scoped["next_before"] is not None
        older = cto.get(f"/api/v1/approvals/decisions?project_id=orbit&before={scoped['next_before']}&limit=100").json()["data"]
        assert older["since"] is None and all(row["at"] < scoped["next_before"] for row in older["items"])
        assert {row["id"] for row in scoped["items"]}.isdisjoint({row["id"] for row in older["items"]})

        # A Project Owner outside the project does not see these decisions.
        theirs = owner.get("/api/v1/approvals/decisions?days=1&limit=100")
        assert theirs.status_code == 200, theirs.text
        assert not [row for row in theirs.json()["data"]["items"] if row["intake_id"] in {approved["id"], rejected["id"], deferred["id"]}]
    finally:
        for intake in (approved, rejected, deferred):
            _retire(intake["id"])
