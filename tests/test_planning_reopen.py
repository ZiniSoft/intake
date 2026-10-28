"""A closed plan reopened as a new revision (FR-PLAN-18, ADR-0059): the old one stays and is superseded, work and
what people reported on it carry over, a running GitLab sync blocks the reopen, and closing again writes only the
Issues that changed."""
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import (
    PlanningApprovalSnapshot, PlanningAssignment, PlanningCandidate, PlanningRun, PlanningSyncJob, PlanningWarning, Project, WorkforceMember,
    WorkforceProjectMembership,
)

client = TestClient(app, headers={"X-User-Subject": "cto"})
TRACKER_USER = "424295"
DATE = date(2031, 5, 22)


def _cleanup(member_id: str) -> None:
    with get_session() as session:
        runs = session.scalars(select(PlanningRun).where(PlanningRun.plan_date == DATE)).all()
        for run in runs:
            for snapshot in session.scalars(select(PlanningApprovalSnapshot).where(PlanningApprovalSnapshot.planning_run_id == run.id)).all():
                for job in session.scalars(select(PlanningSyncJob).where(PlanningSyncJob.planning_snapshot_id == snapshot.id)).all():
                    session.delete(job)
                session.delete(snapshot)
            for model in (PlanningWarning, PlanningCandidate, PlanningAssignment):
                for row in session.scalars(select(model).where(model.planning_run_id == run.id)).all():
                    session.delete(row)
        # newest revision first, so the foreign key to the superseded run is released
        for run in sorted(runs, key=lambda row: -row.revision):
            session.delete(run)
        for row in session.scalars(select(PlanningWarning).where(PlanningWarning.member_id == member_id)).all():
            session.delete(row)
        for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
            session.delete(row)
        member = session.get(WorkforceMember, member_id)
        if member is not None:
            session.delete(member)
        session.commit()


def _place(run: dict, project_id: str, member_id: str, issue: str, slot: str, primary: bool = True) -> dict:
    placed = client.post(f"/api/v1/planning/runs/{run['id']}/assignments", json={
        "expected_run_version": run["version"], "project_id": project_id, "member_id": member_id, "slot": slot,
        "work_type": "DEVELOPMENT", "is_primary": primary, "planned_hours": 2, "source_type": "GITLAB", "source_reference": f"GL#{issue}",
        "gitlab_issue_external_id": issue, "approved_priority": "P2",
    })
    assert placed.status_code == 201, placed.text
    return placed.json()["data"]


def test_a_closed_plan_reopens_as_a_new_revision_and_closing_again_writes_only_what_changed() -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    member = client.post("/api/v1/planning/members", json={
        "display_name": "Reopen Member", "email_reference": f"reopen-{uuid4().hex[:6]}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": TRACKER_USER, "role": "Developer"}],
    }).json()["data"]
    try:
        opened = client.post("/api/v1/planning/runs", json={"plan_date": DATE.isoformat(), "project_ids": [project_id]})
        assert opened.status_code == 201, opened.text
        run = opened.json()["data"]
        _place(run, project_id, member["id"], "780", "MORNING")
        run = client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]
        # An open plan is edited in place, not reopened.
        refused = client.post(f"/api/v1/planning/runs/{run['id']}/reopen", json={"expected_version": run["version"]})
        assert refused.status_code == 422 and "PLANNING_RUN_OPEN" in refused.text, refused.text
        closed = client.post(f"/api/v1/planning/runs/{run['id']}/approve", json={"expected_version": run["version"], "acknowledged_warning_ids": [w["id"] for w in run["warnings"]]})
        assert closed.status_code == 202, closed.text
        assert [job["gitlab_issue_external_id"] for job in closed.json()["data"]["jobs"]] == ["780"]
        run = client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]
        assert run["status"] == "SYNCING"
        # The sync of Issue 780 is still running: wait.
        waiting = client.post(f"/api/v1/planning/runs/{run['id']}/reopen", json={"expected_version": run["version"]})
        assert waiting.status_code == 422 and "PLANNING_SYNC_IN_PROGRESS" in waiting.text, waiting.text
        with get_session() as session:
            for job in session.scalars(select(PlanningSyncJob).where(PlanningSyncJob.gitlab_issue_external_id == "780")).all():
                job.status = "SUCCEEDED"
            stored = session.scalar(select(PlanningRun).where(PlanningRun.id == run["id"]))
            stored.status = "SYNCED"
            assignment = session.scalar(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run["id"]))
            assignment.work_status, assignment.work_status_at, assignment.work_status_note = "IN_PROGRESS", datetime.now(timezone.utc), "đang làm"
            session.commit()

        # Reopen: a new revision with the work and what was reported on it; the old plan is superseded and readable.
        reopened = client.post(f"/api/v1/planning/runs/{run['id']}/reopen", json={"expected_version": run["version"]})
        assert reopened.status_code == 201, reopened.text
        fresh = reopened.json()["data"]
        assert fresh["id"] != run["id"] and fresh["revision"] == 2 and fresh["supersedes_run_id"] == run["id"] and fresh["status"] == "REVIEW_REQUIRED"
        assert len(fresh["assignments"]) == 1 and fresh["assignments"][0]["gitlab_issue_external_id"] == "780"
        assert fresh["assignments"][0]["work_status"] == "IN_PROGRESS" and fresh["assignments"][0]["work_status_note"] == "đang làm"
        assert fresh["assignments"][0]["approved_assignee_external_id"] == TRACKER_USER
        old = client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]
        assert old["status"] == "SUPERSEDED" and len(old["assignments"]) == 1
        assert "PLANNING_RUN_SUPERSEDED" in client.post(f"/api/v1/planning/runs/{run['id']}/reopen", json={"expected_version": old["version"]}).text
        # The day now points at the new revision.
        same = client.post("/api/v1/planning/runs", json={"plan_date": DATE.isoformat(), "project_ids": [project_id]}).json()["data"]
        assert same["id"] == fresh["id"]

        # Change the plan: one more Issue. Closing again writes only that one; 780 is as GitLab already has it.
        _place(fresh, project_id, member["id"], "781", "AFTERNOON", primary=False)
        fresh = client.get(f"/api/v1/planning/runs/{fresh['id']}").json()["data"]
        closed_again = client.post(f"/api/v1/planning/runs/{fresh['id']}/approve", json={"expected_version": fresh["version"], "acknowledged_warning_ids": [w["id"] for w in fresh["warnings"]]})
        assert closed_again.status_code == 202, closed_again.text
        assert [job["gitlab_issue_external_id"] for job in closed_again.json()["data"]["jobs"]] == ["781"]
        with get_session() as session:
            jobs = session.scalars(select(PlanningSyncJob).where(PlanningSyncJob.gitlab_issue_external_id.in_(["780", "781"]))).all()
            assert sorted((job.gitlab_issue_external_id, job.status) for job in jobs) == [("780", "SUCCEEDED"), ("781", "PENDING")]
    finally:
        _cleanup(member["id"])
