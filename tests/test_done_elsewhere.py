"""A carried-over entry recorded as done outside the plan (FR-PLAN-34, fix of 2026-10-19): it gets a state of its own
instead of "dismissed", it cannot be restored to the waiting list, and the next day's plan does not carry the Issue
back while the CTO's acceptance is pending."""
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import IssueVerification, PlanningApprovalSnapshot, PlanningAssignment, PlanningCandidate, PlanningRun, PlanningWarning, Project, WorkforceMember, WorkforceProjectMembership
from app.modules.notify import reminders
from app.modules.planning.day_plans import day_plans

cto = TestClient(app, headers={"X-User-Subject": "cto"})
DAYS = ("2031-09-08", "2031-09-09", "2031-09-10")
ISSUE = "813"


def _cleanup(project_id: str, member_id: str) -> None:
    with get_session() as session:
        for run in session.scalars(select(PlanningRun).where(PlanningRun.plan_date.in_([date.fromisoformat(day) for day in DAYS]))).all():
            for model in (PlanningApprovalSnapshot, PlanningWarning, PlanningAssignment, PlanningCandidate):
                for row in session.scalars(select(model).where(model.planning_run_id == run.id)).all():
                    session.delete(row)
            session.delete(run)
        for row in session.scalars(select(IssueVerification).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id == ISSUE)).all():
            session.delete(row)
        for row in session.scalars(select(PlanningWarning).where(PlanningWarning.member_id == member_id)).all():
            session.delete(row)
        for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
            session.delete(row)
        member = session.get(WorkforceMember, member_id)
        if member is not None:
            session.delete(member)
        session.commit()


def test_a_carried_entry_marked_done_stays_out_of_the_plan_and_off_the_dismissed_list() -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Carried Done", "email_reference": f"carried-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424322", "role": "Developer"}],
    }).json()["data"]
    try:
        # Day one: the Issue is placed and never reported done.
        first = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[0], "project_ids": [project_id]}).json()["data"]
        placed = cto.post(f"/api/v1/planning/runs/{first['id']}/assignments", json={
            "expected_run_version": first["version"], "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 2, "source_type": "GITLAB", "source_reference": f"GL#{ISSUE}",
            "gitlab_issue_external_id": ISSUE, "approved_priority": "P2",
        })
        assert placed.status_code == 201, placed.text
        # Day two: it comes back as a continuation; the CTO records it was done outside the plan.
        second = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[1], "project_ids": [project_id]}).json()["data"]
        carried = next(row for row in second["candidates"] if row["gitlab_issue_external_id"] == ISSUE)
        assert carried["status"] == "READY" and carried["summary"].startswith("Làm tiếp từ")
        done = cto.post(f"/api/v1/planning/runs/{second['id']}/candidates/{carried['id']}/done", json={"note": "Tường làm xong hôm qua, quên báo"})
        assert done.status_code == 200, done.text
        assert done.json()["data"]["status"] == "DONE_ELSEWHERE", "its own state, not the dismissed one"
        again = cto.get(f"/api/v1/planning/runs/{second['id']}").json()["data"]
        states = {row["gitlab_issue_external_id"]: row["status"] for row in again["candidates"]}
        assert states[ISSUE] == "DONE_ELSEWHERE"
        restored = cto.post(f"/api/v1/planning/runs/{second['id']}/candidates/{carried['id']}/restore")
        assert restored.status_code == 422 and "CANDIDATE_DONE_ELSEWHERE" in restored.text, "there is no way back to the waiting list"
        assert cto.post(f"/api/v1/planning/runs/{second['id']}/candidates/{carried['id']}/dismiss").status_code == 422
        with get_session() as session:
            pending = session.scalar(select(IssueVerification).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id == ISSUE, IssueVerification.decision == "PENDING"))
            assert pending is not None and pending.source == "PLAN"
        # Day three: the Issue is still open on the tracker and the day-one assignment is still not "done", yet the
        # plan does not carry it back while the CTO's acceptance is pending.
        third = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[2], "project_ids": [project_id]}).json()["data"]
        assert all(row["gitlab_issue_external_id"] != ISSUE for row in third["candidates"]), [row["gitlab_issue_external_id"] for row in third["candidates"]]
        # On the screen it is neither waiting nor dismissed: the day-two run keeps it under its own state only.
        kept = cto.get(f"/api/v1/planning/runs/{second['id']}").json()["data"]
        assert [row["status"] for row in kept["candidates"] if row["gitlab_issue_external_id"] == ISSUE] == ["DONE_ELSEWHERE"]
    finally:
        _cleanup(project_id, member["id"])


