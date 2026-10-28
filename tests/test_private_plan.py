"""The week plan of the private space (FR-CNT-07..09): rhythm, slots, AI proposal, approval and posting."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_session
from app.main import app
from app.models import AuditEvent, IntakeItem, PlanRequest, PlanSlot
from app.modules.content_plan.service import this_week
from app.services.ai_processor import AIPlanSlot, AIPostDraft, AIProviderTransientError, AIWeekPlan
from app.workers import ai_tasks
from tests.test_private_space import VOICE, _idea, _space, cto

PLAN = "/api/v1/private-space/plan"
DNA = "TAI-LIEU-KE-HOACH: viết cho chủ doanh nghiệp nhỏ. Không viết về giá."


def _when(value: str) -> datetime:
    moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@pytest.fixture()
def plan(monkeypatch):
    """A clean plan before and after: the rhythm lives in the shared private project."""
    asked: list[str] = []
    monkeypatch.setattr("app.modules.content_plan.service._publish", asked.append)
    monkeypatch.setattr("app.modules.drafts.service._publish", lambda draft_id: None)
    project = _space()["project"]
    ideas: list[str] = []
    yield {"project": project, "asked": asked, "ideas": ideas}
    for track in ("business", "technical"):
        cto.put(f"{PLAN}/rhythm?track={track}", json={"slots": []})
    for idea_id in ideas:
        cto.delete(f"/api/v1/intakes/{idea_id}")
    with get_session() as session:
        session.execute(delete(PlanSlot))
        session.execute(delete(PlanRequest))
        session.commit()


def _titled(plan, text: str, title: str) -> dict:
    idea = _idea(plan["project"]["code"], text)
    plan["ideas"].append(idea["id"])
    with get_session() as session:
        session.get(IntakeItem, idea["id"]).normalized_title = title
        session.commit()
    return idea


def test_rhythm_lays_out_this_week_and_the_next_only(plan) -> None:
    saved = cto.put(f"{PLAN}/rhythm?track=business", json={"slots": [
        {"weekday": 4, "channel": "BLOG"},
        {"weekday": 2, "time": "08:00", "channel": "FACEBOOK", "pillar": "  AI trong   vận hành "},
        {"weekday": 2, "time": "08:00", "channel": "FACEBOOK"},
    ]})
    assert saved.status_code == 200, saved.text
    week = saved.json()["data"]
    assert week["week_start"] == this_week().isoformat() and week["editable"] is True
    slots = week["tracks"]["business"]["slots"]
    assert [(slot["weekday"], slot["time"], slot["channel"], slot["state"]) for slot in slots] == [(2, "08:00", "FACEBOOK", "EMPTY"), (4, None, "BLOG", "EMPTY")], "the same slot named twice is one slot"
    assert slots[0]["day"] == (this_week() + timedelta(days=1)).isoformat()
    assert _when(slots[0]["planned_for"]).astimezone(timezone(timedelta(hours=7))).strftime("%H:%M") == "08:00"
    assert _when(slots[1]["planned_for"]).astimezone(timezone(timedelta(hours=7))).strftime("%H:%M") == "09:00", "no hour named means the morning"
    assert week["tracks"]["technical"]["slots"] == [] and len(week["rhythm"]["business"]) == 2

    again = cto.get(PLAN).json()["data"]
    assert [slot["id"] for slot in again["tracks"]["business"]["slots"]] == [slot["id"] for slot in slots], "opening the week twice makes nothing new"
    following = cto.get(f"{PLAN}?week={(this_week() + timedelta(days=7)).isoformat()}").json()["data"]
    assert len(following["tracks"]["business"]["slots"]) == 2
    before = cto.get(f"{PLAN}?week={(this_week() - timedelta(days=7)).isoformat()}").json()["data"]
    assert before["tracks"]["business"]["slots"] == [] and before["editable"] is False, "the past is not laid out afterwards"
    assert cto.get(f"{PLAN}?week={(this_week() + timedelta(days=1)).isoformat()}").status_code == 422

    # Changing the rhythm moves the empty slots and leaves a slot that holds something.
    kept = slots[0]["id"]
    assert cto.patch(f"{PLAN}/slots/{kept}", json={"skipped": True}).json()["data"]["state"] == "SKIPPED"
    changed = cto.put(f"{PLAN}/rhythm?track=business", json={"slots": [{"weekday": 5, "time": "10:30", "channel": "LINKEDIN"}]}).json()["data"]
    assert sorted((slot["weekday"], slot["channel"]) for slot in changed["tracks"]["business"]["slots"]) == [(2, "FACEBOOK"), (5, "LINKEDIN")]

    for wrong in ([{"weekday": 8, "channel": "FACEBOOK"}], [{"weekday": 1, "channel": "TIKTOK"}], [{"weekday": 1, "time": "25:00", "channel": "BLOG"}], [{"weekday": day, "channel": "BLOG"} for day in range(1, 8)] + [{"weekday": 1, "channel": "FACEBOOK"}]):
        assert cto.put(f"{PLAN}/rhythm?track=business", json={"slots": wrong}).status_code == 422, wrong
    assert cto.put(f"{PLAN}/rhythm?track=khac", json={"slots": []}).status_code == 422

    owner = TestClient(app, headers={"X-User-Subject": "owner.private"})
    assert owner.get(PLAN).status_code in (401, 403)
    assert owner.put(f"{PLAN}/rhythm", json={"slots": []}).status_code in (401, 403)
    assert owner.post(f"{PLAN}/propose", json={"track": "business", "week_start": this_week().isoformat()}).status_code in (401, 403)
    assert owner.patch(f"{PLAN}/slots/{kept}", json={"skipped": False}).status_code in (401, 403)


def test_ai_fills_open_slots_and_the_person_decides_each_one(plan, monkeypatch) -> None:
    cto.put("/api/v1/private-space/voice?track=business", json=VOICE)
    cto.put("/api/v1/private-space/master-dna", json={"text": DNA})
    stored = _titled(plan, "Ý có sẵn: vì sao quy trình trên giấy không chạy.", "Y-CO-SAN-TRONG-KHO")
    elsewhere = _titled(plan, "Ý của mạch kia.", "Y-CUA-MACH-KIA")
    cto.put(f"/api/v1/private-space/ideas/{elsewhere['id']}/track", json={"track": "technical"})
    week = cto.put(f"{PLAN}/rhythm?track=business", json={"slots": [
        {"weekday": 2, "time": "08:00", "channel": "FACEBOOK", "pillar": "AI trong vận hành"}, {"weekday": 4, "channel": "BLOG"},
    ]}).json()["data"]
    first, second = week["tracks"]["business"]["slots"]
    ask = {"track": "business", "week_start": this_week().isoformat(), "keywords": "TU-KHOA-TUAN-NAY"}

    asked = cto.post(f"{PLAN}/propose", json=ask)
    assert asked.status_code == 202 and plan["asked"] == [asked.json()["data"]["id"]]
    assert cto.get(PLAN).json()["data"]["tracks"]["business"]["request"] == {"status": "PENDING", "error": None}
    assert cto.post(f"{PLAN}/propose", json={**ask, "week_start": (this_week() - timedelta(days=7)).isoformat()}).status_code == 409

    seen: list[str] = []

    async def propose(source_text: str) -> AIWeekPlan:
        seen.append(source_text)
        key = next(line.split(":")[0].lstrip("- ") for line in source_text.splitlines() if "Y-CO-SAN-TRONG-KHO" in line)
        return AIWeekPlan(slots=[
            AIPlanSlot(slot="S1", idea=key, title="  Vì sao quy trình trên giấy   không chạy ", reason="Lấp trụ đang thiếu.", pillar="AI trong vận hành"),
            AIPlanSlot(slot="S2", idea=None, title="GOC-MOI: ba bước giao việc cho AI", reason="Kho chưa có ý hợp bài blog.", pillar="Bài học làm CTO"),
            AIPlanSlot(slot="S9", idea=None, title="Ô không tồn tại", reason="", pillar=None),
        ])

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "propose_week_plan", propose)
    assert ai_tasks.propose_week_plan(plan["asked"][0]) == "SUCCEEDED"
    assert ai_tasks.propose_week_plan(plan["asked"][0]) == "SKIPPED", "a week proposed once is not proposed again"
    message = seen[0]
    assert "- S1: Thứ Ba" in message and "FACEBOOK, pillar: AI trong vận hành" in message and "- S2: Thứ Năm" in message
    assert "TAI-LIEU-KE-HOACH" in message and "Y-CUA-MACH-KIA" not in message, "an idea filed under the other track is not offered"
    assert "Direction: Kinh doanh" in message
    assert message.index("--- end of master brand document ---") < message.index("Ideas in the store") < message.index("Keywords of the week"), "the author's own text comes before anything untrusted"
    assert "Pillars (posts in the last four weeks)" in message and "Missing pillars" not in message and "TU-KHOA-TUAN-NAY" in message

    proposed = cto.get(PLAN).json()["data"]["tracks"]["business"]
    assert proposed["request"]["status"] == "DONE" and [slot["state"] for slot in proposed["slots"]] == ["PROPOSED", "PROPOSED"]
    assert proposed["slots"][0]["suggestion"] == {"title": "Vì sao quy trình trên giấy không chạy", "reason": "Lấp trụ đang thiếu.", "pillar": "AI trong vận hành", "from_store": True}
    assert proposed["slots"][1]["suggestion"]["from_store"] is False
    with get_session() as session:
        assert "GOC-MOI" not in session.get(PlanSlot, second["id"]).suggestion_ciphertext, "stored encrypted"

    # Taking a stored idea links it; taking a new angle makes an idea in the store, filed under the slot's track.
    taken = cto.post(f"{PLAN}/slots/{first['id']}/accept").json()["data"]
    assert taken["created_idea_id"] is None and taken["slot"]["state"] == "IDEA" and taken["slot"]["idea"]["id"] == stored["id"]
    made = cto.post(f"{PLAN}/slots/{second['id']}/accept").json()["data"]
    plan["ideas"].append(made["created_idea_id"])
    assert made["slot"]["idea"]["id"] == made["created_idea_id"] and made["slot"]["pillar"] == "Bài học làm CTO"
    assert cto.get(f"/api/v1/private-space/ideas/{made['created_idea_id']}/track").json()["data"] == {"track": "business"}
    assert "GOC-MOI" in next(row for row in cto.get("/api/v1/private-space/ideas").json()["data"] if row["id"] == made["created_idea_id"])["note"]
    assert cto.post(f"{PLAN}/slots/{second['id']}/accept").status_code == 409
    assert cto.post(f"{PLAN}/propose", json=ask).status_code == 409, "nothing is open any more"

    # Emptying a slot opens it again; a failed proposal is reported and the person can wave a suggestion away.
    assert cto.patch(f"{PLAN}/slots/{second['id']}", json={"intake_id": None}).json()["data"]["state"] == "EMPTY"
    assert cto.patch(f"{PLAN}/slots/{second['id']}", json={"intake_id": elsewhere["id"]}).json()["data"]["idea"]["id"] == elsewhere["id"]
    assert cto.patch(f"{PLAN}/slots/{second['id']}", json={"intake_id": "00000000-0000-4000-8000-00000000dead"}).status_code == 404
    cto.patch(f"{PLAN}/slots/{second['id']}", json={"intake_id": None})

    async def unavailable(source_text: str) -> AIWeekPlan:
        raise AIProviderTransientError("umodelverse", "UMODELVERSE_UNAVAILABLE")

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "propose_week_plan", unavailable)
    again = cto.post(f"{PLAN}/propose", json=ask).json()["data"]
    assert ai_tasks.propose_week_plan(again["id"]) == "FAILED"
    assert cto.get(PLAN).json()["data"]["tracks"]["business"]["request"] == {"status": "FAILED", "error": "UMODELVERSE_UNAVAILABLE"}

    # Deleting the idea frees its slot.
    assert cto.delete(f"/api/v1/intakes/{stored['id']}").status_code == 200
    assert cto.get(f"{PLAN}/slots/{first['id']}").json()["data"]["state"] == "EMPTY"
    assert cto.get(f"{PLAN}/slots/khong-phai-ma").status_code == 404
    with get_session() as session:
        events = {row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type.in_(["plan_slot", "plan_request"]))).all()}
    assert {"plan.proposal_requested", "plan.proposed", "plan.proposal_failed", "plan.slot_changed"} <= events


def test_a_draft_is_approved_for_a_slot_locked_then_posted(plan, monkeypatch) -> None:
    cto.put("/api/v1/private-space/voice?track=business", json=VOICE)
    idea = _titled(plan, "Ý cho ô của tuần: team mất thời gian tìm việc mỗi sáng.", "Y-CHO-O-CUA-TUAN")
    week = cto.put(f"{PLAN}/rhythm?track=business", json={"slots": [{"weekday": 3, "time": "07:30", "channel": "FACEBOOK"}, {"weekday": 5, "channel": "LINKEDIN"}]}).json()["data"]
    slot, other = week["tracks"]["business"]["slots"]
    start = week["tracks"]["business"]["stats"]
    assert (start["slots"], start["posted"], start["open"]) == (2, 0, 2)

    async def write(source_text: str, long: bool = False) -> AIPostDraft:
        return AIPostDraft(text="Bài viết thử cho ô của tuần.", hooks=[], gaps=[])

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", write)
    drafts = f"/api/v1/intakes/{idea['id']}/drafts"
    assert cto.patch(f"{PLAN}/slots/{slot['id']}", json={"intake_id": idea["id"]}).json()["data"]["state"] == "IDEA"
    draft = cto.post(drafts, json={"channel": "FACEBOOK", "track": "business", "pillar": "AI trong vận hành"}).json()["data"]
    assert cto.post(f"{drafts}/{draft['id']}/approve", json={"slot_id": slot["id"]}).status_code == 409, "nothing to approve before it is written"
    assert ai_tasks.write_post_draft(draft["id"]) == "SUCCEEDED"
    assert cto.get(f"{PLAN}/slots/{slot['id']}").json()["data"]["state"] == "DRAFTED"

    outline = cto.post(drafts, json={"channel": "BLOG", "outline": True}).json()["data"]
    assert ai_tasks.write_post_draft(outline["id"]) == "SUCCEEDED"
    assert cto.post(f"{drafts}/{outline['id']}/approve", json={}).status_code == 422, "an outline is not a post"

    approved = cto.post(f"{drafts}/{draft['id']}/approve", json={"slot_id": slot["id"]})
    assert approved.status_code == 200, approved.text
    approved = approved.json()["data"]
    held = cto.get(f"{PLAN}/slots/{slot['id']}").json()["data"]
    assert held["state"] == "APPROVED" and approved["slot_id"] == slot["id"] and approved["approved_at"]
    assert _when(approved["scheduled_for"]) == _when(held["planned_for"]), "it goes out at the slot's hour"

    # Locked: what was approved is what goes out.
    assert cto.patch(f"{drafts}/{draft['id']}", json={"text": "Sửa sau khi đã duyệt."}).status_code == 409
    assert cto.delete(f"{drafts}/{draft['id']}").status_code == 409
    assert cto.patch(f"{PLAN}/slots/{slot['id']}", json={"intake_id": None}).status_code == 409
    assert cto.patch(f"{PLAN}/slots/{slot['id']}", json={"skipped": True}).status_code == 409
    assert cto.post(f"{drafts}/{draft['id']}/approve", json={"slot_id": "00000000-0000-4000-8000-00000000dead"}).status_code == 404

    # Taking the approval back opens it for editing; the slot keeps its idea.
    assert cto.delete(f"{drafts}/{draft['id']}/approve").json()["data"]["approved_at"] is None
    assert cto.get(f"{PLAN}/slots/{slot['id']}").json()["data"]["state"] == "DRAFTED"
    assert cto.patch(f"{drafts}/{draft['id']}", json={"text": "Bản đã sửa trước khi duyệt lại."}).status_code == 200
    assert cto.post(f"{drafts}/{draft['id']}/approve", json={"slot_id": slot["id"]}).status_code == 200

    # A slot holds one idea: a draft of another idea cannot take it.
    stray = _titled(plan, "Ý viết ngoài kế hoạch.", "Y-NGOAI-KE-HOACH")
    loose = cto.post(f"/api/v1/intakes/{stray['id']}/drafts", json={"channel": "FACEBOOK", "track": "business"}).json()["data"]
    assert ai_tasks.write_post_draft(loose["id"]) == "SUCCEEDED"
    assert cto.post(f"/api/v1/intakes/{stray['id']}/drafts/{loose['id']}/approve", json={"slot_id": slot["id"]}).status_code == 409

    # Posted: the real hour and the link.
    posted_at = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0)
    assert cto.patch(f"{drafts}/{draft['id']}", json={"posted": True, "posted_url": "ftp://khong-phai-web"}).status_code == 422
    assert cto.patch(f"{drafts}/{draft['id']}", json={"posted": True, "posted_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}).status_code == 422
    posted = cto.patch(f"{drafts}/{draft['id']}", json={"posted": True, "posted_at": posted_at.isoformat(), "posted_url": "https://example.com/bai-thu"})
    assert posted.status_code == 200, posted.text
    posted = posted.json()["data"]
    assert _when(posted["posted_at"]) == posted_at and posted["posted_url"] == "https://example.com/bai-thu" and posted["posted_via"] == "MANUAL"
    assert cto.delete(f"{drafts}/{draft['id']}/approve").status_code == 409, "a post that went out stays approved"

    # Written and posted outside the plan: counted on its own.
    assert cto.patch(f"/api/v1/intakes/{stray['id']}/drafts/{loose['id']}", json={"posted": True}).status_code == 200
    track = cto.get(PLAN).json()["data"]["tracks"]["business"]
    assert [row["state"] for row in track["slots"]] == ["POSTED", "EMPTY"]
    assert track["slots"][0]["draft"]["posted_url"] == "https://example.com/bai-thu"
    stats = track["stats"]
    assert (stats["posted"], stats["open"]) == (1, 1)
    assert stats["posted_total"] - start["posted_total"] == 2 and stats["off_plan"] - start["off_plan"] == 1
    assert stats["drafted_ideas"] - start["drafted_ideas"] == 2
    assert {"pillar": "AI trong vận hành", "posted": 1} in stats["pillars"] and "AI trong vận hành" not in stats["missing_pillars"]
    assert "Bài học làm CTO" in stats["missing_pillars"], "a pillar with no post in three weeks is named"

    assert cto.patch(f"{PLAN}/slots/{other['id']}", json={"skipped": True}).json()["data"]["state"] == "SKIPPED"
    assert cto.get(PLAN).json()["data"]["tracks"]["business"]["stats"]["slots"] == 1, "a skipped slot is not owed"
    with get_session() as session:
        events = {row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "post_draft")).all()}
    assert {"draft.approved", "draft.approval_withdrawn", "draft.marked_posted"} <= events
