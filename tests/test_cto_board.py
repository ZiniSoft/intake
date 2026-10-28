"""What reaches the CTO: approval routing, overdue marks, the people view, the CTO's time meter, and how far prod
is behind main (FR-APR-14, FR-PLAN-27, FR-PLAN-28, FR-UI-15, ADR-0052)."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AuditEvent, User
from app.modules.changelog import changelog, entries_behind
from app.modules.intake.routing import approval_owner, projects_with_owner
from app.modules.planning.overview import LOCAL_TZ, _sittings_minutes

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
NOW = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)


def test_who_decides_a_waiting_request() -> None:
    fresh = NOW - timedelta(hours=2)
    assert approval_owner(project_has_owner=True, priority="P2", waiting_since=fresh, now=NOW) == ("PO", False)
    assert approval_owner(project_has_owner=True, priority="P1", waiting_since=fresh, now=NOW) == ("CTO", False)
    assert approval_owner(project_has_owner=False, priority="P3", waiting_since=fresh, now=NOW) == ("CTO", False)
    assert approval_owner(project_has_owner=True, priority="P3", waiting_since=NOW - timedelta(hours=25), now=NOW) == ("CTO", True)


def test_the_queue_says_whose_a_request_is_and_the_cto_can_ask_for_their_part() -> None:
    created = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "MANUAL", "raw_text": f"Việc nhỏ cho đội {uuid4().hex[:6]}"})
    intake = created.json()["data"]
    reviewed = cto.patch(f"/api/v1/intakes/{intake['id']}/review", json={
        "normalized_title": "Việc nhỏ", "normalized_summary": "Đội tự quyết", "suggested_priority": "P3", "proposed_route": "GITLAB", "expected_version": intake["version"],
    })
    assert reviewed.status_code == 200, reviewed.text
    try:
        with get_session() as session:
            owned = projects_with_owner(session)
        rows = cto.get("/api/v1/approvals?limit=100").json()["data"]["items"]
        mine = next(row for row in rows if row["id"] == intake["id"])
        assert mine["approval_overdue"] is False
        assert mine["approval_owner"] == ("PO" if mine["project_id"] in owned else "CTO")
        only_cto = cto.get("/api/v1/approvals?limit=100&owner=CTO").json()["data"]["items"]
        assert all(row["approval_owner"] == "CTO" for row in only_cto)
        assert cto.get("/api/v1/approvals?limit=100&owner=NOBODY").status_code == 422
    finally:
        cto.delete(f"/api/v1/intakes/{intake['id']}")


def test_sittings_merge_close_actions_and_a_lone_action_still_counts() -> None:
    base = NOW
    assert _sittings_minutes([]) == 0
    assert _sittings_minutes([base]) == 2
    assert _sittings_minutes([base, base + timedelta(minutes=3), base + timedelta(minutes=6), base + timedelta(minutes=40)]) == 8
    assert _sittings_minutes([base + timedelta(minutes=30), base]) == 4


def test_the_board_counts_overdue_work_and_times_the_cto_but_not_the_owner() -> None:
    today_local = datetime.now(timezone.utc).astimezone(LOCAL_TZ).date()
    base = datetime.combine(today_local, time(8, 0), tzinfo=LOCAL_TZ)
    with get_session() as session:
        cto_user = session.scalar(select(User).where(User.auth_subject == "cto"))
        ids = []
        for stamp in [base, base + timedelta(minutes=3), base + timedelta(minutes=6), base + timedelta(minutes=40)]:
            event = AuditEvent(id=str(uuid4()), actor_type="USER", actor_id=str(cto_user.id), event_type="test.cto-click", entity_type="test", created_at=stamp)
            session.add(event)
            ids.append(event.id)
        session.commit()
    try:
        shown = cto.get(f"/api/v1/planning/overview/{today_local.isoformat()}").json()["data"]
        assert shown["cto_time"] is not None and shown["cto_time"]["today_minutes"] >= 8, shown["cto_time"]
        assert shown["cto_time"]["actions_today"] >= 4 and shown["cto_time"]["avg7_minutes"] >= 1 and len(shown["cto_time"]["days"]) == 7
        assert shown["overdue_total"] >= 0
        for row in shown["projects"]:
            assert set(row["overdue"]) == {"approvals", "waiting", "work_log", "p0_open"}
            assert {"pending", "urgent", "cto", "po", "overdue", "has_owner"} <= set(row["approvals"])
            assert row["approvals"]["cto"] + row["approvals"]["po"] == row["approvals"]["pending"]
        theirs = owner.get(f"/api/v1/planning/overview/{today_local.isoformat()}").json()["data"]
        assert theirs["cto_time"] is None
    finally:
        with get_session() as session:
            for event_id in ids:
                row = session.get(AuditEvent, event_id)
                if row is not None:
                    session.delete(row)
            session.commit()


def test_people_view_is_the_ctos_and_sums_hours_across_projects() -> None:
    day = (date.today() + timedelta(days=1)).isoformat()
    shown = cto.get(f"/api/v1/planning/people/{day}")
    assert shown.status_code == 200, shown.text
    data = shown.json()["data"]
    assert data["plan_date"] == day and isinstance(data["people"], list)
    for person in data["people"]:
        assert person["state"] in ("OVER", "FREE", "OK", "OFF")
        assert abs(sum(row["hours"] for row in person["projects"]) - person["planned_hours"]) < 0.01
        if person["state"] == "OVER":
            assert person["planned_hours"] > person["available_hours"]
    # A Project Owner gets the view too, limited to the people on their teams (FR-PLAN-28, 2026-10-15).
    theirs = owner.get(f"/api/v1/planning/people/{day}")
    assert theirs.status_code == 200, theirs.text
    assert theirs.json()["data"]["people"] == [], "this owner has no project, so no people"


def test_the_changelog_says_how_far_the_running_build_is_behind(monkeypatch) -> None:
    entries = changelog(include_cto=True)["entries"]
    with_hash = [row for row in entries if row["commits"]]
    assert len(with_hash) >= 2
    # Two commits in one push may share a hash; the running build is behind everything above the first entry with it.
    first_index = lambda sha: next(index for index, row in enumerate(entries) if sha in row["commits"])
    for row in with_hash[:3]:
        sha = row["commits"][0]
        assert entries_behind(entries, sha) == first_index(sha)
        assert entries_behind(entries, sha[:7]) == first_index(sha)
    assert entries_behind(entries, "0000000") is None and entries_behind(entries, "dev") is None
    sha = with_hash[1]["commits"][0]
    monkeypatch.setattr(get_settings(), "git_sha", sha)
    assert changelog(include_cto=True)["behind"] == first_index(sha)
    assert changelog(include_cto=False)["behind"] is None
    assert cto.get("/api/v1/changelog").json()["data"]["behind"] == first_index(sha)
