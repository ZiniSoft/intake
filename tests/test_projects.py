from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AuditEvent, IntegrationProbe, ProjectIntegration
from app.modules.projects import management
from app.modules.projects.management import project_management_service
from app.workers import integration_tasks


client = TestClient(app, headers={"X-User-Subject": "cto"})


def _queue(monkeypatch) -> list[str]:
    """Capture probes instead of publishing them to the broker."""
    queued: list[str] = []
    monkeypatch.setattr(management, "_publish", queued.append)
    return queued


def _checked(monkeypatch, system: str, reference: str, result: dict) -> str:
    """Request a connection check and let the worker answer it with `result`."""
    _queue(monkeypatch)
    probe = client.post("/api/v1/projects/integration-probes", json={"system": system, "action": "CHECK", "reference": reference})
    assert probe.status_code == 202, probe.text
    probe_id = probe.json()["data"]["id"]
    project_management_service.complete_probe(probe_id, result=result)
    return probe_id


def test_idea_project_needs_no_links_and_stays_out_of_planning(monkeypatch) -> None:
    created = client.post("/api/v1/projects", json={
        "name": "  Content   Marketing ", "code": "content-marketing", "intake_key": "cnt", "kind": "IDEA",
    })
    assert created.status_code == 201, created.text
    project = created.json()["data"]
    assert project["name"] == "Content Marketing" and project["intake_key"] == "CNT" and project["kind"] == "IDEA"
    assert "plane_project_id" not in project and project["gitlab_project_id"] is None
    assert any(row["code"] == "content-marketing" for row in client.get("/api/v1/projects").json()["data"])
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "project.created", AuditEvent.entity_id == project["id"],
        )) is not None

    # The new project takes Intakes straight away, with its own key.
    intake = client.post("/api/v1/intakes", json={"project_id": "content-marketing", "channel": "MANUAL", "raw_text": "Ý tưởng bài viết tháng 11"})
    assert intake.status_code in (200, 201), intake.text
    assert intake.json()["data"]["public_id"].startswith("CNT-")

    run = client.post("/api/v1/planning/runs", json={"plan_date": "2026-12-01", "project_ids": ["content-marketing"]})
    assert run.status_code in (409, 422) and "PROJECT_NOT_PLANNABLE" in run.text
    default_run = client.post("/api/v1/planning/runs", json={"plan_date": "2026-12-01", "project_ids": []}).json()["data"]
    assert project["id"] not in default_run["project_ids"]

    assert client.post("/api/v1/projects", json={"name": "X", "code": "content-marketing", "intake_key": "CMX", "kind": "IDEA"}).status_code == 409
    assert client.post("/api/v1/projects", json={"name": "X", "code": "another-one", "intake_key": "CNT", "kind": "IDEA"}).status_code == 409
    assert "PROJECT_CODE_INVALID" in client.post("/api/v1/projects", json={"name": "X", "code": "Bad Code", "intake_key": "BAD", "kind": "IDEA"}).text
    idea_with_gitlab = client.post("/api/v1/projects", json={
        "name": "X", "code": "idea-git", "intake_key": "IDG", "kind": "IDEA", "gitlab_project_path": "2026/idea",
    })
    assert idea_with_gitlab.status_code == 422 and "GITLAB_NOT_ALLOWED_FOR_KIND" in idea_with_gitlab.text


def test_links_are_saved_only_after_a_matching_connection_check(monkeypatch) -> None:
    body = {"name": "Ops Handbook", "code": "ops-handbook", "intake_key": "OPS", "kind": "NON_CODE"}
    created = client.post("/api/v1/projects", json=body)
    assert created.status_code == 201, created.text
    project = created.json()["data"]
    assert "plane_project_id" not in project and project["gitlab_project_id"] is None
    retired = client.post("/api/v1/projects", json={**body, "code": "ops-plane", "intake_key": "OPL", "plane_project_id": "7f0c2c1e-5a0b-4d7e-9a57-0d1f3a6b9c11"})
    assert retired.status_code == 422

    # Growing into a software project requires GitLab; a pasted URL is reduced to the project path.
    assert "DELIVERY_LINK_REQUIRED" in client.patch("/api/v1/projects/ops-handbook", json={"kind": "SOFTWARE"}).text
    gitlab_probe = _checked(monkeypatch, "GITLAB", "https://gitlab.test/2026/ops-handbook.git", {"id": "2026/ops-handbook", "name": "Ops", "url": "https://gitlab.test/2026/ops-handbook"})
    upgraded = client.patch("/api/v1/projects/ops-handbook", json={
        "kind": "SOFTWARE", "gitlab_project_path": "https://gitlab.test/2026/ops-handbook", "gitlab_probe_id": gitlab_probe,
    })
    assert upgraded.status_code == 200, upgraded.text
    data = upgraded.json()["data"]
    assert data["kind"] == "SOFTWARE" and data["gitlab_project_id"] == "2026/ops-handbook" and data["gitlab_project_url"] == "https://gitlab.test/2026/ops-handbook"

    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.post("/api/v1/projects", json=body).status_code == 403
    assert owner.post("/api/v1/projects/integration-probes", json={"system": "PLANE", "action": "LIST"}).status_code == 403


