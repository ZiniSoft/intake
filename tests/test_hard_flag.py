"""The CTO's "hard work" mark on a request (FR-PLAN-39)."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AuditEvent
from tests.test_work_log import _call

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def _create(agent: TestClient, **extra) -> dict:
    created = agent.post("/api/v1/intakes", json={
        "project_id": "orbit", "channel": "MANUAL", "raw_text": f"Yêu cầu thử cờ khó {uuid4().hex[:8]}", **extra,
    })
    assert created.status_code == 201, created.text
    return created.json()["data"]


def _flag_events(intake_id: str) -> list[dict]:
    with get_session() as session:
        rows = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == intake_id, AuditEvent.event_type == "intake.hard_flag_changed")).all()
        return [dict(row.details) for row in rows]


def test_flag_defaults_off_and_only_the_cto_can_set_it() -> None:
    plain = _create(cto)
    assert plain["needs_cto_acceptance"] is False

    marked = _create(cto, needs_cto_acceptance=True)
    assert marked["needs_cto_acceptance"] is True



def test_flag_is_toggled_on_the_detail_by_the_cto_with_an_audit_trail() -> None:
    item = _create(cto)
    refused = owner.patch(f"/api/v1/intakes/{item['id']}/hard-flag", json={"needs_cto_acceptance": True})
    assert refused.status_code in (403, 404)  # the owner has no seat in this project: refused either way

    on = cto.patch(f"/api/v1/intakes/{item['id']}/hard-flag", json={"needs_cto_acceptance": True})
    assert on.status_code == 200 and on.json()["data"]["needs_cto_acceptance"] is True
    cto.patch(f"/api/v1/intakes/{item['id']}/hard-flag", json={"needs_cto_acceptance": True})  # no change, no event
    off = cto.patch(f"/api/v1/intakes/{item['id']}/hard-flag", json={"needs_cto_acceptance": False})
    assert off.json()["data"]["needs_cto_acceptance"] is False
    assert [event["needs_cto_acceptance"] for event in _flag_events(item["id"])] == [True, False]
    assert cto.get(f"/api/v1/intakes/{item['id']}").json()["data"]["needs_cto_acceptance"] is False


def test_mcp_create_and_get_carry_the_flag_for_the_cto_only() -> None:
    token = cto.post("/api/v1/auth/tokens", json={"name": "hard flag test"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    text = f"Yêu cầu thử cờ khó MCP {uuid4().hex[:8]}"
    made = _call(agent, "create_intake", {"project": "orbit", "text": text, "idempotency_key": uuid4().hex, "needs_cto_acceptance": True})["structuredContent"]
    ref = made["id"]
    assert _call(agent, "get_intake", {"ref": ref})["structuredContent"]["needs_cto_acceptance"] is True
