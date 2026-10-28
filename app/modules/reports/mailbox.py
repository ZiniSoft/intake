"""Scans of the Daily Report mailbox: the schedule, and a scan the CTO asks for right now.

The API holds no mailbox credential. It only records a request; the IMAP worker picks it up.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_session
from app.models import MailboxScan

# A request the worker has not finished after this long is treated as lost.
STALE_AFTER = timedelta(minutes=5)
KEEP_HISTORY = timedelta(days=30)


class MailboxScanError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _view(scan: MailboxScan) -> dict[str, object]:
    return {
        "id": str(scan.id), "trigger": scan.trigger, "status": scan.status,
        "ingested": scan.ingested, "duplicates": scan.duplicates, "failed": scan.failed,
        "error_code": scan.error_code, "created_at": scan.created_at, "completed_at": scan.completed_at,
    }


class MailboxScanService:
    def _open_scan(self, session, now: datetime) -> MailboxScan | None:
        """The scan in progress, after closing any the worker never finished."""
        current = None
        for scan in session.scalars(
            select(MailboxScan).where(MailboxScan.status.in_(("PENDING", "RUNNING"))).order_by(MailboxScan.created_at)
        ):
            if now - _aware(scan.created_at) > STALE_AFTER:
                scan.status, scan.error_code, scan.completed_at = "FAILED", "WORKER_UNAVAILABLE", now
            else:
                current = scan
        return current

    def status(self) -> dict[str, object]:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        with get_session() as session:
            current = self._open_scan(session, now)
            last = session.scalar(
                select(MailboxScan).where(MailboxScan.status.in_(("DONE", "FAILED"))).order_by(MailboxScan.completed_at.desc())
            )
            session.commit()
            return {
                "enabled": settings.report_imap_enabled, "mailbox": settings.report_imap_username,
                "poll_minutes": max(settings.report_imap_poll_seconds, 30) // 60,
                "current": _view(current) if current is not None else None,
                "last": _view(last) if last is not None else None,
            }

    def request(self, actor_id: str) -> dict[str, object]:
        if not get_settings().report_imap_enabled:
            raise MailboxScanError("MAILBOX_DISABLED")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            current = self._open_scan(session, now)
            if current is None:
                # Two clicks share one scan: a second request while one is open adds nothing.
                current = MailboxScan(id=str(uuid4()), trigger="MANUAL", status="PENDING", requested_by=actor_id, created_at=now)
                session.add(current)
            session.commit()
        return self.status()

    def claim(self) -> str | None:
        """Worker side: take the oldest waiting request."""
        with get_session() as session:
            scan = session.scalar(
                select(MailboxScan).where(MailboxScan.status == "PENDING").order_by(MailboxScan.created_at).with_for_update(skip_locked=True)
            )
            if scan is None:
                return None
            scan.status = "RUNNING"
            session.commit()
            return str(scan.id)

    def finish(self, scan_id: str | None, stats: dict[str, int] | None = None, error_code: str | None = None) -> None:
        """Worker side: record the outcome. A scheduled scan has no request row, so one is written here."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            scan = session.get(MailboxScan, scan_id) if scan_id else None
            if scan is None:
                scan = MailboxScan(id=str(uuid4()), trigger="SCHEDULED", status="RUNNING", created_at=now)
                session.add(scan)
            stats = stats or {}
            scan.status = "FAILED" if error_code else "DONE"
            scan.error_code = error_code[:64] if error_code else None
            scan.ingested, scan.duplicates, scan.failed = stats.get("ingested", 0), stats.get("duplicates", 0), stats.get("failed", 0)
            scan.completed_at = now
            session.execute(
                delete(MailboxScan).where(MailboxScan.created_at < now - KEEP_HISTORY).execution_options(synchronize_session=False)
            )
            session.commit()


mailbox_scan_service = MailboxScanService()
