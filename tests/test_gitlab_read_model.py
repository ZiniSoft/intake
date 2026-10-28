import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import GitLabIssueSnapshot, Project
from app.modules.integrations import adapters as adapter_module
from app.modules.integrations.adapters import GitLabAdapter
from app.modules.planning.gitlab_read_model import gitlab_read_model_service


client = TestClient(app, headers={"X-User-Subject": "cto"})


def _project_id() -> str:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        assert project is not None
        return str(project.id)


def test_gitlab_adapter_lists_all_issue_pages(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requested_pages: list[str] = []

    def client_factory(**kwargs):
        async def handler(request: httpx.Request) -> httpx.Response:
            page = request.url.params["page"]
            requested_pages.append(page)
            headers = {"X-Next-Page": "2" if page == "1" else ""}
            return httpx.Response(200, json=[{"id": int(page), "iid": int(page), "title": f"Issue {page}"}], headers=headers)

        return real_client(
            base_url=kwargs["base_url"], timeout=kwargs["timeout"], transport=httpx.MockTransport(handler)
        )

    monkeypatch.setattr(adapter_module.httpx, "AsyncClient", client_factory)
    adapter = GitLabAdapter()
    adapter.settings = SimpleNamespace(gitlab_base_url="https://gitlab.test", gitlab_token="secret")
    issues = asyncio.run(adapter.list_all_issues("2026/orbit-platform"))
    assert [issue["iid"] for issue in issues] == [1, 2]
    assert requested_pages == ["1", "2"]


def test_gitlab_read_model_history_conflict_and_cto_acceptance() -> None:
    project_id = _project_id()
    member_response = client.post(
        "/api/v1/planning/members",
        json={
            "display_name": "GitLab Read Test",
            "email_reference": "gitlab-read@example.test",
            "project_mappings": [{
                "project_id": project_id,
                "gitlab_user_external_id": "88",
                "role": "Developer",
            }],
        },
    )
    assert member_response.status_code == 201, member_response.text
    member = member_response.json()["data"]

    issue = {
        "id": 9001,
        "iid": 501,
        "title": "Carry over official GitLab work",
        "state": "opened",
        "labels": ["priority:p1", "type:task"],
        "assignees": [{"id": 88, "name": "GitLab Read Test"}],
        "milestone": {"id": 9, "title": "Pilot"},
        "due_date": "2026-10-09",
        "web_url": "https://gitlab.test/2026/orbit-platform/-/issues/501",
        "updated_at": "2026-10-08T10:00:00Z",
    }
    first_refresh = gitlab_read_model_service.replace_project_snapshot(
        project_id, [issue], fetched_at=datetime(2026, 10, 8, 23, 45, tzinfo=timezone.utc)
    )
    assert first_refresh["created"] == 1
    repeated = gitlab_read_model_service.replace_project_snapshot(
        project_id, [issue], fetched_at=datetime(2026, 10, 8, 23, 50, tzinfo=timezone.utc)
    )
    assert repeated["unchanged"] == 1

    report_body = """BÁO CÁO NGÀY
Ngày: 2026-10-08 | Nhân sự: GitLab Read Test | Tổng thời gian: 4 giờ
=== ORBIT | Orbit ===
[DONE] Carry over official GitLab work | Thời gian: 4 giờ | Tiến độ: 100%
Tham chiếu: GitLab #501 | Plane: Không có | Intake: Không có
Kết quả:
- Email says done but GitLab remains open
"""
    report = client.post(
        "/api/v1/reports/daily/ingest",
        json={
            "mailbox": "report@example.test",
            "uid_validity": "read-model-test",
            "uid": "501",
            "message_id": "<read-model-501@example.test>",
            "sender_address": "gitlab-read@example.test",
            "subject": "DAILY REPORT | 2026-10-08 | GitLab Read Test | ORBIT",
            "body": report_body,
            "received_at": "2026-10-08T10:00:00Z",
        },
    )
    assert report.status_code == 201, report.text

    planning = client.post(
        "/api/v1/planning/runs",
        json={"plan_date": "2026-10-09", "project_ids": [project_id]},
    )
    assert planning.status_code == 201, planning.text
    run = planning.json()["data"]
    assert run["status"] == "REVIEW_REQUIRED"
    assert len(run["assignments"]) == 1
    assert run["assignments"][0]["slot"] == "MORNING"
    assert run["assignments"][0]["planned_hours"] == 4
    assert all(item["gitlab_issue_external_id"] == "501" for item in run["assignments"])
    assert all(item["proposed_priority"] == "P1" for item in run["assignments"])
    assert all(item["approved_priority"] is None for item in run["assignments"])
    assert any(warning["code"] == "EMAIL_DONE_GITLAB_OPEN" for warning in run["warnings"])

    accepted = client.post(
        f"/api/v1/planning/runs/{run['id']}/accept-proposals",
        json={"expected_version": run["version"]},
    )
    assert accepted.status_code == 200, accepted.text
    accepted_run = accepted.json()["data"]
    assert accepted_run["version"] == run["version"] + 1
    assert all(item["approved_priority"] == "P1" for item in accepted_run["assignments"])
    assert all(item["approved_assignee_external_id"] == "88" for item in accepted_run["assignments"])

    approved = client.post(
        f"/api/v1/planning/runs/{run['id']}/approve",
        json={"expected_version": accepted_run["version"], "acknowledged_warning_ids": []},
    )
    assert approved.status_code == 202, approved.text
    assert len(approved.json()["data"]["jobs"]) == 1

    changed_issue = {**issue, "state": "closed", "updated_at": "2026-10-09T08:00:00Z"}
    changed = gitlab_read_model_service.replace_project_snapshot(project_id, [changed_issue])
    assert changed["created"] == 1
    with get_session() as session:
        history = session.scalars(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.project_id == project_id,
            GitLabIssueSnapshot.issue_external_id == "501",
        )).all()
        assert len(history) == 2
        assert sum(row.is_current for row in history) == 1
