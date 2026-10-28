"""From a recording to Intakes that stay true to what was said: the transcript excerpt behind a note item, Intakes
for several items at once, a changed item kind, a recording that goes on in parts, an abandoned upload, and a
second try at transcription (FR-REC-15 to FR-REC-18)."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import Meeting
from app.modules.meetings.service import meeting_service
from app.services.ai_processor import build_intake_message
from tests.test_meeting_notes import MemoryStorage, _note, _recorded_meeting, _transcribed, storage  # noqa: F401 (fixture)

client = TestClient(app, headers={"X-User-Subject": "cto"})


def _noted(monkeypatch, storage: MemoryStorage) -> dict:
    from app.services import ai_processor
    from app.workers import ai_tasks

    meeting = _transcribed(monkeypatch, storage)

    async def fake_note(source_text: str):
        return _note()

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_meeting_note", fake_note)
    assert ai_tasks.generate_meeting_note(meeting["id"]) == "SUCCEEDED"
    return client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]


def test_the_intake_carries_the_words_behind_the_note_item(monkeypatch, storage) -> None:
    detail = _noted(monkeypatch, storage)
    client.patch(f"/api/v1/meetings/{detail['id']}/speakers", json={"names": {"Thành viên 1": "Anh Thanh"}})
    by_kind = {item["kind"]: item for item in detail["note_items"]}
    base = f"/api/v1/meetings/{detail['id']}/note/items"

    created = client.post(f"{base}/{by_kind['BUG']['id']}/intake")
    assert created.status_code == 201, created.text
    bug = next(item for item in created.json()["data"]["note_items"] if item["kind"] == "BUG")
    raw = client.get(f"/api/v1/intakes/{bug['intake_id']}/raw").json()["data"]["raw_text"]
    assert "Trích bản chữ cuộc họp" in raw
    assert "Anh Thanh: Bản deploy lên staging đang lỗi đăng nhập." in raw, "the turn that shares the item's words, with the speaker's name"

    # The whole transcript on request.
    full = client.post(f"{base}/{by_kind['REQUIREMENT']['id']}/intake?full_transcript=true")
    assert full.status_code == 201, full.text
    requirement = next(item for item in full.json()["data"]["note_items"] if item["kind"] == "REQUIREMENT")
    raw_full = client.get(f"/api/v1/intakes/{requirement['intake_id']}/raw").json()["data"]["raw_text"]
    assert "Thành viên 2: Em sửa xong" in raw_full and "Anh Thanh: Bản deploy" in raw_full

    message = build_intake_message("x", channel="MEETING", routes=["NEEDS_INFO", "RESPONSE", "GITLAB"])
    assert "Use only what people said" in message
    assert "Use only what people said" not in build_intake_message("x", channel="ZALO")


def test_excerpt_picks_matching_turns_within_the_budget() -> None:
    from app.modules.meetings import service as module

    class Row:
        def __init__(self, speaker, text):
            self.speaker_label, self.text_ciphertext = speaker, text

    class Item:
        title_ciphertext, detail_ciphertext, topic = "Lỗi thanh toán trên app", None, "Thanh toán"

    class Meeting_:
        speaker_names = {"S1": "Lan"}

    long = [Row("S1", f"Câu chuyện khác số {i} không liên quan gì cả " * 6) for i in range(40)]
    long[20] = Row("S1", "Thanh toán trên app báo lỗi từ sáng nay.")
    monkey = module.MeetingService.__new__(module.MeetingService)
    monkey._segments = staticmethod(lambda session, meeting: long)  # type: ignore[assignment]
    module_decrypt = module.decrypt
    module.decrypt = lambda value: value  # type: ignore[assignment]
    try:
        excerpt = module.MeetingService._transcript_excerpt(monkey, None, Meeting_(), Item(), False)
    finally:
        module.decrypt = module_decrypt  # type: ignore[assignment]
    assert excerpt is not None and "Lan: Thanh toán trên app báo lỗi" in excerpt
    assert "số 19 " in excerpt and "số 21 " in excerpt, "the neighbours come along"
    assert "số 5 " not in excerpt and len(excerpt) <= module.TRANSCRIPT_EXCERPT_CHARS


def test_several_items_become_intakes_at_once_and_a_kind_can_change_first(monkeypatch, storage) -> None:
    detail = _noted(monkeypatch, storage)
    by_kind = {item["kind"]: item for item in detail["note_items"]}
    base = f"/api/v1/meetings/{detail['id']}/note/items"

    # A question the team decided is really a requirement.
    changed = client.patch(f"{base}/{by_kind['QUESTION']['id']}", json={"kind": "REQUIREMENT"})
    assert changed.status_code == 200
    assert next(item for item in changed.json()["data"]["note_items"] if item["id"] == by_kind["QUESTION"]["id"])["can_become_intake"] is True

    bulk = client.post(f"{base}/intakes", json={"item_ids": [by_kind["BUG"]["id"], by_kind["QUESTION"]["id"], by_kind["DECISION"]["id"], by_kind["BUG"]["id"]]})
    assert bulk.status_code == 201, bulk.text
    results = {row["item_id"]: row for row in bulk.json()["data"]["results"]}
    assert len(results) == 3, "a repeated id is handled once"
    assert results[by_kind["BUG"]["id"]]["intake_id"] and results[by_kind["QUESTION"]["id"]]["intake_id"]
    assert results[by_kind["DECISION"]["id"]]["error"] == "NOTE_ITEM_NOT_ACTIONABLE"
    meeting = bulk.json()["data"]["meeting"]
    assert sum(1 for item in meeting["note_items"] if item["intake_id"]) == 2
    again = client.post(f"{base}/intakes", json={"item_ids": [by_kind["BUG"]["id"]]}).json()["data"]["results"][0]
    assert again["error"] == "NOTE_ITEM_HAS_INTAKE"


def test_a_long_recording_goes_on_as_the_next_part(monkeypatch, storage) -> None:
    first = _recorded_meeting()
    second = client.post("/api/v1/meetings", json={"continues_meeting_id": first["id"], "source": "MIC"})
    assert second.status_code == 201, second.text
    part = second.json()["data"]
    assert part["part_number"] == 2 and part["project_code"] == first["project_code"]
    assert part["title"].endswith("(phần 2)") and part["series_id"] == first["id"]
    third = client.post("/api/v1/meetings", json={"continues_meeting_id": part["id"], "source": "MIC"}).json()["data"]
    assert third["part_number"] == 3 and third["title"].endswith("(phần 3)") and "(phần 2)" not in third["title"]
    detail = client.get(f"/api/v1/meetings/{first['id']}").json()["data"]
    assert [row["part_number"] for row in detail["parts"]] == [1, 2, 3] and detail["series_id"] == first["id"]
    assert client.post("/api/v1/meetings", json={"continues_meeting_id": "no-such-meeting", "source": "MIC"}).status_code == 404
    # Leave nothing pending behind: the parts never got sound, the first one never gets transcribed here.
    for row in (part, third):
        client.post(f"/api/v1/meetings/{row['id']}/finish", json={})
    for row in (first, part, third):
        assert client.delete(f"/api/v1/meetings/{row['id']}").status_code == 200


def test_a_stalled_recording_with_live_text_is_finished_as_cut_short_and_its_note_can_be_made(monkeypatch, storage) -> None:
    """FR-REC-18: a reloaded tab leaves the meeting "recording"; what reached the server (here the live text) is kept:
    the meeting ends as cut short, the note is asked for, and "Tạo lại" works instead of answering 409."""
    from uuid import uuid4

    from app.models import MeetingSegment
    from app.services.raw_crypto import encrypt

    meeting = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "MIC"}).json()["data"]
    with get_session() as session:
        row = session.get(Meeting, meeting["id"])
        row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=90)
        session.add(MeetingSegment(id=str(uuid4()), meeting_id=meeting["id"], source="REALTIME", sequence=0, speaker_label=None, start_ms=0, end_ms=2000,
                                   text_ciphertext=encrypt("Xin chào, mình có daily planning"), created_at=datetime.now(timezone.utc)))
        session.commit()
    assert client.post(f"/api/v1/meetings/{meeting['id']}/note/regenerate", json={}).status_code == 409, "still recording: nothing to summarise yet"
    assert meeting_service.fail_stale_recordings() >= 1
    shown = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert shown["status"] == "FINISHED" and shown["transcript_error"] == "UPLOAD_STALLED", shown
    assert shown["transcript_status"] == "SKIPPED" and shown["note_status"] == "PENDING" and shown["duration_seconds"] is not None
    regenerated = client.post(f"/api/v1/meetings/{meeting['id']}/note/regenerate", json={})
    assert regenerated.status_code == 200 and regenerated.json()["data"]["note_status"] == "PENDING", regenerated.text
    assert client.delete(f"/api/v1/meetings/{meeting['id']}").status_code == 200


def test_an_abandoned_upload_is_failed_and_can_be_deleted(monkeypatch, storage) -> None:
    meeting = client.post("/api/v1/meetings", json={"project_id": "orbit", "source": "FILE"}).json()["data"]
    assert meeting["status"] == "RECORDING"
    with get_session() as session:
        row = session.get(Meeting, meeting["id"])
        row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=90)
        session.commit()
    assert client.delete(f"/api/v1/meetings/{meeting['id']}").status_code == 409, "still 'recording' until housekeeping looks"
    assert meeting_service.fail_stale_recordings() >= 1
    shown = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    assert shown["status"] == "FAILED" and shown["transcript_error"] == "UPLOAD_STALLED" and shown["note_status"] == "SKIPPED"
    assert client.delete(f"/api/v1/meetings/{meeting['id']}").status_code == 200
    with get_session() as session:
        assert session.scalar(select(Meeting).where(Meeting.id == meeting["id"])) is None


def test_transcription_can_be_tried_again_after_it_failed(monkeypatch, storage) -> None:
    meeting = _transcribed(monkeypatch, storage)
    base = f"/api/v1/meetings/{meeting['id']}"
    assert client.post(f"{base}/transcript/retry").status_code == 409, "it did not fail"
    with get_session() as session:
        row = session.get(Meeting, meeting["id"])
        row.transcript_status, row.transcript_error, row.transcript_attempts = "FAILED", "PROVIDER_REJECTED", 3
        session.commit()
    shown = client.get(base).json()["data"]
    assert shown["transcript_error"] == "PROVIDER_REJECTED"
    retried = client.post(f"{base}/transcript/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["data"]["transcript_status"] == "PENDING" and retried.json()["data"]["transcript_error"] is None
