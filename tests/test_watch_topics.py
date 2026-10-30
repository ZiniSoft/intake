"""A marketing project listens (FR-MKT-08..10, ADR-0068): pillars with keywords and hashtags, networks and a schedule
within what the CTO opened, one scanning flow for several projects, signals scored into topics by rule, AI words on
top with the rule words as the fallback, Thành bài and Thành chuỗi, the daily caps and the half-hour tick."""
import hashlib
import hmac
import json
import random
import string
import time
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import (
    ApiToken, AuditEvent, PostClick, PostLink, Project, ProjectIntegration, User, UserProjectAccess, WatchCheck, WatchContact, WatchPlatform, WatchRequest,
    WatchSignal, WatchSource, WatchTopic, WorkChannel, WorkComment, WorkforceMember, WorkforceProjectMembership, WorkItem, WorkLink,
)
from app.modules.watch import topics as topics_module
from app.modules.watch.topics import topics_service
from app.services.ai_processor import AIHotTopic, AIHotTopics, AIProviderTransientError
from app.workers import ai_tasks, planning_tasks

cto = TestClient(app, headers={"X-User-Subject": "cto"})
flow = TestClient(app)
KEY = "khoa-doc-cau-hinh-quet-chi-dung-trong-test"
SECRET = "khoa-ky-tin-hieu-chi-dung-trong-test-12"  # gitleaks:allow - synthetic test credential
LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")
PILLARS = [
    {"name": "AI cho đội nhỏ", "description": "Cách đội 2 đến 10 người dùng AI mà không cần kỹ sư", "audience": "Chủ doanh nghiệp nhỏ", "channels": ["FACEBOOK_PAGE", "LINKEDIN"],
     "share_pct": 60, "keywords": [{"text": "AI agent", "priority": "high"}, "tự động hóa", {"text": "aiagent", "kind": "hashtag"}], "samples": [{"title": "Bài mẫu", "url": "https://example.com/mau"}], "avoid": "Không hứa kết quả"},
    {"name": "Câu chuyện khách", "channels": ["FACEBOOK_PAGE"], "share_pct": 40, "keywords": ["case study"]},
]


def _signed(body: dict, secret: str = SECRET) -> dict:
    raw = json.dumps(body).encode()
    stamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), stamp.encode() + b"." + raw, hashlib.sha256).hexdigest()
    return {"content": raw, "headers": {"X-Intake-Timestamp": stamp, "X-Intake-Signature": signature, "Content-Type": "application/json"}}


def _cleanup(code: str, member_ids: list[str], user_ids: list[str]) -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == code))
        if project is not None:
            for work in session.scalars(select(WorkItem).where(WorkItem.project_id == project.id)).all():
                for version in session.scalars(select(WorkChannel).where(WorkChannel.work_id == work.id)).all():
                    for link in session.scalars(select(PostLink).where(PostLink.work_channel_id == version.id)).all():
                        session.execute(delete(PostClick).where(PostClick.link_id == link.id))
                        session.delete(link)
                    session.delete(version)
                for model in (WorkComment, WorkLink):
                    session.execute(delete(model).where(model.work_id == work.id))
                session.delete(work)
            for model in (WatchTopic, WatchSignal, WatchSource, WatchCheck, WatchRequest, AuditEvent, UserProjectAccess, ProjectIntegration, WorkforceProjectMembership):
                session.execute(delete(model).where(model.project_id == project.id))
            session.execute(delete(WatchContact).where(WatchContact.project_id == project.id))
            project.owner_member_id = None
            session.flush()
        for user_id in user_ids:
            session.execute(delete(ApiToken).where(ApiToken.user_id == user_id))
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)
        for member_id in member_ids:
            session.execute(delete(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id))
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
        session.flush()
        if project is not None:
            session.delete(project)
        session.commit()


