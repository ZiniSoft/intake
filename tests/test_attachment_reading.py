"""Pictures on a request are read by the vision model (FR-AI-14, ADR-0061): the file is checked at the door, the
transcript joins the text the AI normalizes, the agent can send pictures with create_intake, and the CTO sees the
transcript in the raw view."""
import base64
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import Attachment, IntakeItem
from app.services import attachment_reader
from app.services.ai_processor import UModelVerseAdapter, VISION_SYSTEM_PROMPT
from app.services.intake_service import intake_store
from tests.test_ai_providers import settings

client = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==")


def _cleanup(intake_ids: list[str]) -> None:
    for intake_id in intake_ids:
        client.delete(f"/api/v1/intakes/{intake_id}")


def test_vision_payload_carries_the_pictures_and_the_vision_model() -> None:
    payload = UModelVerseAdapter(settings()).build_vision_payload([("image/png", PNG), ("image/png", PNG)], "đọc")
    assert payload["model"] == "deepseek-v4-flash-vision-exp" and payload["stream"] is False and "response_format" not in payload
    assert payload["messages"][0] == {"role": "system", "content": VISION_SYSTEM_PROMPT}
    parts = payload["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "đọc"} and len(parts) == 3
    assert parts[1]["type"] == "image_url" and parts[1]["image_url"]["url"].startswith("data:image/png;base64,iVBOR")


def test_the_file_must_be_what_it_says_it_is() -> None:
    assert attachment_reader.detect_mime(PNG) == "image/png"
    assert attachment_reader.detect_mime(b"%PDF-1.4 ...") == "application/pdf"
    assert attachment_reader.detect_mime(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert attachment_reader.detect_mime(b"<html>") is None
    created = client.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Ảnh giả (thử)"})
    intake_id = created.json()["data"]["id"]
    try:
        fake = client.post(f"/api/v1/intakes/{intake_id}/attachments", files={"file": ("x.png", b"not a png at all", "image/png")})
        assert fake.status_code == 415 and "ATTACHMENT_TYPE_MISMATCH" in fake.text
        real = client.post(f"/api/v1/intakes/{intake_id}/attachments", files={"file": ("x.png", PNG, "image/png")})
        assert real.status_code == 201 and real.json()["data"]["ocr_status"] == "NONE"
    finally:
        _cleanup([intake_id])


def test_an_uploaded_picture_can_be_fetched_for_an_authenticated_preview() -> None:
    created = client.post(
        "/api/v1/intakes",
        json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Xem lại ảnh (thử)"},
    )
    intake_id = created.json()["data"]["id"]
    try:
        upload = client.post(
            f"/api/v1/intakes/{intake_id}/attachments",
            files={"file": ("anh-loi.png", PNG, "image/png")},
        )
        assert upload.status_code == 201, upload.text
        attachment_id = client.get(f"/api/v1/intakes/{intake_id}/attachments").json()["data"][0]["id"]

        preview = client.get(f"/api/v1/intakes/{intake_id}/attachments/{attachment_id}/file")
        assert preview.status_code == 200, preview.text
        assert preview.content == PNG
        assert preview.headers["content-type"] == "image/png"
        assert preview.headers["content-disposition"].startswith('attachment; filename="anh-loi.png"')
        assert preview.headers["x-content-type-options"] == "nosniff"
        assert preview.headers["cache-control"] == "no-store"

        missing = client.get(f"/api/v1/intakes/{uuid4()}/attachments/{attachment_id}/file")
        assert missing.status_code == 404
    finally:
        _cleanup([intake_id])


def test_a_pdf_is_rendered_page_by_page_within_the_limit() -> None:
    import fitz

    document = fitz.open()
    for index in range(3):
        page = document.new_page()
        page.insert_text((72, 72), f"Trang {index + 1}")
    content = document.tobytes()
    images, total = attachment_reader.pdf_pages(content, max_pages=2)
    assert total == 3 and len(images) == 2 and all(mime == "image/png" and data.startswith(b"\x89PNG") for mime, data in images)
    try:
        attachment_reader.pdf_pages(b"%PDF-broken", max_pages=2)
    except attachment_reader.AttachmentCheckError as error:
        assert error.code == "ATTACHMENT_PDF_UNREADABLE"
    else:
        raise AssertionError("a broken PDF is refused")


def test_what_the_picture_says_joins_the_text_the_ai_reads(monkeypatch) -> None:
    seen: list[tuple[int, str]] = []

    async def fake_read(images, prompt):
        seen.append((len(images), prompt))
        return "Khách (09:12): app không đăng nhập được từ sáng\nMinh: để em kiểm tra"

    monkeypatch.setattr(attachment_reader.umodelverse_adapter, "read_images", fake_read)
    created = client.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Khách gửi ảnh chat (thử)"})
    intake_id = created.json()["data"]["id"]
    try:
        upload = client.post(f"/api/v1/intakes/{intake_id}/attachments", files={"file": ("chat.png", PNG, "image/png")})
        assert upload.status_code == 201, upload.text
        counts = attachment_reader.read_pending(intake_id)
        assert counts == {"DONE": 1} and seen and seen[0][0] == 1
        with get_session() as session:
            row = session.scalar(select(Attachment).where(Attachment.intake_id == intake_id))
            assert row.ocr_status == "DONE" and row.scan_status == "CLEAN" and row.storage_state == "TRUSTED" and row.page_count == 1
            assert row.ocr_text_ciphertext and "không đăng nhập" not in row.ocr_text_ciphertext, "stored encrypted"
            assert row.ocr_model.startswith("deepseek-v4-flash-vision-exp/")
        source = intake_store.normalization_source(intake_id)
        assert source["origin"] == "RAW"
        assert source["text"].startswith("Khách gửi ảnh chat (thử)\n\n[Ảnh đính kèm 1 - chat.png]\nKhách (09:12): app không đăng nhập được")
        # Read once; a second pass finds nothing to do.
        assert attachment_reader.read_pending(intake_id) == {}
        # The listing says it was read; the raw view (CTO) carries the transcript; the list does not.
        listed = client.get(f"/api/v1/intakes/{intake_id}/attachments").json()["data"]
        assert listed[0]["ocr_status"] == "DONE" and listed[0]["name"] == "chat.png" and "text" not in listed[0]
        raw = client.get(f"/api/v1/intakes/{intake_id}/raw").json()["data"]
        assert raw["attachments"][0]["text"].startswith("Khách (09:12)")
        # Asking to read again resets the file; without a broker the request is kept and says so.
        again = client.post(f"/api/v1/intakes/{intake_id}/attachments/{listed[0]['id']}/read")
        assert again.status_code == 202 and again.json()["data"]["id"] == listed[0]["id"]
    finally:
        _cleanup([intake_id])


def test_a_model_outage_leaves_the_picture_for_later_and_a_bad_file_is_rejected(monkeypatch) -> None:
    from app.services.ai_processor import AIProviderTransientError

    async def down(images, prompt):
        raise AIProviderTransientError("UMODELVERSE", "UMODELVERSE_UNAVAILABLE")

    monkeypatch.setattr(attachment_reader.umodelverse_adapter, "read_images", down)
    created = client.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "MANUAL", "raw_text": "Model nghỉ (thử)"})
    intake_id = created.json()["data"]["id"]
    try:
        assert client.post(f"/api/v1/intakes/{intake_id}/attachments", files={"file": ("a.png", PNG, "image/png")}).status_code == 201
        assert client.post(f"/api/v1/intakes/{intake_id}/attachments", files={"file": ("b.pdf", b"%PDF-not really", "application/pdf")}).status_code == 201
        counts = attachment_reader.read_pending(intake_id)
        assert counts == {"RETRY": 1, "REJECTED": 1}, counts
        rows = {row["name"]: row for row in client.get(f"/api/v1/intakes/{intake_id}/attachments").json()["data"]}
        assert rows["a.png"]["ocr_status"] == "RETRY" and rows["a.png"]["ocr_error"] == "UMODELVERSE_UNAVAILABLE"
        assert rows["b.pdf"]["ocr_status"] == "REJECTED" and rows["b.pdf"]["ocr_error"] == "ATTACHMENT_PDF_UNREADABLE"
        assert intake_store.normalization_source(intake_id)["text"] == "Model nghỉ (thử)"
    finally:
        _cleanup([intake_id])


