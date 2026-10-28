from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select

from app.db import get_session
from app.config import get_settings
from app.models import Attachment, IntakeItem, ProcessingRun
from app.queue.celery_app import celery_app
from app.services.attachment_reader import AttachmentCheckError, check_file
from app.services.raw_crypto import encrypt
from app.services.object_storage import get_object_storage

MAX_ATTACHMENT_SIZE = 5 * 1024 * 1024
ALLOWED_MIME_TYPES = {"application/pdf", "image/jpeg", "image/png", "image/webp"}


async def save_attachment(intake_id: str, upload: UploadFile, *, read_now: bool = True) -> dict[str, object]:
    if upload.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported attachment type")
    content = await upload.read(MAX_ATTACHMENT_SIZE + 1)
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Attachment exceeds 5 MB")
    try:
        return store_attachment(intake_id, upload.filename or "tệp", upload.content_type, content, read_now=read_now)
    except AttachmentCheckError as error:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=error.code) from error
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from error


def store_attachment(intake_id: str, filename: str, mime_type: str, content: bytes, *, read_now: bool = True) -> dict[str, object]:
    """Keep a file next to a request: the bytes in object storage, the record here, checked at the door (FR-AI-09).
    With `read_now` a request that the AI already read gets this file transcribed and read again (FR-AI-14);
    a request about to be processed reads its files in that pass."""
    if mime_type not in ALLOWED_MIME_TYPES:
        raise AttachmentCheckError("ATTACHMENT_TYPE_UNSUPPORTED", "Unsupported attachment type")
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise AttachmentCheckError("ATTACHMENT_TOO_LARGE", "Attachment exceeds 5 MB")
    detected = check_file(content, mime_type)
    with get_session() as session:
        intake = session.scalar(select(IntakeItem).where(IntakeItem.id == intake_id))
        if intake is None:
            raise KeyError(intake_id)
        already_read = session.scalar(select(ProcessingRun.id).where(
            ProcessingRun.intake_id == intake_id, ProcessingRun.status.in_(("SUCCEEDED", "PARTIAL", "FAILED")),
        )) is not None
        object_key = f"{intake_id}/{uuid4().hex}"
        storage = get_object_storage()
        storage.put(object_key, content, mime_type)
        attachment = Attachment(
            id=str(uuid4()),
            intake_id=intake_id,
            object_key=object_key,
            original_name_ciphertext=encrypt(filename),
            declared_mime_type=mime_type,
            detected_mime_type=detected,
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
            storage_state="QUARANTINE",
            scan_status="PENDING",
            ocr_status="NONE",
            purge_after=datetime.now(timezone.utc) + timedelta(days=get_settings().raw_retention_days),
        )
        session.add(attachment)
        try:
            session.commit()
        except Exception:
            storage.delete(object_key)
            raise
        attachment_id = attachment.id
        result = {
            "id": attachment.id,
            "intake_id": intake_id,
            "mime_type": attachment.mime_type,
            "size_bytes": attachment.size_bytes,
            "scan_status": attachment.scan_status,
            "ocr_status": attachment.ocr_status,
        }
    if read_now and already_read and get_settings().attachment_vision_enabled:
        queue_read(attachment_id, intake_id)
    return result


def queue_read(attachment_id: str, intake_id: str) -> bool:
    """Ask the AI worker to transcribe one attachment and read the request again; False when no broker answers."""
    try:
        celery_app.send_task("intake.attachments.read", args=[attachment_id, intake_id], queue="ai.normalize")
        return True
    except Exception:  # noqa: BLE001 - no broker: the file is kept, "Đọc lại" on the request tries again
        return False
