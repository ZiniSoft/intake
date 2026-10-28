"""Posts for a marketing project (FR-MKT-01, FR-MKT-06, ADR-0067): a post with channel versions and their own dates,
the Đã duyệt state, Đã đăng with and without a link, the post done when every version is out, many posts from
lines, one change on many posts, the week listing, campaigns, and the agent's view."""
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, AuditEvent, WorkChannel, WorkComment, WorkItem, WorkLink

cto = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"


def _cleanup(work_ids: list[str], token_ids: list[str] | None = None) -> None:
    with get_session() as session:
        for work_id in work_ids:
            for model in (WorkChannel, WorkComment, WorkLink):
                for row in session.scalars(select(model).where(model.work_id == work_id)).all():
                    session.delete(row)
            for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id)).all():
                session.delete(row)
            row = session.get(WorkItem, work_id)
            if row is not None:
                session.delete(row)
        for token_id in token_ids or []:
            row = session.get(ApiToken, token_id)
            if row is not None:
                session.delete(row)
        session.commit()


def _move(work: dict, status: str, note: str | None = None):
    current = cto.get(f"/api/v1/work/{work['id']}").json()["data"]
    return cto.post(f"/api/v1/work/{work['id']}/move", json={"status": status, "expected_version": current["version"], "note": note})


def test_a_post_goes_out_on_its_channels_each_on_its_own_day() -> None:
    ids: list[str] = []
    try:
        made = cto.post("/api/v1/work", json={
            "project": "orbit", "title": "Ra mắt bản 5.0", "status": "IN_PROGRESS", "urgent": True, "campaign": "  Bản 5.0  ",
            "channels": [{"channel": "FACEBOOK_PAGE", "publish_at": "2026-10-21T04:30:00Z"}, {"channel": "X", "publish_at": "2026-10-22T09:00:00Z", "language": "en"}, {"channel": "X"}],
        })
        assert made.status_code == 201, made.text
        post = made.json()["data"]
        ids.append(post["id"])
        assert post["channel"] == "FACEBOOK_PAGE" and post["format"] == "POST" and post["campaign"] == "Bản 5.0" and post["urgent"] is True
        assert [(v["channel"], v["status"]) for v in post["channels"]] == [("FACEBOOK_PAGE", "DRAFT"), ("X", "DRAFT")], "the same channel twice is kept once"
        assert post["next_publish_at"].startswith("2026-10-21")
        assert "CHANNEL_UNKNOWN" in cto.post("/api/v1/work", json={"project": "orbit", "title": "x", "channels": [{"channel": "MYSPACE"}]}).text or cto.post("/api/v1/work", json={"project": "orbit", "title": "x", "channels": [{"channel": "MYSPACE"}]}).status_code == 422
        video = cto.post("/api/v1/work", json={"project": "orbit", "title": "Clip 30 giây", "channels": [{"channel": "TIKTOK"}]}).json()["data"]
        ids.append(video["id"])
        assert video["format"] == "VIDEO", "the format follows the channel"

        # One more channel, then a date change, then the Đã duyệt column.
        more = cto.post(f"/api/v1/work/{post['id']}/channels", json={"channel": "LINKEDIN", "publish_at": "2026-10-23T08:00:00Z", "language": "en"})
        assert more.status_code == 201 and [v["channel"] for v in more.json()["data"]["channels"]] == ["FACEBOOK_PAGE", "X", "LINKEDIN"]
        assert "CHANNEL_EXISTS" in cto.post(f"/api/v1/work/{post['id']}/channels", json={"channel": "X"}).text
        x_version = next(v for v in more.json()["data"]["channels"] if v["channel"] == "X")
        moved = cto.patch(f"/api/v1/work/{post['id']}/channels/{x_version['id']}", json={"publish_at": "2026-10-24T09:00:00Z", "status": "READY"})
        assert moved.status_code == 200 and next(v for v in moved.json()["data"]["channels"] if v["channel"] == "X")["publish_at"].startswith("2026-10-24")
        assert _move(post, "ACCEPTANCE").status_code == 200
        approved = _move(post, "APPROVED")
        assert approved.status_code == 200 and approved.json()["data"]["status"] == "APPROVED"

        # Out on every channel: with a link, and once without (allowed, remembered in the audit).
        detail = cto.get(f"/api/v1/work/{post['id']}").json()["data"]
        versions = {v["channel"]: v for v in detail["channels"]}
        assert cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['FACEBOOK_PAGE']['id']}", json={"status": "PUBLISHED", "published_url": "https://www.facebook.com/acme/posts/test-50"}).status_code == 200
        assert "URL_INVALID" in cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['X']['id']}", json={"status": "PUBLISHED", "published_url": "x.com/post"}).text
        assert cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['X']['id']}", json={"status": "PUBLISHED"}).status_code == 200
        with get_session() as session:
            published = session.scalars(select(AuditEvent).where(AuditEvent.entity_id == post["id"], AuditEvent.event_type == "work.published")).all()
            assert len(published) == 2 and any(row.details.get("published_without_url") for row in published)
        still = cto.get(f"/api/v1/work/{post['id']}").json()["data"]
        assert still["status"] == "APPROVED", "one channel version is still waiting"
        assert "CHANNEL_PUBLISHED" in cto.delete(f"/api/v1/work/{post['id']}/channels/{versions['X']['id']}").text
        assert cto.patch(f"/api/v1/work/{post['id']}/channels/{versions['LINKEDIN']['id']}", json={"status": "PUBLISHED", "published_url": "https://www.linkedin.com/posts/test-50"}).status_code == 200
        done = cto.get(f"/api/v1/work/{post['id']}").json()["data"]
        assert done["status"] == "DONE" and done["closed_note"] == "Đã đăng trên mọi kênh"
        assert any(h["event_type"] == "work.moved" and h["actor_name"] == "hệ thống" for h in done["history"][:3])

        # Campaign labels in use; the week listing brings the post back by its publish dates even when closed.
        assert any(row["name"] == "Bản 5.0" for row in cto.get("/api/v1/work/campaigns", params={"project": "orbit"}).json()["data"])
        week = cto.get("/api/v1/work", params={"project": "orbit", "week": "2026-10-19"}).json()["data"]
        assert any(row["id"] == post["id"] for row in week)
        with get_session() as session:
            item = session.get(WorkItem, post["id"])
            item.closed_at = item.closed_at - timedelta(days=60)
            session.commit()
        assert not any(row["id"] == post["id"] for row in cto.get("/api/v1/work", params={"project": "orbit"}).json()["data"])
        assert any(row["id"] == post["id"] for row in cto.get("/api/v1/work", params={"project": "orbit", "week": "2026-10-19"}).json()["data"])
    finally:
        _cleanup(ids)