def test_the_agent_sends_pictures_with_the_request() -> None:
    key = f"pic-{uuid4().hex[:10]}"
    token = client.post("/api/v1/auth/tokens", json={"name": "ảnh thử"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    response = agent.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "create_intake", "arguments": {
        "project": "orbit", "text": "Khách chụp màn hình lỗi (thử)", "idempotency_key": key,
        "attachments": [{"name": "loi.png", "mime_type": "image/png", "data_base64": base64.b64encode(PNG).decode("ascii")}],
    }}})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert "structuredContent" in result, result
    data = result["structuredContent"]
    intake_id = data["id"]
    try:
        assert data["created"] is True and data["attachments"] == 1 and "ảnh đính kèm" in data["note"]
        with get_session() as session:
            rows = session.scalars(select(Attachment).where(Attachment.intake_id == intake_id)).all()
            assert len(rows) == 1 and rows[0].detected_mime_type == "image/png" and rows[0].ocr_status == "NONE"
        bad = agent.post(MCP, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "create_intake", "arguments": {
            "project": "orbit", "text": "Ảnh giả (thử)", "idempotency_key": f"{key}-bad",
            "attachments": [{"mime_type": "image/png", "data_base64": base64.b64encode(b"nope").decode("ascii")}],
        }}})
        assert "ATTACHMENT_TYPE_MISMATCH" in bad.text
        with get_session() as session:
            assert session.scalar(select(IntakeItem.id).where(IntakeItem.normalized_title == "Ảnh giả (thử)")) is None, "checked before anything is made"
    finally:
        _cleanup([intake_id])
        client.delete(f"/api/v1/auth/tokens/{token['id']}")