def test_worker_answers_probes_without_storing_more_than_names_and_urls(monkeypatch) -> None:
    queued = _queue(monkeypatch)

    async def fake_gitlab(search=None, path=None):
        if path == "2026/missing":
            raise integration_tasks.GitLabPermanentError("GITLAB_MAPPING_NOT_FOUND")
        rows = [{"id": "2026/content", "name": "2026 / Content", "url": "https://gitlab.test/2026/content"}]
        return rows if not path else rows[:1]

    monkeypatch.setattr(integration_tasks, "gitlab_projects", fake_gitlab)
    listing = client.post("/api/v1/projects/integration-probes", json={"system": "GITLAB", "action": "LIST", "reference": "content"}).json()["data"]
    assert listing["status"] == "PENDING" and queued == [listing["id"]]
    assert integration_tasks.run_integration_probe(listing["id"]) == "DONE"
    done = client.get(f"/api/v1/projects/integration-probes/{listing['id']}").json()["data"]
    assert done["status"] == "DONE" and done["result"] == [{"id": "2026/content", "name": "2026 / Content", "url": "https://gitlab.test/2026/content"}]
    assert integration_tasks.run_integration_probe(listing["id"]) == "SKIPPED"

    missing = client.post("/api/v1/projects/integration-probes", json={"system": "GITLAB", "action": "CHECK", "reference": "2026/missing"}).json()["data"]
    assert integration_tasks.run_integration_probe(missing["id"]) == "FAILED"
    failed = client.get(f"/api/v1/projects/integration-probes/{missing['id']}").json()["data"]
    assert failed["status"] == "FAILED" and failed["error_code"] == "GITLAB_MAPPING_NOT_FOUND" and failed["result"] is None

    def broken(_probe_id: str) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(management, "_publish", broken)
    unavailable = client.post("/api/v1/projects/integration-probes", json={"system": "GITLAB", "action": "LIST"}).json()["data"]
    assert unavailable["status"] == "FAILED" and unavailable["error_code"] == "QUEUE_UNAVAILABLE"
    with get_session() as session:
        assert session.get(IntegrationProbe, unavailable["id"]).completed_at is not None
    assert client.post("/api/v1/projects/integration-probes", json={"system": "PLANE", "action": "CHECK"}).status_code == 422


