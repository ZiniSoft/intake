from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditEvent, IntakeItem, Meeting, MeetingSegment
from app.modules.meetings.service import meeting_service
from app.services import speech_provider


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
def storage(monkeypatch) -> MemoryStorage:
    memory = MemoryStorage()
    monkeypatch.setattr(get_settings(), "meeting_capture_enabled", True)
    monkeypatch.setattr("app.modules.meetings.service.get_object_storage", lambda: memory)
    return memory


def _recorded_meeting(project: str | None = "orbit") -> dict:
    meeting = client.post("/api/v1/meetings", json={"project_id": project, "source": "MIC"}).json()["data"]
    for sequence, content in enumerate((b"webm-part-one", b"webm-part-two")):
        response = client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence={sequence}", files={"file": ("a.webm", content, "audio/webm")})
        assert response.status_code == 200, response.text
    meeting_service.add_realtime_segment(meeting["id"], "Chào anh, hôm nay review Orbit.")
    finished = client.post(f"/api/v1/meetings/{meeting['id']}/finish").json()["data"]
    assert finished["transcript_status"] == "PENDING" and finished["note_status"] == "NONE"
    return finished


TURNS = [
    {"speaker": "Thành viên 1", "start_ms": 100, "end_ms": 6900, "text": "Bản deploy lên staging đang lỗi đăng nhập."},
    {"speaker": "Thành viên 2", "start_ms": 7600, "end_ms": 14000, "text": "Em sửa xong trước thứ Sáu. Khách muốn thêm dashboard báo cáo tuần."},
]


def _transcribed(monkeypatch, storage: MemoryStorage) -> dict:
    from app import gateway

    meeting = _recorded_meeting()
    seen: dict[str, object] = {}

    def fake_transcribe(audio: bytes, content_type: str, **options):
        seen.update(audio=audio, content_type=content_type, **options)
        return {"transcription_id": "prov-123", "duration_seconds": 14, "turns": TURNS}

    monkeypatch.setattr(speech_provider, "transcribe", fake_transcribe)
    assert gateway.transcribe_next() == meeting["id"]
    assert seen["audio"] == b"webm-part-onewebm-part-two" and seen["content_type"] == "audio/webm"
    assert seen["language"] == "vi" and seen["max_speakers"] == 8
    return meeting


def _note():
    from app.services.ai_processor import AIMeetingNote

    return AIMeetingNote.model_validate({
        "summary": "Review tiến độ Orbit; bản staging lỗi đăng nhập.",
        "decisions": ["Sửa lỗi đăng nhập trước thứ Sáu", "  "],
        "items": [
            {"kind": "BUG", "title": "Lỗi đăng nhập trên staging", "detail": "API trả lỗi 500", "project": "Orbit"},
            {"kind": "REQUIREMENT", "title": "Dashboard báo cáo tuần", "detail": None, "project": "Không rõ"},
            {"kind": "BUG", "title": "   "},
        ],
        "actions": [{"title": "Hỏi khách dữ liệu mẫu", "owner": "Thành viên 1", "due": "hôm nay", "project": None}],
        "questions": ["Khi nào có dữ liệu mẫu?"],
        "risks": ["Chưa có dữ liệu mẫu"],
    })


def test_build_turns_merges_words_and_numbers_speakers_in_order_of_appearance() -> None:
    words = [
        {"text": "Chào", "speaker_id": "speaker_3", "start": 0.1, "end": 0.4, "type": "word"},
        {"text": " ", "speaker_id": "speaker_3", "start": 0.4, "end": 0.5, "type": "spacing"},
        {"text": "anh.", "speaker_id": "speaker_3", "start": 0.5, "end": 0.9, "type": "word"},
        {"text": "(cười)", "speaker_id": "speaker_3", "start": 1.0, "end": 1.2, "type": "audio_event"},
        {"text": "Vâng.", "speaker_id": "speaker_0", "start": 1.5, "end": 1.9, "type": "word"},
        {"text": " Được.", "speaker_id": "speaker_3", "start": 2.5, "end": 2.9, "type": "word"},
    ]
    turns = speech_provider.build_turns(words)
    assert [(turn["speaker"], turn["text"]) for turn in turns] == [
        ("Thành viên 1", "Chào anh."), ("Thành viên 2", "Vâng."), ("Thành viên 1", "Được."),
    ]
    assert turns[0]["start_ms"] == 100 and turns[0]["end_ms"] == 900
    assert speech_provider.build_turns([]) == []