def test_an_accepted_issue_leaves_daily_planning_even_when_the_tracker_write_failed() -> None:
    """INT-26W43-001 (Issue #21): once the CTO accepted the work, Daily Planning must not show it any more, neither
    under "done outside the plan, waiting for acceptance" nor as waiting work on the next day. Before the fix both
    happened whenever the Issue was still "opened" in the read model, which is the case until the tracker write
    (note + close) succeeds, and for good when it fails."""
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Accepted Gone", "email_reference": f"accepted-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424323", "role": "Developer"}],
    }).json()["data"]
    try:
        first = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[0], "project_ids": [project_id]}).json()["data"]
        placed = cto.post(f"/api/v1/planning/runs/{first['id']}/assignments", json={
            "expected_run_version": first["version"], "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 2, "source_type": "GITLAB", "source_reference": f"GL#{ISSUE}",
            "gitlab_issue_external_id": ISSUE, "approved_priority": "P2",
        })
        assert placed.status_code == 201, placed.text
        second = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[1], "project_ids": [project_id]}).json()["data"]
        carried = next(row for row in second["candidates"] if row["gitlab_issue_external_id"] == ISSUE)
        assert cto.post(f"/api/v1/planning/runs/{second['id']}/candidates/{carried['id']}/done", json={"note": "Tường làm xong hôm qua"}).status_code == 200
        before = cto.get(f"/api/v1/planning/runs/{second['id']}").json()["data"]
        waiting_row = next(row for row in before["candidates"] if row["gitlab_issue_external_id"] == ISSUE)
        assert waiting_row["status"] == "DONE_ELSEWHERE" and waiting_row["accepted_at"] is None, "still waiting for the CTO: shown"

        # The CTO accepts; the write to the tracker fails, so the read model keeps the Issue open.
        with get_session() as session:
            row = session.scalar(select(IssueVerification).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id == ISSUE, IssueVerification.decision == "PENDING"))
            row.decision, row.decided_at, row.sync_status, row.sync_error = "ACCEPTED", datetime.now(timezone.utc), "FAILED", "thử: tracker không nhận"
            session.commit()

        after = cto.get(f"/api/v1/planning/runs/{second['id']}").json()["data"]
        accepted_row = next(row for row in after["candidates"] if row["gitlab_issue_external_id"] == ISSUE)
        assert accepted_row["accepted_at"] is not None, "the screen needs to know the acceptance happened to take the line down"

        # The item placed on day one stays as the day's record, drawn as accepted on every screen and in the bot's line.
        first_again = cto.get(f"/api/v1/planning/runs/{first['id']}").json()["data"]
        placed_row = next(row for row in first_again["assignments"] if row["gitlab_issue_external_id"] == ISSUE)
        assert placed_row["accepted_at"] is not None, "the placed card must say the CTO accepted it"
        board = next(block for block in day_plans(date.fromisoformat(DAYS[0]), None)["projects"] if block["id"] == project_id)
        card = next(item for person in board["people"] for item in person["assignments"] if item["issue"] == ISSUE)
        assert card["accepted_at"] is not None, "the overview card too"
        with get_session() as session:
            text = reminders.plan_private_message(session, session.get(WorkforceMember, member["id"]), date.fromisoformat(DAYS[0]))
        assert "đã nghiệm thu" in text, text

        third = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[2], "project_ids": [project_id]}).json()["data"]
        assert all(row["gitlab_issue_external_id"] != ISSUE for row in third["candidates"]), "accepted work is not offered again"
    finally:
        _cleanup(project_id, member["id"])
