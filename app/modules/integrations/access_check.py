"""Which permissions a GitLab or GitHub token has, and which are missing (FR-INTG-23, ADR-0080).

Runs in the integration worker only (it alone holds the tokens). Every call is a read, except one GitHub call that asks
to create an Issue with an empty body: GitHub refuses it with 422 when the token may write Issues and with 403 when it
may not, so nothing is ever created. A check that cannot tell reads as UNKNOWN, never as OK.

Each check is {"key", "status": OK | MISSING | WARN | UNKNOWN, "detail"}; the screen words them from the key.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx

from app.modules.integrations import github
from app.modules.integrations.adapters import GitLabPermanentError, GitLabTransientError
from app.modules.integrations.github import GitHubPermanentError, GitHubTransientError
from app.modules.integrations.gitlab_connection import credentials

EXPIRY_WARNING = timedelta(days=14)
GITLAB_ROLES = {10: "Guest", 15: "Planner", 20: "Reporter", 30: "Developer", 40: "Maintainer", 50: "Owner"}
GITLAB_MIN_ROLE = 20


def _check(key: str, status: str, detail: object | None = None) -> dict[str, object]:
    return {"key": key, "status": status, "detail": None if detail is None else str(detail)}


def _expiry(day: date | None, today: date) -> dict[str, object]:
    if day is None:
        return _check("expires", "OK", "never")
    if day <= today:
        return _check("expires", "MISSING", day.isoformat())
    return _check("expires", "WARN" if day - today <= EXPIRY_WARNING else "OK", day.isoformat())


def _summary(system: str, checks: list[dict[str, object]], **extra: object) -> dict[str, object]:
    return {"system": system, "ok": not any(row["status"] == "MISSING" for row in checks), "checks": checks, **extra}


async def gitlab_access(project_path: str | None = None, *, today: date | None = None) -> dict[str, object]:
    """Scopes api and read_repository, the expiry date and, with a project, at least the Reporter role on it."""
    current = credentials()
    if not current.token or not current.base_url:
        raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
    today = today or datetime.now(timezone.utc).date()
    headers = {"PRIVATE-TOKEN": current.token}
    checks: list[dict[str, object]] = []
    extra: dict[str, object] = {"source": current.source, "base_url": current.base_url}
    async with httpx.AsyncClient(base_url=current.base_url, timeout=20) as client:
        try:
            me = await client.get("/api/v4/personal_access_tokens/self", headers=headers)
            if me.status_code == 401:
                checks.append(_check("token_valid", "MISSING"))
                return _summary("GITLAB", checks, **extra)
            checks.append(_check("token_valid", "OK"))
            body = me.json() if me.status_code == 200 else {}
            if me.status_code == 200 and isinstance(body, dict) and isinstance(body.get("scopes"), list):
                scopes = {str(scope) for scope in body["scopes"]}
                checks.append(_check("scope_api", "OK" if "api" in scopes else "MISSING"))
                checks.append(_check("scope_read_repository", "OK" if "read_repository" in scopes or "write_repository" in scopes else "MISSING"))
                raw = str(body.get("expires_at") or "")[:10]
                checks.append(_expiry(date.fromisoformat(raw) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw) else None, today))
            elif me.status_code == 403:
                # A token that can only read the repository is refused by every API call.
                checks.append(_check("scope_api", "MISSING"))
                checks.append(_check("scope_read_repository", "UNKNOWN"))
                return _summary("GITLAB", checks, **extra)
            else:
                checks.append(_check("scope_api", "UNKNOWN"))
                checks.append(_check("scope_read_repository", "UNKNOWN"))
            if project_path:
                project = await client.get(f"/api/v4/projects/{quote(project_path, safe='')}", headers=headers)
                if project.status_code == 404:
                    checks.append(_check("project_found", "MISSING", project_path))
                elif project.status_code == 200:
                    checks.append(_check("project_found", "OK", project_path))
                    checks.append(_gitlab_role(project.json()))
                else:
                    checks.append(_check("project_found", "UNKNOWN", f"HTTP {project.status_code}"))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
    return _summary("GITLAB", checks, **extra)


def _gitlab_role(body: object) -> dict[str, object]:
    permissions = body.get("permissions") if isinstance(body, dict) else None
    levels = [
        int((permissions.get(kind) or {}).get("access_level") or 0)
        for kind in ("project_access", "group_access") if isinstance(permissions, dict) and isinstance(permissions.get(kind), dict)
    ]
    if not levels:
        # GitLab leaves this empty for an administrator, and some versions for inherited access.
        return _check("project_role", "UNKNOWN")
    level = max(levels)
    name = GITLAB_ROLES.get(level, str(level))
    return _check("project_role", "OK" if level >= GITLAB_MIN_ROLE else "MISSING", name)


def _org_policy(response: httpx.Response) -> bool:
    """GitHub's refusal when an organization limits fine-grained tokens (for example their lifetime)."""
    try:
        message = str((response.json() or {}).get("message") or "")
    except ValueError:
        return False
    return response.status_code == 403 and "forbids access via a fine-grained personal access token" in message


