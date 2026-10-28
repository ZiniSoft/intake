from __future__ import annotations

import imaplib
import logging
import ssl
import time
from pathlib import Path

from app.config import get_settings
from app.modules.reports.mailbox import mailbox_scan_service
from app.modules.reports.service import daily_report_service


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("intake.imap")
READY_FILE = Path("/tmp/imap-worker-ready")
# How often the worker looks for a scan the CTO asked for.
MANUAL_CHECK_SECONDS = 5


def ingest_once() -> dict[str, int]:
    settings = get_settings()
    if not settings.report_imap_password:
        raise RuntimeError("REPORT_IMAP_PASSWORD is required when REPORT_IMAP_ENABLED=true")
    if not settings.report_imap_host or not settings.report_imap_username:
        raise RuntimeError("REPORT_IMAP_HOST and REPORT_IMAP_USERNAME are required when REPORT_IMAP_ENABLED=true")
    context = ssl.create_default_context()
    with imaplib.IMAP4_SSL(settings.report_imap_host, settings.report_imap_port, ssl_context=context, timeout=20) as client:
        client.login(settings.report_imap_username, settings.report_imap_password)
        status, _ = client.select(settings.report_imap_folder, readonly=True)
        if status != "OK":
            raise RuntimeError(f"Unable to open IMAP folder {settings.report_imap_folder!r} as read-only")
        uid_validity_response = client.response("UIDVALIDITY")
        uid_validity = "unknown"
        if uid_validity_response[1] and uid_validity_response[1][0]:
            raw_uid_validity = uid_validity_response[1][0]
            uid_validity = raw_uid_validity.decode() if isinstance(raw_uid_validity, bytes) else str(raw_uid_validity)
        search_status, search_data = client.uid("search", None, "ALL")
        if search_status != "OK":
            raise RuntimeError("Unable to list IMAP messages")
        raw_uids = search_data[0].split() if search_data and search_data[0] else []
        # Bodies are fetched only for UIDs that are not stored yet; the search itself returns IDs only.
        known = daily_report_service.known_uids(settings.report_imap_username, uid_validity)
        new_uids = [raw for raw in raw_uids if (raw.decode() if isinstance(raw, bytes) else str(raw)) not in known]
        selected_uids = new_uids[-max(settings.report_imap_fetch_limit, 1):]
        ingested = 0
        duplicates = 0
        failed = 0
        for raw_uid in selected_uids:
            uid = raw_uid.decode() if isinstance(raw_uid, bytes) else str(raw_uid)
            fetch_status, message_data = client.uid("fetch", uid, "(BODY.PEEK[])")
            if fetch_status != "OK":
                failed += 1
                continue
            raw_message = next(
                (part[1] for part in message_data if isinstance(part, tuple) and isinstance(part[1], bytes)),
                None,
            )
            if raw_message is None:
                failed += 1
                continue
            try:
                result = daily_report_service.ingest_rfc822(
                    mailbox=settings.report_imap_username,
                    uid_validity=uid_validity,
                    uid=uid,
                    raw_message=raw_message,
                )
                duplicates += int(bool(result["duplicate"]))
                ingested += int(not bool(result["duplicate"]))
            except Exception:
                logger.exception("Daily Report ingestion failed for IMAP UID %s", uid)
                failed += 1
        client.logout()
        return {"ingested": ingested, "duplicates": duplicates, "failed": failed}


def probe_once() -> None:
    ingest_once()


def run_scan(scan_id: str | None) -> None:
    """One scan with its outcome recorded; scan_id is set when the CTO asked for it."""
    settings = get_settings()
    try:
        stats = ingest_once()
    except Exception as exc:
        READY_FILE.unlink(missing_ok=True)
        logger.error("IMAPS probe failed: %s", type(exc).__name__)
        mailbox_scan_service.finish(scan_id, error_code=type(exc).__name__)
        return
    READY_FILE.touch()
    logger.info(
        "IMAPS read-only ingestion succeeded for %s:%s/%s: %s",
        settings.report_imap_host,
        settings.report_imap_port,
        settings.report_imap_folder,
        stats,
    )
    mailbox_scan_service.finish(scan_id, stats=stats)


def run_pending_scan() -> bool:
    scan_id = mailbox_scan_service.claim()
    if scan_id is None:
        return False
    run_scan(scan_id)
    return True


def main() -> None:
    settings = get_settings()
    if not settings.report_imap_enabled:
        logger.warning("IMAPS probe is disabled; set REPORT_IMAP_ENABLED=true after adding the mailbox credential")
        READY_FILE.touch()
        while True:
            time.sleep(3600)
    while True:
        run_scan(None)
        deadline = time.monotonic() + max(settings.report_imap_poll_seconds, 30)
        while time.monotonic() < deadline:
            time.sleep(MANUAL_CHECK_SECONDS)
            try:
                run_pending_scan()
            except Exception as exc:
                logger.error("Mailbox scan request could not be read: %s", type(exc).__name__)


if __name__ == "__main__":
    main()
