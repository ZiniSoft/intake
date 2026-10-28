"""What an attachment says (FR-AI-14, ADR-0061). The file is checked first (magic bytes against the declared type,
size, PDF pages, no password, no embedded files), a PDF is rendered page by page, and the vision model transcribes
what it sees. Only the transcript is kept, encrypted like the source; the file itself stays where it is."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import Attachment, AuditEvent
from app.services.ai_processor import AIProviderPermanentError, AIProviderTransientError, VISION_PROMPT_VERSION, umodelverse_adapter
from app.services.object_storage import get_object_storage
from app.services.raw_crypto import decrypt, encrypt

logger = logging.getLogger(__name__)

MAGIC = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "application/pdf": (b"%PDF-",),
}
RENDER_DPI = 110
READ_PROMPT = "Ghi lại toàn bộ chữ trong ảnh đính kèm này theo đúng quy tắc."


class AttachmentCheckError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_mime(content: bytes) -> str | None:
    """The type the bytes say they are, from their first bytes; None when they match none of the allowed types."""
    for mime, heads in MAGIC.items():
        if any(content.startswith(head) for head in heads):
            return mime
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def check_file(content: bytes, declared_mime: str) -> str:
    """Magic bytes must agree with the declared type (FR-AI-09); returns the detected type."""
    detected = detect_mime(content)
    if detected is None or detected != declared_mime:
        raise AttachmentCheckError("ATTACHMENT_TYPE_MISMATCH", "File content does not match its declared type")
    return detected


def pdf_pages(content: bytes, max_pages: int) -> tuple[list[tuple[str, bytes]], int]:
    """The first pages of a PDF as PNG images, and how many pages the file has. Encrypted PDFs and PDFs carrying
    embedded files are refused (ADR-0015)."""
    import fitz  # pymupdf

    try:
        document = fitz.open(stream=content, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 - whatever pymupdf raises, the file is not a readable PDF
        raise AttachmentCheckError("ATTACHMENT_PDF_UNREADABLE", "PDF cannot be opened") from exc
    try:
        if document.needs_pass:
            raise AttachmentCheckError("ATTACHMENT_PDF_ENCRYPTED", "Encrypted PDF is not read")
        if document.embfile_count() > 0:
            raise AttachmentCheckError("ATTACHMENT_PDF_EMBEDDED_FILES", "PDF with embedded files is not read")
        total = document.page_count
        images: list[tuple[str, bytes]] = []
        for index in range(min(total, max(1, max_pages))):
            pixmap = document.load_page(index).get_pixmap(dpi=RENDER_DPI)
            images.append(("image/png", pixmap.tobytes("png")))
        return images, total
    finally:
        document.close()


def images_of(content: bytes, mime: str, max_pages: int) -> tuple[list[tuple[str, bytes]], int]:
    if mime == "application/pdf":
        return pdf_pages(content, max_pages)
    return [(mime, content)], 1


def _mark(session, attachment: Attachment, status: str, *, error: str | None = None, text: str | None = None, model: str | None = None, pages: int | None = None) -> None:
    now = datetime.now(timezone.utc)
    attachment.ocr_status = status
    attachment.ocr_error = error
    attachment.ocr_at = now
    if text is not None:
        attachment.ocr_text_ciphertext = encrypt(text)
        attachment.ocr_model = model
    if pages is not None:
        attachment.page_count = pages


def read_attachment(attachment_id: str) -> str:
    """Read one attachment with the vision model. Returns DONE, SKIPPED (already read or reading disabled), REJECTED
    (the file failed its checks), FAILED (the model refused for good) or RETRY (the model was unreachable; the
    attachment stays unread so a later pass takes it)."""
    settings = get_settings()
    with get_session() as session:
        attachment = session.scalar(select(Attachment).where(Attachment.id == attachment_id).with_for_update())
        if attachment is None or attachment.purged_at is not None:
            return "SKIPPED"
        if attachment.ocr_status not in ("NONE", "RETRY"):
            return "SKIPPED"
        if not settings.attachment_vision_enabled:
            _mark(session, attachment, "SKIPPED", error="VISION_DISABLED")
            session.commit()
            return "SKIPPED"
        attachment.ocr_status = "RUNNING"
        session.commit()
        intake_id, object_key, declared = str(attachment.intake_id), attachment.object_key, attachment.declared_mime_type or ""
    try:
        content = get_object_storage().get(object_key)
        mime = check_file(content, declared)
        images, pages = images_of(content, mime, settings.attachment_pdf_max_pages)
    except AttachmentCheckError as error:
        with get_session() as session:
            attachment = session.get(Attachment, attachment_id)
            attachment.scan_status = "REJECTED"
            _mark(session, attachment, "REJECTED", error=error.code)
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="SYSTEM", actor_id="attachment-reader", event_type="attachment.rejected",
                entity_type="attachment", entity_id=attachment_id, details={"intake_id": intake_id, "code": error.code}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
        return "REJECTED"
    except Exception:  # noqa: BLE001 - storage trouble: leave it for a later pass
        logger.exception("attachment %s could not be loaded", attachment_id)
        with get_session() as session:
            attachment = session.get(Attachment, attachment_id)
            _mark(session, attachment, "RETRY", error="STORAGE_UNAVAILABLE")
            session.commit()
        return "RETRY"
    try:
        text = asyncio.run(umodelverse_adapter.read_images(images, READ_PROMPT))
    except AIProviderTransientError as error:
        with get_session() as session:
            attachment = session.get(Attachment, attachment_id)
            attachment.scan_status, attachment.storage_state = "CLEAN", "TRUSTED"
            _mark(session, attachment, "RETRY", error=error.code, pages=pages)
            session.commit()
        return "RETRY"
    except AIProviderPermanentError as error:
        with get_session() as session:
            attachment = session.get(Attachment, attachment_id)
            attachment.scan_status, attachment.storage_state = "CLEAN", "TRUSTED"
            _mark(session, attachment, "FAILED", error=error.code, pages=pages)
            session.commit()
        return "FAILED"
    with get_session() as session:
        attachment = session.get(Attachment, attachment_id)
        attachment.scan_status, attachment.storage_state = "CLEAN", "TRUSTED"
        _mark(session, attachment, "DONE", text=text, model=f"{umodelverse_adapter.describe('vision')[1]}/{VISION_PROMPT_VERSION}", pages=pages)
        attachment.ocr_error = "PARTIAL" if pages > len(images) else None
        session.commit()
    return "DONE"


def read_pending(intake_id: str) -> dict[str, int]:
    """Every unread attachment of a request, one after the other; the counts say what happened."""
    with get_session() as session:
        ids = session.scalars(select(Attachment.id).where(
            Attachment.intake_id == intake_id, Attachment.ocr_status.in_(("NONE", "RETRY")), Attachment.purged_at.is_(None),
        ).order_by(Attachment.created_at)).all()
    counts: dict[str, int] = {}
    for attachment_id in ids:
        outcome = read_attachment(str(attachment_id))
        counts[outcome] = counts.get(outcome, 0) + 1
    return counts


def transcripts(session, intake_id: str) -> list[dict[str, object]]:
    """The attachments of a request with what was read from each, in upload order, names decrypted."""
    rows = []
    for index, row in enumerate(session.scalars(select(Attachment).where(Attachment.intake_id == intake_id, Attachment.purged_at.is_(None)).order_by(Attachment.created_at)).all(), start=1):
        rows.append({
            "id": str(row.id), "index": index, "name": decrypt(row.original_name_ciphertext) if row.original_name_ciphertext else None,
            "mime_type": row.declared_mime_type, "size_bytes": row.size_bytes, "ocr_status": row.ocr_status, "ocr_error": row.ocr_error,
            "ocr_at": row.ocr_at, "page_count": row.page_count, "pages_read": min(row.page_count or 0, get_settings().attachment_pdf_max_pages) if row.declared_mime_type == "application/pdf" else (1 if row.ocr_status == "DONE" else 0),
            "text": decrypt(row.ocr_text_ciphertext) if row.ocr_status == "DONE" and row.ocr_text_ciphertext else None,
        })
    return rows
