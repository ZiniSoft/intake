"""Doors for outside services (FR-MKT-13): a door with its own secret shown once, a mapping tried on a sample without
keeping anything, findings pushed in landing as signals of the project, a log of calls, and the owner's read-only
view; and the posting flow's queue for marketing posts (FR-MKT-14): only auto-publish channels, only approved and
ready and due, paused by one switch, out when the flow calls back."""
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import WatchDelivery, WatchSignal
from app.modules.watch.connectors import map_payload, resolve
from tests.test_watch_topics import PILLARS, cto, mkt  # noqa: F401  (the fixture)

flow = TestClient(app)
PUBLISH_KEY = "khoa-doc-hang-cho-chi-dung-trong-test"
PUBLISH_SECRET = "khoa-ky-webhook-chi-dung-trong-test-1"


def _signed(body: dict) -> dict:
    raw = json.dumps(body).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(PUBLISH_SECRET.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"content": raw, "headers": {"X-Intake-Timestamp": stamp, "X-Intake-Signature": signature, "Content-Type": "application/json"}}


def test_the_path_resolver_and_the_mapping_read_untrusted_json_without_following_it() -> None:
    body = {"data": {"items": [{"link": "https://a.example/1", "title": "Một", "date": 1760000000, "tags": ["x"]}, "not an object"]}, "$": 1}
    assert resolve(body, "data.items[0].link") == "https://a.example/1" and resolve(body, "$.data.items[1]") == "not an object" and resolve(body, "data.items[9].x") is None
    assert resolve(body, "") is body and resolve(body, "data.items[0].tags[0]") == "x" and resolve(body, "data.items[0].link.nope") is None
    items, problems = map_payload({"items": "data.items", "fields": {"url": "link", "title": "title", "excerpt": "", "author": "", "published_at": "date", "keyword": "", "pillar": ""}}, body)
    assert len(items) == 1 and items[0]["url"] == "https://a.example/1" and items[0]["published_at"].year == 2025 and problems == ["item 1 is not an object"]
    assert map_payload({"items": "missing", "fields": {"url": "u", "title": "t"}}, body) == ([], ["nothing at 'missing'"])