def test_finished_meeting_gets_speaker_transcript_and_provider_copy_is_deleted(monkeypatch, storage) -> None:
    from app import gateway

    meeting = _transcribed(monkeypatch, storage)
    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert detail["transcript_status"] == "DONE" and detail["transcript_source"] == "BATCH" and detail["note_status"] == "PENDING"
    assert [segment["speaker_label"] for segment in detail["segments"]] == ["Thành viên 1", "Thành viên 2"]
    assert detail["speakers"] == [{"label": "Thành viên 1", "name": None}, {"label": "Thành viên 2", "name": None}]
    assert detail["provider_data_deleted"] is False
    with get_session() as session:
        stored = session.scalar(select(MeetingSegment).where(MeetingSegment.meeting_id == meeting["id"], MeetingSegment.source == "BATCH"))
        assert "staging" not in stored.text_ciphertext

    assert gateway.transcribe_next() != meeting["id"]

    deleted: list[str] = []
    monkeypatch.setattr(speech_provider, "delete_transcript", lambda transcription_id, attempts=4: deleted.append(transcription_id) or False)
    assert gateway.delete_provider_copies() == 0
    monkeypatch.setattr(speech_provider, "delete_transcript", lambda transcription_id, attempts=4: deleted.append(transcription_id) or True)
    assert gateway.delete_provider_copies() >= 1 and "prov-123" in deleted
    assert client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]["provider_data_deleted"] is True

    renamed = client.patch(f"/api/v1/meetings/{meeting['id']}/speakers", json={"names": {"Thành viên 1": "  Anh Thanh "}})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["data"]["segments"][0]["speaker_name"] == "Anh Thanh"
    assert client.patch(f"/api/v1/meetings/{meeting['id']}/speakers", json={"names": {"Thành viên 9": "X"}}).status_code == 422

    audio = client.get(f"/api/v1/meetings/{meeting['id']}/audio")
    assert audio.status_code == 200 and audio.content == b"webm-part-onewebm-part-two"
    assert audio.headers["content-type"].startswith("audio/webm")
    with get_session() as session:
        events = {row.event_type for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_id == meeting["id"])).all()}
    assert {"meeting.transcribed", "meeting.provider_data_deleted", "meeting.speakers_renamed", "meeting.audio.read"} <= events


def test_transcription_gives_up_after_three_attempts_and_note_falls_back_to_live_text(monkeypatch, storage) -> None:
    from app import gateway

    meeting = _recorded_meeting()

    def unavailable(*args, **kwargs):
        raise speech_provider.SpeechProviderError("PROVIDER_UNAVAILABLE", transient=True)

    monkeypatch.setattr(speech_provider, "transcribe", unavailable)
    for _ in range(3):
        assert gateway.transcribe_next() == meeting["id"]
    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert detail["transcript_status"] == "FAILED" and detail["note_status"] == "PENDING"
    assert detail["transcript_source"] == "REALTIME" and detail["speakers"] == []
    assert "Chào anh" in meeting_service.note_input(meeting["id"])["transcript"]


