"""Move a project's delivery from the company GitLab to a GitHub repository, for new work only (FR-PRJ-13, ADR-0079).

The GitLab link is kept but switched off: it stops syncing and nothing is copied to GitHub. Old Issue numbers are
moved aside ("5" becomes "gitlab:5") in every table keyed by Issue number, so a new GitHub #5 never reads the
acceptance, evidence or plan history of the GitLab #5 as its own. Old Issues stay reachable through their stored URLs.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, literal, not_, select, update

from app.models import (
    ExternalLink,
    GitLabIssueSnapshot,
    IssueEvidenceLink,
    IssueVerification,
    PlanningAssignment,
    PlanningCandidate,
    PlanningSyncJob,
    ProjectIntegration,
    ReportItem,
    WorkItem,
)

MOVED_PREFIX = "gitlab:"
SWITCH_TARGETS = ("GITHUB",)


def is_moved(issue_external_id: str | None) -> bool:
    """An Issue of the GitLab project the project left: read-only history, never written to the current tracker."""
    return str(issue_external_id or "").startswith(MOVED_PREFIX)


def open_issues(session, project_id: str) -> int:
    """GitLab Issues still open in the last read of the tracker: the work that stays behind on GitLab."""
    return int(session.scalar(select(func.count()).select_from(GitLabIssueSnapshot).where(
        GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.is_current.is_(True),
        GitLabIssueSnapshot.state == "opened", not_(GitLabIssueSnapshot.issue_external_id.startswith(MOVED_PREFIX)),
    )) or 0)


def _columns():
    """Every place an Issue number of this project is kept, with the filter that limits it to GitLab rows."""
    return (
        (GitLabIssueSnapshot, GitLabIssueSnapshot.issue_external_id, ()),
        (IssueVerification, IssueVerification.issue_external_id, ()),
        (IssueEvidenceLink, IssueEvidenceLink.issue_external_id, ()),
        (PlanningAssignment, PlanningAssignment.gitlab_issue_external_id, ()),
        (PlanningCandidate, PlanningCandidate.gitlab_issue_external_id, ()),
        (PlanningSyncJob, PlanningSyncJob.gitlab_issue_external_id, ()),
        (ReportItem, ReportItem.gitlab_issue_external_id, ()),
        (WorkItem, WorkItem.issue_external_id, (WorkItem.issue_system == "GITLAB",)),
        (ExternalLink, ExternalLink.external_id, (ExternalLink.target_system == "GITLAB",)),
    )


def retire_gitlab(session, project_id: str, mapping: ProjectIntegration, now: datetime) -> dict[str, object]:
    """Switch the GitLab link off and move its Issue numbers aside. The caller owns the transaction."""
    previous = {
        "system": "GITLAB", "project_external_id": mapping.project_external_id,
        "project_url": (mapping.config or {}).get("project_url"), "switched_at": now.isoformat(),
    }
    counts = {"open_issues": open_issues(session, project_id)}
    moved = 0
    for model, column, extra in _columns():
        result = session.execute(
            update(model)
            .where(model.project_id == project_id, column.is_not(None), not_(column.startswith(MOVED_PREFIX)), *extra)
            .values({column.key: literal(MOVED_PREFIX) + column})
            .execution_options(synchronize_session=False)
        )
        moved += result.rowcount or 0
    session.execute(
        update(GitLabIssueSnapshot).where(GitLabIssueSnapshot.project_id == project_id).values(is_current=False)
        .execution_options(synchronize_session=False)
    )
    mapping.config = {**(mapping.config or {}), "previous": previous}
    mapping.project_external_id = None
    mapping.enabled = False
    mapping.updated_at = now
    return {**counts, "moved_rows": moved, "previous": previous}
