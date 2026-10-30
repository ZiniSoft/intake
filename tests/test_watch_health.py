"""Every twelve hours Intake checks that the scanning flow outside is delivering, and warns when it is not (FR-CNT-13)."""
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditEvent, WatchCheck, WatchContact
from app.modules.watch.service import watch_service
from app.queue.celery_app import celery_app
from app.workers import planning_tasks
from tests.test_private_space import cto
from tests.test_watch_flow import KEY, WATCH, _signed, flow, watch  # noqa: F401  (the fixture)

HEALTH = f"{WATCH}/health"
DEMAND = f"{WATCH}/demand?track=business"


def _track(data: dict, name: str = "business") -> dict:
    return next(row for row in data["tracks"] if row["track"] == name)


def test_a_track_short_of_signals_with_none_arriving_is_a_warning_with_its_cause(watch, monkeypatch) -> None:  # noqa: F811
    # Earlier tests called the flow's routes: start from a scanner that has never been heard from.
    with get_session() as session:
        session.execute(delete(WatchCheck))
        session.execute(delete(WatchContact))
        session.commit()
    try:
        quiet = cto.post(f"{HEALTH}/check").json()["data"]
        assert _track(quiet)["checked_at"] is None and not _track(quiet)["warning"], "a track that asked for nothing is not checked"

        assert cto.put(DEMAND, json={"wanted_per_week": 2, "weekday": 7, "time": "20:00", "lookback_days": 7}).status_code == 200

        # The cause named is the first one that explains the silence.
        monkeypatch.setattr(get_settings(), "watch_webhook_secret", "")
        closed = _track(cto.post(f"{HEALTH}/check").json()["data"])
        assert (closed["warning"], closed["reason"], closed["remaining"]) == (True, "ROUTES_CLOSED", 2)
        monkeypatch.setattr(get_settings(), "watch_webhook_secret", "khoa-ky-tin-hieu-chi-dung-trong-test-12")  # gitleaks:allow - synthetic test credential
        assert _track(cto.post(f"{HEALTH}/check").json()["data"])["reason"] == "NO_SOURCES"
        source = cto.post(f"{WATCH}/sources", json={"url": "https://blog.example.com/feed", "track": "business"}).json()["data"]
        assert _track(cto.post(f"{HEALTH}/check").json()["data"])["reason"] == "NO_KEYWORDS"
        cto.put(f"{WATCH}/keywords?track=business", json={"pillars": {"AI trong vận hành": ["chatbot trả lời khách"]}})
        silent = cto.post(f"{HEALTH}/check").json()["data"]
        assert _track(silent)["reason"] == "FLOW_SILENT" and silent["last_config_at"] is None
        assert flow.get("/api/v1/watch/config", headers={"Authorization": f"Bearer {KEY}"}).status_code == 200
        calling = cto.post(f"{HEALTH}/check").json()["data"]
        assert _track(calling)["reason"] == "NOTHING_SENT" and calling["last_config_at"] and calling["last_signal_at"] is None
        assert not _track(calling, "technical")["warning"] and _track(calling, "technical")["checked_at"] is None

        # A signal coming in clears the warning at once, without waiting for the next check.
        sent = flow.post("/api/v1/watch/signals", **_signed({"items": [{"url": "https://blog.example.com/bai-ve", "title": "Một bài quét về", "source_id": source["id"]}]}))
        assert sent.json()["data"]["accepted"] == 1
        cleared = cto.get(HEALTH).json()["data"]
        assert not _track(cleared)["warning"] and cleared["last_signal_at"]
        fine = _track(cto.post(f"{HEALTH}/check").json()["data"])
        assert (fine["warning"], fine["reason"], fine["received_in_check"], fine["remaining"]) == (False, None, 1, 1)

        # Thirteen hours on with nothing new, still one short: a warning again.
        later = datetime.now(timezone.utc) + timedelta(hours=13)
        assert watch_service.check(True, now=later) == [{"track": "business", "status": "WARNING", "reason": "FLOW_SILENT", "received": 0, "remaining": 1}]
        assert _track(cto.get(HEALTH).json()["data"])["warning"] is True

        # Enough for the week: silence is no longer a problem.
        cto.put(DEMAND, json={"wanted_per_week": 1, "weekday": 7, "time": "20:00", "lookback_days": 7})
        assert watch_service.check(True, now=later + timedelta(hours=12))[0]["status"] == "OK"
        assert _track(cto.get(HEALTH).json()["data"])["warning"] is False

        # The scheduled task runs the same check, twice a day, twelve hours apart.
        assert planning_tasks.check_watch_health()["checked"] == 1
        schedule = celery_app.conf.beat_schedule["watch-health-check-12h"]
        assert schedule["task"] == "intake.watch.health-check" and schedule["schedule"].hour == {7, 19}
        with get_session() as session:
            warned = session.scalars(select(AuditEvent).where(AuditEvent.event_type == "watch.check_warning")).all()
        assert {row.details["reason"] for row in warned} >= {"ROUTES_CLOSED", "NO_SOURCES", "NO_KEYWORDS", "FLOW_SILENT", "NOTHING_SENT"}

        owner = TestClient(app, headers={"X-User-Subject": "owner.private"})
        assert owner.get(HEALTH).status_code in (401, 403) and owner.post(f"{HEALTH}/check").status_code in (401, 403)
    finally:
        cto.put(DEMAND, json={"wanted_per_week": 0, "weekday": 7, "time": "20:00", "lookback_days": 7})
        with get_session() as session:
            session.execute(delete(WatchCheck))
            session.execute(delete(WatchContact))
            session.commit()
