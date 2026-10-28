from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import Attachment, AuditEvent, SourceMessage
from app.services.object_storage import get_object_storage


def purge_expired_raw(now: datetime | None = None) -> int:
    current_time = now or datetime.now(timezone.utc)
    purged_count = 0
    with get_session() as session:
        sources = session.scalars(
            select(SourceMessage).where(
                SourceMessage.purge_after <= current_time,
                SourceMessage.purged_at.is_(None),
                SourceMessage.raw_content_ciphertext.is_not(None),
            )
        ).all()
        for source in sources:
            source.raw_content_ciphertext = None
            source.sender_reference_ciphertext = None
            source.raw_payload = None
            source.purged_at = current_time
            purged_count += 1
        attachments = session.scalars(
            select(Attachment).where(
                Attachment.purge_after <= current_time,
                Attachment.purged_at.is_(None),
            )
        ).all()
        storage = get_object_storage()
        for attachment in attachments:
            storage.delete(attachment.object_key)
            attachment.storage_state = "PURGED"
            attachment.scan_status = "PURGED"
            attachment.purged_at = current_time
        if purged_count:
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    actor_type="WORKER",
                    actor_id="retention-worker",
                    event_type="retention.raw_purged",
                    entity_type="source_message",
                    details={"purged_source_count": purged_count},
                    created_at=current_time,
                )
            )
        session.commit()
    return purged_count
