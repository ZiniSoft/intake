from __future__ import annotations

import hashlib
import json
import re
from urllib.parse import quote

import httpx

from app.modules.integrations.description import details_markdown
from app.config import get_settings


GITLAB_PRIORITY_LABELS = {
    "P0": "priority:p0",
    "P1": "priority:p1",
    "P2": "priority:p2",
    "P3": "priority:p3",
}

GITLAB_TYPE_LABELS = {
    "BUG": "type:bug",
    "FEATURE": "type:feature",
    "SCOPE_CHANGE": "type:feature",
    "TASK": "type:task",
    "FEEDBACK": "type:task",
    "QUESTION": "type:task",
    "UNCLEAR": "type:task",
    "TECH_DEBT": "type:tech-debt",
}


class GitLabAdapter:
    def __init__(self) -> None:
        self.settings = get_settings()

    def build_issue_payload(self, approved: dict[str, object]) -> dict[str, object]:
        if not approved.get("approved"):
            raise ValueError("External issue creation requires an approval snapshot")
        public_id = str(approved.get("intake_public_id") or approved.get("public_id") or "").strip()
        if not public_id:
            raise ValueError("GitLab issue creation requires an Intake public ID")
        summary = str(approved.get("description") or approved.get("summary") or "").strip()
        priority = str(approved.get("approved_priority") or "P3").upper()
        item_type = str(approved.get("item_type") or "TASK").upper()
        priority_label = GITLAB_PRIORITY_LABELS.get(priority)
        type_label = GITLAB_TYPE_LABELS.get(item_type)
        if not priority_label:
            raise ValueError(f"Unsupported GitLab priority: {priority}")
        if not type_label:
            raise ValueError(f"Unsupported GitLab item type: {item_type}")
        marker = self.issue_marker(public_id)
        specific = details_markdown(approved.get("details"))
        # What the request itself asks for comes first; the team's standing checks follow.
        return {
            "title": _external_title(public_id, str(approved["title"])),
            "description": (
                f"{summary}\n\n"
                + (f"{specific}\n\n" if specific else "")
                # Without request-specific criteria the standing checks keep their old heading.
                + ("## Definition of done\n\n" if specific else "## Acceptance criteria\n\n")
                + "- [ ] Triển khai đúng nội dung đã được CTO duyệt.\n"
                "- [ ] Có test phù hợp và pipeline đạt.\n"
                "- [ ] Cập nhật tài liệu hoặc ghi rõ lý do không cần cập nhật.\n\n"
                "## Traceability\n\n"
                f"- Intake: `{public_id}`\n"
                f"- Priority: `{priority}`\n\n"
                f"{marker}"
            ),
            "issue_type": "issue",
            "labels": ",".join(("source:intake", priority_label, type_label)),
        }

    @staticmethod
    def issue_marker(public_id: str) -> str:
        return f"<!-- {get_settings().integration_marker_prefix}:{public_id} -->"

    async def find_issue(self, project_path: str, public_id: str) -> dict | None:
        if not self.settings.gitlab_base_url or not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        encoded_project = quote(project_path, safe="")
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token}
        marker = self.issue_marker(public_id)
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            try:
                response = await client.get(
                    f"/api/v4/projects/{encoded_project}/issues",
                    params={
                        "scope": "all",
                        "state": "all",
                        "search": public_id,
                        "in": "description",
                        "per_page": 100,
                    },
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _gitlab_http_error(exc.response.status_code) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
        body = response.json()
        if not isinstance(body, list):
            raise GitLabPermanentError("GITLAB_INVALID_RESPONSE")
        for issue in body:
            if isinstance(issue, dict) and marker in str(issue.get("description") or ""):
                return issue
        return None

    async def create_issue(self, project_path: str, approved: dict[str, object], idempotency_key: str) -> dict:
        if not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        payload = self.build_issue_payload(approved)
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token, "Idempotency-Key": idempotency_key}
        encoded_project = quote(project_path, safe="")
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            try:
                response = await client.post(
                    f"/api/v4/projects/{encoded_project}/issues",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _gitlab_http_error(exc.response.status_code) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
        body = response.json()
        if not isinstance(body, dict) or not body.get("iid") or not body.get("web_url"):
            raise GitLabPermanentError("GITLAB_INVALID_RESPONSE")
        return body

    async def refresh_issue(self, project_path: str, issue_iid: str, approved: dict[str, object], idempotency_key: str, *, reopen: bool = False) -> dict:
        """Bring the Issue of an earlier decision up to date with the new approval; reopen it when it was closed."""
        if not self.settings.gitlab_base_url or not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        payload = self.build_issue_payload(approved)
        if reopen:
            payload["state_event"] = "reopen"
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token, "Idempotency-Key": f"{idempotency_key}:refresh"}
        encoded_project = quote(project_path, safe="")
        encoded_issue = quote(str(issue_iid), safe="")
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            try:
                response = await client.put(f"/api/v4/projects/{encoded_project}/issues/{encoded_issue}", json=payload, headers=headers)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _gitlab_http_error(exc.response.status_code) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
        body = response.json()
        if not isinstance(body, dict) or str(body.get("iid") or "") != str(issue_iid):
            raise GitLabPermanentError("GITLAB_INVALID_RESPONSE")
        return body

    async def accept_issue(self, project_path: str, issue_iid: str, note: str, *, close: bool) -> dict:
        """The CTO accepted the work (FR-PLAN-31): a note on the Issue, then the Issue closed. The only write beyond
        assignee, milestone and due date that the allowlist permits (ADR-0055)."""
        if not self.settings.gitlab_base_url or not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token}
        encoded_project = quote(project_path, safe="")
        encoded_issue = quote(str(issue_iid), safe="")
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            try:
                response = await client.post(f"/api/v4/projects/{encoded_project}/issues/{encoded_issue}/notes", json={"body": note}, headers=headers)
                response.raise_for_status()
                if close:
                    response = await client.put(f"/api/v4/projects/{encoded_project}/issues/{encoded_issue}", json={"state_event": "close"}, headers=headers)
                    response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _gitlab_http_error(exc.response.status_code) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
        body = response.json()
        return body if isinstance(body, dict) else {}

    @staticmethod
    def build_planning_update_payload(approved: dict[str, object]) -> dict[str, object]:
        """Assignee always; milestone and due date only when the plan has them, so a missing field is never erased
        on GitLab (ADR-0013)."""
        try:
            assignee_id = int(str(approved["assignee_external_id"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("GitLab assignee and milestone IDs must be numeric") from exc
        payload: dict[str, object] = {"assignee_ids": [assignee_id]}
        milestone = approved.get("milestone_external_id")
        if milestone not in (None, ""):
            try:
                payload["milestone_id"] = int(str(milestone))
            except (TypeError, ValueError) as exc:
                raise ValueError("GitLab assignee and milestone IDs must be numeric") from exc
        due_date = str(approved.get("due_date") or "").strip()
        if due_date:
            payload["due_date"] = due_date
        return payload

    async def get_issue_by_iid(self, project_path: str, issue_iid: str) -> dict:
        if not self.settings.gitlab_base_url or not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        encoded_project = quote(project_path, safe="")
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token}
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            try:
                response = await client.get(
                    f"/api/v4/projects/{encoded_project}/issues/{quote(str(issue_iid), safe='')}",
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _gitlab_http_error(exc.response.status_code) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
        body = response.json()
        if not isinstance(body, dict) or str(body.get("iid") or "") != str(issue_iid):
            raise GitLabPermanentError("GITLAB_INVALID_RESPONSE")
        return body

    async def issue_evidence(self, project_path: str, issue_iid: str) -> dict[str, object]:
        """What GitLab holds behind one Issue: merge requests that reference it, commits that mention it (GitLab
        writes a system note for each), and the last pipeline of the newest such commit. Three small reads."""
        if not self.settings.gitlab_base_url or not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        encoded_project = quote(project_path, safe="")
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token}
        base = f"/api/v4/projects/{encoded_project}"
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            async def read(path: str, params: dict[str, object]) -> object:
                try:
                    response = await client.get(path, params=params, headers=headers)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _gitlab_http_error(exc.response.status_code) from exc
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
                return response.json()

            related = await read(f"{base}/issues/{issue_iid}/related_merge_requests", {"per_page": 50})
            merge_requests = [
                {"iid": str(item.get("iid")), "state": str(item.get("state") or ""), "title": str(item.get("title") or "")[:200],
                 "merged_at": item.get("merged_at"), "web_url": item.get("web_url"), "sha": item.get("sha")}
                for item in (related if isinstance(related, list) else []) if isinstance(item, dict)
            ]
            notes = await read(f"{base}/issues/{issue_iid}/notes", {"per_page": 100, "sort": "desc", "order_by": "created_at"})
            commits = []
            for note in (notes if isinstance(notes, list) else []):
                if not isinstance(note, dict) or not note.get("system"):
                    continue
                found = _COMMIT_MENTION.search(str(note.get("body") or ""))
                if found:
                    commits.append({"sha": found.group(1), "at": note.get("created_at")})
            pipeline = None
            newest = next((item["sha"] for item in merge_requests if item.get("sha") and item.get("state") == "merged"), None) or (commits[0]["sha"] if commits else None)
            if newest:
                commit = await read(f"{base}/repository/commits/{newest}", {})
                last = commit.get("last_pipeline") if isinstance(commit, dict) and isinstance(commit.get("last_pipeline"), dict) else None
                if last:
                    pipeline = {"status": str(last.get("status") or ""), "sha": newest, "web_url": last.get("web_url")}
        return {"merge_requests": merge_requests, "commits": commits[:20], "pipeline": pipeline}

    async def list_all_issues(self, project_path: str) -> list[dict[str, object]]:
        if not self.settings.gitlab_base_url or not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        encoded_project = quote(project_path, safe="")
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token}
        issues: list[dict[str, object]] = []
        page = 1
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            while page <= 100:
                try:
                    response = await client.get(
                        f"/api/v4/projects/{encoded_project}/issues",
                        params={"scope": "all", "state": "all", "per_page": 100, "page": page},
                        headers=headers,
                    )
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    raise _gitlab_http_error(exc.response.status_code) from exc
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
                body = response.json()
                if not isinstance(body, list):
                    raise GitLabPermanentError("GITLAB_INVALID_RESPONSE")
                issues.extend(issue for issue in body if isinstance(issue, dict))
                next_page = response.headers.get("X-Next-Page", "").strip()
                if not next_page:
                    break
                try:
                    page = int(next_page)
                except ValueError as exc:
                    raise GitLabPermanentError("GITLAB_INVALID_PAGINATION") from exc
        return issues

    async def update_issue_planning(
        self,
        project_path: str,
        issue_iid: str,
        approved: dict[str, object],
        idempotency_key: str,
    ) -> dict:
        if not self.settings.gitlab_base_url or not self.settings.gitlab_token:
            raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
        encoded_project = quote(project_path, safe="")
        encoded_issue = quote(str(issue_iid), safe="")
        headers = {"PRIVATE-TOKEN": self.settings.gitlab_token, "Idempotency-Key": idempotency_key}
        payload = self.build_planning_update_payload(approved)
        async with httpx.AsyncClient(base_url=self.settings.gitlab_base_url, timeout=30) as client:
            try:
                response = await client.put(
                    f"/api/v4/projects/{encoded_project}/issues/{encoded_issue}",
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _gitlab_http_error(exc.response.status_code) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
        body = response.json()
        if not isinstance(body, dict) or str(body.get("iid") or "") != str(issue_iid):
            raise GitLabPermanentError("GITLAB_INVALID_RESPONSE")
        return body


async def gitlab_projects(search: str | None = None, path: str | None = None) -> list[dict[str, object]]:
    """Projects the shared token can reach; with `path`, exactly that project. Returns only names and URLs."""
    settings = get_settings()
    if not settings.gitlab_token:
        raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
    headers = {"PRIVATE-TOKEN": settings.gitlab_token}
    async with httpx.AsyncClient(base_url=settings.gitlab_base_url, timeout=30) as client:
        try:
            if path:
                response = await client.get(f"/api/v4/projects/{quote(path, safe='')}", headers=headers)
            else:
                params: dict[str, object] = {"membership": "true", "simple": "true", "archived": "false", "per_page": 50, "order_by": "last_activity_at"}
                if search:
                    params["search"] = search
                response = await client.get("/api/v4/projects", params=params, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _gitlab_http_error(exc.response.status_code) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
    body = response.json()
    rows = [body] if isinstance(body, dict) else body if isinstance(body, list) else []
    return [
        {"id": str(row.get("path_with_namespace")), "name": str(row.get("name_with_namespace") or row.get("name") or ""), "url": row.get("web_url")}
        for row in rows if isinstance(row, dict) and row.get("path_with_namespace")
    ]


async def gitlab_project_members(path: str) -> list[dict[str, object]]:
    """Active users of one GitLab project, to map a workforce member to a GitLab assignee."""
    settings = get_settings()
    if not settings.gitlab_token:
        raise GitLabPermanentError("GITLAB_NOT_CONFIGURED")
    headers = {"PRIVATE-TOKEN": settings.gitlab_token}
    async with httpx.AsyncClient(base_url=settings.gitlab_base_url, timeout=30) as client:
        try:
            response = await client.get(f"/api/v4/projects/{quote(path, safe='')}/members/all", params={"per_page": 100}, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _gitlab_http_error(exc.response.status_code) from exc
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise GitLabTransientError("GITLAB_UNAVAILABLE") from exc
    body = response.json()
    return sorted((
        {"id": str(row.get("id")), "name": str(row.get("name") or row.get("username") or ""), "username": row.get("username")}
        for row in (body if isinstance(body, list) else [])
        if isinstance(row, dict) and row.get("id") and row.get("state", "active") == "active"
    ), key=lambda row: str(row["name"]).lower())


class GitLabTransientError(RuntimeError):
    pass


class GitLabPermanentError(RuntimeError):
    pass


# "mentioned in commit abc123…" is how GitLab records a commit that names an Issue.
_COMMIT_MENTION = re.compile(r"mentioned in commit ([0-9a-f]{7,40})")


def _gitlab_http_error(status_code: int) -> RuntimeError:
    if status_code in (408, 409, 425, 429) or status_code >= 500:
        return GitLabTransientError(f"GITLAB_HTTP_{status_code}")
    if status_code in (401, 403):
        return GitLabPermanentError("GITLAB_AUTH_FAILED")
    if status_code == 404:
        return GitLabPermanentError("GITLAB_MAPPING_NOT_FOUND")
    return GitLabPermanentError(f"GITLAB_HTTP_{status_code}")


def _external_title(public_id: str, title: str) -> str:
    prefix = f"[{public_id}]"
    normalized = title.strip()
    if normalized.startswith(prefix):
        return normalized[:255]
    return f"{prefix} {normalized}"[:255]


def payload_hash(payload: dict[str, object]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
