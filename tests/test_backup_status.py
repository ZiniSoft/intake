"""The System tab reports whether the daily backup is fresh (NFR-REL-02)."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import get_session
from app.main import app
from app.models import BackupRun


client = TestClient(app, headers={"X-User-Subject": "cto"})


def _runs(*entries: tuple[str, float, str | None]) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.execute(delete(BackupRun))
        for status, hours_ago, error in entries:
            at = now - timedelta(hours=hours_ago)
            session.add(BackupRun(
                id=str(uuid4()), status=status, file_name="intake-test.tar.enc" if status == "DONE" else None,
                size_bytes=1024 if status == "DONE" else 0, table_count=41, object_count=3, error_code=error, started_at=at, completed_at=at,
            ))
        session.commit()


def _backup() -> dict:
    return client.get("/api/v1/operations/status").json()["data"]


def test_backup_is_reported_as_never_fresh_overdue_and_failed() -> None:
    _runs()
    assert _backup()["backup"] == "never"

    _runs(("DONE", 2, None))
    status = _backup()
    assert status["backup"] == "healthy"
    assert status["backup_detail"]["last_ok_file"] == "intake-test.tar.enc" and status["backup_detail"]["last_error_code"] is None

    _runs(("DONE", 30, None))
    assert _backup()["backup"] == "overdue"

    # A failure after a good backup is shown, and the good one still counts while it is fresh.
    _runs(("DONE", 5, None), ("FAILED", 1, "PASSPHRASE_MISSING"))
    status = _backup()
    assert status["backup"] == "healthy" and status["backup_detail"]["last_error_code"] == "PASSPHRASE_MISSING"
    _runs()
