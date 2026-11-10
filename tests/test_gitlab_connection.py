"""FR-INTG-22, FR-INTG-23 (ADR-0080): the company GitLab connected on a screen, one token for writing and reading
files, and a check that names the missing permissions."""
import asyncio
import base64
from datetime import date, datetime, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import GithubToken, GitlabConnection, Project, ProjectIntegration
from app.modules.integrations import access_check, gitlab_connection, repo_reader
from app.modules.integrations.adapters import GitLabAdapter
from app.modules.projects import management
from app.workers import integration_tasks

cto = TestClient(app, headers={"X-User-Subject": "cto"})
URL = "/api/v1/integrations/gitlab-connection"
VALUE = "glpat-" + "zt3stz0123456789abcd" + "WXYZ"
GH_NAME = "GITHUB_TOKEN_ZTEST_ACCESS"


def _mappings() -> dict[str, tuple[bool, str]]:
    with get_session() as session:
        return {row.id: (row.enabled, row.base_url) for row in session.scalars(select(ProjectIntegration).where(ProjectIntegration.system == "GITLAB")).all()}


@pytest.fixture(autouse=True)
def clean():
    before = _mappings()
    yield
    with get_session() as session:
        row = session.get(GitlabConnection, "default")
        if row is not None:
            session.delete(row)
        token = session.get(GithubToken, GH_NAME)
        if token is not None:
            session.delete(token)
        for mapping in session.scalars(select(ProjectIntegration).where(ProjectIntegration.system == "GITLAB")).all():
            if mapping.id in before:
                mapping.enabled, mapping.base_url = before[mapping.id]
        for project in session.scalars(select(Project).where(Project.code.like("ZTGL%"))).all():
            for mapping in session.scalars(select(ProjectIntegration).where(ProjectIntegration.project_id == project.id)).all():
                session.delete(mapping)
            session.flush()
            session.delete(project)
        session.commit()
    get_settings.cache_clear()


def _test_project(code: str, *, previous: bool) -> str:
    now = datetime.now(timezone.utc)
    project_id = str(uuid4())
    with get_session() as session:
        session.add(Project(id=project_id, code=code, intake_key=code[-4:], name=f"Thử {code}", kind="SOFTWARE", status="ACTIVE",
                            project_settings={}, created_at=now, updated_at=now))
        session.flush()
        config = {"previous": {"system": "GITLAB"}} if previous else {}
        session.add(ProjectIntegration(id=str(uuid4()), project_id=project_id, system="GITLAB", base_url="https://old.test",
                                       project_external_id=None if previous else f"ztest/{code.lower()}", credential_ref="GITLAB_TOKEN",
                                       enabled=False, config=config, created_at=now, updated_at=now))
        session.commit()
    return project_id


def _enabled(project_id: str) -> bool:
    with get_session() as session:
        return bool(session.scalar(select(ProjectIntegration.enabled).where(ProjectIntegration.project_id == project_id)))


def test_saved_connection_hides_the_token_and_wins_over_the_environment(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "env-token-0123456789-abcd")
    monkeypatch.setenv("GITLAB_BASE_URL", "https://env-gitlab.test")
    get_settings.cache_clear()
    assert gitlab_connection.credentials().source == "ENV"
    assert cto.get(URL).json()["data"]["source"] == "ENV"

    response = cto.put(URL, json={"base_url": "https://gitlab.ztest.test/api/v4/", "token": VALUE})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["configured"] and data["base_url"] == "https://gitlab.ztest.test" and data["key_hint"] == "WXYZ"
    assert VALUE not in response.text and VALUE not in cto.get(URL).text
    with get_session() as session:
        assert VALUE not in session.get(GitlabConnection, "default").token_enc

    current = gitlab_connection.credentials()
    assert (current.base_url, current.token, current.source) == ("https://gitlab.ztest.test", VALUE, "APP")
    adapter = GitLabAdapter()
    assert adapter.settings.gitlab_token == VALUE and adapter.settings.gitlab_base_url == "https://gitlab.ztest.test"

    # Only the address changes when no token is sent.
    assert cto.put(URL, json={"base_url": "https://gitlab2.ztest.test"}).status_code == 200
    assert gitlab_connection.credentials().token == VALUE

    assert cto.delete(URL).status_code == 204
    assert gitlab_connection.credentials().source == "ENV"
    assert cto.delete(URL).status_code == 404


