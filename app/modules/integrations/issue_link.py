"""Pre-filled "new issue" link for a GitHub repository (FR-INTG-20).

The link is built only from the normalized title, summary and details. Raw customer text, the sender and
attachments never enter it. The person opens the page in their own browser and submits it under their own account,
so Intake needs no token for this.
"""
from __future__ import annotations

import re
from urllib.parse import quote, urlsplit

from sqlalchemy import select

from app.db import get_session
from app.models import IntakeItem, Project, ProjectIntegration
from app.modules.integrations.description import details_markdown

# GitHub rejects URLs over about 8 KB; the body is shortened so the whole link stays under this size.
MAX_URL_LENGTH = 7000
REPO_PATTERN = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$")
TITLE_PREFIX = re.compile(r"^\[[A-Z]{2,8}-[0-9A-Z]+-\d+\]\s*")


class IssueLinkError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def repo_url_of(session, project: Project) -> str | None:
    """The GitHub repository of a project: its mapping first, then the repository a showcase item recorded."""
    mapping = session.scalar(select(ProjectIntegration).where(ProjectIntegration.project_id == project.id, ProjectIntegration.system == "GITHUB"))
    if mapping is not None and mapping.project_external_id and "/" in mapping.project_external_id:
        return f"https://github.com/{mapping.project_external_id.strip('/')}"
    url = str((project.project_settings or {}).get("repo_url") or "").strip()
    match = REPO_PATTERN.match(url)
    return f"https://github.com/{match.group(1)}/{match.group(2)}" if match else None


def build_new_issue_url(repo_url: str, title: str, body: str) -> tuple[str, bool]:
    """Returns the link and whether the body had to be shortened."""
    head = f"{repo_url}/issues/new?title={quote(title[:255], safe='')}&body="
    encoded = quote(body, safe="")
    if len(head) + len(encoded) <= MAX_URL_LENGTH:
        return head + encoded, False
    room = MAX_URL_LENGTH - len(head) - len(quote("\n\n…(đã rút gọn)", safe=""))
    cut = body
    while len(quote(cut, safe="")) > max(room, 0) and cut:
        cut = cut[: int(len(cut) * 0.9)]
    return head + quote(cut.rstrip() + "\n\n…(đã rút gọn)", safe=""), True


def new_issue_link(intake_id: str) -> dict[str, object]:
    with get_session() as session:
        item = session.get(IntakeItem, intake_id)
        if item is None:
            raise IssueLinkError("NOT_FOUND", "Intake not found")
        title = TITLE_PREFIX.sub("", (item.normalized_title or "").strip())
        summary = (item.normalized_summary or "").strip()
        if not title or not summary:
            raise IssueLinkError("NOT_NORMALIZED", "The request has no normalized title and summary yet")
        project = session.get(Project, item.project_id)
        repo = repo_url_of(session, project) if project is not None else None
        if repo is None:
            raise IssueLinkError("NO_REPOSITORY", "This project has no GitHub repository")
        details = details_markdown(item.normalized_details, link_related=False)
        body = summary + (f"\n\n{details}" if details else "")
        url, shortened = build_new_issue_url(repo, title, body)
        host = urlsplit(url).netloc
        return {"url": url, "repository": repo.removeprefix("https://github.com/"), "host": host, "shortened": shortened}
