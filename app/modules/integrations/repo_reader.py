"""Reading one file from a project's main repository (ADR-0063, ADR-0080). Nothing here writes.

GitLab: the separate read token `GITLAB_REPO_READ_TOKEN` when one is still set, else the company GitLab token saved on
a screen (scope read_repository). GitHub: `GITHUB_REPO_READ_TOKEN_<NAME>` (or `GITHUB_REPO_READ_TOKEN`) when set, else
the project's own token saved on a screen (permission Contents: Read)."""
from __future__ import annotations

import base64
import os
import re
from urllib.parse import quote

import httpx

from app.modules.integrations import github, gitlab_connection

GITHUB_API = "https://api.github.com"
TOKEN_NAME = re.compile(r"^GITHUB_TOKEN_[A-Z0-9_]+$")
# Tried in turn when the token may read files but not the project record (read_repository without read_api).
DEFAULT_BRANCHES = ("main", "master", "develop")


class RepoReadError(RuntimeError):
    def __init__(self, code: str, transient: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.transient = transient


def _decode(content: str) -> str:
    return base64.b64decode(content.encode("ascii")).decode("utf-8", errors="replace")


async def read_gitlab_file(project_path: str, path: str) -> tuple[str, str]:
    """The file's text and its blob id on the project's default branch."""
    base_url, token = gitlab_connection.read_token()
    if not base_url or not token:
        raise RepoReadError("GITLAB_READ_NOT_CONFIGURED")
    headers = {"PRIVATE-TOKEN": token}
    encoded = quote(project_path, safe="")
    file_url = f"/api/v4/projects/{encoded}/repository/files/{quote(path, safe='')}"
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        try:
            project = await client.get(f"/api/v4/projects/{encoded}", headers=headers)
            if project.status_code == 404:
                raise RepoReadError("GITLAB_PROJECT_NOT_FOUND")
            if project.status_code in (401, 403):
                # A token with only read_repository may not read the project record, yet reads files: try the usual
                # branch names in turn, so the token stays as narrow as it is.
                refs = DEFAULT_BRANCHES
            else:
                project.raise_for_status()
                refs = (str(project.json().get("default_branch") or "main"),)
            response = None
            for ref in refs:
                response = await client.get(file_url, params={"ref": ref}, headers=headers)
                if response.status_code != 404:
                    break
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RepoReadError("GITLAB_UNAVAILABLE", transient=True) from exc
        except httpx.HTTPStatusError as exc:
            raise RepoReadError("GITLAB_UNAVAILABLE", transient=exc.response.status_code >= 500) from exc
    if response is None or response.status_code == 404:
        raise RepoReadError("CONTEXT_FILE_MISSING")
    if response.status_code in (401, 403):
        raise RepoReadError("GITLAB_READ_FORBIDDEN")
    if response.status_code >= 500:
        raise RepoReadError("GITLAB_UNAVAILABLE", transient=True)
    if response.status_code != 200:
        raise RepoReadError("GITLAB_READ_REJECTED")
    body = response.json()
    return _decode(str(body.get("content") or "")), str(body.get("blob_id") or body.get("last_commit_id") or "")


def _github_token(token_ref: str) -> str:
    """The read token that pairs with the project's issue token name: GITHUB_TOKEN_X reads with GITHUB_REPO_READ_TOKEN_X."""
    suffix = token_ref[len("GITHUB_TOKEN_"):] if TOKEN_NAME.match(token_ref or "") else ""
    for name in ([f"GITHUB_REPO_READ_TOKEN_{suffix}"] if suffix else []) + ["GITHUB_REPO_READ_TOKEN"]:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    # One token per customer, saved on a screen (ADR-0076), reads the file too when it has Contents: Read (ADR-0080).
    stored = github._stored_token(token_ref) if suffix else None
    if stored:
        return stored
    raise RepoReadError("GITHUB_READ_NOT_CONFIGURED")


async def read_github_file(token_ref: str, repository: str, path: str) -> tuple[str, str]:
    token = _github_token(token_ref)
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    async with httpx.AsyncClient(base_url=GITHUB_API, timeout=30) as client:
        try:
            response = await client.get(f"/repos/{repository}/contents/{path}", headers=headers)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RepoReadError("GITHUB_UNAVAILABLE", transient=True) from exc
    if response.status_code == 404:
        raise RepoReadError("CONTEXT_FILE_MISSING")
    if response.status_code in (401, 403):
        raise RepoReadError("GITHUB_READ_FORBIDDEN")
    if response.status_code >= 500:
        raise RepoReadError("GITHUB_UNAVAILABLE", transient=True)
    if response.status_code != 200:
        raise RepoReadError("GITHUB_READ_REJECTED")
    body = response.json()
    if not isinstance(body, dict) or body.get("type") != "file":
        raise RepoReadError("CONTEXT_FILE_MISSING")
    return _decode(str(body.get("content") or "").replace("\n", "")), str(body.get("sha") or "")


async def read_context_file(repo: dict[str, str], path: str) -> tuple[str, str]:
    if repo["system"] == "GITLAB":
        return await read_gitlab_file(repo["target"], path)
    return await read_github_file(repo.get("token_ref", ""), repo["target"], path)