def test_validation_and_only_the_cto():
    assert cto.put(URL, json={"base_url": "gitlab.ztest", "token": VALUE}).status_code == 422
    assert cto.put(URL, json={"base_url": "https://gitlab.ztest.test", "token": "short"}).status_code == 422
    assert cto.put(URL, json={"base_url": "https://gitlab.ztest.test"}).status_code == 422
    other = TestClient(app, headers={"X-User-Subject": "owner"})
    assert other.get(URL).status_code in (401, 403)
    assert other.put(URL, json={"base_url": "https://gitlab.ztest.test", "token": VALUE}).status_code in (401, 403)


def test_saving_switches_on_linked_projects_but_not_one_moved_to_github():
    linked = _test_project("ZTGLA", previous=False)
    moved = _test_project("ZTGLB", previous=True)
    response = cto.put(URL, json={"base_url": "https://gitlab.ztest.test", "token": VALUE})
    assert response.status_code == 200 and response.json()["data"]["projects_enabled"] >= 1
    assert _enabled(linked) and not _enabled(moved)


def test_the_repo_reader_reads_with_the_saved_token_unless_a_separate_one_is_set(monkeypatch):
    monkeypatch.delenv("GITLAB_REPO_READ_TOKEN", raising=False)
    get_settings.cache_clear()
    assert cto.put(URL, json={"base_url": "https://gitlab.ztest.test", "token": VALUE}).status_code == 200
    assert gitlab_connection.read_token() == ("https://gitlab.ztest.test", VALUE)
    seen: list[str] = []
    original = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("PRIVATE-TOKEN"))
        if "repository/files" in request.url.raw_path.decode():
            return httpx.Response(200, json={"content": base64.b64encode(b"ok").decode(), "blob_id": "b1"})
        return httpx.Response(200, json={"default_branch": "main"})

    monkeypatch.setattr(repo_reader.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(handler), **kw))
    assert asyncio.run(repo_reader.read_gitlab_file("ztest/x", "docs/agent/CONTEXT.md")) == ("ok", "b1")
    assert set(seen) == {VALUE}

    monkeypatch.setenv("GITLAB_REPO_READ_TOKEN", "separate-read-token-0123456789")
    get_settings.cache_clear()
    assert gitlab_connection.read_token()[1] == "separate-read-token-0123456789"


_ASYNC_CLIENT = httpx.AsyncClient


def _mock(monkeypatch, handler):
    # Built on the real client so a test may mock twice.
    monkeypatch.setattr(access_check.httpx, "AsyncClient", lambda **kw: _ASYNC_CLIENT(transport=httpx.MockTransport(handler), **kw))


def test_gitlab_check_names_a_missing_scope_a_low_role_and_a_near_expiry(monkeypatch):
    assert cto.put(URL, json={"base_url": "https://gitlab.ztest.test", "token": VALUE}).status_code == 200

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET" and request.headers.get("PRIVATE-TOKEN") == VALUE
        path = request.url.raw_path.decode()
        if path.endswith("/personal_access_tokens/self"):
            return httpx.Response(200, json={"scopes": ["api"], "expires_at": "2026-11-15", "active": True})
        if path.startswith("/api/v4/projects/"):
            return httpx.Response(200, json={"permissions": {"project_access": {"access_level": 10}, "group_access": None}})
        return httpx.Response(500)

    _mock(monkeypatch, handler)
    result = asyncio.run(access_check.gitlab_access("ztest/app", today=date(2026, 11, 9)))
    checks = {row["key"]: row for row in result["checks"]}
    assert result["source"] == "APP" and result["ok"] is False
    assert checks["scope_api"]["status"] == "OK" and checks["scope_read_repository"]["status"] == "MISSING"
    assert checks["expires"]["status"] == "WARN" and checks["project_role"] == {"key": "project_role", "status": "MISSING", "detail": "Guest"}


def test_gitlab_check_reports_a_token_that_cannot_call_the_api(monkeypatch):
    assert cto.put(URL, json={"base_url": "https://gitlab.ztest.test", "token": VALUE}).status_code == 200
    _mock(monkeypatch, lambda request: httpx.Response(403, json={"error": "insufficient_scope"}))
    result = asyncio.run(access_check.gitlab_access(None))
    checks = {row["key"]: row["status"] for row in result["checks"]}
    assert checks == {"token_valid": "OK", "scope_api": "MISSING", "scope_read_repository": "UNKNOWN"}


