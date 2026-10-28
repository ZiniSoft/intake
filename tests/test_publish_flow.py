"""The posting flow outside Intake (FR-CNT-10): a read-only queue and a signed call back."""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditEvent
from app.services.ai_processor import AIPostDraft
from app.workers import ai_tasks
from tests.test_private_space import _idea, _space, cto

KEY = "khoa-doc-hang-cho-chi-dung-trong-test"
SECRET = "khoa-ky-webhook-chi-dung-trong-test-1"
# No cookie, no subject header: the flow is not a signed-in person.
flow = TestClient(app)


def _signed(body: dict, secret: str = SECRET, at: float | None = None) -> dict:
    raw = json.dumps(body).encode()
    stamp = str(int(at if at is not None else time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"content": raw, "headers": {"X-Intake-Timestamp": stamp, "X-Intake-Signature": signature, "Content-Type": "application/json"}}


@pytest.fixture()
def approved(monkeypatch):
    monkeypatch.setattr("app.modules.drafts.service._publish", lambda draft_id: None)

    async def write(source_text: str, long: bool = False) -> AIPostDraft:
        return AIPostDraft(text="NOI-DUNG-DA-DUYET cho luồng đăng.", hooks=[], gaps=[])

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", write)
    project = _space()["project"]
    idea = _idea(project["code"], "Ý thử cho luồng đăng bên ngoài.")
    drafts = f"/api/v1/intakes/{idea['id']}/drafts"
    made = []
    for channel in ("LINKEDIN", "THREADS"):
        draft = cto.post(drafts, json={"channel": channel, "track": "business"}).json()["data"]
        assert ai_tasks.write_post_draft(draft["id"]) == "SUCCEEDED"
        made.append(draft["id"])
    yield {"drafts": drafts, "ready": made[0], "waiting": made[1]}
    cto.delete(f"/api/v1/intakes/{idea['id']}")


def test_both_routes_are_closed_until_their_secrets_are_set(approved, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "publish_api_key", None)
    monkeypatch.setattr(get_settings(), "publish_webhook_secret", "ngan")
    assert flow.get("/api/v1/publish/queue", headers={"Authorization": "Bearer bat-ky"}).status_code == 404
    assert flow.post("/api/v1/publish/events", **_signed({"draft_id": approved["ready"], "status": "POSTED"}, secret="ngan")).status_code == 404, "a short secret counts as none"


def test_the_flow_reads_only_what_was_approved(approved, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "publish_api_key", KEY)
    when = (datetime.now(timezone.utc) + timedelta(days=1)).replace(microsecond=0)
    assert cto.post(f"{approved['drafts']}/{approved['ready']}/approve", json={"scheduled_for": when.isoformat()}).status_code == 200

    assert flow.get("/api/v1/publish/queue").status_code == 401
    assert flow.get("/api/v1/publish/queue", headers={"Authorization": f"Bearer {KEY}x"}).status_code == 401
    assert flow.get("/api/v1/publish/queue", headers={"Authorization": KEY}).status_code == 401

    queue = flow.get("/api/v1/publish/queue", headers={"Authorization": f"Bearer {KEY}"})
    assert queue.status_code == 200, queue.text
    mine = [row for row in queue.json()["data"] if row["draft_id"] in (approved["ready"], approved["waiting"])]
    assert [row["draft_id"] for row in mine] == [approved["ready"]], "a draft that is not approved never leaves"
    assert mine[0]["text"] == "NOI-DUNG-DA-DUYET cho luồng đăng." and mine[0]["channel"] == "LINKEDIN" and mine[0]["track"] == "business"
    assert datetime.fromisoformat(mine[0]["scheduled_for"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc) == when
    assert flow.get("/api/v1/publish/queue?channel=THREADS", headers={"Authorization": f"Bearer {KEY}"}).json()["data"] == [] or approved["ready"] not in [
        row["draft_id"] for row in flow.get("/api/v1/publish/queue?channel=THREADS", headers={"Authorization": f"Bearer {KEY}"}).json()["data"]
    ]

    # The key reads the queue and nothing else.
    assert flow.get("/api/v1/private-space", headers={"Authorization": f"Bearer {KEY}"}).status_code in (401, 403)
    assert flow.get(approved["drafts"], headers={"Authorization": f"Bearer {KEY}"}).status_code in (401, 403, 404)


def test_a_signed_call_back_records_the_post_once(approved, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "publish_api_key", KEY)
    monkeypatch.setattr(get_settings(), "publish_webhook_secret", SECRET)
    events = "/api/v1/publish/events"
    posted_at = (datetime.now(timezone.utc) - timedelta(minutes=12)).replace(microsecond=0)
    said = {"draft_id": approved["ready"], "status": "POSTED", "posted_at": posted_at.isoformat(), "url": "https://example.com/da-dang", "platform": "linkedin"}

    assert flow.post(events, **_signed(said)).status_code == 409, "not approved: none of the flow's business"
    assert cto.post(f"{approved['drafts']}/{approved['ready']}/approve", json={}).status_code == 200

    # Unsigned, wrongly signed, stale, or changed after signing.
    assert flow.post(events, json=said).status_code == 401
    assert flow.post(events, **_signed(said, secret="mot-khoa-khac-dai-hon-hai-muoi-bon-ky-tu")).status_code == 401
    assert flow.post(events, **_signed(said, at=time.time() - 3600)).status_code == 401
    tampered = _signed(said)
    tampered["content"] = tampered["content"].replace(b"da-dang", b"da-sua")
    assert flow.post(events, **tampered).status_code == 401
    assert cto.get(approved["drafts"]).json()["data"][-1]["posted_at"] is None, "nothing was recorded by a refused call"

    assert flow.post(events, **_signed({**said, "status": "FAILED", "error": "  Nền tảng   từ chối bài. "})).json()["data"]["publish_error"] == "Nền tảng từ chối bài."
    still = next(row for row in cto.get(approved["drafts"]).json()["data"] if row["id"] == approved["ready"])
    assert still["posted_at"] is None and still["approved_at"] and still["publish_error"] == "Nền tảng từ chối bài."
    assert approved["ready"] in [row["draft_id"] for row in flow.get("/api/v1/publish/queue", headers={"Authorization": f"Bearer {KEY}"}).json()["data"]], "a failed post stays in the queue"

    done = flow.post(events, **_signed(said))
    assert done.status_code == 200, done.text
    recorded = next(row for row in cto.get(approved["drafts"]).json()["data"] if row["id"] == approved["ready"])
    assert datetime.fromisoformat(recorded["posted_at"].replace("Z", "+00:00")).replace(tzinfo=timezone.utc) == posted_at
    assert recorded["posted_url"] == "https://example.com/da-dang" and recorded["posted_via"] == "WEBHOOK" and recorded["publish_error"] is None

    # Said again, or said differently later: the first record stands.
    again = flow.post(events, **_signed({**said, "url": "https://example.com/khac", "posted_at": datetime.now(timezone.utc).isoformat()}))
    assert again.status_code == 200 and again.json()["data"]["posted_url"] == "https://example.com/da-dang"
    assert approved["ready"] not in [row["draft_id"] for row in flow.get("/api/v1/publish/queue", headers={"Authorization": f"Bearer {KEY}"}).json()["data"]]

    assert flow.post(events, **_signed({"draft_id": "00000000-0000-4000-8000-00000000dead", "status": "POSTED"})).status_code == 404
    assert flow.post(events, **_signed({"draft_id": approved["ready"], "status": "DELETED"})).status_code == 422
    assert flow.post(events, **_signed({**said, "url": "javascript:alert(1)"})).status_code == 422
    with get_session() as session:
        rows = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == approved["ready"], AuditEvent.actor_type == "INTEGRATION")).all()
    assert sorted(row.event_type for row in rows) == ["draft.post_failed", "draft.posted_by_flow"], "one record of each thing that happened"
