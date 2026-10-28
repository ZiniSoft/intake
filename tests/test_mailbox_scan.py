"""Asking for a scan of the Daily Report mailbox right now (FR-EML-14)."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import MailboxScan
from app.modules.reports.mailbox import mailbox_scan_service
from app.workers import imap_probe


client = TestClient(app, headers={"X-User-Subject": "cto"})


def _clear() -> None:
    with get_session() as session:
        session.execute(delete(MailboxScan))
        session.commit()


def test_scan_now_is_refused_while_the_mailbox_is_off(monkeypatch) -> None:
    _clear()
    monkeypatch.setattr(get_settings(), "report_imap_enabled", False)
    response = client.post("/api/v1/reports/mailbox/scan")
    assert response.status_code == 409
    assert response.json()["error"] == "MAILBOX_DISABLED"
    assert client.get("/api/v1/reports/mailbox").json()["data"]["enabled"] is False


def test_scan_now_is_run_by_the_worker_and_reported(monkeypatch) -> None:
    _clear()
    monkeypatch.setattr(get_settings(), "report_imap_enabled", True)

    first = client.post("/api/v1/reports/mailbox/scan")
    assert first.status_code == 202
    scan = first.json()["data"]["current"]
    assert scan["status"] == "PENDING" and scan["trigger"] == "MANUAL"
    # A second click joins the scan already waiting.
    assert client.post("/api/v1/reports/mailbox/scan").json()["data"]["current"]["id"] == scan["id"]

    monkeypatch.setattr(imap_probe, "ingest_once", lambda: {"ingested": 3, "duplicates": 0, "failed": 1})
    assert imap_probe.run_pending_scan() is True
    assert imap_probe.run_pending_scan() is False

    status = client.get("/api/v1/reports/mailbox").json()["data"]
    assert status["current"] is None
    assert status["last"]["id"] == scan["id"]
    assert (status["last"]["status"], status["last"]["ingested"], status["last"]["failed"]) == ("DONE", 3, 1)


def test_failed_and_lost_scans_are_reported(monkeypatch) -> None:
    _clear()
    monkeypatch.setattr(get_settings(), "report_imap_enabled", True)

    def refuse() -> dict[str, int]:
        raise TimeoutError("mail server did not answer")

    monkeypatch.setattr(imap_probe, "ingest_once", refuse)
    imap_probe.run_scan(None)
    last = client.get("/api/v1/reports/mailbox").json()["data"]["last"]
    assert (last["trigger"], last["status"], last["error_code"]) == ("SCHEDULED", "FAILED", "TimeoutError")

    # A request no worker picked up stops blocking new ones.
    lost = client.post("/api/v1/reports/mailbox/scan").json()["data"]["current"]["id"]
    with get_session() as session:
        session.get(MailboxScan, lost).created_at = datetime.now(timezone.utc) - timedelta(minutes=10)
        session.commit()
    again = client.post("/api/v1/reports/mailbox/scan").json()["data"]
    assert again["current"]["id"] != lost
    assert again["last"]["id"] == lost and again["last"]["error_code"] == "WORKER_UNAVAILABLE"
    mailbox_scan_service.finish(again["current"]["id"], stats={})


def test_project_owner_cannot_scan_the_mailbox() -> None:
    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.post("/api/v1/reports/mailbox/scan").status_code == 403
    assert owner.get("/api/v1/reports/mailbox").status_code == 403