def test_github_check_asks_to_write_without_creating_anything(monkeypatch):
    with get_session() as session:
        session.add(GithubToken(name=GH_NAME, token_enc=__import__("app.services.raw_crypto", fromlist=["x"]).encrypt("ghp_ztest0123456789abcdefWXYZ"), key_hint="WXYZ"))
        session.commit()
    posts: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST":
            posts.append(request.content)
            return httpx.Response(422, json={"message": "Validation Failed"})
        if path == "/repos/ztest/app":
            return httpx.Response(200, json={"full_name": "ztest/app", "has_issues": True, "size": 10},
                                  headers={"github-authentication-token-expiration": "2027-02-01 00:00:00 UTC"})
        if path == "/repos/ztest/app/issues":
            return httpx.Response(200, json=[])
        if path.startswith("/repos/ztest/app/contents"):
            return httpx.Response(403, json={"message": "Resource not accessible by personal access token"})
        return httpx.Response(500)

    _mock(monkeypatch, handler)
    result = asyncio.run(access_check.github_access(GH_NAME, "ztest/app", today=date(2026, 11, 9)))
    checks = {row["key"]: row["status"] for row in result["checks"]}
    assert checks == {"token_valid": "OK", "metadata": "OK", "issues_read": "OK", "issues_write": "OK", "contents_read": "MISSING", "expires": "OK"}
    assert result["ok"] is False and posts == [b"{}"]


def _github_token():
    with get_session() as session:
        session.add(GithubToken(name=GH_NAME, token_enc=__import__("app.services.raw_crypto", fromlist=["x"]).encrypt("ghp_ztest0123456789abcdefWXYZ"), key_hint="WXYZ"))
        session.commit()


def _read_only_handler(private: bool, refusal: str = "Resource not accessible by personal access token"):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(403, json={"message": refusal})
        if request.url.path == "/repos/ztest/app":
            return httpx.Response(200, json={"full_name": "ztest/app", "has_issues": True, "size": 10, "private": private})
        return httpx.Response(200, json=[])
    return handler


def test_github_check_names_the_usual_cause_of_a_read_only_token(monkeypatch):
    # FR-INTG-23: a public repository read but not written usually means "Public repositories" access, an Issues
    # permission added under Organizations, or a token still waiting for the organization's approval.
    _github_token()
    _mock(monkeypatch, _read_only_handler(private=False))
    checks = {row["key"]: row for row in asyncio.run(access_check.github_access(GH_NAME, "ztest/app", today=date(2026, 11, 9)))["checks"]}
    assert checks["issues_read"]["status"] == "OK"
    assert checks["issues_write"] == {"key": "issues_write", "status": "MISSING", "detail": "public_read_only"}

    _mock(monkeypatch, _read_only_handler(private=True))
    checks = {row["key"]: row for row in asyncio.run(access_check.github_access(GH_NAME, "ztest/app", today=date(2026, 11, 9)))["checks"]}
    assert checks["issues_write"] == {"key": "issues_write", "status": "MISSING", "detail": "read_only"}


def test_github_check_names_an_organization_token_policy(monkeypatch):
    _github_token()
    policy = "The 'ztest' organization forbids access via a fine-grained personal access tokens if the token's lifetime is greater than 90 days."
    _mock(monkeypatch, _read_only_handler(private=False, refusal=policy))
    checks = {row["key"]: row for row in asyncio.run(access_check.github_access(GH_NAME, "ztest/app", today=date(2026, 11, 9)))["checks"]}
    assert checks["issues_write"] == {"key": "issues_write", "status": "MISSING", "detail": "org_policy"}

    _mock(monkeypatch, lambda request: httpx.Response(403, json={"message": policy}))
    checks = {row["key"]: row for row in asyncio.run(access_check.github_access(GH_NAME, "ztest/app", today=date(2026, 11, 9)))["checks"]}
    assert checks == {"token_valid": {"key": "token_valid", "status": "OK", "detail": None}, "metadata": {"key": "metadata", "status": "MISSING", "detail": "org_policy"}}


def test_access_probe_runs_in_the_worker(monkeypatch):
    queued: list[str] = []
    monkeypatch.setattr(management, "_publish", queued.append)
    probes = "/api/v1/projects/integration-probes"
    missing = cto.post(probes, json={"system": "GITHUB", "action": "ACCESS", "token_ref": GH_NAME})
    assert missing.status_code == 422, missing.text

    async def fake_access(project_path=None):
        return {"system": "GITLAB", "ok": True, "checks": [{"key": "token_valid", "status": "OK", "detail": None}], "project": project_path}

    monkeypatch.setattr(integration_tasks.access_check, "gitlab_access", fake_access)
    probe = cto.post(probes, json={"system": "GITLAB", "action": "ACCESS"}).json()["data"]
    assert probe["action"] == "ACCESS" and queued == [probe["id"]]
    assert integration_tasks.run_integration_probe(probe["id"]) == "DONE"
    done = cto.get(f"{probes}/{probe['id']}").json()["data"]
    assert done["status"] == "DONE" and done["result"]["ok"] is True and done["result"]["project"] is None
