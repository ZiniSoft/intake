"""The prompt preview shows exactly what the AI would be sent for a draft (FR-CNT-14)."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AuditEvent
from app.services.ai_processor import POST_DRAFT_PROMPT_VERSION, POST_DRAFT_SYSTEM_PROMPT, AIPostDraft
from app.workers import ai_tasks
from tests.test_private_space import VOICE, _idea, _space, cto

PREVIEW = "/api/v1/private-space/prompt-preview"
NOTES = "/api/v1/private-space/notes"


def _joined(data: dict) -> str:
    return "\n\n".join(block["text"] for block in data["blocks"]).strip()


def test_the_preview_is_what_the_worker_sends(monkeypatch) -> None:
    monkeypatch.setattr("app.modules.drafts.service._publish", lambda draft_id: None)
    project = _space()["project"]
    cto.put("/api/v1/private-space/voice?track=business", json=VOICE)
    cto.put("/api/v1/private-space/master-dna", json={"text": "TAI-LIEU-XEM-TRUOC: xưng tôi, gọi anh chị."})
    note = cto.post(NOTES, json={"track": "business", "kind": "FACT", "text": "DU-KIEN-XEM-TRUOC: đội có 6 người."}).json()["data"]
    idea = _idea(project["code"], "GHI-CHU-Y-XEM-TRUOC: team mất thời gian tìm việc mỗi sáng.")
    choices = {"channel": "LINKEDIN", "track": "business", "goal": "DISCUSSION", "audience": "SME", "pillar": "AI trong vận hành", "angle": "kể từ góc người quản lý"}
    try:
        seen: list[str] = []

        async def write(source_text: str, long: bool = False) -> AIPostDraft:
            seen.append(source_text)
            return AIPostDraft(text="Bài thử.", hooks=[], gaps=[])

        monkeypatch.setattr(ai_tasks.umodelverse_adapter, "write_post_draft", write)
        draft = cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json=choices).json()["data"]
        assert ai_tasks.write_post_draft(draft["id"]) == "SUCCEEDED"

        shown = cto.post(PREVIEW, json={**choices, "intake_id": idea["id"]})
        assert shown.status_code == 200, shown.text
        data = shown.json()["data"]
        assert _joined(data) == seen[0], "what is shown is what the model was sent, to the character"
        assert data["system_prompt"] == POST_DRAFT_SYSTEM_PROMPT and data["prompt_version"] == POST_DRAFT_PROMPT_VERSION and data["system_chars"] == len(POST_DRAFT_SYSTEM_PROMPT)
        assert data["message_chars"] == len(seen[0]) and data["placeholder"] is False and data["model"]
        trust = {block["key"]: block["trust"] for block in data["blocks"]}
        assert trust == {"choices": "CHOICE", "author": "AUTHOR", "dna": "AUTHOR", "notebook": "AUTHOR", "samples": "UNTRUSTED", "angle": "CHOICE", "about": "DATA", "note": "UNTRUSTED"}
        assert [block["key"] for block in data["blocks"]].index("notebook") < [block["key"] for block in data["blocks"]].index("note")
        assert "GHI-CHU-Y-XEM-TRUOC" in next(block["text"] for block in data["blocks"] if block["key"] == "note")

        # The same for a piece written from an outline.
        outline = cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "BLOG", "outline": True, "track": "business"}).json()["data"]
        assert ai_tasks.write_post_draft(outline["id"]) == "SUCCEEDED"
        blog = cto.post(f"/api/v1/intakes/{idea['id']}/drafts", json={"channel": "BLOG", "track": "business", "source_draft_id": outline["id"]}).json()["data"]
        assert ai_tasks.write_post_draft(blog["id"]) == "SUCCEEDED"
        from_outline = cto.post(PREVIEW, json={"channel": "BLOG", "track": "business", "intake_id": idea["id"], "source_draft_id": outline["id"]}).json()["data"]
        assert _joined(from_outline) == seen[-1] and "outline" in [block["key"] for block in from_outline["blocks"]]

        # No idea chosen: its places are held, and nothing of any idea is read.
        held = cto.post(PREVIEW, json={"track": "business", "channel": "FACEBOOK"}).json()["data"]
        assert held["placeholder"] is True and "[ghi chú của ý tưởng]" in _joined(held) and "GHI-CHU-Y-XEM-TRUOC" not in _joined(held)

        # The voice as it stands on the screen, not yet saved; what is cut is said.
        long_sample = "Một câu của bài mẫu dài. " * 150
        unsaved = cto.post(PREVIEW, json={"track": "business", "channel": "FACEBOOK", "master_dna": "TAI-LIEU-CHUA-LUU", "voice": {**VOICE, "samples": [{"text": long_sample, "channel": "FACEBOOK"}]}}).json()["data"]
        assert "TAI-LIEU-CHUA-LUU" in _joined(unsaved) and "TAI-LIEU-XEM-TRUOC" not in _joined(unsaved)
        samples = next(block for block in unsaved["blocks"] if block["key"] == "samples")
        assert samples["cuts"] == [{"what": "sample 1 characters", "kept": 3000, "total": len(long_sample)}]
        assert cto.get("/api/v1/private-space").json()["data"]["master_dna"].startswith("TAI-LIEU-XEM-TRUOC"), "a preview saves nothing"

        assert cto.post(PREVIEW, json={"track": "business", "channel": "FACEBOOK", "outline": True}).status_code == 422
        assert cto.post(PREVIEW, json={"track": "business", "intake_id": "00000000-0000-4000-8000-00000000dead"}).status_code == 404
        software = _idea("orbit", "Yêu cầu phần mềm, không thuộc khu riêng.")
        assert cto.post(PREVIEW, json={"track": "business", "intake_id": software["id"]}).status_code == 404
        cto.post(f"/api/v1/intakes/{software['id']}/reject", json={"reason": "dọn test", "expected_version": software["version"]})
        owner = TestClient(app, headers={"X-User-Subject": "owner.private"})
        assert owner.post(PREVIEW, json={"track": "business"}).status_code in (401, 403)
        with get_session() as session:
            assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "draft.prompt_previewed", AuditEvent.entity_id == idea["id"]).limit(1)) is not None
    finally:
        cto.delete(f"{NOTES}/{note['id']}")
        cto.delete(f"/api/v1/intakes/{idea['id']}")
