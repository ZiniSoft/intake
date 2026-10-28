"""An agent on a marketing project (FR-MCP-09, ADR-0068): it hears what the owner hears, writes the words of a
version and reads them against the channel's rule, makes a post of a topic as the owner, hands in what it found on the
web, and the two prompts are served as commands. The Developer's agent sees the week but none of the owner's buttons."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app
from app.modules.mcp.prompts import command_file
from app.modules.watch.topics import topics_service
from tests.test_watch_topics import PILLARS, _seed_signals, cto, mkt  # noqa: F401  (the fixture)

MCP = "/api/v1/mcp-server"


def rpc(client: TestClient, method: str, params: dict | None = None) -> dict:
    response = client.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})
    assert response.status_code == 200, response.text
    return response.json()


def call(client: TestClient, name: str, arguments: dict) -> dict:
    result = rpc(client, "tools/call", {"name": name, "arguments": arguments})["result"]
    if result.get("isError"):
        return {"error": result["content"][0]["text"]}
    return result["structuredContent"]


def _agent(client: TestClient, name: str) -> TestClient:
    token = client.post("/api/v1/auth/tokens", json={"name": name}).json()["data"]["token"]
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


def test_the_owners_agent_hears_plans_writes_and_links_within_the_owners_rights(mkt) -> None:  # noqa: F811
    po, writer, code, project_id = mkt["po"], mkt["writer"], mkt["code"], mkt["project_id"]
    assert po.put(f"/api/v1/projects/{code}/watch/pillars", json={"pillars": PILLARS}).status_code == 200
    _seed_signals(mkt)
    topics_service.build(project_id, ai=None)
    agent = _agent(po, "agent của PO marketing")
    names = {tool["name"] for tool in rpc(agent, "tools/list")["result"]["tools"]}
    assert {"hot_topics", "trending", "get_pillars", "week_plan", "review_queue", "topic_to_post", "dismiss_topic", "refresh_topics", "set_channel_text", "get_short_link", "add_signals"} <= names

    # What the owner sees on Tuần này, and the frame every run reads.
    heard = call(agent, "hot_topics", {"project": code})
    assert heard["has_sources"] and heard["refresh_left"] == 3 and [row["score"] for row in heard["topics"]] == [14, 9, 5]
    strong = heard["topics"][0]
    assert strong["pillar"] == "AI cho đội nhỏ" and strong["signals"][0]["url"].startswith("https://") and "excerpt" not in strong["signals"][0]
    assert "PROJECT_NOT_MARKETING" in call(agent, "hot_topics", {"project": "orbit"}).get("error", "") or "PROJECT_NOT_FOUND" in call(agent, "hot_topics", {"project": "orbit"}).get("error", "")
    rising = call(agent, "trending", {"project": code, "days": 7})
    by_word = {row["keyword"].lower(): row for row in rising["keywords"]}
    assert by_word["ai agent"]["count"] == 3 and by_word["ai agent"]["sources"] == 3 and by_word["ai agent"]["priority"] == "high" and by_word["#aiagent"]["kind"] == "hashtag"
    assert by_word["tự động hóa"]["count"] == 5 and by_word["tự động hóa"]["previous"] == 0
    frame = call(agent, "get_pillars", {"project": code})
    assert [row["name"] for row in frame["pillars"]] == ["AI cho đội nhỏ", "Câu chuyện khách"] and frame["pillars"][0]["avoid"] == "Không hứa kết quả"
    assert any(rule["code"] == "X" and rule["language"] == "en" for rule in frame["channel_rules"]) and frame["ai_runs_at"] == ["06:00", "13:00"] and len(frame["sources"]) == 1

    # A series from the strongest topic, as the owner; the audit says an agent did it.
    week = (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat()
    made = call(agent, "topic_to_post", {"project": code, "topic": strong["id"], "mode": "series", "angle": 0, "week_of": week})
    assert "error" not in made, made
    assert made["status"] == "DISCUSS" and {v["channel"] for v in made["channels"]} == {"FACEBOOK_PAGE", "LINKEDIN"} and len(made["links"]) >= 1
    assert call(agent, "hot_topics", {"project": code, "state": "USED"})["topics"][0]["work_id"] == made["id"]
    assert call(agent, "dismiss_topic", {"project": code, "topic": heard["topics"][2]["id"]}) == {"dismissed": True}
    plan = call(agent, "week_plan", {"project": code, "week_of": week})
    assert plan["numbers"]["scheduled"] == 2 and plan["by_channel"] == {"FACEBOOK_PAGE": 1, "LINKEDIN": 1} and len(plan["empty_days"]) == 5 and plan["tiles"][0]["work"] == made["code"]

    # The words of the LinkedIn version, read back against its rule; then too long.
    written = call(agent, "set_channel_text", {"work": made["code"], "channel": "LINKEDIN", "text": "Small teams can run an agent in a week. " * 3})
    assert written["chars"] == 119 and written["max_chars"] == 3000 and written["language"] == "en" and not written["over_short"] and not written["over_long"]
    too_long = call(agent, "set_channel_text", {"work": made["code"], "channel": "LINKEDIN", "text": "l" * 3001})
    assert too_long["over_long"] and too_long["over_short"]
    assert "CHANNEL_MISSING" in call(agent, "set_channel_text", {"work": made["code"], "channel": "X", "text": "x"})["error"]
    link = call(agent, "get_short_link", {"work": made["code"], "channel": "LINKEDIN", "target_url": "https://example.test/ra-mat"})
    assert len(link["code"]) == 8 and "utm_source=linkedin" in link["target_url"] and call(agent, "get_short_link", {"work": made["code"], "channel": "LINKEDIN", "target_url": "https://example.test/ra-mat"})["code"] == link["code"]
    queue = call(agent, "review_queue", {"project": code})
    assert queue["count"] == 0
    assert cto.post(f"/api/v1/work/{made['id']}/move", json={"status": "IN_PROGRESS", "expected_version": cto.get(f"/api/v1/work/{made['id']}").json()["data"]["version"]}).status_code == 200

    # What the agent found on the web itself lands as signals marked agent, and a new topic scores one notch lower.
    found = call(agent, "add_signals", {"project": code, "items": [
        {"url": "https://news.example.net/agent-cua-hang", "title": "AGENT-TIM Agent chăm khách ở cửa hàng tiện lợi", "keyword": "AI agent", "pillar": "AI cho đội nhỏ", "published_at": datetime.now(timezone.utc).isoformat()},
        {"url": "https://news.example.net/agent-cua-hang", "title": "trùng"},
        {"url": "ftp://x", "title": "xấu"},
    ]})
    assert (found["accepted"], found["duplicates"], [row["reason"] for row in found["rejected"]]) == (1, 1, ["url, title and a known track are required"])
    assert "ARGUMENT_INVALID" in call(agent, "add_signals", {"project": code, "items": []})["error"]
    topics_service.build(project_id, ai=None)
    fresh = [row for row in call(agent, "hot_topics", {"project": code})["topics"]]
    # One agent finding on a used keyword: 2 + 1 + 2 (pillar) + 2 (fresh) - 1 (agent) - 3 (used lately) = 3.
    assert [(row["title"][:9], row["score"], row["signals"][0]["via"]) for row in fresh if row["title"].startswith("AGENT-TIM")] == [("AGENT-TIM", 3, "agent")]
    asked = call(agent, "refresh_topics", {"project": code})
    assert asked["status"] == "PENDING" and asked["refresh_left"] == 2 and len(mkt["asked"]) == 1

    # The writer's agent: reads the week and the topics, writes only its own post, has no owner's buttons.
    writer_agent = _agent(writer, "agent của người viết")
    writer_names = {tool["name"] for tool in rpc(writer_agent, "tools/list")["result"]["tools"]}
    assert {"hot_topics", "trending", "get_pillars", "week_plan", "review_queue", "set_channel_text"} <= writer_names
    assert not ({"topic_to_post", "dismiss_topic", "refresh_topics", "get_short_link", "add_signals"} & writer_names)
    assert "NOT_YOUR_WORK" in call(writer_agent, "set_channel_text", {"work": made["code"], "channel": "LINKEDIN", "text": "mine?"})["error"]
    assert call(writer_agent, "hot_topics", {"project": code})["kept_this_week"] == 1

    # The two prompts: listed, rendered with the argument, and served as command files.
    listed = {row["name"] for row in rpc(agent, "prompts/list")["result"]["prompts"]}
    assert {"hot_topics", "draft_post"} <= listed
    rendered = rpc(agent, "prompts/get", {"name": "draft_post", "arguments": {"work": made["code"]}})["result"]["messages"][0]["content"]["text"]
    assert f"get_work với work={made['code']}" in rendered and "set_channel_text" in rendered and "CHỜ tôi đồng ý" in rendered
    morning = rpc(agent, "prompts/get", {"name": "hot_topics", "arguments": {}})["result"]["messages"][0]["content"]["text"]
    assert "hot_topics, trending (7 ngày), week_plan và review_queue" in morning
    assert command_file("in-hot-topics")[0] == "in-hot-topics.md" and "$ARGUMENTS" in command_file("in-draft-post")[1]
    # The sheet on the screen: the marketing commands named, one sentence per tool, the owner's tools kept from the writer.
    sheet = po.get("/api/v1/auth/agent-commands").json()["data"]["marketing"]
    assert sheet["commands"] == ["hot_topics", "draft_post", "content_day", "week"] and [row["tool"] for row in sheet["tools"]][:2] == ["hot_topics", "trending"]
    assert all("{project}" in row["sentence"] or row["tool"] in ("set_channel_text", "get_short_link") for row in sheet["tools"]) and len(sheet["tools"]) == 11
    assert len(writer.get("/api/v1/auth/agent-commands").json()["data"]["marketing"]["tools"]) == 6
    files = cto.get("/api/v1/agent-commands/files/in-draft-post.md")
    assert files.status_code == 200 and "get_pillars" in files.text
