from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session, init_db
from app.models import AuditEvent, GitLabIssueSnapshot, IssueVerification

# How far back a closed Issue still gets its code traces looked up, and how old a lookup may be before it is redone.
EVIDENCE_WINDOW_DAYS = 14
EVIDENCE_STALE_HOURS = 20
EVIDENCE_BATCH = 30

# What a project accepts as the trace of code behind a closed Issue (projects.settings.done_evidence).
DONE_EVIDENCE_COMMIT = "COMMIT"  # a commit or merge request that mentions the Issue
DONE_EVIDENCE_MR = "MR"  # a merged merge request, and its pipeline not failed
DONE_EVIDENCE_CHOICES = (DONE_EVIDENCE_COMMIT, DONE_EVIDENCE_MR)

# The ladder of "done", from a word in an email to the CTO having looked (FR-PLAN-22).
LEVEL_SELF_REPORTED = 0
LEVEL_CLOSED = 1
LEVEL_TRACED = 2
LEVEL_ACCEPTED = 5
LEVEL_NAMES = {LEVEL_SELF_REPORTED: "SELF_REPORTED", LEVEL_CLOSED: "CLOSED", LEVEL_TRACED: "TRACED", LEVEL_ACCEPTED: "ACCEPTED"}


def done_level(state: str, evidence: dict | None, done_evidence: str = DONE_EVIDENCE_COMMIT, accepted: bool = False) -> int:
    """Where an Issue stands on the ladder, from what the read model holds about it."""
    if state != "closed":
        return LEVEL_SELF_REPORTED
    if accepted:
        return LEVEL_ACCEPTED
    evidence = evidence or {}
    merge_requests = [item for item in evidence.get("merge_requests") or [] if isinstance(item, dict)]
    commits = [item for item in evidence.get("commits") or [] if isinstance(item, dict)]
    pipeline = evidence.get("pipeline") if isinstance(evidence.get("pipeline"), dict) else None
    if done_evidence == DONE_EVIDENCE_MR:
        merged = any(item.get("state") == "merged" for item in merge_requests)
        failed = pipeline is not None and pipeline.get("status") == "failed"
        return LEVEL_TRACED if merged and not failed else LEVEL_CLOSED
    return LEVEL_TRACED if merge_requests or commits else LEVEL_CLOSED


def evidence_summary(evidence: dict | None) -> dict[str, object]:
    """The few numbers the screen shows about the traces."""
    evidence = evidence or {}
    merge_requests = [item for item in evidence.get("merge_requests") or [] if isinstance(item, dict)]
    pipeline = evidence.get("pipeline") if isinstance(evidence.get("pipeline"), dict) else None
    return {
        "commits": len([item for item in evidence.get("commits") or [] if isinstance(item, dict)]),
        "merge_requests": len(merge_requests),
        "merged": len([item for item in merge_requests if item.get("state") == "merged"]),
        "pipeline": pipeline.get("status") if pipeline else None,
        "links": [str(item.get("web_url")) for item in merge_requests if item.get("web_url")][:3],
    }


