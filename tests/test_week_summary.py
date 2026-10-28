"""The week page: evening board snapshots and the week in counts (FR-PLAN-29, FR-PLAN-30, ADR-0053)."""
from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import BoardDailySnapshot
from app.modules.planning.snapshot import snapshot_board
from app.modules.planning.week import monday_of, week_summary, week_text

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def _clean(day: date) -> None:
    with get_session() as session:
        for row in session.scalars(select(BoardDailySnapshot).where(BoardDailySnapshot.snapshot_date == day)).all():
            session.delete(row)
        session.commit()


def test_the_evening_snapshot_keeps_one_row_per_project_and_replaces_itself() -> None:
    day = date(2031, 3, 5)   # a day with no plans, far from any seed data
    _clean(day)
    try:
        first = snapshot_board(day)
        assert first["projects"] >= 1
        again = snapshot_board(day)
        assert again["projects"] == first["projects"]
        with get_session() as session:
            rows = session.scalars(select(BoardDailySnapshot).where(BoardDailySnapshot.snapshot_date == day)).all()
            assert len(rows) == first["projects"]
            assert all(row.readiness_state in ("READY", "MISSING", "NO_WORK") for row in rows)
    finally:
        _clean(day)


def test_the_week_is_counted_from_its_monday_and_the_snapshots_feed_it() -> None:
    day = date(2031, 3, 5)   # Wednesday
    _clean(day)
    try:
        snapshot_board(day)
        summary = week_summary(day, None, cto_user_id=None)
        assert summary["week_start"] == monday_of(day) == date(2031, 3, 3) and summary["week_end"] == date(2031, 3, 9)
        assert summary["days_passed"] == 0 and summary["cto_days"] is None
        assert summary["process"]["board_days"] >= 1
        for row in summary["projects"]:
            assert set(row) >= {"hours", "plans", "done", "items", "reports", "requests", "board"}
            assert row["board"]["days"] >= 1
        text = week_text(summary)
        assert text.startswith("Tuần 03/03 - 09/03") and "Quy trình" in text
    finally:
        _clean(day)


def test_the_route_scopes_the_owner_and_times_only_the_cto() -> None:
    monday = monday_of(date.today() - timedelta(days=7))
    mine = cto.get(f"/api/v1/planning/week/{monday.isoformat()}")
    assert mine.status_code == 200, mine.text
    data = mine.json()["data"]
    assert data["week_start"] == monday.isoformat() and data["days_passed"] == 7
    assert data["cto_days"] is not None and len(data["cto_days"]) == 7
    assert data["text"].startswith("Tuần ")
    for person in data["people"]:
        assert abs(sum(row["planned"] for row in person["projects"]) - person["hours"]["planned"]) < 0.11
    theirs = owner.get(f"/api/v1/planning/week/{monday.isoformat()}")
    assert theirs.status_code == 200, theirs.text
    their_data = theirs.json()["data"]
    assert their_data["cto_days"] is None
    assert {row["id"] for row in their_data["projects"]} <= {row["id"] for row in data["projects"]}
    assert len(their_data["projects"]) < len(data["projects"])
    assert owner.post(f"/api/v1/planning/board-snapshots/{monday.isoformat()}").status_code == 403


def test_the_cto_can_write_a_snapshot_by_hand() -> None:
    day = date(2031, 3, 6)
    _clean(day)
    try:
        written = cto.post(f"/api/v1/planning/board-snapshots/{day.isoformat()}")
        assert written.status_code == 200, written.text
        assert written.json()["data"]["snapshot_date"] == day.isoformat()
    finally:
        _clean(day)