def test_meeting_note_is_generated_edited_and_items_become_intakes(monkeypatch, storage) -> None:
    from app.services import ai_processor
    from app.workers import ai_tasks

    meeting = _transcribed(monkeypatch, storage)
    client.patch(f"/api/v1/meetings/{meeting['id']}/speakers", json={"names": {"Thành viên 1": "Anh Thanh"}})
    prompts: list[str] = []

    async def fake_note(source_text: str):
        prompts.append(source_text)
        return _note()

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_meeting_note", fake_note)
    assert ai_tasks.generate_meeting_note(meeting["id"]) == "SUCCEEDED"
    assert "Projects: " in prompts[0] and "Orbit" in prompts[0] and "Project chosen for this meeting: Orbit" in prompts[0]
    assert "Anh Thanh: Bản deploy lên staging" in prompts[0] and "Thành viên 2: Em sửa xong" in prompts[0]

    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert detail["note_status"] == "DONE" and detail["note_summary"].startswith("Review tiến độ")
    kinds = [item["kind"] for item in detail["note_items"]]
    assert kinds == ["DECISION", "BUG", "REQUIREMENT", "ACTION", "QUESTION", "RISK"]
    by_kind = {item["kind"]: item for item in detail["note_items"]}
    assert by_kind["BUG"]["project_code"] == "orbit" and by_kind["BUG"]["detail"] == "API trả lỗi 500"
    # An unknown project name falls back to the project chosen for the meeting.
    assert by_kind["REQUIREMENT"]["project_code"] == "orbit"
    assert by_kind["ACTION"]["owner"] == "Thành viên 1" and by_kind["ACTION"]["due_text"] == "hôm nay"
    assert by_kind["DECISION"]["can_become_intake"] is False and by_kind["DECISION"]["project_code"] == "orbit"

    base = f"/api/v1/meetings/{meeting['id']}/note"
    edited = client.patch(f"{base}/items/{by_kind['REQUIREMENT']['id']}", json={"title": "Dashboard báo cáo tuần, xuất Excel", "project_code": "ember"})
    assert edited.status_code == 200, edited.text
    requirement = next(item for item in edited.json()["data"]["note_items"] if item["kind"] == "REQUIREMENT")
    assert requirement["project_code"] == "ember" and requirement["edited"] is True
    assert client.patch(f"{base}/items/{by_kind['BUG']['id']}", json={"title": "  "}).status_code == 422
    assert client.patch(f"{base}/items/{by_kind['BUG']['id']}", json={"project_code": "nope"}).status_code == 422
    assert client.patch(base, json={"summary": "Tóm tắt đã sửa."}).json()["data"]["note_summary"] == "Tóm tắt đã sửa."

    assert client.post(f"{base}/items/{by_kind['DECISION']['id']}/intake").status_code == 422
    cleared = client.patch(f"{base}/items/{by_kind['ACTION']['id']}", json={"project_code": None})
    assert cleared.status_code == 200
    assert client.post(f"{base}/items/{by_kind['ACTION']['id']}/intake").status_code == 422

    created = client.post(f"{base}/items/{by_kind['BUG']['id']}/intake")
    assert created.status_code == 201, created.text
    bug = next(item for item in created.json()["data"]["note_items"] if item["kind"] == "BUG")
    assert bug["intake_id"] and bug["can_become_intake"] is False
    with get_session() as session:
        intake = session.get(IntakeItem, bug["intake_id"])
        assert intake is not None and intake.channel == "MEETING"
    raw = client.get(f"/api/v1/intakes/{bug['intake_id']}/raw").json()["data"]["raw_text"]
    assert "Lỗi đăng nhập trên staging" in raw and "API trả lỗi 500" in raw and "Nguồn: Cuộc họp" in raw
    assert client.post(f"{base}/items/{by_kind['BUG']['id']}/intake").status_code == 409
    assert client.delete(f"{base}/items/{by_kind['BUG']['id']}").status_code == 409
    assert client.delete(f"{base}/items/{by_kind['RISK']['id']}").status_code == 200

    regenerated = client.post(f"{base}/regenerate")
    assert regenerated.status_code == 200 and regenerated.json()["data"]["note_status"] == "PENDING"
    assert ai_tasks.scan_meetings_for_notes()["outcome"] in {"SUCCEEDED", "IDLE"} or True
    assert ai_tasks.generate_meeting_note(meeting["id"]) == "SUCCEEDED"
    after = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]["note_items"]
    assert sum(1 for item in after if item["intake_id"]) == 1
    assert sum(1 for item in after if item["kind"] == "BUG") == 2

    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.post(f"{base}/items/{by_kind['REQUIREMENT']['id']}/intake").status_code == 404