def _as_datetime(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _as_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def normalize_gitlab_issue(issue: dict[str, object]) -> dict[str, object]:
    assignees = issue.get("assignees") if isinstance(issue.get("assignees"), list) else []
    milestone = issue.get("milestone") if isinstance(issue.get("milestone"), dict) else {}
    closed_by = issue.get("closed_by") if isinstance(issue.get("closed_by"), dict) else {}
    labels = sorted({str(label) for label in (issue.get("labels") or []) if str(label).strip()})
    normalized = {
        "issue_external_id": str(issue.get("iid") or "").strip(),
        "global_external_id": str(issue.get("id")) if issue.get("id") is not None else None,
        "title": str(issue.get("title") or "").strip(),
        "state": str(issue.get("state") or "unknown").lower(),
        "labels": labels,
        "assignee_external_ids": sorted({
            str(item.get("id")) for item in assignees if isinstance(item, dict) and item.get("id") is not None
        }),
        "milestone_external_id": str(milestone.get("id")) if milestone.get("id") is not None else None,
        "milestone_title": str(milestone.get("title")) if milestone.get("title") else None,
        "due_date": _as_date(issue.get("due_date")),
        "web_url": str(issue.get("web_url")) if issue.get("web_url") else None,
        "external_updated_at": _as_datetime(issue.get("updated_at")),
        "closed_at": _as_datetime(issue.get("closed_at")),
        "closed_by_external_id": str(closed_by.get("id")) if closed_by.get("id") is not None else None,
    }
    if not normalized["issue_external_id"] or not normalized["title"]:
        raise ValueError("GitLab issue requires iid and title")
    return normalized


def _payload_hash(normalized: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(normalized, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class GitLabReadModelService:
    def __init__(self) -> None:
        init_db()

    def replace_project_snapshot(
        self,
        project_id: str,
        issues: list[dict[str, object]],
        *,
        fetched_at: datetime | None = None,
    ) -> dict[str, object]:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        created = 0
        unchanged = 0
        retired = 0
        with get_session() as session:
            current_rows = {
                row.issue_external_id: row
                for row in session.scalars(select(GitLabIssueSnapshot).where(
                    GitLabIssueSnapshot.project_id == project_id,
                    GitLabIssueSnapshot.is_current.is_(True),
                )).all()
            }
            seen: set[str] = set()
            for raw_issue in issues:
                normalized = normalize_gitlab_issue(raw_issue)
                issue_id = str(normalized["issue_external_id"])
                seen.add(issue_id)
                digest = _payload_hash(normalized)
                current = current_rows.get(issue_id)
                if current is not None and current.payload_hash == digest:
                    current.fetched_at = fetched_at
                    current.last_seen_at = fetched_at
                    unchanged += 1
                    continue
                if current is not None:
                    current.is_current = False
                historical = session.scalar(select(GitLabIssueSnapshot).where(
                    GitLabIssueSnapshot.project_id == project_id,
                    GitLabIssueSnapshot.issue_external_id == issue_id,
                    GitLabIssueSnapshot.payload_hash == digest,
                ))
                if historical is not None:
                    historical.is_current = True
                    historical.fetched_at = fetched_at
                    historical.last_seen_at = fetched_at
                    unchanged += 1
                    continue
                session.add(GitLabIssueSnapshot(
                    id=str(uuid4()), project_id=project_id, payload_hash=digest,
                    is_current=True, fetched_at=fetched_at, last_seen_at=fetched_at,
                    created_at=fetched_at, **normalized,
                ))
                created += 1
            for issue_id, row in current_rows.items():
                if issue_id not in seen:
                    row.is_current = False
                    retired += 1
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="SYSTEM", actor_id="integration-worker",
                event_type="planning.gitlab-read-model.refreshed", entity_type="project", entity_id=project_id,
                details={"received": len(issues), "created": created, "unchanged": unchanged, "retired": retired},
                created_at=fetched_at,
            ))
            session.commit()
        return {
            "project_id": project_id, "received": len(issues), "created": created,
            "unchanged": unchanged, "retired": retired, "fetched_at": fetched_at.isoformat(),
        }

    def evidence_targets(self, project_id: str, now: datetime | None = None) -> list[str]:
        """Closed Issues of the last two weeks whose code traces are missing or old: these get looked up."""
        now = now or datetime.now(timezone.utc)
        since = now - timedelta(days=EVIDENCE_WINDOW_DAYS)
        stale = now - timedelta(hours=EVIDENCE_STALE_HOURS)
        with get_session() as session:
            rows = session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.is_current.is_(True),
                GitLabIssueSnapshot.state == "closed", GitLabIssueSnapshot.closed_at.is_not(None), GitLabIssueSnapshot.closed_at >= since,
            ).order_by(GitLabIssueSnapshot.closed_at.desc())).all()
            # An open Issue someone reported done waits for acceptance; its traces are worth reading too (FR-PLAN-31).
            waiting = session.execute(select(IssueVerification.issue_external_id).where(
                IssueVerification.project_id == project_id, IssueVerification.decision == "PENDING",
            )).all()
            waiting_ids = {str(issue) for (issue,) in waiting}
            if waiting_ids:
                rows = list(rows) + list(session.scalars(select(GitLabIssueSnapshot).where(
                    GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.state == "opened",
                    GitLabIssueSnapshot.issue_external_id.in_(sorted(waiting_ids)),
                )).all())
            wanted = []
            seen: set[str] = set()
            for row in rows:
                if row.issue_external_id in seen:
                    continue
                seen.add(row.issue_external_id)
                fetched = row.evidence_fetched_at
                if fetched is not None and not fetched.tzinfo:
                    fetched = fetched.replace(tzinfo=timezone.utc)
                if fetched is None or fetched < stale:
                    wanted.append(row.issue_external_id)
            return wanted[:EVIDENCE_BATCH]

    def store_evidence(self, project_id: str, issue_id: str, evidence: dict[str, object], fetched_at: datetime | None = None) -> None:
        fetched_at = fetched_at or datetime.now(timezone.utc)
        with get_session() as session:
            for row in session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.issue_external_id == issue_id,
                GitLabIssueSnapshot.is_current.is_(True),
            )).all():
                row.evidence = evidence
                row.evidence_fetched_at = fetched_at
            session.commit()

    @staticmethod
    def accepted_issue_ids(session, project_id: str) -> set[str]:
        return {
            row.issue_external_id for row in session.scalars(select(IssueVerification).where(
                IssueVerification.project_id == project_id, IssueVerification.decision == "ACCEPTED",
            )).all()
        }


gitlab_read_model_service = GitLabReadModelService()
