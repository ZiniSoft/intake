from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditEvent, Meeting, MeetingSegment
from app.modules.meetings.service import audio_object_key, meeting_service
from app.services.raw_crypto import decrypt_bytes


client = TestClient(app, headers={"X-User-Subject": "cto"})


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "meeting_capture_enabled", True)


def _start(project: str | None = "orbit", source: str = "MIC") -> dict:
    response = client.post("/api/v1/meetings", json={"project_id": project, "source": source})
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_meeting_capture_is_off_by_default() -> None:
    response = client.post("/api/v1/meetings", json={"source": "MIC"})
    assert response.status_code == 409
    assert "MEETING_CAPTURE_DISABLED" in response.text


def test_meeting_lifecycle_stores_encrypted_audio_in_order(monkeypatch, tmp_path) -> None:
    from app.services import object_storage

    _enable(monkeypatch)
    stored: dict[str, bytes] = {}

    class MemoryStorage:
        def put(self, key: str, content: bytes, content_type: str) -> None:
            stored[key] = content

        def get(self, key: str) -> bytes:
            return stored[key]

        def delete(self, key: str) -> None:
            stored.pop(key, None)

    monkeypatch.setattr("app.modules.meetings.service.get_object_storage", lambda: MemoryStorage())
    meeting = _start()
    assert meeting["status"] == "RECORDING" and meeting["project_code"] == "orbit" and meeting["max_minutes"] == 60

    first = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=0", files={"file": ("a.webm", b"chunk-zero", "audio/webm;codecs=opus")})
    assert first.status_code == 200, first.text
    retry = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=0", files={"file": ("a.webm", b"chunk-zero", "audio/webm")})
    assert retry.status_code == 200 and retry.json()["data"]["audio_chunk_count"] == 1
    gap = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=5", files={"file": ("a.webm", b"x", "audio/webm")})
    assert gap.status_code == 409
    wrong_type = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=1", files={"file": ("a.exe", b"x", "application/octet-stream")})
    assert wrong_type.status_code == 422
    second = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=1", files={"file": ("b.webm", b"chunk-one", "audio/webm")})
    assert second.json()["data"]["audio_bytes"] == len(b"chunk-zero") + len(b"chunk-one")

    key = audio_object_key(meeting["id"], 0)
    assert stored[key] != b"chunk-zero" and decrypt_bytes(stored[key]) == b"chunk-zero"

    listen = client.get(f"/api/v1/meetings/{meeting['id']}/audio")
    assert listen.content == b"chunk-zerochunk-one" and listen.headers["content-disposition"].startswith("inline")
    saved = client.get(f"/api/v1/meetings/{meeting['id']}/audio?download=true")
    assert saved.content == b"chunk-zerochunk-one"
    assert saved.headers["content-disposition"] == f"attachment; filename=meeting-{meeting['id'][:8]}.webm"

    assert meeting_service.add_realtime_segment(meeting["id"], "  Chào anh, hôm nay review Orbit.  ") == 0
    assert meeting_service.add_realtime_segment(meeting["id"], "   ") is None
    assert meeting_service.add_realtime_segment(meeting["id"], "Bản deploy đang lỗi.") == 1
    with get_session() as session:
        row = session.scalar(select(MeetingSegment).where(MeetingSegment.meeting_id == meeting["id"], MeetingSegment.sequence == 0))
        assert "Chào anh" not in row.text_ciphertext

    # The sound reached the server late (the line was down); the browser says how long the talk really was.
    finished = client.post(f"/api/v1/meetings/{meeting['id']}/finish", json={"duration_seconds": 0})
    assert finished.status_code == 200, finished.text
    data = finished.json()["data"]
    assert data["status"] == "FINISHED" and data["duration_seconds"] == 0
    assert client.post(f"/api/v1/meetings/{meeting['id']}/finish", json={"duration_seconds": 5}).json()["data"]["duration_seconds"] == 0, "finishing twice changes nothing"
    assert [segment["text"] for segment in data["segments"]] == ["Chào anh, hôm nay review Orbit.", "Bản deploy đang lỗi."]

    late = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=2", files={"file": ("c.webm", b"x", "audio/webm")})
    assert late.status_code == 409
    assert meeting_service.recording_context(meeting["id"]) is None

    detail = client.get(f"/api/v1/meetings/{meeting['id']}")
    assert detail.status_code == 200
    with get_session() as session:
        events = {row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_id == meeting["id"])).all()}
    assert {"meeting.started", "meeting.finished", "meeting.transcript.read"} <= events
    listed = client.get("/api/v1/meetings").json()["data"]
    assert any(row["id"] == meeting["id"] and "segments" not in row for row in listed)


