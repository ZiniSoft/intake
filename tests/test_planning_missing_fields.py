"""A plan whose Issue has no milestone or due date closes once the warning was seen (FR-PLAN-20, ADR-0013): the
tracker update then carries only the fields the plan has."""
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import (
    PlanningApprovalSnapshot, PlanningAssignment, PlanningRun, PlanningSyncJob, PlanningWarning, Project, WorkforceMember, WorkforceProjectMembership,
)

client = TestClient(app, headers={"X-User-Subject": "cto"})
EMAIL = "planning-missing-fields@example.test"
# A tracker user id no other test seeds an Issue for, so the morning proposals leave this member alone.
TRACKER_USER = "424299"


def _member() -> dict:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    members = client.get("/api/v1/planning/members").json()["data"]
    existing = next((row for row in members if row["email_reference"] == EMAIL), None)
    if existing:
        return existing
    created = client.post("/api/v1/planning/members", json={
        "display_name": "Missing Fields Member", "email_reference": EMAIL,
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": TRACKER_USER, "role": "Developer"}],
    })
    assert created.status_code == 201, created.text
    return created.json()["data"]


def _cleanup(run_id: str, member_id: str) -> None:
    with get_session() as session:
        for job in session.scalars(select(PlanningSyncJob).join(PlanningApprovalSnapshot, PlanningApprovalSnapshot.id == PlanningSyncJob.planning_snapshot_id).where(PlanningApprovalSnapshot.planning_run_id == run_id)).all():
            session.delete(job)
        for model in (PlanningApprovalSnapshot, PlanningWarning, PlanningAssignment):
            for row in session.scalars(select(model).where(model.planning_run_id == run_id)).all():
                session.delete(row)
        run = session.get(PlanningRun, run_id)
        if run is not None:
            session.delete(run)
        for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
            session.delete(row)
        member = session.get(WorkforceMember, member_id)
        if member is not None:
            session.delete(member)
        session.commit()


def test_a_missing_milestone_is_a_warning_to_see_not_a_wall() -> None:
    member = _member()
    project_id = member["project_mappings"][0]["project_id"]
    opened = client.post("/api/v1/planning/runs", json={"plan_date": "2031-05-06", "project_ids": [project_id]})
    assert opened.status_code == 201, opened.text
    run = opened.json()["data"]
    try:
        placed = client.post(f"/api/v1/planning/runs/{run['id']}/assignments", json={
            "expected_run_version": run["version"], "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 3, "source_type": "GITLAB", "source_reference": "GL#777",
            "gitlab_issue_external_id": "777", "approved_priority": "P2",
        })
        assert placed.status_code == 201, placed.text
        version = client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]["version"]
        with get_session() as session:
            warning = PlanningWarning(
                id=str(uuid4()), planning_run_id=run["id"], assignment_id=None, member_id=member["id"], project_id=project_id,
                code="GITLAB_MILESTONE_MISSING", severity="WARNING", source_values={"gitlab_issue": "777"},
                message="Issue #777 has no milestone; acknowledge before closing the plan", created_at=datetime.now(timezone.utc),
            )
            session.add(warning)
            session.commit()
            warning_id = str(warning.id)
        blocked = client.post(f"/api/v1/planning/runs/{run['id']}/approve", json={"expected_version": version, "acknowledged_warning_ids": []})
        assert blocked.status_code == 422 and blocked.json()["error"] == "WARNING_UNACKNOWLEDGED", blocked.text
        approved = client.post(f"/api/v1/planning/runs/{run['id']}/approve", json={"expected_version": version, "acknowledged_warning_ids": [warning_id]})
        assert approved.status_code == 202, approved.text
        # The warning the closer acknowledged is recorded as seen, like a critical one.
        with get_session() as session:
            seen = session.get(PlanningWarning, warning_id)
            assert seen is not None and seen.acknowledged_at is not None and seen.acknowledged_by is not None
        assert approved.json()["data"]["jobs"][0]["gitlab_issue_external_id"] == "777"
        with get_session() as session:
            job = session.scalar(select(PlanningSyncJob).join(PlanningApprovalSnapshot, PlanningApprovalSnapshot.id == PlanningSyncJob.planning_snapshot_id).where(PlanningApprovalSnapshot.planning_run_id == run["id"]))
            assert job is not None and "milestone_external_id" not in job.after_state and "due_date" not in job.after_state
            assert job.after_state["assignee_external_id"] == TRACKER_USER
    finally:
        _cleanup(run["id"], member["id"])