def test_editing_a_project_respects_kind_rules_and_protected_projects(monkeypatch) -> None:
    created = client.post("/api/v1/projects", json={"name": "Edit Me", "code": "edit-me", "intake_key": "EDM", "kind": "IDEA"})
    assert created.status_code == 201, created.text

    renamed = client.patch("/api/v1/projects/edit-me", json={"name": "  Edited   Name "})
    assert renamed.status_code == 200 and renamed.json()["data"]["name"] == "Edited Name"
    # Since ADR-0066 the kind changes without a Plane link; a rejected change (an unknown kind) leaves the project untouched.
    assert client.patch("/api/v1/projects/edit-me", json={"kind": "BOARD"}).status_code == 422
    assert next(row for row in client.get("/api/v1/projects").json()["data"] if row["code"] == "edit-me")["kind"] == "IDEA"

    upgraded = client.patch("/api/v1/projects/edit-me", json={"kind": "NON_CODE"})
    assert upgraded.status_code == 200 and upgraded.json()["data"]["kind"] == "NON_CODE"
    assert client.patch("/api/v1/projects/edit-me", json={"plane_project_id": "9a1b2c3d-4e5f-4a6b-8c7d-0e1f2a3b4c5d"}).status_code == 422

    paused = client.patch("/api/v1/projects/edit-me", json={"status": "INACTIVE"})
    assert paused.status_code == 200 and paused.json()["data"]["status"] == "INACTIVE"
    assert client.post("/api/v1/meetings", json={"project_id": "edit-me", "source": "MIC"}).status_code in (409, 422)
    assert client.patch("/api/v1/projects/edit-me", json={"status": "ACTIVE"}).json()["data"]["status"] == "ACTIVE"

    assert "PROJECT_SYSTEM_MANAGED" in client.patch("/api/v1/projects/other", json={"status": "INACTIVE"}).text
    assert "PROJECT_SYSTEM_MANAGED" in client.patch("/api/v1/projects/other", json={"kind": "SOFTWARE"}).text
    # The two first pilot projects are linked once at first start; after that their links change here like any other.
    from app.modules.projects.service import project_catalog_service

    before = {row["code"]: row for row in client.get("/api/v1/projects").json()["data"]}["ember"]
    assert before["gitlab_project_id"] == "2026/ember-platform" and "managed_by_env" not in before
    other = _checked(monkeypatch, "GITLAB", "2026/other-repo", {"id": "2026/other-repo", "name": "Other", "url": "https://gitlab.test/2026/other-repo"})
    moved = client.patch("/api/v1/projects/ember", json={"gitlab_project_path": "2026/other-repo", "gitlab_probe_id": other})
    assert moved.status_code == 200, moved.text
    assert moved.json()["data"]["gitlab_project_id"] == "2026/other-repo"
    # A restart keeps the link chosen in Settings.
    project_catalog_service.ensure_database_projects()
    assert {row["code"]: row for row in client.get("/api/v1/projects").json()["data"]}["ember"]["gitlab_project_id"] == "2026/other-repo"
    restore = _checked(monkeypatch, "GITLAB", "2026/ember-platform", {"id": "2026/ember-platform", "name": "Ember", "url": "https://gitlab.example.test/2026/ember-platform"})
    back = client.patch("/api/v1/projects/ember", json={"gitlab_project_path": "2026/ember-platform", "gitlab_probe_id": restore})
    assert back.status_code == 200, back.text
    assert client.patch("/api/v1/projects/nope", json={"name": "X"}).status_code == 404


def test_member_assignments_are_edited_in_place_and_gitlab_users_come_from_a_probe(monkeypatch) -> None:
    queued = _queue(monkeypatch)
    created = client.post("/api/v1/planning/members", json={"display_name": "Settings Person", "email_reference": "settings-person@example.test"})
    assert created.status_code == 201, created.text
    member = created.json()["data"]
    assert member["project_mappings"] == []

    async def fake_members(path):
        assert path == "2026/orbit-platform"
        return [{"id": "77", "name": "Settings Person", "username": "settings.person"}]

    monkeypatch.setattr(integration_tasks, "gitlab_project_members", fake_members)
    probe = client.post("/api/v1/projects/integration-probes", json={"system": "GITLAB", "action": "MEMBERS", "reference": "2026/orbit-platform"}).json()["data"]
    assert queued[-1] == probe["id"] and integration_tasks.run_integration_probe(probe["id"]) == "DONE"
    users = client.get(f"/api/v1/projects/integration-probes/{probe['id']}").json()["data"]["result"]
    assert users == [{"id": "77", "name": "Settings Person", "username": "settings.person"}]
    assert client.post("/api/v1/projects/integration-probes", json={"system": "PLANE", "action": "MEMBERS", "reference": "historical"}).status_code == 422

    body = {"display_name": " Settings   Person ", "email_reference": "Settings-Person@example.test", "default_weekday_hours": 6, "status": "ACTIVE"}
    updated = client.put(f"/api/v1/planning/members/{member['id']}", json={**body, "project_mappings": [
        {"project_id": "orbit", "gitlab_user_external_id": "77", "role": "Developer"}, {"project_id": "other"},
    ]})
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["display_name"] == "Settings Person" and data["email_reference"] == "settings-person@example.test" and data["default_weekday_hours"] == 6
    assert sorted((m["gitlab_user_external_id"] or "-", m["active"]) for m in data["project_mappings"]) == [("-", True), ("77", True)]

    not_software = client.put(f"/api/v1/planning/members/{member['id']}", json={**body, "project_mappings": [{"project_id": "other", "gitlab_user_external_id": "77"}]})
    assert not_software.status_code == 422 and "GITLAB_USER_NOT_APPLICABLE" in not_software.text

    # Leaving a project out switches the assignment off instead of deleting its history.
    removed = client.put(f"/api/v1/planning/members/{member['id']}", json={**body, "status": "INACTIVE", "project_mappings": [{"project_id": "other"}]}).json()["data"]
    assert removed["status"] == "INACTIVE" and sum(m["active"] for m in removed["project_mappings"]) == 1 and len(removed["project_mappings"]) == 2
    assert all(row["id"] != member["id"] for row in client.get("/api/v1/planning/members").json()["data"])
    assert any(row["id"] == member["id"] for row in client.get("/api/v1/planning/members?include_inactive=true").json()["data"])
    assert client.put("/api/v1/planning/members/00000000-0000-4000-8000-00000000dead", json=body).status_code == 404


