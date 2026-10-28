"""The repo-reader against GitLab (ADR-0063): a token with only read_repository cannot read the project record (403 on
GET /projects/:id) but can read files, so the reader tries the usual branch names; a wrong token still says so."""
import asyncio
import base64
import json

import httpx
import pytest

from app.config import get_settings
from app.modules.integrations import repo_reader


@pytest.fixture
def gitlab(monkeypatch):
    """A fake GitLab behind httpx: the handler decides per path; the token comes from the environment like on the server."""
    monkeypatch.setenv("GITLAB_REPO_READ_TOKEN", "fixture-gitlab-read-token")
    monkeypatch.setenv("GITLAB_BASE_URL", "https://gitlab.test")
    get_settings.cache_clear()
    calls: list[str] = []
    original = httpx.AsyncClient

    def install(handler):
        def transport_handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.raw_path.decode())
            assert request.headers.get("PRIVATE-TOKEN") == "fixture-gitlab-read-token"
            return handler(request)
        monkeypatch.setattr(repo_reader.httpx, "AsyncClient", lambda **kw: original(transport=httpx.MockTransport(transport_handler), **kw))
        return calls

    yield install
    get_settings.cache_clear()


def _file(text: str) -> httpx.Response:
    return httpx.Response(200, json={"content": base64.b64encode(text.encode()).decode(), "blob_id": "blob123"})


def test_a_read_repository_token_reads_the_file_without_the_project_record(gitlab) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.raw_path.decode() == "/api/v4/projects/2026%2Fember-platform":
            return httpx.Response(403, json={"message": "403 Forbidden"})
        if "repository/files" in request.url.raw_path.decode():
            return _file("## 1. Sản phẩm\n- a\n") if request.url.params.get("ref") == "master" else httpx.Response(404, json={"message": "404 File Not Found"})
        return httpx.Response(500)

    calls = gitlab(handler)
    text, sha = asyncio.run(repo_reader.read_gitlab_file("2026/ember-platform", "docs/agent/CONTEXT.md"))
    assert text.startswith("## 1.") and sha == "blob123"
    assert [c for c in calls if "ref=" in c] == [
        "/api/v4/projects/2026%2Fember-platform/repository/files/docs%2Fagent%2FCONTEXT.md?ref=main",
        "/api/v4/projects/2026%2Fember-platform/repository/files/docs%2Fagent%2FCONTEXT.md?ref=master",
    ], "main first, then master; develop never needed"


def test_the_default_branch_is_used_when_the_token_may_read_it(gitlab) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.raw_path.decode() == "/api/v4/projects/2026%2Forbit-platform":
            return httpx.Response(200, json={"default_branch": "release"})
        if "repository/files" in request.url.raw_path.decode() and request.url.params.get("ref") == "release":
            return _file("x")
        return httpx.Response(404, json={})

    calls = gitlab(handler)
    assert asyncio.run(repo_reader.read_gitlab_file("2026/orbit-platform", "docs/agent/CONTEXT.md"))[1] == "blob123"
    assert sum("ref=" in c for c in calls) == 1


def test_missing_file_wrong_token_and_missing_project_each_have_their_code(gitlab) -> None:
    def forbidden_everywhere(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "403 Forbidden"})

    gitlab(forbidden_everywhere)
    with pytest.raises(repo_reader.RepoReadError) as error:
        asyncio.run(repo_reader.read_gitlab_file("2026/ember-platform", "docs/agent/CONTEXT.md"))
    assert error.value.code == "GITLAB_READ_FORBIDDEN"

    def no_file_on_any_branch(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403) if request.url.raw_path.decode().endswith("ember-platform") else httpx.Response(404, json={})

    gitlab(no_file_on_any_branch)
    with pytest.raises(repo_reader.RepoReadError) as error:
        asyncio.run(repo_reader.read_gitlab_file("2026/ember-platform", "docs/agent/CONTEXT.md"))
    assert error.value.code == "CONTEXT_FILE_MISSING"

    gitlab(lambda request: httpx.Response(404, json={"message": "404 Project Not Found"}))
    with pytest.raises(repo_reader.RepoReadError) as error:
        asyncio.run(repo_reader.read_gitlab_file("2026/nope", "docs/agent/CONTEXT.md"))
    assert error.value.code == "GITLAB_PROJECT_NOT_FOUND"
