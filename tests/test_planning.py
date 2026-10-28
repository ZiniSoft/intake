from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import OutboxEvent, PlanningApprovalSnapshot, PlanningSyncJob, Project
from app.modules.planning.service import planning_service


client = TestClient(app, headers={"X-User-Subject": "cto"})


def _create_member() -> dict:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        assert project is not None
        project_id = str(project.id)
    response = client.post(
        "/api/v1/planning/members",
        json={
            "display_name": "Planning Test Member",
            "email_reference": "planning-test@example.test",
            "project_mappings": [
                {
                    "project_id": project_id,
                    "gitlab_user_external_id": "42",
                    "role": "Developer",
                }
            ],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_weekday_and_weekend_capacity_defaults_and_ot_override() -> None:
    member = _create_member()
    weekday = client.get("/api/v1/planning/capacities/2026-10-02")
    assert weekday.status_code == 200
    weekday_row = next(item for item in weekday.json()["data"] if item["member_id"] == member["id"])
    assert weekday_row["base_hours"] == 8
    assert weekday_row["available_hours"] == 8
    assert weekday_row["version"] == 0

    weekend = client.get("/api/v1/planning/capacities/2026-10-03")
    weekend_row = next(item for item in weekend.json()["data"] if item["member_id"] == member["id"])
    assert weekend_row["base_hours"] == 0
    assert weekend_row["available_hours"] == 0

    missing_reason = client.put(
        f"/api/v1/planning/capacities/2026-10-03/{member['id']}",
        json={"expected_version": 0, "override_hours": 4, "support_hours": 1},
    )
    assert missing_reason.status_code == 422
    assert missing_reason.json()["error"] == "OVERRIDE_REASON_REQUIRED"

    updated = client.put(
        f"/api/v1/planning/capacities/2026-10-03/{member['id']}",
        json={
            "expected_version": 0,
            "override_hours": 4,
            "support_hours": 1,
            "reason": "OT release",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["available_hours"] == 3
    assert updated.json()["data"]["version"] == 1


def test_planning_assignment_wip_and_approval_create_one_job_per_issue() -> None:
    members = client.get("/api/v1/planning/members").json()["data"]
    member = next(item for item in members if item["email_reference"] == "planning-test@example.test")
    project_id = member["project_mappings"][0]["project_id"]
    first = client.post(
        "/api/v1/planning/runs",
        json={"plan_date": "2026-10-02", "project_ids": [project_id]},
    )
    assert first.status_code == 201, first.text
    run = first.json()["data"]
    repeated = client.post(
        "/api/v1/planning/runs",
        json={"plan_date": "2026-10-02", "project_ids": [project_id]},
    )
    assert repeated.json()["data"]["id"] == run["id"]

    missing_issue = client.post(
        f"/api/v1/planning/runs/{run['id']}/assignments",
        json={
            "expected_run_version": run["version"],
            "project_id": project_id,
            "member_id": member["id"],
            "slot": "MORNING",
            "work_type": "DEVELOPMENT",
            "is_primary": True,
            "planned_hours": 3,
            "source_type": "MANUAL",
            "source_reference": "quick-add",
        },
    )
    assert missing_issue.status_code == 422
    assert missing_issue.json()["error"] == "GITLAB_ISSUE_REQUIRED"

    morning = client.post(
        f"/api/v1/planning/runs/{run['id']}/assignments",
        json={
            "expected_run_version": run["version"],
            "project_id": project_id,
            "member_id": member["id"],
            "slot": "MORNING",
            "work_type": "DEVELOPMENT",
            "is_primary": True,
            "planned_hours": 3,
            "source_type": "GITLAB",
            "source_reference": "GL#125",
            "gitlab_issue_external_id": "125",
            "approved_priority": "P1",
            "approved_milestone_external_id": "9",
            "approved_due_date": "2026-10-02",
        },
    )
    assert morning.status_code == 201, morning.text
    run_after_morning = client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]
    assert run_after_morning["version"] == 2

    second_primary = client.post(
        f"/api/v1/planning/runs/{run['id']}/assignments",
        json={
            "expected_run_version": 2,
            "project_id": project_id,
            "member_id": member["id"],
            "slot": "AFTERNOON",
            "work_type": "DEVELOPMENT",
            "is_primary": True,
            "planned_hours": 2,
            "source_type": "GITLAB",
            "source_reference": "GL#126",
            "gitlab_issue_external_id": "126",
        },
    )
    assert second_primary.status_code == 422
    assert second_primary.json()["error"] == "MULTIPLE_PRIMARY_DOING"

    duplicate_issue = client.post(
        f"/api/v1/planning/runs/{run['id']}/assignments",
        json={
            "expected_run_version": 2,
            "project_id": project_id,
            "member_id": member["id"],
            "slot": "AFTERNOON",
            "work_type": "DEVELOPMENT",
            "is_primary": True,
            "planned_hours": 2,
            "source_type": "GITLAB",
            "source_reference": "GL#125",
            "gitlab_issue_external_id": "125",
            "approved_priority": "P1",
            "approved_milestone_external_id": "9",
            "approved_due_date": "2026-10-02",
        },
    )
    assert duplicate_issue.status_code == 422
    assert duplicate_issue.json()["error"] == "ISSUE_ALREADY_PLANNED"

    approved = client.post(
        f"/api/v1/planning/runs/{run['id']}/approve",
        json={"expected_version": 2, "acknowledged_warning_ids": []},
    )
    assert approved.status_code == 202, approved.text
    approval_data = approved.json()["data"]
    assert approval_data["status"] == "SYNCING"
    assert len(approval_data["jobs"]) == 1
    assert approval_data["jobs"][0]["gitlab_issue_external_id"] == "125"

    repeated_approval = client.post(
        f"/api/v1/planning/runs/{run['id']}/approve",
        json={"expected_version": 2, "acknowledged_warning_ids": []},
    )
    assert repeated_approval.status_code == 202
    assert repeated_approval.json()["data"]["snapshot_id"] == approval_data["snapshot_id"]

    with get_session() as session:
        snapshots = session.scalars(
            select(PlanningApprovalSnapshot).where(PlanningApprovalSnapshot.planning_run_id == run["id"])
        ).all()
        jobs = session.scalars(
            select(PlanningSyncJob).where(PlanningSyncJob.planning_snapshot_id == snapshots[0].id)
        ).all()
        events = session.scalars(
            select(OutboxEvent).where(OutboxEvent.event_type == "planning.gitlab-update.requested.v1")
        ).all()
        assert len(snapshots) == 1
        assert len(jobs) == 1
        assert len([event for event in events if event.aggregate_id == jobs[0].id]) == 1

    job_id = approval_data["jobs"][0]["id"]
    sync_status = client.get(f"/api/v1/planning/runs/{run['id']}/sync-jobs")
    assert sync_status.status_code == 200, sync_status.text
    assert sync_status.json()["data"]["snapshot_id"] == approval_data["snapshot_id"]
    assert sync_status.json()["data"]["jobs"][0]["status"] == "PENDING"

    planning_service.fail_sync(job_id, "TEST_GITLAB_FAILURE")
    failed_status = client.get(f"/api/v1/planning/runs/{run['id']}/sync-jobs")
    assert failed_status.status_code == 200, failed_status.text
    failed_job = failed_status.json()["data"]["jobs"][0]
    assert failed_job["status"] == "FAILED"
    assert failed_job["error_code"] == "TEST_GITLAB_FAILURE"

    retried = client.post(f"/api/v1/planning/runs/{run['id']}/sync-jobs/{job_id}/retry")
    assert retried.status_code == 202, retried.text
    assert retried.json()["data"]["status"] == "PENDING"
    assert retried.json()["data"]["error_code"] is None

    repeated_retry = client.post(f"/api/v1/planning/runs/{run['id']}/sync-jobs/{job_id}/retry")
    assert repeated_retry.status_code == 422
    assert repeated_retry.json()["error"] == "PLANNING_SYNC_NOT_RETRYABLE"

    with get_session() as session:
        retry_events = session.scalars(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == job_id,
                OutboxEvent.dedupe_key.like("planning-sync-retry:%"),
            )
        ).all()
        assert len(retry_events) == 1


def test_project_owner_cannot_approve_planning() -> None:
    owner_client = TestClient(app, headers={"X-User-Subject": "project-owner"})
    response = owner_client.post(
        "/api/v1/planning/runs",
        json={"plan_date": "2026-10-05", "project_ids": []},
    )
    # A Project Owner without a project has no plan to open; a plan over every project is the CTO's.
    assert response.status_code == 404