def test_finish_takes_the_browser_measure_but_not_more_than_the_clock(monkeypatch) -> None:
    _enable(monkeypatch)
    meeting = _start()
    longer = client.post(f"/api/v1/meetings/{meeting['id']}/finish", json={"duration_seconds": 3600})
    assert longer.status_code == 200 and longer.json()["data"]["duration_seconds"] < 60, "a measure past the wall clock is capped"
    assert client.post(f"/api/v1/meetings/{_start()['id']}/finish", json={"duration_seconds": -1}).status_code == 422
    assert client.post(f"/api/v1/meetings/{_start()['id']}/finish").status_code == 200, "no body: the server's clock"


def test_only_cto_reaches_meetings(monkeypatch) -> None:
    _enable(monkeypatch)
    meeting = _start()
    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.get(f"/api/v1/meetings/{meeting['id']}").status_code == 404
    assert owner.get("/api/v1/meetings").json()["data"] == []
    assert owner.post("/api/v1/meetings", json={"source": "MIC"}).status_code == 404
    assert owner.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC"}).status_code == 404
    assert client.get("/api/v1/meetings/00000000-0000-4000-8000-00000000beef").status_code == 404
    assert client.post("/api/v1/meetings", json={"project_id": "nope", "source": "MIC"}).status_code == 422


def test_glossary_scopes_and_realtime_keyterm_limits(monkeypatch) -> None:
    _enable(monkeypatch)
    shared = client.post("/api/v1/meetings/glossary", json={"term": "  staging   deploy "})
    assert shared.status_code == 201 and shared.json()["data"]["term"] == "staging deploy"
    assert client.post("/api/v1/meetings/glossary", json={"term": "Staging Deploy"}).status_code == 409
    project_term = client.post("/api/v1/meetings/glossary", json={"term": "Orbit", "project_id": "orbit"})
    assert project_term.json()["data"]["project_code"] == "orbit"
    long_term = client.post("/api/v1/meetings/glossary", json={"term": "Bảng điều khiển báo cáo tuần", "project_id": "orbit"})
    assert long_term.json()["data"]["usable_in_realtime"] is False
    client.post("/api/v1/meetings/glossary", json={"term": "Ember", "project_id": "ember"})

    for_orbit = [row["term"] for row in client.get("/api/v1/meetings/glossary?project_id=orbit").json()["data"]]
    assert "Orbit" in for_orbit and "staging deploy" in for_orbit and "Ember" not in for_orbit

    meeting = _start(project="orbit")
    context = meeting_service.recording_context(meeting["id"])
    assert context["keyterms"][0] == "Orbit"
    assert "staging deploy" in context["keyterms"] and "Ember" not in context["keyterms"]
    assert all(len(term) <= 20 for term in context["keyterms"]) and len(context["keyterms"]) <= 50
    assert context["deadline"] - datetime.now(timezone.utc) <= timedelta(minutes=60)

    assert client.delete(f"/api/v1/meetings/glossary/{project_term.json()['data']['id']}").status_code == 200
    assert client.delete(f"/api/v1/meetings/glossary/{project_term.json()['data']['id']}").status_code == 404


def test_gateway_translates_provider_messages_and_checks_origin() -> None:
    from app import gateway

    assert gateway.client_event({"message_type": "partial_transcript", "text": "xin ch"}) == {"type": "partial", "text": "xin ch"}
    assert gateway.client_event({"message_type": "committed_transcript_with_timestamps", "text": "xin chào"}) == {"type": "committed", "text": "xin chào"}
    assert gateway.client_event({"message_type": "session_started", "config": {}}) == {"type": "ready"}
    assert gateway.client_event({"message_type": "auth_error", "error": "key abc invalid"}) == {"type": "error", "code": "PROVIDER_ERROR"}
    assert gateway.client_event({"message_type": "something_else"}) is None

    # Health: what the browser sent against what reached the provider, and the widest gap between browser frames.
    clock = iter([0.0, 0.25, 0.5, 3.1, 3.35])
    health = gateway.StreamHealth(now=lambda: next(clock))
    for _ in range(5):
        health.received(8000)
    health.sent(8000)
    health.sent(8000)
    health.provider_rtt_ms = 180
    report = health.event()
    assert report == {"type": "health", "backlog_seconds": 0.8, "client_gap_ms": 2600, "provider_rtt_ms": 180, "dropped": 0}
    assert health.event()["client_gap_ms"] == 0, "each report covers its own window"

    url = gateway.provider_url("vi", ["Orbit", "API"])
    assert url.startswith("wss://api.elevenlabs.io/v1/speech-to-text/realtime?")
    assert "model_id=scribe_v2_realtime" in url and "audio_format=pcm_16000" in url
    assert url.count("keyterms=") == 2 and "xi-api-key" not in url

    with TestClient(gateway.app) as gateway_client:
        assert gateway_client.get("/gateway-health").json()["status"] == "ok"
        for headers in ({}, {"origin": "https://evil.example"}):
            try:
                with gateway_client.websocket_connect("/api/v1/meetings/00000000-0000-4000-8000-000000000001/stream", headers=headers):
                    raise AssertionError("unauthenticated stream must be refused")
            except Exception as exc:
                assert getattr(exc, "code", None) == 4401, exc
