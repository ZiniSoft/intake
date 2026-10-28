from datetime import date, datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import GitLabIssueSnapshot, Project


client = TestClient(app, headers={"X-User-Subject": "cto"})


def test_unified_quick_add_creates_intake_and_promotes_only_with_gitlab_issue() -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        assert project is not None
        project_id = str(project.id)

    member_response = client.post(
        "/api/v1/planning/members",
        json={
            "display_name": "Quick Add Test",
            "email_reference": "quick-add-test@example.test",
            "project_mappings": [{
                "project_id": project_id,
                "gitlab_user_external_id": "99001",
                "role": "Developer",
            }],
        },
    )
    assert member_response.status_code == 201, member_response.text
    member = member_response.json()["data"]

    run_response = client.post(
        "/api/v1/planning/runs",
        json={"plan_date": "2026-11-03", "project_ids": [project_id]},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()["data"]

    form_payload = {
        "expected_run_version": run["version"],
        "mode": "FORM",
        "project_id": project_id,
        "title": "Urgent customer fix",
        "content": "Reported during the morning planning meeting.",
        "channel": "MEETING",
        "requested_hours": 2,
        "target_slot": "MORNING",
    }
    form = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add",
        headers={"Idempotency-Key": "quick-add-form-2026-11-03"},
        json=form_payload,
    )
    assert form.status_code == 201, form.text
    form_candidate = form.json()["data"]
    assert form_candidate["source_type"] == "FORM"
    assert form_candidate["status"] == "PENDING_TRIAGE"
    assert form_candidate["intake_id"] is not None

    replay = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add",
        headers={"Idempotency-Key": "quick-add-form-2026-11-03"},
        json=form_payload,
    )
    assert replay.status_code == 201
    assert replay.json()["data"]["id"] == form_candidate["id"]

    paste = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add",
        json={
            "expected_run_version": run["version"] + 1,
            "mode": "PASTE",
            "project_id": project_id,
            "content": "Chat request: investigate intermittent login failure",
            "channel": "ZALO",
        },
    )
    assert paste.status_code == 201, paste.text
    assert paste.json()["data"]["status"] == "PENDING_TRIAGE"
    assert paste.json()["data"]["intake_id"] is not None

    missing_gitlab = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add/{form_candidate['id']}/promote",
        json={
            "expected_run_version": run["version"] + 2,
            "member_id": member["id"],
            "slot": "MORNING",
            "planned_hours": 2,
        },
    )
    assert missing_gitlab.status_code == 422
    assert missing_gitlab.json()["error"] == "GITLAB_ISSUE_REQUIRED"

    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(GitLabIssueSnapshot(
            id="39b298f8-3b1c-49e3-9d44-bc18ec8f3cef",
            project_id=project_id,
            issue_external_id="99001",
            global_external_id="199001",
            title="Official GitLab urgent customer fix",
            state="opened",
            labels=["priority:p1"],
            assignee_external_ids=["99001"],
            milestone_external_id="77",
            milestone_title="Pilot",
            due_date=date(2026, 11, 3),
            web_url="https://gitlab.test/orbit/-/issues/99001",
            payload_hash="quick-add-gitlab-99001",
            is_current=True,
            fetched_at=now,
            last_seen_at=now,
            created_at=now,
        ))
        session.commit()

    existing = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add",
        json={
            "expected_run_version": run["version"] + 2,
            "mode": "EXISTING",
            "project_id": project_id,
            "source_system": "GITLAB",
            "reference": "#99001",
            "requested_hours": 2,
            "target_slot": "MORNING",
        },
    )
    assert existing.status_code == 201, existing.text
    gitlab_candidate = existing.json()["data"]
    assert gitlab_candidate["status"] == "READY"
    assert gitlab_candidate["proposed_priority"] == "P1"

    promoted = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add/{gitlab_candidate['id']}/promote",
        json={
            "expected_run_version": run["version"] + 3,
            "member_id": member["id"],
            "slot": "MORNING",
            "planned_hours": 2,
        },
    )
    assert promoted.status_code == 200, promoted.text
    promoted_candidate = promoted.json()["data"]
    assert promoted_candidate["status"] == "ASSIGNED"
    assert promoted_candidate["assignment_id"] is not None

    linked_form = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add/{form_candidate['id']}/promote",
        json={
            "expected_run_version": run["version"] + 4,
            "member_id": member["id"],
            "gitlab_issue_external_id": "99001",
            "slot": "AFTERNOON",
            "planned_hours": 2,
        },
    )
    # INT-26W44-001: the Issue is already in the plan, so the waiting entry joins that line instead of being refused.
    assert linked_form.status_code == 200, linked_form.text
    merged = linked_form.json()["data"]
    assert merged["status"] == "ASSIGNED" and merged["assignment_id"] == promoted_candidate["assignment_id"]

    final_run = client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]
    # Requests other tests left synced in this project wait here too (FR-PLAN-21); count what this test added.
    assert len([row for row in final_run["candidates"] if not (row["summary"] or "").startswith("Yêu cầu Intake đã có Issue")]) == 3
    assert len(final_run["assignments"]) == 1
    assert all(item["approved_priority"] is None for item in final_run["assignments"])
    assert all(item["proposed_priority"] == "P1" for item in final_run["assignments"])

    # Do not let this synthetic read-model row generate proposals in unrelated tests.
    with get_session() as session:
        snapshot = session.scalar(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.issue_external_id == "99001",
            GitLabIssueSnapshot.payload_hash == "quick-add-gitlab-99001",
        ))
        assert snapshot is not None
        snapshot.is_current = False
        session.commit()


def test_project_owner_cannot_use_quick_add() -> None:
    owner_client = TestClient(app, headers={"X-User-Subject": "project-owner"})
    response = owner_client.post(
        "/api/v1/planning/runs/not-accessible/quick-add",
        json={
            "expected_run_version": 1,
            "mode": "PASTE",
            "project_id": "orbit",
            "content": "Not authorized",
        },
    )
    assert response.status_code == 403


def test_plane_cannot_be_used_as_a_new_quick_add_source() -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "ember"))
        assert project is not None
        project_id = str(project.id)
    run_response = client.post(
        "/api/v1/planning/runs",
        json={"plan_date": "2026-11-04", "project_ids": [project_id]},
    )
    assert run_response.status_code == 201, run_response.text
    run = run_response.json()["data"]

    from_plane = client.post(
        f"/api/v1/planning/runs/{run['id']}/quick-add",
        json={
            "expected_run_version": run["version"],
            "mode": "EXISTING",
            "project_id": project_id,
            "source_system": "PLANE",
            "reference": "plane-quick-add-1",
        },
    )
    assert from_plane.status_code == 422
