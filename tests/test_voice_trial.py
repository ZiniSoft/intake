"""Hearing the voice: a short piece written from what is on the screen, saved nowhere (FR-CNT-16)."""
from fastapi.testclient import TestClient

from app.main import app
from app.services.ai_processor import AIPostDraft, AIProviderTransientError
from tests.test_private_space import VOICE, _space, cto

TRIAL = "/api/v1/private-space/voice-trial"


def test_a_trial_writes_from_the_screen_and_saves_nothing(monkeypatch) -> None:
    _space()
    cto.put("/api/v1/private-space/master-dna", json={"text": "TAI-LIEU-DA-LUU"})
    seen: list[str] = []

    async def write(source_text: str, long: bool = False) -> AIPostDraft:
        seen.append(source_text)
        return AIPostDraft(text="Đoạn thử ngắn theo giọng.", hooks=["bỏ"], gaps=["bỏ"])

    monkeypatch.setattr("app.services.ai_processor.umodelverse_adapter.write_post_draft", write)
    heard = cto.post(TRIAL, json={"track": "technical", "master_dna": "TAI-LIEU-CHUA-LUU", "voice": {**VOICE, "tone": "GIONG-TREN-MAN-HINH"}, "idea": "  một   dòng ý mẫu "})
    assert heard.status_code == 200, heard.text
    data = heard.json()["data"]
    assert data["text"] == "Đoạn thử ngắn theo giọng." and data["message_chars"] == len(seen[0]) and data["prompt_version"].startswith("post-draft-")
    message = seen[0]
    assert "Trial: 80 to 120 words" in message and "Direction: Kỹ thuật" in message and "GIONG-TREN-MAN-HINH" in message
    assert "TAI-LIEU-CHUA-LUU" in message and "TAI-LIEU-DA-LUU" not in message, "what is on the screen, not what was saved"
    assert "một dòng ý mẫu" in message
    assert cto.get("/api/v1/private-space").json()["data"]["master_dna"] == "TAI-LIEU-DA-LUU", "a trial saves nothing"

    async def down(source_text: str, long: bool = False) -> AIPostDraft:
        raise AIProviderTransientError("umodelverse", "UMODELVERSE_UNAVAILABLE")

    monkeypatch.setattr("app.services.ai_processor.umodelverse_adapter.write_post_draft", down)
    assert cto.post(TRIAL, json={"track": "business"}).status_code == 503
    owner = TestClient(app, headers={"X-User-Subject": "owner.private"})
    assert owner.post(TRIAL, json={"track": "business"}).status_code in (401, 403)
    cto.put("/api/v1/private-space/master-dna", json={"text": ""})