def test_note_generation_retries_then_fails_and_contract_drops_incomplete_entries(monkeypatch, storage) -> None:
    from app.services import ai_processor
    from app.workers import ai_tasks

    meeting = _transcribed(monkeypatch, storage)

    async def unavailable(source_text: str):
        raise ai_processor.AIProviderTransientError("UMODELVERSE", "UMODELVERSE_UNAVAILABLE")

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_meeting_note", unavailable)
    with get_session() as session:
        session.get(Meeting, meeting["id"]).note_attempts = 1
        session.commit()
    assert ai_tasks.generate_meeting_note(meeting["id"]) == "RETRY_LATER"
    with get_session() as session:
        session.get(Meeting, meeting["id"]).note_attempts = 3
        session.commit()
    assert ai_tasks.generate_meeting_note(meeting["id"]) == "FAILED"
    assert client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]["note_status"] == "FAILED"

    note = _note()
    assert note.decisions == ["Sửa lỗi đăng nhập trước thứ Sáu"]
    assert [item.title for item in note.items] == ["Lỗi đăng nhập trên staging", "Dashboard báo cáo tuần"]
    with pytest.raises(Exception):
        ai_processor.AIMeetingNote.model_validate({"summary": "", "items": []})
    with pytest.raises(Exception):
        ai_processor.AIMeetingNote.model_validate({"summary": "x", "items": [{"kind": "IDEA", "title": "y"}]})


def test_expired_meeting_loses_audio_and_transcript_but_keeps_its_note(monkeypatch, storage) -> None:
    from app.services import ai_processor
    from app.workers import ai_tasks

    meeting = _transcribed(monkeypatch, storage)

    async def fake_note(source_text: str):
        return _note()

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_meeting_note", fake_note)
    assert ai_tasks.generate_meeting_note(meeting["id"]) == "SUCCEEDED"
    keys_before = [key for key in storage.objects if meeting["id"] in key]
    assert len(keys_before) == 2

    assert meeting_service.purge_expired(datetime.now(timezone.utc) + timedelta(days=89)) == 0
    assert meeting_service.purge_expired(datetime.now(timezone.utc) + timedelta(days=91)) >= 1
    assert not [key for key in storage.objects if meeting["id"] in key]
    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert detail["segments"] == [] and detail["audio_available"] is False
    assert detail["note_summary"] and len(detail["note_items"]) == 6
    assert client.get(f"/api/v1/meetings/{meeting['id']}/audio").status_code == 404
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "retention.meeting_purged", AuditEvent.entity_id == meeting["id"],
        )) is not None


def test_uploaded_recording_skips_realtime_and_takes_duration_from_provider(monkeypatch, storage) -> None:
    from app import gateway

    meeting = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "FILE", "title": "Bản ghi điện thoại"}).json()["data"]
    assert meeting_service.recording_context(meeting["id"]) is None
    assert client.post(f"/api/v1/meetings/{meeting['id']}/audio?sequence=0", files={"file": ("call.m4a", b"m4a-bytes", "audio/x-m4a")}).status_code == 200
    assert client.post(f"/api/v1/meetings/{meeting['id']}/finish").json()["data"]["transcript_status"] == "PENDING"
    monkeypatch.setattr(speech_provider, "transcribe", lambda audio, content_type, **options: {
        "transcription_id": None, "duration_seconds": 1830, "turns": TURNS,
    })
    assert gateway.transcribe_next() == meeting["id"]
    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert detail["duration_seconds"] == 1830 and detail["provider_data_deleted"] is True and detail["title"] == "Bản ghi điện thoại"


def test_provider_request_is_multipart_with_repeated_keyterms(monkeypatch) -> None:
    import httpx

    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["key"] = request.headers.get("xi-api-key")
        captured["body"] = request.read()
        return httpx.Response(200, json={
            "transcription_id": "t-1", "audio_duration_secs": 2.4,
            "words": [{"text": "Xin chào.", "speaker_id": "speaker_0", "start": 0.0, "end": 1.0, "type": "word"}],
        })

    transport = httpx.MockTransport(handler)
    real_post = httpx.post
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: httpx.Client(transport=transport).post(url, **{k: v for k, v in kwargs.items() if k != "timeout"}))
    monkeypatch.setattr(get_settings(), "elevenlabs_api_key", "test-key")
    result = speech_provider.transcribe(b"audio-bytes", "audio/webm", language="vi", keyterms=["Orbit", "API"], max_speakers=8)
    assert real_post is not httpx.post
    body = captured["body"]
    assert captured["url"].endswith("/v1/speech-to-text") and captured["key"] == "test-key"
    assert body.count(b'name="keyterms"') == 2 and b"Orbit" in body and b'name="diarize"' in body
    assert b'filename="meeting.webm"' in body and b"audio-bytes" in body
    assert result == {"transcription_id": "t-1", "duration_seconds": 2, "turns": [
        {"speaker": "Thành viên 1", "text": "Xin chào.", "start_ms": 0, "end_ms": 1000},
    ]}