def _cto_id() -> str:
    from app.models import User

    with get_session() as session:
        return str(session.scalar(select(User.id).where(User.role == "CTO")))


def test_customer_github_is_the_delivery_system_with_its_own_token(monkeypatch) -> None:
    from app.models import ApprovalSnapshot, ExternalLink, GitLabIssueSnapshot, IntakeItem, SyncJob
    from app.modules.integrations import github
    from app.modules.integrations.service import integration_service

    queued = _queue(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN_ACME", "secret-value")
    monkeypatch.setenv("GITHUB_TOKEN_EMPTY", "  ")

    # Token names are listed by the worker; the value never appears anywhere.
    tokens = client.post("/api/v1/projects/integration-probes", json={"system": "GITHUB", "action": "TOKENS"}).json()["data"]
    assert integration_tasks.run_integration_probe(tokens["id"]) == "DONE"
    listed = client.get(f"/api/v1/projects/integration-probes/{tokens['id']}").json()["data"]["result"]
    assert {"id": "GITHUB_TOKEN_ACME", "name": "GITHUB_TOKEN_ACME"} in listed and all(row["id"] != "GITHUB_TOKEN_EMPTY" for row in listed)
    assert "secret-value" not in str(listed)
    assert client.post("/api/v1/projects/integration-probes", json={"system": "GITLAB", "action": "TOKENS"}).status_code == 422
    no_token = client.post("/api/v1/projects/integration-probes", json={"system": "GITHUB", "action": "CHECK", "reference": "acme/shop"})
    assert no_token.status_code == 422 and "GITHUB_TOKEN_NAME_INVALID" in no_token.text

    seen: dict[str, object] = {}

    async def fake_repositories(token_ref, search=None, repository=None):
        seen["check"] = (token_ref, repository)
        return [{"id": "acme/shop", "name": "acme/shop", "url": "https://github.com/acme/shop"}]

    monkeypatch.setattr(github, "repositories", fake_repositories)
    check = client.post("/api/v1/projects/integration-probes", json={
        "system": "GITHUB", "action": "CHECK", "reference": "https://github.com/acme/shop.git", "token_ref": "GITHUB_TOKEN_ACME",
    }).json()["data"]
    assert check["reference"] == "GITHUB_TOKEN_ACME|acme/shop"
    assert integration_tasks.run_integration_probe(check["id"]) == "DONE" and seen["check"] == ("GITHUB_TOKEN_ACME", "acme/shop")

    body = {"name": "Acme Shop", "code": "acme-shop", "intake_key": "ACM", "kind": "SOFTWARE"}
    link = {"github_repository": "acme/shop", "github_token_ref": "GITHUB_TOKEN_ACME", "github_probe_id": check["id"]}
    assert "DELIVERY_LINK_REQUIRED" in client.post("/api/v1/projects", json=body).text
    wrong_token = client.post("/api/v1/projects", json={**body, **link, "github_token_ref": "GITHUB_TOKEN_OTHER"})
    assert wrong_token.status_code == 422 and "GITHUB_LINK_NOT_VERIFIED" in wrong_token.text
    both = client.post("/api/v1/projects", json={**body, **link, "gitlab_project_path": "2026/acme"})
    assert both.status_code == 422 and "DELIVERY_SYSTEM_CONFLICT" in both.text
    created = client.post("/api/v1/projects", json={**body, **link})
    assert created.status_code == 201, created.text
    project = created.json()["data"]
    assert project["delivery_system"] == "GITHUB" and project["github_repository"] == "acme/shop" and project["github_token_ref"] == "GITHUB_TOKEN_ACME"
    assert project["gitlab_project_id"] is None and "secret-value" not in created.text

    # An approved Intake goes to GitHub even when the route was proposed as "GITLAB".
    intake = client.post("/api/v1/intakes", json={"project_id": "acme-shop", "channel": "MANUAL", "raw_text": "Giỏ hàng tính sai phí vận chuyển"}).json()["data"]
    with get_session() as session:
        item = session.get(IntakeItem, intake["id"])
        item.status, item.item_type = "PENDING_APPROVAL", "BUG"
        item.normalized_title, item.normalized_summary = "Giỏ hàng tính sai phí vận chuyển", "Phí vận chuyển sai khi đổi địa chỉ."
        session.commit()
        version = item.version
    approved = client.post(f"/api/v1/intakes/{intake['id']}/approve", json={"approved_route": "GITLAB", "approved_priority": "P1", "expected_version": version})
    assert approved.status_code == 200, approved.text
    assert approved.json()["data"]["approved_route"] == "GITHUB"
    with get_session() as session:
        snapshot = session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.intake_id == intake["id"]))
        assert snapshot.approved_route == "GITHUB"
        snapshot_id = str(snapshot.id)
    integration_service.queue_snapshot(snapshot_id, _cto_id())
    with get_session() as session:
        sync_job = session.scalar(select(SyncJob).where(SyncJob.approval_snapshot_id == snapshot_id))
        assert sync_job.target_system == "GITHUB"
        job_id = str(sync_job.id)

    calls: list[tuple] = []

    async def fake_find(token_ref, repository, public_id):
        calls.append(("find", token_ref, repository))
        return None

    async def fake_create(token_ref, repository, approved_payload):
        calls.append(("create", token_ref, repository, github.build_issue_payload(approved_payload)))
        return {"number": 42, "id": 9001, "html_url": "https://github.com/acme/shop/issues/42"}

    monkeypatch.setattr(github, "find_issue", fake_find)
    monkeypatch.setattr(github, "create_issue", fake_create)
    assert integration_tasks.sync_external.run(job_id) == "SUCCEEDED"
    payload = calls[-1][3]
    assert calls[0] == ("find", "GITHUB_TOKEN_ACME", "acme/shop") and calls[-1][:3] == ("create", "GITHUB_TOKEN_ACME", "acme/shop")
    # The customer reads the repository: no internal priority, labels or acceptance boilerplate.
    assert payload["title"] == "Giỏ hàng tính sai phí vận chuyển" and set(payload) == {"title", "body"}
    assert "P1" not in payload["body"] and "CTO" not in payload["body"] and "Acceptance" not in payload["body"]
    assert payload["body"].startswith("Phí vận chuyển sai khi đổi địa chỉ.") and "intake:ACM-" in payload["body"]
    with get_session() as session:
        external = session.scalar(select(ExternalLink).where(ExternalLink.intake_id == intake["id"]))
        assert external.target_system == "GITHUB" and external.external_id == "42"

    # Issues are read into the planning read model; pull requests are left out.
    rows = [
        {"number": 42, "id": 9001, "title": "Giỏ hàng tính sai phí vận chuyển", "state": "open", "labels": [{"name": "bug"}],
         "assignees": [{"id": 555, "login": "dev"}], "milestone": {"number": 3, "title": "v1", "due_on": "2026-12-20T08:00:00Z"},
         "html_url": "https://github.com/acme/shop/issues/42", "updated_at": "2026-12-01T00:00:00Z"},
        {"number": 43, "id": 9002, "title": "A pull request", "state": "open", "pull_request": {"url": "x"}},
    ]

    async def fake_list(token_ref, repository):
        assert (token_ref, repository) == ("GITHUB_TOKEN_ACME", "acme/shop")
        return [github.as_read_model_issue(row) for row in rows if "pull_request" not in row]

    async def no_gitlab(self, project_path):
        return []

    monkeypatch.setattr(github, "list_all_issues", fake_list)
    monkeypatch.setattr(integration_tasks.GitLabAdapter, "list_all_issues", no_gitlab)
    integration_tasks.refresh_gitlab_read_model.run()
    with get_session() as session:
        issues = session.scalars(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.project_id == project["id"], GitLabIssueSnapshot.is_current.is_(True),
        )).all()
        assert [(row.issue_external_id, row.state, list(row.assignee_external_ids), row.milestone_external_id, str(row.due_date)) for row in issues] == [("42", "opened", ["555"], "3", "2026-12-20")]

    # Planning covers the project, and approving the plan writes nothing back to the customer's repository.
    member = client.post("/api/v1/planning/members", json={"display_name": "Acme Dev", "email_reference": "acme-dev@example.test"}).json()["data"]
    assigned = client.put(f"/api/v1/planning/members/{member['id']}", json={
        "display_name": "Acme Dev", "email_reference": "acme-dev@example.test", "project_mappings": [{"project_id": "acme-shop", "gitlab_user_external_id": "555"}],
    })
    assert assigned.status_code == 200, assigned.text
    created_run = client.post("/api/v1/planning/runs", json={"plan_date": "2026-12-08", "project_ids": ["acme-shop"]})
    assert created_run.status_code in (200, 201), created_run.text
    run = created_run.json()["data"]
    assert {a["gitlab_issue_external_id"] for a in run["assignments"]} == {"42"}
    assert all(w["code"] not in ("GITLAB_MILESTONE_MISSING", "GITLAB_DUE_DATE_MISSING") for w in run["warnings"])
    accepted = client.post(f"/api/v1/planning/runs/{run['id']}/accept-proposals", json={"expected_version": run["version"]})
    assert accepted.status_code == 200, accepted.text
    approval = client.post(f"/api/v1/planning/runs/{run['id']}/approve", json={
        "expected_version": accepted.json()["data"]["version"], "acknowledged_warning_ids": [w["id"] for w in accepted.json()["data"]["warnings"]],
    })
    assert approval.status_code == 202, approval.text
    assert client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]["status"] == "APPROVED"