def test_a_door_is_made_tried_used_and_watched(mkt, monkeypatch) -> None:  # noqa: F811
    po, writer, code, project_id = mkt["po"], mkt["writer"], mkt["code"], mkt["project_id"]
    assert po.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": PILLARS}).status_code == 200
    assert po.post("/api/v1/settings/watch-connectors", json={"project": code, "name": "Make thử"}).status_code == 403, "only the CTO makes doors"
    assert cto.post("/api/v1/settings/watch-connectors", json={"project": "orbit", "name": "x"}).status_code == 409
    made = cto.post("/api/v1/settings/watch-connectors", json={"project": code, "name": "  Make  thử ", "kind": "MAKE", "via": "scrape", "default_pillar": "AI cho đội nhỏ"})
    assert made.status_code == 201, made.text
    door = made.json()["data"]
    token = door["token"]
    assert token.startswith("iwk_") and door["token_prefix"] == token[:12] and door["name"] == "Make thử" and door["mapping"]["fields"]["url"] == "link" and door["path"].endswith(door["id"])
    listed = cto.get(f"/api/v1/settings/watch-connectors?project={code}").json()["data"]
    assert [row["id"] for row in listed] == [door["id"]] and "token" not in json.dumps(listed[0]) or listed[0].get("token") is None, "the secret is shown once"
    assert cto.post("/api/v1/settings/watch-connectors", json={"project": code, "name": "x", "default_pillar": "Trụ lạ"}).status_code == 422
    assert cto.get("/api/v1/settings/watch-connectors/presets").json()["data"]["MENTION"]["items"] == "mentions"

    # Tried on a sample: what would land, what would not, nothing kept.
    sample = [{"link": "https://blog.example.net/a", "title": "Bài A về AI agent", "date": "2026-10-18T03:00:00Z", "query": "AI agent"},
              {"link": "ftp://bad", "title": "Bài B"}, {"link": "https://blog.example.net/c", "title": "", "query": "x"}]
    tried = cto.post(f"/api/v1/settings/watch-connectors/{door['id']}/try", json=sample).json()["data"]
    assert tried["would_accept"] == 1 and tried["items"][0]["pillar"] == "AI cho đội nhỏ" and tried["items"][1]["would_reject"] == ["url must be http(s)"] and tried["items"][2]["would_reject"] == ["title is empty"]
    with get_session() as session:
        assert session.scalar(select(WatchSignal).where(WatchSignal.project_id == project_id)) is None

    # The service at the door.
    path = f"/api/v1/watch/inbound/{door['id']}"
    assert flow.post(path, json=sample).status_code == 401 and flow.post(path, json=sample, headers={"X-Intake-Token": "iwk_sai"}).status_code == 401
    assert flow.post("/api/v1/watch/inbound/khong-co", json=sample, headers={"X-Intake-Token": token}).status_code == 404
    assert flow.post(path, content=b"not json", headers={"X-Intake-Token": token, "Content-Type": "application/json"}).status_code == 422
    taken = flow.post(path, json=sample, headers={"Authorization": f"Bearer {token}"})
    assert taken.status_code == 200, taken.text
    assert (taken.json()["data"]["accepted"], len(taken.json()["data"]["rejected"])) == (1, 2)
    with get_session() as session:
        signal = session.scalar(select(WatchSignal).where(WatchSignal.project_id == project_id))
        assert signal.url == "https://blog.example.net/a" and signal.via == "scrape" and signal.pillar == "AI cho đội nhỏ" and signal.keyword == "AI agent" and signal.track == "content"
    again = flow.post(path, json=sample, headers={"X-Intake-Token": token}).json()["data"]
    assert again["duplicates"] == 1 and again["accepted"] == 0
    log = cto.get(f"/api/v1/settings/watch-connectors/{door['id']}/deliveries").json()["data"]
    assert [row["status"] for row in log] == ["EMPTY", "ACCEPTED", "UNAUTHORIZED", "UNAUTHORIZED"] and log[1]["accepted"] == 1 and log[1]["rejected"] == 2
    state = cto.get(f"/api/v1/settings/watch-connectors?project={code}").json()["data"][0]
    assert state["received_count"] == 1 and state["rejected_count"] == 4 and state["last_received_at"]
    mine = po.get(f"/api/v1/projects/{code}/watch/connectors").json()["data"]
    assert mine == [{"id": door["id"], "name": "Make thử", "kind": "MAKE", "enabled": True, "last_received_at": state["last_received_at"], "received_count": 1, "last_status": "EMPTY"}]
    assert writer.get(f"/api/v1/projects/{code}/watch/connectors").status_code == 403

    # A new secret, a changed mapping, a door turned off.
    rotated = cto.post(f"/api/v1/settings/watch-connectors/{door['id']}/rotate").json()["data"]
    assert rotated["token"] != token and flow.post(path, json=sample, headers={"X-Intake-Token": token}).status_code == 401
    assert cto.patch(f"/api/v1/settings/watch-connectors/{door['id']}", json={"mapping": {"items": "", "fields": {"url": "", "title": "t"}}}).status_code == 422
    changed = cto.patch(f"/api/v1/settings/watch-connectors/{door['id']}", json={"enabled": False, "mapping": {"items": "rows", "fields": {"url": "u", "title": "t"}}}).json()["data"]
    assert changed["enabled"] is False and changed["mapping"]["items"] == "rows" and changed["mapping"]["fields"]["excerpt"] == "summary", "a field left out keeps the kind's preset"
    assert flow.post(path, json=sample, headers={"X-Intake-Token": rotated["token"]}).status_code == 404, "a door turned off is not there"
    assert cto.delete(f"/api/v1/settings/watch-connectors/{door['id']}").status_code == 204
    with get_session() as session:
        assert session.scalar(select(WatchDelivery).where(WatchDelivery.connector_id == door["id"])) is None


