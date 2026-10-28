"""GitHub as the delivery system of a customer's project (ADR-0021).

Each project has its own token, named by an environment variable that only the integration worker
receives. Nothing here is imported by the API process for network calls.
"""
from __future__ import annotations

import os
import re

import httpx

from app.config import get_settings

from app.modules.integrations.description import details_markdown


GITHUB_API = "https://api.github.com"
TOKEN_NAME = re.compile(r"^GITHUB_TOKEN_[A-Z0-9_]{1,40}$")
REPOSITORY = re.compile(r"^[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+$")
PAGE_LIMIT = 20


class GitHubTransientError(RuntimeError):
    pass


class GitHubPermanentError(RuntimeError):
    pass


def issue_marker(public_id: str) -> str:
    return f"<!-- {get_settings().integration_marker_prefix}:{public_id} -->"


def token_names() -> list[str]:
    """Names, never values, of the GitHub tokens this process was given."""
    return sorted(name for name, value in os.environ.items() if TOKEN_NAME.match(name) and value.strip())


def _headers(token_ref: str) -> dict[str, str]:
    if not TOKEN_NAME.match(token_ref or ""):
        raise GitHubPermanentError("GITHUB_TOKEN_NAME_INVALID")
    token = os.environ.get(token_ref, "").strip()
    if not token:
        raise GitHubPermanentError("GITHUB_TOKEN_NOT_FOUND")
    return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def _http_error(response: httpx.Response) -> RuntimeError:
    status_code = response.status_code
    rate_limited = status_code == 429 or (status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0")
    if rate_limited or status_code in (408, 425) or status_code >= 500:
        return GitHubTransientError("GITHUB_RATE_LIMITED" if rate_limited else f"GITHUB_HTTP_{status_code}")
    if status_code in (401, 403):
        return GitHubPermanentError("GITHUB_AUTH_FAILED")
    if status_code in (404, 410):
        return GitHubPermanentError("GITHUB_MAPPING_NOT_FOUND")
    return GitHubPermanentError(f"GITHUB_HTTP_{status_code}")


async def _request(method: str, path: str, token_ref: str, **kwargs) -> httpx.Response:
    headers = _headers(token_ref)
    async with httpx.AsyncClient(base_url=GITHUB_API, timeout=30) as client:
        try:
            response = await client.request(method, path, headers=headers, **kwargs)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitHubTransientError("GITHUB_UNAVAILABLE") from exc
    if response.status_code >= 400:
        raise _http_error(response)
    return response


def _repo(row: dict) -> dict[str, object]:
    return {"id": str(row.get("full_name")), "name": str(row.get("full_name") or ""), "url": row.get("html_url")}


async def repositories(token_ref: str, search: str | None = None, repository: str | None = None) -> list[dict[str, object]]:
    """Repositories the token can reach; with `repository`, exactly that one."""
    if repository:
        if not REPOSITORY.match(repository):
            raise GitHubPermanentError("GITHUB_REPOSITORY_INVALID")
        body = (await _request("GET", f"/repos/{repository}", token_ref)).json()
        return [_repo(body)] if isinstance(body, dict) and body.get("full_name") else []
    body = (await _request("GET", "/user/repos", token_ref, params={"per_page": 100, "sort": "pushed"})).json()
    rows = [_repo(row) for row in (body if isinstance(body, list) else []) if isinstance(row, dict) and row.get("full_name")]
    needle = (search or "").strip().lower()
    return [row for row in rows if needle in str(row["name"]).lower()] if needle else rows


async def assignees(token_ref: str, repository: str) -> list[dict[str, object]]:
    body = (await _request("GET", f"/repos/{repository}/assignees", token_ref, params={"per_page": 100})).json()
    return sorted((
        {"id": str(row.get("id")), "name": str(row.get("login") or ""), "username": row.get("login")}
        for row in (body if isinstance(body, list) else []) if isinstance(row, dict) and row.get("id")
    ), key=lambda row: str(row["name"]).lower())


def build_issue_payload(approved: dict[str, object]) -> dict[str, object]:
    """The customer reads this repository: only the approved title and description, plus a hidden marker.

    No internal priority, labels or acceptance boilerplate.
    """
    if not approved.get("approved"):
        raise ValueError("External issue creation requires an approval snapshot")
    public_id = str(approved.get("intake_public_id") or "").strip()
    if not public_id:
        raise ValueError("GitHub issue creation requires an Intake public ID")
    title = re.sub(r"^\[[A-Z]{2,8}-[0-9A-Z]+-\d+\]\s*", "", str(approved["title"]).strip())
    summary = str(approved.get("description") or approved.get("summary") or "").strip()
    # The customer reads this repository: related internal issue numbers are left out.
    specific = details_markdown(approved.get("details"), link_related=False)
    return {"title": title[:255], "body": f"{summary}\n\n" + (f"{specific}\n\n" if specific else "") + issue_marker(public_id)}


async def find_issue(token_ref: str, repository: str, public_id: str) -> dict | None:
    """A retry must not create a second issue: look for the marker among the most recently created ones."""
    marker = issue_marker(public_id)
    body = (await _request(
        "GET", f"/repos/{repository}/issues", token_ref,
        params={"state": "all", "per_page": 100, "sort": "created", "direction": "desc"},
    )).json()
    for row in body if isinstance(body, list) else []:
        if isinstance(row, dict) and "pull_request" not in row and marker in str(row.get("body") or ""):
            return row
    return None


async def create_issue(token_ref: str, repository: str, approved: dict[str, object]) -> dict:
    body = (await _request("POST", f"/repos/{repository}/issues", token_ref, json=build_issue_payload(approved))).json()
    if not isinstance(body, dict) or not body.get("number"):
        raise GitHubPermanentError("GITHUB_INVALID_RESPONSE")
    return body


async def refresh_issue(token_ref: str, repository: str, number: str, approved: dict[str, object], *, reopen: bool = False) -> dict:
    """Bring the issue of an earlier decision up to date with the new approval; reopen it when it was closed."""
    payload = build_issue_payload(approved)
    if reopen:
        payload["state"] = "open"
    body = (await _request("PATCH", f"/repos/{repository}/issues/{number}", token_ref, json=payload)).json()
    if not isinstance(body, dict) or not body.get("number"):
        raise GitHubPermanentError("GITHUB_INVALID_RESPONSE")
    return body


async def accept_issue(token_ref: str, repository: str, number: str, note: str, *, close: bool) -> dict:
    """The CTO accepted the work (FR-PLAN-31): a comment on the issue, then the issue closed."""
    await _request("POST", f"/repos/{repository}/issues/{number}/comments", token_ref, json={"body": note})
    if not close:
        return {}
    body = (await _request("PATCH", f"/repos/{repository}/issues/{number}", token_ref, json={"state": "closed", "state_reason": "completed"})).json()
    return body if isinstance(body, dict) else {}


def as_read_model_issue(row: dict) -> dict[str, object]:
    """Shape a GitHub issue like the GitLab issues the planning read model already understands."""
    milestone = row.get("milestone") if isinstance(row.get("milestone"), dict) else None
    due = str(milestone.get("due_on") or "")[:10] if milestone else ""
    return {
        "iid": row.get("number"), "id": row.get("id"), "title": row.get("title"),
        "state": "opened" if row.get("state") == "open" else "closed",
        "labels": [label.get("name") if isinstance(label, dict) else label for label in (row.get("labels") or [])],
        "assignees": [{"id": user.get("id")} for user in (row.get("assignees") or []) if isinstance(user, dict)],
        "milestone": {"id": milestone.get("number"), "title": milestone.get("title")} if milestone else None,
        "due_date": due or None, "web_url": row.get("html_url"), "updated_at": row.get("updated_at"),
        "closed_at": row.get("closed_at"), "closed_by": {"id": (row.get("closed_by") or {}).get("id")} if isinstance(row.get("closed_by"), dict) else None,
    }


async def issue_evidence(token_ref: str, repository: str, number: str) -> dict[str, object]:
    """Commits and pull requests that reference an Issue, from its timeline; shaped like the GitLab traces."""
    body = (await _request(
        "GET", f"/repos/{repository}/issues/{number}/timeline", token_ref, params={"per_page": 100},
    )).json()
    commits, merge_requests = [], []
    for event in (body if isinstance(body, list) else []):
        if not isinstance(event, dict):
            continue
        if event.get("event") == "referenced" and event.get("commit_id"):
            commits.append({"sha": str(event["commit_id"]), "at": event.get("created_at")})
        source = event.get("source") if isinstance(event.get("source"), dict) else {}
        issue = source.get("issue") if isinstance(source.get("issue"), dict) else {}
        pull = issue.get("pull_request") if isinstance(issue.get("pull_request"), dict) else None
        if event.get("event") == "cross-referenced" and pull is not None:
            merge_requests.append({
                "iid": str(issue.get("number")), "state": "merged" if pull.get("merged_at") else str(issue.get("state") or ""),
                "title": str(issue.get("title") or "")[:200], "merged_at": pull.get("merged_at"), "web_url": issue.get("html_url"), "sha": None,
            })
    return {"merge_requests": merge_requests, "commits": commits[:20], "pipeline": None}


async def list_all_issues(token_ref: str, repository: str) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    for page in range(1, PAGE_LIMIT + 1):
        body = (await _request(
            "GET", f"/repos/{repository}/issues", token_ref, params={"state": "all", "per_page": 100, "page": page},
        )).json()
        rows = body if isinstance(body, list) else []
        # The issues endpoint also returns pull requests.
        issues.extend(as_read_model_issue(row) for row in rows if isinstance(row, dict) and "pull_request" not in row)
        if len(rows) < 100:
            break
    return issues