@pytest.fixture()
def mkt(monkeypatch):
    """A made-up marketing project with an owner login and a writer login; the flow's secrets set; nothing queued."""
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(topics_module, "_publish", lambda project_id, actor_id: asked.append((project_id, actor_id)))
    monkeypatch.setattr("app.modules.watch.service._publish", lambda request_id: None)
    monkeypatch.setattr(get_settings(), "watch_api_key", KEY)
    monkeypatch.setattr(get_settings(), "watch_webhook_secret", SECRET)
    tag = uuid4().hex[:6]
    code = f"mkt-{tag}"
    key = "T" + "".join(random.choices(string.ascii_uppercase, k=4))
    made = cto.post("/api/v1/projects", json={"name": f"Marketing thử {tag}", "code": code, "intake_key": key, "kind": "NON_CODE"})
    assert made.status_code == 201, made.text
    project_id = made.json()["data"]["id"]
    members: list[str] = []
    users: list[str] = []
    try:
        owner = cto.post("/api/v1/planning/members", json={"display_name": f"Owner {tag}", "email_reference": f"po{tag}@example.test"}).json()["data"]
        members.append(owner["id"])
        team = cto.put(f"/api/v1/projects/{code}/team", json={"owner_member_id": owner["id"], "member_ids": []})
        assert team.status_code == 200, team.text
        issued = team.json()["data"]["issued"]
        users.append(next(row for row in cto.get("/api/v1/users").json()["data"] if row["subject"] == issued["subject"])["id"])
        po = TestClient(app, headers={"X-User-Subject": issued["subject"]})
        assert po.post("/api/v1/auth/password", json={"current_password": issued["temporary_password"], "new_password": f"po-pass-{tag}-long"}).status_code == 200
        writer_member = cto.post("/api/v1/planning/members", json={"display_name": f"Viết {tag}", "email_reference": f"viet-{tag}@example.test",
                                                                   "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "0", "role": "Developer"}]}).json()["data"]
        members.append(writer_member["id"])
        dev = cto.post("/api/v1/users", json={"subject": f"viet{tag}", "role": "DEVELOPER", "member_id": writer_member["id"]})
        assert dev.status_code == 201, dev.text
        users.append(dev.json()["data"]["account"]["id"])
        writer = TestClient(app, headers={"X-User-Subject": f"viet{tag}"})
        assert writer.post("/api/v1/auth/password", json={"current_password": dev.json()["data"]["temporary_password"], "new_password": f"viet-pass-{tag}-long"}).status_code == 200
        yield {"project_id": project_id, "code": code, "key": key, "po": po, "writer": writer, "writer_member_id": writer_member["id"], "asked": asked}
    finally:
        cto.put("/api/v1/settings/watch-platforms/YOUTUBE", json={"enabled": False})
        _cleanup(code, members, users)


def _send(items: list[dict]) -> dict:
    sent = flow.post("/api/v1/watch/signals", **_signed({"items": items}))
    assert sent.status_code == 200, sent.text
    return sent.json()["data"]


def _seed_signals(mkt: dict) -> dict:
    """Three groups: a strong one on a priority keyword from three sites, a repeated one from one source, a scraped hashtag one."""
    key = mkt["key"]
    source = mkt["po"].post(f"/api/v1/projects/{mkt['code']}/watch/sources", json={"url": "https://blog.example.com/feed", "track": "content", "label": "Blog thử"}).json()["data"]
    fresh = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    items = [
        {"url": "https://a.example.com/1", "title": "DOI-NHO-1 Doanh nghiệp nhỏ bắt đầu dùng AI agent", "project": key, "track": "content", "pillar": "AI cho đội nhỏ", "keyword": "AI agent", "priority": "high", "published_at": fresh},
        {"url": "https://b.example.com/2", "title": "DOI-NHO-2 Cửa hàng 5 người dùng agent trả lời khách", "project": key.lower(), "pillar": "AI cho đội nhỏ", "keyword": "AI agent", "priority": "high"},
        {"url": "https://c.example.com/3", "title": "DOI-NHO-3 Có ai thử agent trả lời inbox chưa", "project": key, "keyword": "AI agent"},
        *[{"url": f"https://blog.example.com/tu-dong-{n}", "title": f"TU-DONG-{n} Tự động hóa đơn hàng", "source_id": source["id"], "pillar": "AI cho đội nhỏ", "keyword": "tự động hóa"} for n in range(5)],
        {"url": "https://tiktok.example.com/v/1", "title": "HASHTAG-1 clip về aiagent", "project": key, "keyword": "#aiagent", "via": "scrape"},
        {"url": "https://threads.example.com/p/2", "title": "HASHTAG-2 thread về aiagent", "project": key, "keyword": "#aiagent", "via": "scrape"},
        {"url": "https://a.example.com/1", "title": "Trùng", "project": key},
        {"url": "https://nowhere.example.com/x", "title": "Dự án lạ", "project": "ZZZZ"},
    ]
    result = _send(items)
    assert (result["accepted"], result["duplicates"]) == (10, 1) and [row["reason"] for row in result["rejected"]] == ["unknown project"], result
    return {"source": source}


def test_pillars_settings_and_the_flow_config_cover_the_marketing_project(mkt) -> None:
    po, writer, code = mkt["po"], mkt["writer"], mkt["code"]
    saved = po.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": PILLARS})
    assert saved.status_code == 200, saved.text
    first = saved.json()["data"][0]
    assert first["keywords"] == [{"text": "AI agent", "kind": "keyword", "priority": "high"}, {"text": "tự động hóa", "kind": "keyword", "priority": "normal"}, {"text": "#aiagent", "kind": "hashtag", "priority": "normal"}]
    assert first["channels"] == ["FACEBOOK_PAGE", "LINKEDIN"] and first["share_pct"] == 60 and first["samples"][0]["url"] == "https://example.com/mau" and first["avoid"] == "Không hứa kết quả"
    assert writer.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": PILLARS}).status_code == 403, "a writer reads the pillars, the owner writes them"
    assert cto.get("/api/v1/projects/orbit/watch/pillars").status_code == 409, "a software project has no pillars to listen on"
    assert po.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": [{"name": "A"}, {"name": "a"}]}).status_code == 422, "two pillars with one name"

    settings = po.get(f"/api/v1/projects/{code}/watch/settings").json()["data"]
    assert settings["schedule"] == {"times": ["06:00", "13:00"], "weekdays": [1, 2, 3, 4, 5, 6, 7]} and settings["scan_every_hours"] == 2
    assert {"WEB", "TRENDS"} <= set(settings["open_networks"]) and "YOUTUBE" not in settings["open_networks"] and settings["max_ai_runs_per_day"] == 4
    refused = po.put(f"/api/v1/projects/{code}/watch/settings", json={"networks": ["YOUTUBE"]})
    assert refused.status_code == 422 and "NETWORK_NOT_OPEN" in refused.text, "a network the CTO has not opened cannot be turned on"
    assert po.put("/api/v1/settings/watch-platforms/YOUTUBE", json={"enabled": True}).status_code == 403
    assert cto.put("/api/v1/settings/watch-platforms/LINKEDIN", json={"enabled": True}).status_code == 422, "nothing reads LinkedIn yet"
    assert cto.put("/api/v1/settings/watch-platforms/YOUTUBE", json={"enabled": True}).status_code == 200
    changed = po.put(f"/api/v1/projects/{code}/watch/settings", json={"networks": ["YOUTUBE", "WEB"], "times": ["13:00", "06:00", "18:00"], "weekdays": [1, 2, 3, 4, 5], "scan_every_hours": 4})
    assert changed.status_code == 200, changed.text
    assert changed.json()["data"]["networks"] == ["YOUTUBE", "WEB"] and changed.json()["data"]["schedule"]["times"] == ["06:00", "13:00", "18:00"] and changed.json()["data"]["ai_runs_per_week"] == 15
    assert "SCHEDULE_INVALID" in po.put(f"/api/v1/projects/{code}/watch/settings", json={"times": ["01:00", "02:00", "03:00", "04:00", "05:00"]}).text, "more runs than the CTO's cap"
    assert "SCHEDULE_INVALID" in po.put(f"/api/v1/projects/{code}/watch/settings", json={"scan_every_hours": 3}).text

    source = po.post(f"/api/v1/projects/{code}/watch/sources", json={"url": "https://trends.google.com/trending/rss?geo=VN", "track": "content", "label": "Trends"})
    assert source.status_code == 201 and source.json()["data"]["track"] == "content", source.text
    keywords = po.get(f"/api/v1/projects/{code}/watch/keywords").json()["data"]
    assert keywords["track"] == "content" and keywords["pillars"][0] == {"pillar": "AI cho đội nhỏ", "keywords": ["AI agent", "tự động hóa", "#aiagent"]}
    assert po.post(f"/api/v1/projects/{code}/watch/keywords/suggest").status_code == 202

    config = flow.get("/api/v1/watch/config", headers={"Authorization": f"Bearer {KEY}"})
    assert config.status_code == 200, config.text
    mine = next(row for row in config.json()["data"]["projects"] if row["project"] == mkt["key"])
    assert mine["kind"] == "NON_CODE" and mine["networks"] == ["YOUTUBE", "WEB"] and mine["scan_every_hours"] == 4 and mine["next_scan_at"] is None, "the first read has no rhythm to count from"
    track = mine["tracks"][0]
    assert track["track"] == "content" and [row["url"] for row in track["sources"]] == ["https://trends.google.com/trending/rss?geo=VN"]
    assert track["pillars"][0]["keywords"] == ["AI agent", "tự động hóa", "#aiagent"] and track["pillars"][0]["terms"][0] == {"text": "AI agent", "kind": "keyword", "priority": "high"}
    assert track["demand"]["wanted_per_week"] == 30 and track["demand"]["accept_up_to"] == 45
    again = next(row for row in flow.get("/api/v1/watch/config", headers={"Authorization": f"Bearer {KEY}"}).json()["data"]["projects"] if row["project"] == mkt["key"])
    assert again["next_scan_at"] is not None, "from the second read on, the flow knows when to come back"
    health = po.get(f"/api/v1/projects/{code}/watch/health").json()["data"]
    assert health["last_config_at"] and health["tracks"][0]["track"] == "content"


def test_signals_land_on_their_project_and_are_scored_into_topics_by_rule(mkt) -> None:
    po, writer, code, project_id = mkt["po"], mkt["writer"], mkt["code"], mkt["project_id"]
    assert po.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": PILLARS}).status_code == 200
    _seed_signals(mkt)
    with get_session() as session:
        rows = session.scalars(select(WatchSignal).where(WatchSignal.project_id == project_id)).all()
        assert len(rows) == 10 and all(row.track == "content" for row in rows)
        scraped = next(row for row in rows if row.url == "https://tiktok.example.com/v/1")
        assert (scraped.via, scraped.priority) == ("scrape", "normal") and next(row for row in rows if row.url == "https://a.example.com/1").priority == "high"

    assert topics_service.build(project_id, ai=None) is not None
    board = writer.get(f"/api/v1/watch-topics?project={code}")
    assert board.status_code == 200, board.text
    data = board.json()["data"]
    assert data["has_sources"] and data["refresh_left"] == 3 and data["kept_this_week"] == 0 and data["built_at"]
    titles = [(row["score"], row["pillar"], row["sources"], len(row["signals"]), row["ai_written"]) for row in data["topics"]]
    # Three sites on a priority keyword with a fresh post: 2*3 + 3 + 2 (pillar) + 2 (fresh) + 1 (priority) = 14.
    # Five posts from one source: 2 + 5 + 2 = 9. Two scraped hashtag posts: 2*2 + 2 - 1 = 5.
    assert titles == [(14, "AI cho đội nhỏ", 3, 3, False), (9, "AI cho đội nhỏ", 1, 5, False), (5, None, 2, 2, False)], titles
    strong = data["topics"][0]
    assert strong["title"].startswith("DOI-NHO-1") and "3 nguồn, 3 bài" in strong["why"] and strong["angles"] == []
    assert cto.get("/api/v1/watch-topics?project=orbit").status_code == 409

    # Built again, the same subjects land on the same rows; the words of the AI are kept, the score is refreshed.
    ai = [{"id": strong["id"], "title": "Đội ba người làm được gì với agent trong một tuần", "why": "Ba nguồn cùng nói. Trụ AI cho đội nhỏ mới có một bài tuần này.",
           "angles": ["Góc một", "Góc hai", "Góc ba", "Góc bốn"], "channels": ["FACEBOOK_PAGE", "LINKEDIN"], "caution": "Số liệu trong nhóm Facebook chưa kiểm.", "pillar": "AI cho đội nhỏ"}]
    assert topics_service.apply_ai(project_id, ai) == 1
    _send([{"url": "https://d.example.com/4", "title": "DOI-NHO-4 thêm một bài", "project": mkt["key"], "keyword": "AI agent", "pillar": "AI cho đội nhỏ"}])
    topics_service.build(project_id, ai=None)
    data = po.get(f"/api/v1/watch-topics?project={code}").json()["data"]
    assert len(data["topics"]) == 3, "no duplicate for a subject built twice in a week"
    strong = data["topics"][0]
    assert strong["id"] == ai[0]["id"] and strong["title"] == ai[0]["title"] and strong["angles"] == ["Góc một", "Góc hai", "Góc ba"] and strong["ai_written"] and strong["sources"] == 4

    # The worker: rules, one AI call with the team's standard first, the answer laid on; an AI error leaves the rule words.
    seen: list[str] = []

    async def summarize(source_text: str) -> AIHotTopics:
        seen.append(source_text)
        return AIHotTopics(topics=[AIHotTopic(index=2, title="Chủ đề từ AI", why="Vì.", angles=["A"], channels=["THREADS"], caution="", pillar="Trụ lạ")])

    import app.workers.ai_tasks as tasks
    tasks_adapter = tasks.umodelverse_adapter
    original = tasks_adapter.summarize_topics
    try:
        tasks_adapter.summarize_topics = summarize
        assert ai_tasks.summarize_topics(project_id) == "SUCCEEDED"
    finally:
        tasks_adapter.summarize_topics = original
    message = seen[0]
    assert message.index("Pillars (written by the team's owner)") < message.index("Channel rules") < message.index("Topics (found by a scanning tool")
    assert "avoid: Không hứa kết quả" in message and "[0] keyword: AI agent" in message and "x" * 50 not in message
    data = po.get(f"/api/v1/watch-topics?project={code}").json()["data"]
    weak = data["topics"][2]
    assert weak["title"] == "Chủ đề từ AI" and weak["pillar"] is None, "a pillar the project does not have is not taken"

    async def broken(source_text: str) -> AIHotTopics:
        raise AIProviderTransientError("umodelverse", "UMODELVERSE_UNAVAILABLE")

    try:
        tasks_adapter.summarize_topics = broken
        assert ai_tasks.summarize_topics(project_id) == "FAILED"
    finally:
        tasks_adapter.summarize_topics = original
    with get_session() as session:
        last = session.scalar(select(AuditEvent).where(AuditEvent.project_id == project_id, AuditEvent.event_type == "watch.topics_built").order_by(AuditEvent.created_at.desc()).limit(1))
        assert last.details["ai"] == "failed" and last.details["error"] == "UMODELVERSE_UNAVAILABLE"
    assert po.get(f"/api/v1/watch-topics?project={code}").json()["data"]["topics"][2]["title"] == "Chủ đề từ AI", "the words already there stand"


def test_thanh_bai_and_thanh_chuoi_make_posts_and_remember_what_was_used(mkt) -> None:
    po, writer, code, project_id = mkt["po"], mkt["writer"], mkt["code"], mkt["project_id"]
    assert po.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": PILLARS}).status_code == 200
    _seed_signals(mkt)
    topics_service.build(project_id, ai=None)
    data = po.get(f"/api/v1/watch-topics?project={code}").json()["data"]
    strong, repeated, scraped = data["topics"]
    topics_service.apply_ai(project_id, [{"id": strong["id"], "title": strong["title"], "angles": ["Góc A", "Góc B"], "pillar": "AI cho đội nhỏ"}])

    assert writer.post(f"/api/v1/watch-topics/{strong['id']}/post?project={code}", json={"mode": "series"}).status_code == 403
    monday = (datetime.now(LOCAL).date() + timedelta(days=7))
    monday -= timedelta(days=monday.weekday())
    made = po.post(f"/api/v1/watch-topics/{strong['id']}/post?project={code}", json={"mode": "series", "angle": 1, "member_id": mkt["writer_member_id"], "week": monday.isoformat()})
    assert made.status_code == 201, made.text
    post = made.json()["data"]
    assert post["status"] == "DISCUSS" and post["title"] == "Góc B" and post["member_id"] == mkt["writer_member_id"] and post["project_id"] == project_id
    assert "Nguồn:" in post["description"] and "https://a.example.com/1" in post["description"]
    versions = {row["channel"]: row for row in post["channels"]}
    assert set(versions) == {"FACEBOOK_PAGE", "LINKEDIN"}, "the pillar's channels"
    fb_day = datetime.fromisoformat(versions["FACEBOOK_PAGE"]["publish_at"]).astimezone(LOCAL).date()
    li_day = datetime.fromisoformat(versions["LINKEDIN"]["publish_at"]).astimezone(LOCAL).date()
    assert fb_day == monday + timedelta(days=1) and li_day == fb_day + timedelta(days=1) and versions["LINKEDIN"]["language"] == "en"
    assert datetime.fromisoformat(versions["FACEBOOK_PAGE"]["publish_at"]).astimezone(LOCAL).strftime("%H:%M") == "11:30", "the channel's first good hour"
    assert [link["note"] for link in post["links"]][:1] == ["DOI-NHO-1 Doanh nghiệp nhỏ bắt đầu dùng AI agent"] and 1 <= len(post["links"]) <= 5
    again = po.post(f"/api/v1/watch-topics/{strong['id']}/post?project={code}", json={"mode": "post"})
    assert again.status_code == 201 and again.json()["data"]["id"] == post["id"], "asked twice, the same post"

    plain = po.post(f"/api/v1/watch-topics/{repeated['id']}/post?project={code}", json={"mode": "post"})
    assert plain.status_code == 201 and plain.json()["data"]["channels"] == [] and plain.json()["data"]["title"].startswith("TU-DONG-")
    assert po.delete(f"/api/v1/watch-topics/{scraped['id']}?project={code}").status_code == 204
    assert po.delete(f"/api/v1/watch-topics/khong-phai-ma?project={code}").status_code == 404
    data = po.get(f"/api/v1/watch-topics?project={code}").json()["data"]
    assert data["kept_this_week"] == 2 and [(row["state"], bool(row["work_id"])) for row in data["topics"]] == [("USED", True), ("USED", True), ("DISMISSED", False)]
    with get_session() as session:
        states = {row.url: row.state for row in session.scalars(select(WatchSignal).where(WatchSignal.project_id == project_id)).all()}
        assert states["https://a.example.com/1"] == "USED" and states["https://blog.example.com/tu-dong-0"] == "USED" and states["https://tiktok.example.com/v/1"] == "DISMISSED", "dropping a topic drops its signals, so it does not come back"
        kept = session.scalars(select(AuditEvent).where(AuditEvent.project_id == project_id, AuditEvent.event_type == "watch.topic_kept")).all()
        assert {row.details["mode"] for row in kept} == {"series", "post"}
    assert po.post(f"/api/v1/watch-topics/{scraped['id']}/post?project={code}", json={"mode": "post"}).status_code == 409, "a dropped topic makes nothing"

    # The keyword a used topic stood on counts against a new group on the same keyword for two weeks: 2 + 1 + 2 - 3 = 2.
    _send([{"url": "https://blog.example.com/tu-dong-moi", "title": "TU-DONG-MOI lại tự động hóa", "project": mkt["key"], "keyword": "tự động hóa", "pillar": "AI cho đội nhỏ"}])
    topics_service.build(project_id, ai=None)
    fresh = [row for row in po.get(f"/api/v1/watch-topics?project={code}").json()["data"]["topics"] if row["state"] == "NEW"]
    assert [(row["title"][:11], row["score"]) for row in fresh] == [("TU-DONG-MOI", 2)], fresh


def test_refresh_is_capped_per_day_and_the_tick_finds_the_projects_due(mkt, monkeypatch) -> None:
    po, code, project_id = mkt["po"], mkt["code"], mkt["project_id"]
    assert po.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": PILLARS}).status_code == 200
    assert po.post(f"/api/v1/watch-topics/refresh?project={code}").status_code == 202
    assert po.post(f"/api/v1/watch-topics/refresh?project={code}").json()["data"]["refresh_left"] == 1
    assert po.post(f"/api/v1/watch-topics/refresh?project={code}").json()["data"]["refresh_left"] == 0
    fourth = po.post(f"/api/v1/watch-topics/refresh?project={code}")
    assert fourth.status_code == 429 and "TOPICS_LIMIT" in fourth.text
    assert len(mkt["asked"]) == 3 and mkt["asked"][0][0] == project_id
    assert po.get(f"/api/v1/watch-topics?project={code}").json()["data"]["refresh_left"] == 0

    # The half-hour tick: a project with a source and a time in the half hour that just passed is due, once.
    assert topics_service.due_projects() == [] or project_id not in topics_service.due_projects(), "no source yet, nothing to build from"
    po.post(f"/api/v1/projects/{code}/watch/sources", json={"url": "https://blog.example.com/feed", "track": "content"})
    now = datetime.now(timezone.utc)
    stamp = (now - timedelta(minutes=10)).astimezone(LOCAL).strftime("%H:%M")
    assert po.put(f"/api/v1/projects/{code}/watch/settings", json={"times": [stamp], "weekdays": [1, 2, 3, 4, 5, 6, 7]}).status_code == 200
    sent: list[tuple] = []
    monkeypatch.setattr(planning_tasks.celery_app, "send_task", lambda name, args=None, queue=None, **kwargs: sent.append((name, args, queue)))
    assert planning_tasks.watch_topics_tick()["due"] >= 1 and ("intake.watch.topics", [project_id, "scheduler"], "ai.normalize") in sent
    assert project_id not in topics_service.due_projects(now), "the same half hour is not run twice"
    assert project_id not in topics_service.due_projects(now + timedelta(hours=2)), "two hours later that time has passed"
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(AuditEvent.project_id == project_id, AuditEvent.event_type == "watch.topics_scheduled")) is not None