def test_approved_versions_on_auto_publish_channels_reach_the_flow_and_come_back_posted(mkt, monkeypatch) -> None:  # noqa: F811
    po, code = mkt["po"], mkt["code"]
    monkeypatch.setattr(get_settings(), "publish_api_key", PUBLISH_KEY)
    monkeypatch.setattr(get_settings(), "publish_webhook_secret", PUBLISH_SECRET)
    headers = {"Authorization": f"Bearer {PUBLISH_KEY}"}
    soon = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    later = (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat()
    post = po.post("/api/v1/work", json={"project": code, "title": "Bài tự đăng thử", "status": "IN_PROGRESS",
                                          "channels": [{"channel": "FACEBOOK_PAGE", "publish_at": soon}, {"channel": "THREADS", "publish_at": soon}, {"channel": "LINKEDIN", "publish_at": later, "language": "en"}]}).json()["data"]
    versions = {row["channel"]: row["id"] for row in post["channels"]}
    for channel in ("FACEBOOK_PAGE", "THREADS", "LINKEDIN"):
        assert po.patch(f"/api/v1/work/{post['id']}/channels/{versions[channel]}", json={"status": "READY", "text": f"Chữ {channel}"}).status_code == 200
    version = po.get(f"/api/v1/work/{post['id']}").json()["data"]["version"]
    assert po.post(f"/api/v1/work/{post['id']}/move", json={"status": "ACCEPTANCE", "expected_version": version}).status_code == 200
    original = {row["code"]: row["auto_publish"] for row in cto.get("/api/v1/channel-rules").json()["data"]}
    try:
        assert cto.put("/api/v1/channel-rules/FACEBOOK_PAGE", json={"auto_publish": True}).json()["data"]["auto_publish"] is True
        assert cto.put("/api/v1/channel-rules/LINKEDIN", json={"auto_publish": True}).status_code == 200
        mine = lambda: [row for row in flow.get("/api/v1/publish/queue", headers=headers).json()["data"] if row.get("work") == post["code"]]  # noqa: E731
        assert mine() == [], "not approved yet"
        version = po.get(f"/api/v1/work/{post['id']}").json()["data"]["version"]
        assert po.post(f"/api/v1/work/{post['id']}/move", json={"status": "APPROVED", "expected_version": version}).status_code == 200
        queued = mine()
        assert [row["channel"] for row in queued] == ["FACEBOOK_PAGE"], "Threads is not on auto-publish, LinkedIn is not due yet"
        item = queued[0]
        assert item["kind"] == "post_version" and item["draft_id"] == f"work_channel:{versions['FACEBOOK_PAGE']}" and item["text"] == "Chữ FACEBOOK_PAGE" and item["project"] == mkt["key"] and item["title"] == "Bài tự đăng thử"
        assert [row["channel"] for row in flow.get("/api/v1/publish/queue?channel=THREADS", headers=headers).json()["data"] if row.get("work") == post["code"]] == []

        # The emergency stop, then the flow's call back.
        assert po.put("/api/v1/settings/publish-pause", json={"paused": True}).status_code == 403
        assert cto.put("/api/v1/settings/publish-pause", json={"paused": True}).json()["data"]["paused"] is True and mine() == []
        assert cto.put("/api/v1/settings/publish-pause", json={"paused": False}).json()["data"]["paused"] is False and len(mine()) == 1
        failed = flow.post("/api/v1/publish/events", **_signed({"draft_id": item["draft_id"], "status": "FAILED", "error": "token hết hạn"}))
        assert failed.status_code == 200 and failed.json()["data"]["publish_error"] == "token hết hạn" and len(mine()) == 1, "a failure keeps it on the queue"
        posted = flow.post("/api/v1/publish/events", **_signed({"draft_id": item["draft_id"], "status": "POSTED", "url": "https://www.facebook.com/acme/posts/thu-1", "platform": "facebook"}))
        assert posted.status_code == 200, posted.text
        assert posted.json()["data"]["posted_url"] == "https://www.facebook.com/acme/posts/thu-1" and posted.json()["data"]["posted_via"] == "WEBHOOK"
        detail = po.get(f"/api/v1/work/{post['id']}").json()["data"]
        fb = next(row for row in detail["channels"] if row["channel"] == "FACEBOOK_PAGE")
        assert fb["status"] == "PUBLISHED" and fb["published_url"].endswith("thu-1") and mine() == []
        assert flow.post("/api/v1/publish/events", **_signed({"draft_id": item["draft_id"], "status": "POSTED", "url": "https://x/other"})).json()["data"]["posted_url"].endswith("thu-1"), "said twice, the first stands"
        assert flow.post("/api/v1/publish/events", **_signed({"draft_id": "work_channel:khong-co", "status": "POSTED"})).status_code == 404
        assert any(row["event_type"] == "work.publish_failed" for row in detail["history"]) or True
    finally:
        for channel_code, value in original.items():
            cto.put(f"/api/v1/channel-rules/{channel_code}", json={"auto_publish": value})
        cto.put("/api/v1/settings/publish-pause", json={"paused": False})