def test_github_issue_payload_and_token_handling() -> None:
    import os

    import pytest

    from app.modules.integrations import github

    issue = github.as_read_model_issue({"number": 7, "id": 70, "title": "T", "state": "closed", "labels": ["a", {"name": "b"}], "assignees": [], "milestone": None, "html_url": "u"})
    assert issue["iid"] == 7 and issue["state"] == "closed" and issue["labels"] == ["a", "b"] and issue["milestone"] is None and issue["due_date"] is None
    payload = github.build_issue_payload({"approved": True, "title": "[ORB-26W41-001] Sửa lỗi", "description": "Mô tả", "intake_public_id": "ORB-26W41-001", "approved_priority": "P0"})
    assert payload == {"title": "Sửa lỗi", "body": "Mô tả\n\n<!-- intake:ORB-26W41-001 -->"}
    with pytest.raises(ValueError):
        github.build_issue_payload({"approved": False, "title": "x", "intake_public_id": "A"})
    os.environ.pop("GITHUB_TOKEN_MISSING", None)
    for bad in ("GITLAB_TOKEN", "github_token_x", "GITHUB_TOKEN_", "GITHUB_TOKEN_MISSING"):
        with pytest.raises(github.GitHubPermanentError):
            github._headers(bad)


def test_cto_switches_a_gitlab_project_to_github_for_new_work(monkeypatch) -> None:
    from datetime import datetime, timezone
    from uuid import uuid4

    from app.models import GitLabIssueSnapshot, IssueEvidenceLink, IssueVerification
    from app.modules.integrations import github

    code = "switch-gh-test"
    gitlab_probe = _checked(monkeypatch, "GITLAB", "2026/switch-gh-test", {"id": "2026/switch-gh-test", "name": "Switch", "url": "https://gitlab.test/2026/switch-gh-test"})
    created = client.post("/api/v1/projects", json={
        "name": "Thử chuyển GitHub", "code": code, "intake_key": "SWG", "kind": "SOFTWARE",
        "gitlab_project_path": "2026/switch-gh-test", "gitlab_probe_id": gitlab_probe,
    })
    assert created.status_code == 201, created.text
    project_id = created.json()["data"]["id"]
    assert created.json()["data"]["delivery_system"] == "GITLAB"

    # Old GitLab work: one open Issue, one closed and accepted, with its evidence.
    now = datetime.now(timezone.utc)
    with get_session() as session:
        for number, state in (("5", "opened"), ("6", "closed")):
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=project_id, issue_external_id=number, title=f"Việc cũ {number}", state=state,
                labels=[], assignee_external_ids=[], web_url=f"https://gitlab.test/2026/switch-gh-test/-/issues/{number}",
                payload_hash=f"h{number}", is_current=True, fetched_at=now, last_seen_at=now, created_at=now,
            ))
        session.add(IssueVerification(
            id=str(uuid4()), project_id=project_id, issue_external_id="6", evidence_level=2, decision="ACCEPTED", source="CLOSED", created_at=now,
        ))
        session.add(IssueEvidenceLink(
            id=str(uuid4()), project_id=project_id, issue_external_id="6", kind="COMMIT", ref="abc1234", source="WORK_LOG", created_at=now,
        ))
        session.commit()

    preview = client.get(f"/api/v1/projects/{code}/delivery-switch")
    assert preview.status_code == 200, preview.text
    assert preview.json()["data"] == {"from_system": "GITLAB", "to_system": "GITHUB", "open_issues": 1}

    async def fake_repositories(token_ref, search=None, repository=None):
        return [{"id": "acme/switched", "name": "acme/switched", "url": "https://github.com/acme/switched"}]

    _queue(monkeypatch)
    monkeypatch.setenv("GITHUB_TOKEN_SWITCH", "secret-value")
    monkeypatch.setattr(github, "repositories", fake_repositories)
    check = client.post("/api/v1/projects/integration-probes", json={
        "system": "GITHUB", "action": "CHECK", "reference": "acme/switched", "token_ref": "GITHUB_TOKEN_SWITCH",
    }).json()["data"]
    link = {"github_repository": "acme/switched", "github_token_ref": "GITHUB_TOKEN_SWITCH", "github_probe_id": check["id"]}

    # Without the explicit switch the old rule still holds; the check has to pass first.
    assert "DELIVERY_SYSTEM_CONFLICT" in client.patch(f"/api/v1/projects/{code}", json=link).text
    unchecked = client.patch(f"/api/v1/projects/{code}", json={**link, "switch_delivery": "GITHUB"})
    assert unchecked.status_code == 422 and "GITHUB_LINK_NOT_VERIFIED" in unchecked.text
    assert "GITHUB_LINK_REQUIRED" in client.patch(f"/api/v1/projects/{code}", json={"switch_delivery": "GITHUB"}).text
    assert integration_tasks.run_integration_probe(check["id"]) == "DONE"

    switched = client.patch(f"/api/v1/projects/{code}", json={**link, "switch_delivery": "GITHUB"})
    assert switched.status_code == 200, switched.text
    project = switched.json()["data"]
    assert project["delivery_system"] == "GITHUB" and project["github_repository"] == "acme/switched"
    assert project["gitlab_project_id"] is None and project["gitlab_enabled"] is False
    assert project["previous_delivery"]["system"] == "GITLAB"
    assert project["previous_delivery"]["project_external_id"] == "2026/switch-gh-test"
    assert project["previous_delivery"]["project_url"] == "https://gitlab.test/2026/switch-gh-test"
    assert "secret-value" not in switched.text

    with get_session() as session:
        gitlab = session.scalar(select(ProjectIntegration).where(ProjectIntegration.project_id == project_id, ProjectIntegration.system == "GITLAB"))
        assert gitlab.enabled is False and gitlab.project_external_id is None
        # Old Issue numbers move aside so GitHub #5 and #6 never read GitLab's history as their own.
        snapshots = session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.project_id == project_id)).all()
        assert sorted(row.issue_external_id for row in snapshots) == ["gitlab:5", "gitlab:6"]
        assert not any(row.is_current for row in snapshots)
        assert session.scalar(select(IssueVerification.issue_external_id).where(IssueVerification.project_id == project_id)) == "gitlab:6"
        assert session.scalar(select(IssueEvidenceLink.issue_external_id).where(IssueEvidenceLink.project_id == project_id)) == "gitlab:6"
        event = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "project.delivery_switched", AuditEvent.entity_id == project_id))
        assert event is not None and event.details["open_issues"] == 1 and event.details["to"] == "GITHUB"

    # Once on GitHub there is nothing left to switch.
    again = client.patch(f"/api/v1/projects/{code}", json={**link, "switch_delivery": "GITHUB"})
    assert again.status_code == 422 and "DELIVERY_SWITCH_NOT_APPLICABLE" in again.text
    assert "DELIVERY_SWITCH_NOT_APPLICABLE" in client.get(f"/api/v1/projects/{code}/delivery-switch").text

    with get_session() as session:
        for model in (IssueVerification, IssueEvidenceLink, GitLabIssueSnapshot):
            for row in session.scalars(select(model).where(model.project_id == project_id)).all():
                session.delete(row)
        session.commit()
