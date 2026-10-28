"""A request that was approved and given an Issue waits in the day's plan until someone takes it (FR-PLAN-21)."""
import hashlib
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AuditEvent, ExternalLink, GitLabIssueSnapshot, IntakeItem, IssueVerification, Project
from tests.test_intake_reopen import _approved, _historical_plane, _mark_synced

client = TestClient(app, headers={"X-User-Subject": "cto"})


def _run(day: str) -> dict:
    response = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]})
    assert response.status_code in (200, 201), response.text
    return response.json()["data"]


def _waiting(run: dict, intake_id: str) -> list[dict]:
    return [row for row in run["candidates"] if row["intake_id"] == intake_id]


def _snapshot(issue_id: str, *, state: str = "opened", assignees: list | None = None, title: str = "Issue trong GitLab") -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=project.id, issue_external_id=issue_id, title=title, state=state,
            labels=["priority:p1"], assignee_external_ids=assignees or [], milestone_external_id=None, milestone_title=None, due_date=None,
            web_url=None, payload_hash=hashlib.sha256(f"waiting:{issue_id}:{state}:{assignees}".encode()).hexdigest(),
            is_current=True, fetched_at=now, last_seen_at=now,
        ))
        session.commit()


def test_a_synced_request_nobody_has_taken_waits_to_be_assigned() -> None:
    day = "2027-01-12"
    before = _run(day)

    # An Issue the read model already knows, open and with no assignee.
    known = _approved("GITLAB")
    known_issue = str(71000 + int(uuid4().int % 900))
    _snapshot(known_issue)
    _mark_synced(known["id"], "GITLAB", known_issue)

    # An Issue made after the read model was last loaded: Intake knows it exists.
    fresh = _approved("GITLAB")
    fresh_issue = str(72000 + int(uuid4().int % 900))
    _mark_synced(fresh["id"], "GITLAB", fresh_issue)

    # Someone already has this one; this one is closed; this one went to Plane only.
    taken = _approved("GITLAB")
    taken_issue = str(73000 + int(uuid4().int % 900))
    _snapshot(taken_issue, assignees=["4242"])
    _mark_synced(taken["id"], "GITLAB", taken_issue)
    closed = _approved("GITLAB")
    closed_issue = str(74000 + int(uuid4().int % 900))
    _snapshot(closed_issue, state="closed")
    _mark_synced(closed["id"], "GITLAB", closed_issue)
    plane_only = _historical_plane()
    _mark_synced(plane_only["id"], "PLANE", f"wi-{uuid4().hex[:8]}")

    run = _run(day)
    assert run["id"] == before["id"] and run["version"] == before["version"] + 1 and run["status"] == "REVIEW_REQUIRED", "the open run takes them in"
    first = _waiting(run, known["id"])
    assert len(first) == 1
    assert (first[0]["source_type"], first[0]["status"], first[0]["gitlab_issue_external_id"], first[0]["proposed_priority"], first[0]["member_id"]) == ("INTAKE", "READY", known_issue, "P2", None)
    assert first[0]["source_reference"] == known["public_id"] and f"GitLab #{known_issue}" in first[0]["summary"]

    second = _waiting(run, fresh["id"])
    assert len(second) == 1 and second[0]["status"] == "READY" and second[0]["gitlab_issue_external_id"] == fresh_issue
    with get_session() as session:
        stand_in = session.scalar(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == fresh_issue, GitLabIssueSnapshot.is_current.is_(True)))
        assert stand_in is not None and stand_in.state == "opened" and stand_in.assignee_external_ids == [] and stand_in.labels == ["priority:p2"]
    for other in (taken, closed, plane_only):
        assert _waiting(run, other["id"]) == []

    # Opening the day again adds nothing twice.
    again = _run(day)
    assert again["version"] == run["version"] and len(_waiting(again, known["id"])) == 1 and len(_waiting(again, fresh["id"])) == 1

    # A request dropped or marked a duplicate is not offered on another day; an Issue missing from a newer read model is not either.
    dropped = _approved("GITLAB")
    _mark_synced(dropped["id"], "GITLAB", str(75000 + int(uuid4().int % 900)))
    with get_session() as session:
        session.get(IntakeItem, dropped["id"]).duplicate_of_id = known["id"]
        gone = session.scalar(select(ExternalLink).where(ExternalLink.intake_id == fresh["id"]))
        gone.created_at = datetime.now(timezone.utc) - timedelta(days=3)
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == fresh_issue)).all():
            row.is_current = False
        # The read model was loaded again after that Issue was made, and the Issue was not in it.
        session.add(AuditEvent(
            id=str(uuid4()), project_id=gone.project_id, actor_type="SYSTEM", actor_id="integration-worker",
            event_type="planning.gitlab-read-model.refreshed", entity_type="project", entity_id=gone.project_id, details={}, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
    another = _run("2027-01-13")
    assert _waiting(another, dropped["id"]) == [] and _waiting(another, fresh["id"]) == [], "an Issue that vanished from GitLab is not offered"
    assert len(_waiting(another, known["id"])) == 1, "still nobody's: it waits on the next day too"

    # Out of the way for the other tests that share this project.
    with get_session() as session:
        for intake_id in (known["id"], fresh["id"], taken["id"], closed["id"], dropped["id"]):
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == intake_id)).all():
                link.target_system = "PLANE"
        session.commit()


def test_an_accepted_request_is_not_offered_again_unless_its_issue_was_reopened_since() -> None:
    """INT-26W43-001 (Issue #21): the CTO accepted the Issue of a request, but the tracker still shows it open (the
    close failed, or has not run yet). The request must not come back to "waiting to be assigned". Only an Issue
    that GitLab shows changed after the acceptance, and open, is work again."""
    day = "2027-02-02"
    accepted = _approved("GITLAB")
    issue = str(76000 + int(uuid4().int % 900))
    _snapshot(issue)
    _mark_synced(accepted["id"], "GITLAB", issue)
    decided = datetime.now(timezone.utc) - timedelta(hours=2)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        session.add(IssueVerification(
            id=str(uuid4()), project_id=project.id, issue_external_id=issue, planning_run_id=None, evidence_level=1,
            decision="ACCEPTED", decided_at=decided, source="PLAN", sync_status="FAILED", sync_error="thử: tracker không nhận",
            created_at=decided - timedelta(hours=1),
        ))
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == issue)).all():
            row.external_updated_at = decided - timedelta(days=1)
        session.commit()
    try:
        run = _run(day)
        assert _waiting(run, accepted["id"]) == [], "accepted is done, whatever the read model says"

        # GitLab shows the Issue touched after the acceptance and still open: someone reopened it, it is work again.
        with get_session() as session:
            for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == issue)).all():
                row.external_updated_at = decided + timedelta(hours=1)
            session.commit()
        reopened = _run("2027-02-03")
        assert len(_waiting(reopened, accepted["id"])) == 1
    finally:
        with get_session() as session:
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == accepted["id"])).all():
                link.target_system = "PLANE"
            for row in session.scalars(select(IssueVerification).where(IssueVerification.issue_external_id == issue)).all():
                session.delete(row)
            for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == issue)).all():
                session.delete(row)
            session.commit()
