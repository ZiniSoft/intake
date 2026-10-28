"""ADR-0031: the CTO's private space, and post drafts written from an idea."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditEvent, IdeaTrack, PostDraft, TrackNote
from app.modules.drafts.service import draft_service
from app.services.ai_processor import AIPostDraft, AIProviderTransientError
from app.workers import ai_tasks


cto = TestClient(app, headers={"X-User-Subject": "cto"})
OWN_PASSWORD = "Owner-pass-2026!"

VOICE = {
    "positioning": "CTO chia sẻ cách đưa AI vào vận hành",
    "audience": "Chủ doanh nghiệp nhỏ",
    "pillars": ["  Bài học   làm CTO ", "AI trong vận hành"],
    "tone": "thẳng, có ví dụ thật",
    "avoid": "chính trị",
    "default_channel": "FACEBOOK",
    "samples": [{"text": "Ba tháng trước team tôi mất hai giờ mỗi sáng để biết ai làm gì. Giờ thì không.", "channel": "FACEBOOK"}],
}


@pytest.fixture()
def sent(monkeypatch) -> list[str]:
    queue: list[str] = []
    monkeypatch.setattr("app.modules.drafts.service._publish", queue.append)
    return queue


def _space() -> dict:
    opened = cto.post("/api/v1/private-space")
    assert opened.status_code == 201, opened.text
    return opened.json()["data"]


def _idea(code: str, text: str) -> dict:
    created = cto.post("/api/v1/intakes", json={"project_id": code, "channel": "MANUAL", "raw_text": text})
    assert created.status_code == 201, created.text
    return created.json()["data"]


def _owner(subject: str, project: str) -> TestClient:
    from tests.test_project_owner import _staff

    member = _staff(f"Owner {subject}", f"{subject}@example.test")
    team = cto.put(f"/api/v1/projects/{project}/team", json={"owner_member_id": member["id"], "member_ids": []})
    assert team.status_code == 200, team.text
    issued = team.json()["data"]["issued"]
    client = TestClient(app, headers={"X-User-Subject": subject})
    changed = client.post("/api/v1/auth/password", json={"current_password": issued["temporary_password"], "new_password": OWN_PASSWORD})
    assert changed.status_code == 200, changed.text
    return client


def test_private_space_opens_once_and_stays_off_company_screens() -> None:
    space = _space()
    project = space["project"]
    assert project["name"] == "Riêng" and space["voice"]["default_channel"] == "FACEBOOK"
    assert _space()["project"]["id"] == project["id"], "Opening twice gives the same space"

    idea = _idea(project["code"], "Ý riêng: mở bài bằng một con số gây sốc rồi mới kể chuyện.")
    assert idea["public_id"].startswith("RIE-") or "-" in idea["public_id"]

    # Company lists, counts and the project list never show it, even when asked for by project.
    listed = cto.get("/api/v1/intakes?limit=100").json()["data"]
    assert idea["id"] not in [row["id"] for row in listed["items"]]
    assert cto.get(f"/api/v1/intakes?limit=100&project_id={project['id']}").json()["data"]["items"] == []
    assert cto.get(f"/api/v1/intakes?limit=100&search={idea['public_id']}").json()["data"]["items"] == []
    assert project["id"] not in [row["id"] for row in cto.get("/api/v1/projects").json()["data"]]

    before = cto.get("/api/v1/intakes?limit=1").json()["data"]["summary"]["pending_approval"]
    processed = cto.post(f"/api/v1/intakes/{idea['id']}/process")
    assert processed.status_code in (200, 202), processed.text
    state = cto.get(f"/api/v1/intakes/{idea['id']}").json()["data"]["status"]
    if state == "PENDING_APPROVAL":
        assert cto.get("/api/v1/intakes?limit=1").json()["data"]["summary"]["pending_approval"] == before
        assert idea["id"] not in [row["id"] for row in cto.get("/api/v1/approvals?limit=100").json()["data"]["items"]]

    # Inside the space it is there.
    ideas = cto.get("/api/v1/private-space/ideas").json()["data"]
    mine = next(row for row in ideas if row["id"] == idea["id"])
    assert mine["state"] == "NO_DRAFT" and "con số gây sốc" in mine["note"]
    assert cto.get("/api/v1/private-space/ideas?search=khong-co-y-nao-nhu-the").json()["data"] == []
    assert cto.get("/api/v1/private-space/ideas?state=NOPE").status_code == 422
    assert cto.get("/api/v1/private-space").json()["data"]["counts"]["no_draft"] >= 1


def test_project_owner_cannot_reach_the_private_space(sent) -> None:
    project = _space()["project"]
    idea = _idea(project["code"], "Ý riêng mà Project Owner không được thấy.")
    owner = _owner("owner.private", "ember")

    assert owner.get("/api/v1/private-space").status_code == 403
    assert owner.post("/api/v1/private-space").status_code == 403
    assert owner.get("/api/v1/private-space/ideas").status_code == 403
    assert owner.put("/api/v1/private-space/voice", json=VOICE).status_code == 403
    assert owner.get(f"/api/v1/intakes/{idea['id']}").status_code == 404
    assert owner.get(f"/api/v1/intakes/{idea['id']}/drafts").status_code == 404
    assert owner.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "FACEBOOK"}).status_code == 404
    assert owner.post("/api/v1/intakes", json={"project_id": project["code"], "channel": "MANUAL", "raw_text": "x" * 20}).status_code == 404
    assert project["id"] not in [row["id"] for row in owner.get("/api/v1/projects").json()["data"]]
    assert sent == []


def test_voice_is_saved_and_checked() -> None:
    _space()
    saved = cto.put("/api/v1/private-space/voice", json=VOICE)
    assert saved.status_code == 200, saved.text
    voice = saved.json()["data"]["voice"]
    assert voice["pillars"] == ["Bài học làm CTO", "AI trong vận hành"] and len(voice["samples"]) == 1
    assert cto.get("/api/v1/private-space").json()["data"]["voice"]["tone"] == "thẳng, có ví dụ thật"

    assert cto.put("/api/v1/private-space/voice", json={**VOICE, "pillars": [f"trụ {n}" for n in range(6)]}).status_code == 422
    assert cto.put("/api/v1/private-space/voice", json={**VOICE, "samples": [{"text": "ngắn", "channel": "FACEBOOK"}]}).status_code == 422
    assert cto.put("/api/v1/private-space/voice", json={**VOICE, "samples": VOICE["samples"] * 9}).status_code == 422
    assert cto.put("/api/v1/private-space/voice", json={**VOICE, "default_channel": "TIKTOK"}).status_code == 422


def test_draft_is_written_by_the_worker_adapted_edited_marked_and_deleted(sent, monkeypatch) -> None:
    project = _space()["project"]
    cto.put("/api/v1/private-space/voice", json=VOICE)
    idea = _idea(project["code"], "Team tôi từng mất 2 giờ mỗi sáng để xếp việc. Viết bài kể chuyện này.")
    seen: list[str] = []

    async def write(source_text: str, long: bool = False) -> AIPostDraft:
        seen.append(source_text)
        return AIPostDraft(text="  2 giờ mỗi sáng. Đó là thời gian team tôi từng mất.  ", hooks=["Câu mở khác 1", "", "Câu mở khác 2"], gaps=["[tên công cụ]"])

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", write)

    asked = cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "FACEBOOK", "angle": "kể từ góc người quản lý"})
    assert asked.status_code == 202, asked.text
    draft = asked.json()["data"]
    assert draft["status"] == "PENDING" and draft["text"] is None and sent == [draft["id"]]

    assert ai_tasks.write_post_draft(draft["id"]) == "SUCCEEDED"
    message = seen[0]
    assert "Channel: FACEBOOK" in message and "2 giờ mỗi sáng" in message, "the CTO may read the original, so the AI gets it"
    assert "kể từ góc người quản lý" in message and "Ba tháng trước team tôi" in message and "Bài học làm CTO" in message
    assert ai_tasks.write_post_draft(draft["id"]) == "SKIPPED", "a written draft is not written again"

    written = cto.get(f"/api/v1/intakes/{idea['id']}/drafts").json()["data"][0]
    assert written["status"] == "DONE" and written["text"] == "2 giờ mỗi sáng. Đó là thời gian team tôi từng mất."
    assert written["hooks"] == ["Câu mở khác 1", "Câu mở khác 2"] and written["gaps"] == ["[tên công cụ]"]
    with get_session() as session:
        stored = session.get(PostDraft, draft["id"])
        assert "2 giờ" not in (stored.text_ciphertext or ""), "stored encrypted"

    adapted = cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "LINKEDIN", "source_draft_id": draft["id"]}).json()["data"]
    assert ai_tasks.write_post_draft(adapted["id"]) == "SUCCEEDED"
    assert "Draft to adapt (written for FACEBOOK)" in seen[1] and "Channel: LINKEDIN" in seen[1]

    edited = cto.patch(f"/api/v1/intakes/{idea['id']}/drafts/{draft['id']}", json={"text": "Bản tôi đã sửa."})
    assert edited.status_code == 200 and edited.json()["data"]["text"] == "Bản tôi đã sửa." and edited.json()["data"]["edited_at"]
    assert cto.patch(f"/api/v1/intakes/{idea['id']}/drafts/{draft['id']}", json={"text": "   "}).status_code == 422

    listed = {row["id"]: row for row in cto.get("/api/v1/private-space/ideas").json()["data"]}
    assert listed[idea["id"]]["state"] == "DRAFTED" and listed[idea["id"]]["channels"] == ["FACEBOOK", "LINKEDIN"]
    posted = cto.patch(f"/api/v1/intakes/{idea['id']}/drafts/{draft['id']}", json={"posted": True}).json()["data"]
    assert posted["posted_at"] and posted["text"] == "Bản tôi đã sửa."
    assert cto.get("/api/v1/private-space/ideas?state=POSTED").json()["data"][0]["id"] == idea["id"]
    assert cto.patch(f"/api/v1/intakes/{idea['id']}/drafts/{draft['id']}", json={"posted": False}).json()["data"]["posted_at"] is None

    assert cto.delete(f"/api/v1/intakes/{idea['id']}/drafts/{adapted['id']}").status_code == 204
    assert cto.delete(f"/api/v1/intakes/{idea['id']}/drafts/{adapted['id']}").status_code == 404
    with get_session() as session:
        events = {row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "post_draft")).all()}
    assert {"draft.requested", "draft.written", "draft.edited", "draft.marked_posted", "draft.deleted"} <= events


def test_draft_failure_is_reported_and_drafts_are_only_for_idea_projects(sent, monkeypatch) -> None:
    project = _space()["project"]
    idea = _idea(project["code"], "Một ý sẽ gặp lỗi nhà cung cấp AI.")

    async def unavailable(source_text: str, long: bool = False) -> AIPostDraft:
        raise AIProviderTransientError("umodelverse", "UMODELVERSE_UNAVAILABLE")

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", unavailable)
    draft = cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "THREADS"}).json()["data"]
    assert ai_tasks.write_post_draft(draft["id"]) == "FAILED"
    failed = cto.get(f"/api/v1/intakes/{idea['id']}/drafts").json()["data"][0]
    assert failed["status"] == "FAILED" and failed["error"] == "UMODELVERSE_UNAVAILABLE" and failed["text"] is None
    assert cto.patch(f"/api/v1/intakes/{idea['id']}/drafts/{draft['id']}", json={"posted": True}).status_code == 409
    assert cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "FACEBOOK", "source_draft_id": draft["id"]}).status_code == 409

    software = _idea("orbit", "Yêu cầu phần mềm, không phải ý để viết bài.")
    refused = cto.post(f"/api/v1/intakes/{software['id']}/drafts", json={"channel": "FACEBOOK"})
    assert refused.status_code == 409 and "DRAFTS_NOT_FOR_KIND" in refused.text
    assert cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "TIKTOK"}).status_code == 422
    assert cto.post("/api/v1/intakes/00000000-0000-4000-8000-00000000dead/drafts", json={"channel": "FACEBOOK"}).status_code == 404


def test_ai_does_not_get_the_original_when_the_asker_may_not_read_it(sent) -> None:
    project = _space()["project"]
    idea = _idea(project["code"], "NGUYEN-VAN-GOC-BI-MAT: nội dung gốc chỉ người có quyền mới đọc.")
    draft = draft_service.request(
        idea["id"], channel="FACEBOOK", angle=None, source_draft_id=None, actor_id="someone", may_read_raw=False, publisher=sent.append,
    )
    source = draft_service.input(str(draft["id"]))
    # The original is withheld; the title and summary are what this person can already read on the Intake.
    assert source["note"] == "" and "Idea note" not in ai_tasks.build_draft_message(source)
    allowed = draft_service.request(
        idea["id"], channel="FACEBOOK", angle=None, source_draft_id=None, actor_id="cto", may_read_raw=True, publisher=sent.append,
    )
    assert "NGUYEN-VAN-GOC-BI-MAT" in draft_service.input(str(allowed["id"]))["note"]


DNA = "TAI-LIEU-THU: Xưng Thành, gọi người đọc là anh/chị. Mỗi bài một vấn đề. Số liệu chưa kiểm thì ghi rõ là mục tiêu."


def test_both_directions_share_one_master_document() -> None:
    _space()
    first = cto.put("/api/v1/private-space/voice?track=business", json=VOICE)
    assert first.status_code == 200, first.text
    master = cto.put("/api/v1/private-space/master-dna", json={"text": DNA})
    assert master.status_code == 200, master.text
    second = cto.put("/api/v1/private-space/voice?track=technical", json={**VOICE, "name": "  Nhật ký nghề ", "tone": "kể chuyện, chậm", "samples": []})
    assert second.status_code == 200, second.text
    data = cto.get("/api/v1/private-space").json()["data"]
    voices = data["voices"]
    assert set(voices) == {"business", "technical"} and data["master_dna"] == DNA, "one document for both directions"
    assert voices["business"]["name"] == "Kinh doanh" and len(voices["business"]["samples"]) == 1 and "dna" not in voices["business"]
    assert voices["technical"]["name"] == "Nhật ký nghề" and voices["technical"]["samples"] == [] and voices["technical"]["direction_note"] == "Hướng Kỹ thuật trong Master DNA"
    assert data["voice"]["name"] == "Kinh doanh", "the first direction is still the default voice"

    assert cto.put("/api/v1/private-space/voice?track=khac", json=VOICE).status_code == 422
    assert cto.put("/api/v1/private-space/master-dna", json={"text": "x" * 40001}).status_code == 422

    # A document a track held before the core was shared stands in until a master document is saved.
    from app.models import Project

    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == _space()["project"]["code"]))
        current = dict(project.project_settings or {})
        current.pop("master_dna", None)
        current["voices"] = {"business": {**current["voices"]["business"], "dna": "TAI-LIEU-CU-CUA-MACH"}, "personal": current["voices"]["technical"]}
        current["rhythm"] = {"business": [{"weekday": 2, "time": "08:00", "channel": "FACEBOOK", "pillar": None}]}
        project.project_settings = current
        session.commit()
    legacy = cto.get("/api/v1/private-space").json()["data"]
    assert legacy["master_dna"] == "TAI-LIEU-CU-CUA-MACH" and legacy["voices"]["business"]["samples"] == voices["business"]["samples"], "settings under the old names are still read"
    assert len(cto.get("/api/v1/private-space/plan").json()["data"]["rhythm"]["business"]) == 1
    assert cto.put("/api/v1/private-space/master-dna", json={"text": DNA}).json()["data"]["master_dna"] == DNA
    cto.put("/api/v1/private-space/plan/rhythm?track=business", json={"slots": []})


def test_an_idea_is_filed_under_a_track_and_the_draft_follows_it(sent, monkeypatch) -> None:
    project = _space()["project"]
    cto.put("/api/v1/private-space/voice?track=business", json=VOICE)
    cto.put("/api/v1/private-space/master-dna", json={"text": DNA})
    cto.put("/api/v1/private-space/voice?track=technical", json={**VOICE, "tone": "GIONG-CA-NHAN", "samples": [], "references": [{"title": "Tài liệu công ty", "text": "THAM-CHIEU-KY-THUAT: dữ kiện để đối chiếu."}]})
    idea = _idea(project["code"], "Ý thử mạch: quy trình trên giấy khác hệ thống chạy thật.")
    track = f"/api/v1/private-space/ideas/{idea['id']}/track"

    assert cto.get(track).json()["data"] == {"track": None}
    assert cto.put(track, json={"track": "technical"}).status_code == 200
    assert cto.get(track).json()["data"] == {"track": "technical"}
    assert cto.put(track, json={"track": "khac"}).status_code == 422
    assert cto.get("/api/v1/private-space/ideas/00000000-0000-4000-8000-00000000dead/track").status_code == 404
    listed = cto.get("/api/v1/private-space/ideas?track=technical").json()["data"]
    assert [row["track"] for row in listed if row["id"] == idea["id"]] == ["technical"]
    assert idea["id"] not in [row["id"] for row in cto.get("/api/v1/private-space/ideas?track=business").json()["data"]]

    seen: list[str] = []

    async def write(source_text: str, long: bool = False) -> AIPostDraft:
        seen.append(source_text)
        return AIPostDraft(text="Bài viết thử cho một mạch nội dung.", hooks=[], gaps=[])

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", write)
    drafts = f"/api/v1/intakes/{idea['id']}/drafts"

    # Nothing chosen: the idea's own track, and its voice.
    own = cto.post(drafts, json={"channel": "FACEBOOK"}).json()["data"]
    assert own["track"] == "technical" and own["goal"] is None
    assert ai_tasks.write_post_draft(own["id"]) == "SUCCEEDED"
    assert "GIONG-CA-NHAN" in seen[0] and "TAI-LIEU-THU" in seen[0] and "Direction: Kỹ thuật" in seen[0] and "Goal:" not in seen[0], "the shared document, read as the technical direction"
    assert "--- reference 1: Tài liệu công ty ---" in seen[0] and seen[0].index("--- end of master brand document ---") < seen[0].index("--- reference 1") < seen[0].index("Idea note")

    # Chosen: the other track with its brand document, a goal, an audience and a pillar.
    chosen = cto.post(drafts, json={"channel": "LINKEDIN", "track": "business", "goal": "DISCUSSION", "audience": "DEVELOPER", "pillar": "  AI trong vận hành "})
    assert chosen.status_code == 202, chosen.text
    chosen = chosen.json()["data"]
    assert (chosen["track"], chosen["goal"], chosen["audience"], chosen["pillar"]) == ("business", "DISCUSSION", "DEVELOPER", "AI trong vận hành")
    assert ai_tasks.write_post_draft(chosen["id"]) == "SUCCEEDED"
    message = seen[1]
    assert "--- master brand document ---" in message and "TAI-LIEU-THU" in message and "GIONG-CA-NHAN" not in message and "Direction: Kinh doanh" in message
    assert "THAM-CHIEU-KY-THUAT" not in message, "a reference document belongs to the direction it was given to"
    assert "Goal: DISCUSSION" in message and "Audience: DEVELOPER" in message and "Pillar: AI trong vận hành" in message
    assert message.index("--- end of master brand document ---") < message.index("Idea note"), "the author's document is never mixed with the untrusted note"

    # A post for an industry group is a rewrite of a written draft, on its own channel.
    group = cto.post(drafts, json={"channel": "FACEBOOK", "group_context": "FNB", "audience": "DEVELOPER", "source_draft_id": chosen["id"]}).json()["data"]
    assert group["channel"] == "FACEBOOK_GROUP" and group["group_context"] == "FNB" and group["audience"] is None, "the group is the reader"
    assert ai_tasks.write_post_draft(group["id"]) == "SUCCEEDED"
    assert "Channel: FACEBOOK_GROUP" in seen[2] and "Group: F&B" in seen[2] and "Draft to adapt (written for LINKEDIN)" in seen[2]

    assert cto.post(drafts, json={"channel": "FACEBOOK_GROUP"}).status_code == 422, "a group post names its industry"
    for wrong in ({"group_context": "BANK"}, {"goal": "SELL"}, {"audience": "EVERYONE"}, {"track": "khac"}, {"pillar": "x" * 121}):
        assert cto.post(drafts, json={"channel": "FACEBOOK", **wrong}).status_code == 422, wrong
    assert len(sent) == 3

    # Deleting the idea takes its track with it.
    assert cto.delete(f"/api/v1/intakes/{idea['id']}").status_code == 200
    assert cto.get(track).status_code == 404
    with get_session() as session:
        assert session.get(IdeaTrack, idea["id"]) is None


def test_notebook_belongs_to_a_track_and_is_read_before_the_idea(sent, monkeypatch) -> None:
    project = _space()["project"]
    notes = "/api/v1/private-space/notes"
    fact = cto.post(notes, json={"track": "technical", "kind": "FACT", "text": "  DU-KIEN-THU: đội có   6 người. "})
    assert fact.status_code == 201, fact.text
    assert fact.json()["data"]["text"] == "DU-KIEN-THU: đội có 6 người."
    result = cto.post(notes, json={"track": "technical", "kind": "RESULT", "text": "KET-QUA-THU: bài về quy trình được xem nhiều."}).json()["data"]
    other = cto.post(notes, json={"track": "business", "kind": "DECISION", "text": "QUYET-DINH-MACH-KIA: không viết về giá."}).json()["data"]
    created = [fact.json()["data"]["id"], result["id"], other["id"]]
    try:
        listed = cto.get(f"{notes}?track=technical").json()["data"]
        assert [row["kind"] for row in listed if row["id"] in created] == ["FACT", "RESULT"], "what is true comes first"
        assert other["id"] not in [row["id"] for row in listed]
        with get_session() as session:
            assert "DU-KIEN-THU" not in session.get(TrackNote, created[0]).text_ciphertext, "stored encrypted"
        assert cto.post(notes, json={"track": "khac", "kind": "FACT", "text": "một ghi chú"}).status_code == 422
        assert cto.post(notes, json={"track": "technical", "kind": "RUMOUR", "text": "một ghi chú"}).status_code == 422
        assert cto.post(notes, json={"track": "technical", "kind": "FACT", "text": "x" * 1001}).status_code == 422
        owner = TestClient(app, headers={"X-User-Subject": "owner.private"})
        assert owner.get(notes).status_code in (401, 403) and owner.post(notes, json={"track": "technical", "kind": "FACT", "text": "một ghi chú"}).status_code in (401, 403)

        # Something this track already published.
        earlier = _idea(project["code"], "Ý đã đăng trước đó của mạch cá nhân.")
        with get_session() as session:
            from app.models import IntakeItem

            session.get(IntakeItem, earlier["id"]).normalized_title = "TIEU-DE-DA-DANG"
            session.commit()

        seen: list[tuple[str, bool]] = []

        async def write(source_text: str, long: bool = False) -> AIPostDraft:
            seen.append((source_text, long))
            return AIPostDraft(text="Nội dung thử cho một bài dài.", hooks=["Tiêu đề khác"], gaps=[])

        monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", write)
        old = cto.post(f"/api/v1/intakes/{earlier['id']}/drafts", json={"channel": "FACEBOOK", "track": "technical"}).json()["data"]
        assert ai_tasks.write_post_draft(old["id"]) == "SUCCEEDED"
        assert cto.patch(f"/api/v1/intakes/{earlier['id']}/drafts/{old['id']}", json={"posted": True}).status_code == 200

        idea = _idea(project["code"], "Ý thử bài dài: cách đội nhỏ dùng AI để viết phần mềm.")
        drafts = f"/api/v1/intakes/{idea['id']}/drafts"
        assert cto.post(drafts, json={"channel": "FACEBOOK", "outline": True}).status_code == 422, "an outline is for a long piece"

        outline = cto.post(drafts, json={"channel": "BLOG", "outline": True, "track": "technical", "goal": "FOLLOW", "audience": "AI_USER"})
        assert outline.status_code == 202, outline.text
        outline = outline.json()["data"]
        assert (outline["kind"], outline["channel"], outline["goal"], outline["audience"]) == ("OUTLINE", "BLOG", "FOLLOW", "AI_USER")
        assert ai_tasks.write_post_draft(outline["id"]) == "SUCCEEDED"
        message, long = seen[-1]
        assert "Kind: OUTLINE" in message and long is False, "an outline is short"
        assert "FACT: DU-KIEN-THU" in message and "RESULT: KET-QUA-THU" in message and "QUYET-DINH-MACH-KIA" not in message
        assert message.index("--- end of notebook ---") < message.index("Idea note"), "the notebook is never mixed with the untrusted note"
        assert "Already published" in message and "- TIEU-DE-DA-DANG" in message

        for channel in ("BLOG", "VIDEO_SCRIPT"):
            piece = cto.post(drafts, json={"channel": channel, "track": "technical", "source_draft_id": outline["id"]}).json()["data"]
            assert piece["kind"] == "POST" and piece["channel"] == channel
            assert ai_tasks.write_post_draft(piece["id"]) == "SUCCEEDED"
            message, long = seen[-1]
            assert f"Channel: {channel}" in message and "Outline to follow" in message and "Draft to adapt" not in message and long is True
        long_text = "Một đoạn của bài blog. " * 900
        assert cto.patch(f"{drafts}/{piece['id']}", json={"text": long_text}).status_code == 200, "a long piece can be saved after editing"

        assert cto.delete(f"{notes}/{created[1]}").status_code == 204
        assert cto.delete(f"{notes}/{created[1]}").status_code == 404
        assert cto.delete(f"{notes}/khong-phai-ma").status_code == 404
        with get_session() as session:
            events = {row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "track_note")).all()}
        assert {"private_space.note_added", "private_space.note_removed"} <= events
    finally:
        for note_id in created:
            cto.delete(f"{notes}/{note_id}")


def test_context_money_and_adapting_to_the_other_direction(sent, monkeypatch) -> None:
    project = _space()["project"]
    cto.put("/api/v1/private-space/master-dna", json={"text": DNA})
    cto.put("/api/v1/private-space/voice?track=technical", json={**VOICE, "samples": [], "default_channel": "BLOG"})
    idea = _idea(project["code"], "Ý thử chuyển thể: cùng một dữ kiện, hai hướng đọc khác nhau.")
    drafts = f"/api/v1/intakes/{idea['id']}/drafts"
    seen: list[str] = []

    async def write(source_text: str, long: bool = False) -> AIPostDraft:
        seen.append(source_text)
        return AIPostDraft(text="DU-KIEN-GOC: bài viết thử cho hướng Kinh doanh.", hooks=[], gaps=[])

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", write)

    # Money belongs to the technical direction only; an example must be called one.
    assert cto.post(drafts, json={"channel": "FACEBOOK", "track": "business", "commercial": "AFFILIATE"}).status_code == 422
    assert cto.post(drafts, json={"channel": "FACEBOOK", "track": "business", "context": "RUMOUR"}).status_code == 422
    first = cto.post(drafts, json={"channel": "FACEBOOK", "track": "business", "context": "EXAMPLE", "commercial": "NONE"})
    assert first.status_code == 202, first.text
    first = first.json()["data"]
    assert (first["context"], first["commercial"]) == ("EXAMPLE", None)
    assert ai_tasks.write_post_draft(first["id"]) == "SUCCEEDED"
    assert "Context: EXAMPLE (made up to show a point; must be called an example)" in seen[0] and "Commercial:" not in seen[0]

    # The same facts, read for the other direction.
    adapted = cto.post(drafts, json={"channel": "BLOG", "track": "technical", "source_draft_id": first["id"], "commercial": "AFFILIATE", "context": "EXAMPLE"})
    assert adapted.status_code == 202, adapted.text
    adapted = adapted.json()["data"]
    assert (adapted["track"], adapted["commercial"]) == ("technical", "AFFILIATE")
    assert ai_tasks.write_post_draft(adapted["id"]) == "SUCCEEDED"
    message = seen[1]
    assert "Draft to adapt (written for the other direction: Kinh doanh, channel FACEBOOK)" in message and "DU-KIEN-GOC" in message
    assert "Direction: Kỹ thuật" in message and "Commercial: AFFILIATE (the author earns from links)" in message

    # Within one direction, adapting keeps the plain label.
    again = cto.post(drafts, json={"channel": "LINKEDIN", "track": "business", "source_draft_id": first["id"]}).json()["data"]
    assert ai_tasks.write_post_draft(again["id"]) == "SUCCEEDED"
    assert "Draft to adapt (written for FACEBOOK)" in seen[2] and "other direction" not in seen[2]
    assert len(sent) == 3
    cto.delete(f"/api/v1/intakes/{idea['id']}")
    cto.put("/api/v1/private-space/voice?track=technical", json={**VOICE, "samples": []})