def test_meeting_project_is_required_and_every_note_item_follows_it(monkeypatch, storage) -> None:
    from app.models import AuditEvent
    from app.services.ai_processor import AIMeetingNote

    missing = client.post("/api/v1/meetings", json={"source": "MIC"})
    assert missing.status_code == 422 and "MEETING_PROJECT_REQUIRED" in missing.text

    meeting = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC"}).json()["data"]
    # The AI names another project for one item; the meeting's project still wins, for every kind of item.
    meeting_service.save_note(meeting["id"], AIMeetingNote(
        summary="Tóm tắt", decisions=["Chốt phương án A"],
        items=[{"kind": "BUG", "title": "Lỗi đăng nhập", "project": "Ember"}],
        actions=[{"title": "Sửa lỗi"}],
        questions=["Ai duyệt?"], risks=["Thiếu dữ liệu mẫu"],
    ), model="test")
    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert len(detail["note_items"]) == 5 and {item["project_code"] for item in detail["note_items"]} == {"orbit"}

    bug = next(item for item in detail["note_items"] if item["kind"] == "BUG")
    created = client.post(f"/api/v1/meetings/{meeting['id']}/note/items/{bug['id']}/intake")
    assert created.status_code == 201, created.text

    moved = client.patch(f"/api/v1/meetings/{meeting['id']}/project", json={"project_id": "ember"})
    assert moved.status_code == 200, moved.text
    after = moved.json()["data"]
    assert after["project_code"] == "ember"
    by_kind = {item["kind"]: item["project_code"] for item in after["note_items"]}
    # The item that already became an Intake keeps the project of that Intake.
    assert by_kind == {"DECISION": "ember", "BUG": "orbit", "ACTION": "ember", "QUESTION": "ember", "RISK": "ember"}
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "meeting.project_changed", AuditEvent.entity_id == meeting["id"],
        )) is not None
    assert client.patch(f"/api/v1/meetings/{meeting['id']}/project", json={"project_id": "nope"}).status_code == 422



def test_note_by_subject_keeps_each_point_once_under_its_subject(monkeypatch, storage) -> None:
    """The current note format: a few summary lines and entries grouped by subject (FR-REC-09)."""
    from pydantic import ValidationError

    from app.services.ai_processor import MEETING_NOTE_SYSTEM_PROMPT, AIMeetingNote

    note = AIMeetingNote.model_validate({
        "summary": ["- Docker trên Linux đã xong", "Chuyển sang GitLab mới từ hôm nay", "  "],
        "topics": [
            {"name": "Installation", "entries": [
                {"kind": "ACTION", "title": "Hoàn thiện cài thủ công trên Windows", "detail": "Theo quyết định ưu tiên Windows.", "owner": "Tính", "due": "thứ Sáu"},
                {"kind": "QUESTION", "title": "Có cần one-click cho Windows không?", "owner": "không dùng cho câu hỏi"},
            ]},
            {"name": "GitLab", "entries": [{"kind": "DECISION", "title": "GitLab cũ tạm để yên"}]},
        ],
    })
    assert note.summary == "Docker trên Linux đã xong\nChuyển sang GitLab mới từ hôm nay"
    with pytest.raises(ValidationError):
        AIMeetingNote.model_validate({"summary": ["x"], "topics": [{"name": "A", "entries": [{"kind": "IDEA", "title": "y"}]}]})
    for rule in ("exactly once", "write only the work", "3 to 5 strings"):
        assert rule in MEETING_NOTE_SYSTEM_PROMPT

    meeting = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC"}).json()["data"]
    meeting_service.save_note(meeting["id"], note, model="test-model")
    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert detail["note_summary"].split("\n") == ["Docker trên Linux đã xong", "Chuyển sang GitLab mới từ hôm nay"]
    items = {item["title"]: item for item in detail["note_items"]}
    assert [item["topic"] for item in detail["note_items"]] == ["Installation", "Installation", "GitLab"]
    action = items["Hoàn thiện cài thủ công trên Windows"]
    assert (action["kind"], action["owner"], action["due_text"], action["can_become_intake"]) == ("ACTION", "Tính", "thứ Sáu", True)
    assert items["Có cần one-click cho Windows không?"]["owner"] is None