def _write_refusal(response: httpx.Response, repo: dict[str, object], read_ok: bool) -> str | None:
    """Why a token that may not write Issues usually got that way, for the screen's hint (ADR-0080 note)."""
    if _org_policy(response):
        return "org_policy"
    if not read_ok:
        return None
    # A public repository is readable by any token: "Public repositories" access, an Issues permission added under
    # Organizations instead of Repositories, and a token awaiting the organization's approval all look like this.
    return "public_read_only" if repo.get("private") is False else "read_only"


def _github_expiry(response: httpx.Response, today: date) -> dict[str, object]:
    raw = (response.headers.get("github-authentication-token-expiration") or "")[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return _check("expires", "OK", "never")
    return _expiry(date.fromisoformat(raw), today)


async def github_access(token_ref: str, repository: str, *, today: date | None = None) -> dict[str, object]:
    """Metadata (the repository is visible), Issues read and write, Contents read, and the expiry date."""
    if not github.REPOSITORY.match(repository or ""):
        raise GitHubPermanentError("GITHUB_REPOSITORY_INVALID")
    headers = github._headers(token_ref)
    today = today or datetime.now(timezone.utc).date()
    checks: list[dict[str, object]] = []
    extra: dict[str, object] = {"token_ref": token_ref, "repository": repository}
    async with httpx.AsyncClient(base_url=github.GITHUB_API, timeout=20) as client:
        try:
            repo = await client.get(f"/repos/{repository}", headers=headers)
            if repo.status_code == 401:
                checks.append(_check("token_valid", "MISSING"))
                return _summary("GITHUB", checks, **extra)
            if repo.status_code >= 500 or repo.status_code == 429:
                raise GitHubTransientError(f"GITHUB_HTTP_{repo.status_code}")
            checks.append(_check("token_valid", "OK"))
            if repo.status_code != 200:
                # A fine-grained token that was not given this repository sees it as missing.
                checks.append(_check("metadata", "MISSING", "org_policy" if _org_policy(repo) else repository))
                return _summary("GITHUB", checks, **extra)
            checks.append(_check("metadata", "OK", repository))
            parsed = repo.json()
            body = parsed if isinstance(parsed, dict) else {}
            if body.get("has_issues") is False:
                checks.append(_check("issues_enabled", "MISSING"))
            issues = await client.get(f"/repos/{repository}/issues", params={"per_page": 1, "state": "all"}, headers=headers)
            checks.append(_check("issues_read", "OK" if issues.status_code == 200 else "MISSING" if issues.status_code in (403, 404) else "UNKNOWN"))
            # An empty body is refused before anything is created: 422 means the token may write Issues.
            write = await client.post(f"/repos/{repository}/issues", json={}, headers=headers)
            if write.status_code in (403, 404):
                checks.append(_check("issues_write", "MISSING", _write_refusal(write, body, issues.status_code == 200)))
            else:
                checks.append(_check("issues_write", "OK" if write.status_code == 422 else "UNKNOWN"))
            contents = await client.get(f"/repos/{repository}/contents/", headers=headers)
            if contents.status_code == 200:
                checks.append(_check("contents_read", "OK"))
            elif contents.status_code == 404 and int(body.get("size") or 0) == 0:
                checks.append(_check("contents_read", "UNKNOWN", "empty"))
            else:
                checks.append(_check("contents_read", "MISSING" if contents.status_code in (403, 404) else "UNKNOWN"))
            checks.append(_github_expiry(repo, today))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitHubTransientError("GITHUB_UNAVAILABLE") from exc
    return _summary("GITHUB", checks, **extra)