def test_many_posts_from_lines_and_one_change_on_many() -> None:
    ids: list[str] = []
    try:
        made = cto.post("/api/v1/work/bulk", json={"project": "orbit", "rows": [
            {"title": "Bài 1", "channel": "FACEBOOK_PAGE", "publish_at": "2026-10-26T04:30:00Z"},
            {"title": "Bài 2", "channel": "THREADS", "publish_at": "2026-10-27T05:00:00Z", "campaign": "Tuần 44"},
            {"title": "   ", "channel": "X"},
            {"title": "Bài 4"},
        ]})
        assert made.status_code == 201, made.text
        rows = made.json()["data"]
        assert [row.get("error") for row in rows] == [None, None, "TITLE_REQUIRED", None]
        ids += [row["id"] for row in rows if row.get("id")]
        assert cto.get(f"/api/v1/work/{ids[1]}").json()["data"]["campaign"] == "Tuần 44"
        assert cto.get(f"/api/v1/work/{ids[2]}").json()["data"]["channels"] == []

        changed = cto.post("/api/v1/work/bulk-update", json={"ids": ids, "publish_at": "2026-10-30T04:30:00Z", "status": "IN_PROGRESS"})
        assert changed.status_code == 200 and changed.json()["data"]["changed"] == 3, changed.text
        first = cto.get(f"/api/v1/work/{ids[0]}").json()["data"]
        assert first["status"] == "IN_PROGRESS" and first["channels"][0]["publish_at"].startswith("2026-10-30")
        owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
        refused = owner.post("/api/v1/work/bulk-update", json={"ids": ids, "status": "DISCUSS"}).json()["data"]
        assert refused["changed"] == 0 and len(refused["errors"]) == 3, "outside the owner's projects nothing moves"
    finally:
        _cleanup(ids)


def test_the_agent_makes_a_post_with_a_channel_and_lists_a_week() -> None:
    token = cto.post("/api/v1/auth/tokens", json={"name": "test agent bài"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    ids: list[str] = []
    try:
        answer = agent.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "create_work", "arguments": {
            "project": "orbit", "title": "Bài cho X về nghiệm thu", "channel": "X", "publish_at": "2026-11-03T09:00", "campaign": "Nghiệm thu", "urgent": True}}}).json()
        made = answer["result"]["structuredContent"]
        ids.append(made["id"])
        assert made["channel"] == "X" and made["urgent"] is True and made["channels"][0]["publish_at"].startswith("2026-11-03")
        bad = agent.post(MCP, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "create_work", "arguments": {"project": "orbit", "title": "x", "channel": "X", "publish_at": "next monday"}}}).json()
        assert "ARGUMENT_INVALID" in bad["result"]["content"][0]["text"]
        listed = agent.post(MCP, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_work", "arguments": {"project": "orbit", "week_of": "2026-11-05", "channel": "X"}}}).json()["result"]["structuredContent"]
        assert any(row["id"] == made["id"] for row in listed["items"]) and all(row["channel"] == "X" or any(v["channel"] == "X" for v in row["channels"]) for row in listed["items"])
    finally:
        _cleanup(ids, token_ids=[token["id"]])
