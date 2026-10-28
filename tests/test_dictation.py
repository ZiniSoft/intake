import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.modules.meetings.service import meeting_service
from app.services.ai_processor import AIProviderTransientError, AIRequestText
from app.workers import ai_tasks


client = TestClient(app, headers={"X-User-Subject": "cto"})


class MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(self, key: str, content: bytes, content_type: str) -> None:
        self.objects[key] = content

    def get(self, key: str) -> bytes:
        return self.objects[key]

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)


@pytest.fixture()
def published(monkeypatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(get_settings(), "meeting_capture_enabled", True)
    memory = MemoryStorage()
    monkeypatch.setattr("app.modules.meetings.service.get_object_storage", lambda: memory)
    monkeypatch.setattr("app.modules.meetings.service._publish_rewrite", sent.append)
    return sent


def _spoken(kind: str = "DICTATION", text: str | None = "Ờ thì, trang đăng nhập Orbit bị lỗi, à không, bị chậm, khoảng 8 giây.") -> dict:
    meeting = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC", "kind": kind}).json()["data"]
    response = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=0", files={"file": ("a.webm", b"webm-part", "audio/webm")})
    assert response.status_code == 200, response.text
    if text:
        meeting_service.add_realtime_segment(meeting["id"], text)
    return client.post(f"/api/v1/meetings/{meeting['id']}/finish").json()["data"]


def test_dictation_keeps_audio_but_skips_speakers_and_note(published) -> None:
    finished = _spoken()
    assert finished["kind"] == "DICTATION" and finished["title"].startswith("Nói để nhập")
    # A meeting with audio would wait for speaker separation and then a note; a spoken request does neither.
    assert finished["transcript_status"] == "SKIPPED" and finished["note_status"] == "SKIPPED"
    assert meeting_service.claim_transcription() != finished["id"]
    assert client.get(f"/api/v1/meetings/{finished['id']}/audio").status_code == 200

    listed = [row["id"] for row in client.get("/api/v1/meetings").json()["data"]]
    assert finished["id"] not in listed
    with_dictation = [row["id"] for row in client.get("/api/v1/meetings?include_dictation=true").json()["data"]]
    assert finished["id"] in with_dictation

    assert client.post("/api/v1/meetings", json={"source": "MIC", "kind": "PODCAST"}).status_code == 422


def test_rewrite_is_done_by_the_worker_and_read_back(published, monkeypatch) -> None:
    finished = _spoken()
    seen: list[str] = []

    async def rewrite(source_text: str) -> AIRequestText:
        seen.append(source_text)
        return AIRequestText(text="  Trang đăng nhập Orbit bị chậm, khoảng 8 giây.  ")

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "rewrite_request", rewrite)

    asked = client.post(f"/api/v1/meetings/{finished['id']}/rewrite")
    assert asked.status_code == 202, asked.text
    assert asked.json()["data"]["rewrite_status"] == "PENDING" and asked.json()["data"]["rewrite_text"] is None
    # Asking again while one is running does not start a second one.
    assert client.post(f"/api/v1/meetings/{finished['id']}/rewrite").status_code == 202
    assert published == [finished["id"]]

    assert ai_tasks.rewrite_spoken_request(finished["id"]) == "SUCCEEDED"
    assert "8 giây" in seen[0] and "Orbit" in seen[0]
    detail = client.get(f"/api/v1/meetings/{finished['id']}/rewrite").json()["data"]
    assert detail["rewrite_status"] == "DONE" and detail["rewrite_text"] == "Trang đăng nhập Orbit bị chậm, khoảng 8 giây."


def test_rewrite_failure_is_reported_and_can_be_asked_again(published, monkeypatch) -> None:
    finished = _spoken()

    async def unavailable(source_text: str) -> AIRequestText:
        raise AIProviderTransientError("umodelverse", "UMODELVERSE_TIMEOUT")

    monkeypatch.setattr(ai_tasks.umodelverse_adapter, "rewrite_request", unavailable)
    client.post(f"/api/v1/meetings/{finished['id']}/rewrite")
    assert ai_tasks.rewrite_spoken_request(finished["id"]) == "FAILED"
    detail = client.get(f"/api/v1/meetings/{finished['id']}").json()["data"]
    assert detail["rewrite_status"] == "FAILED" and detail["rewrite_error"] == "UMODELVERSE_TIMEOUT" and detail["rewrite_text"] is None

    assert client.post(f"/api/v1/meetings/{finished['id']}/rewrite").json()["data"]["rewrite_status"] == "PENDING"
    assert published == [finished["id"], finished["id"]]


def test_rewrite_needs_a_finished_recording_with_words(published) -> None:
    silent = _spoken(text=None)
    assert client.post(f"/api/v1/meetings/{silent['id']}/rewrite").status_code == 409
    recording = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC", "kind": "DICTATION"}).json()["data"]
    meeting_service.add_realtime_segment(recording["id"], "Đang nói dở.")
    assert client.post(f"/api/v1/meetings/{recording['id']}/rewrite").status_code == 409
    client.post(f"/api/v1/meetings/{recording['id']}/finish")
    assert published == []


def test_a_recording_can_be_renamed_and_deleted(published) -> None:
    """FR-REC-12."""
    from app.db import get_session
    from app.models import AuditEvent, MeetingSegment
    from sqlalchemy import select

    finished = _spoken(kind="MEETING")
    meeting_id = finished["id"]
    renamed = client.patch(f"/api/v1/meetings/{meeting_id}", json={"title": "  Họp   review  sprint 12 "})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["data"]["title"] == "Họp review sprint 12"
    assert client.patch(f"/api/v1/meetings/{meeting_id}", json={"title": "   "}).status_code == 422
    assert client.patch(f"/api/v1/meetings/{meeting_id}", json={"title": "x" * 201}).status_code == 422

    recording = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC"}).json()["data"]
    assert client.delete(f"/api/v1/meetings/{recording['id']}").status_code == 409
    client.post(f"/api/v1/meetings/{recording['id']}/finish")
    assert client.delete(f"/api/v1/meetings/{recording['id']}").status_code == 200

    assert client.get(f"/api/v1/meetings/{meeting_id}/audio").status_code == 200
    removed = client.delete(f"/api/v1/meetings/{meeting_id}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"] == {"deleted": True, "intakes_kept": 0}
    assert client.get(f"/api/v1/meetings/{meeting_id}").status_code == 404
    assert client.get(f"/api/v1/meetings/{meeting_id}/audio").status_code == 404
    assert client.delete(f"/api/v1/meetings/{meeting_id}").status_code == 404
    assert meeting_id not in [row["id"] for row in client.get("/api/v1/meetings?include_dictation=true").json()["data"]]
    with get_session() as session:
        assert session.scalars(select(MeetingSegment).where(MeetingSegment.meeting_id == meeting_id)).all() == []
        events = [row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_id == meeting_id)).all()]
    assert "meeting.renamed" in events and "meeting.deleted" in events
