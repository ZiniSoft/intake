"""Who is who on the tracker (FR-PLAN-32, ADR-0056).

Planning writes the assignee of an Issue on GitLab or GitHub, so every person it assigns must be mapped to a tracker
user of that project (FR-PLAN-14, fail closed). The mapping used to be typed by the CTO alone, and a new project
started with nobody mapped. Now the tracker's member list is matched to the team by email and by name, a unique
match is filled in by itself, the assignee an Issue already carries is offered as a one-click mapping, and a Project
Owner can set the mapping for their own project right where the planning dialog needs it.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import AuditEvent, GitLabIssueSnapshot, ProjectIntegration, WorkforceMember, WorkforceProjectMembership
from app.modules.projects.management import ProjectError, project_management_service


def _plain(text: str | None) -> str:
    if not text:
        return ""
    value = unicodedata.normalize("NFD", text)
    value = "".join(char for char in value if unicodedata.category(char) != "Mn").replace("đ", "d").replace("Đ", "d").lower()
    return " ".join(re.findall(r"[a-z0-9]+", value))


def _name_key(text: str | None) -> str:
    """Names compare as a sorted bag of words: 'Doan Tran' and 'Tran Doan' are the same person."""
    return " ".join(sorted(_plain(text).split()))


def tracker_of(project_id: str) -> tuple[str, str, str | None] | None:
    """(system, project path or repository, token reference) of the project's enabled tracker, or None."""
    with get_session() as session:
        mapping = session.scalar(select(ProjectIntegration).where(
            ProjectIntegration.project_id == project_id, ProjectIntegration.enabled.is_(True),
            ProjectIntegration.system.in_(("GITLAB", "GITHUB")), ProjectIntegration.project_external_id.is_not(None),
        ))
        if mapping is None:
            return None
        return mapping.system, str(mapping.project_external_id), (str(mapping.credential_ref) if mapping.credential_ref else None)


def start_lookup(project_id: str, actor_id: str) -> dict[str, object] | None:
    """Ask the integration worker for the tracker's users. The API holds no tracker token (only the worker does), so
    the list arrives through a probe; the caller polls `lookup`. None when the project has no tracker."""
    tracker = tracker_of(project_id)
    if tracker is None:
        return None
    system, target, token_ref = tracker
    try:
        probe = project_management_service.request_probe(system, "MEMBERS", target, actor_id, token_ref=token_ref if system == "GITHUB" else None)
    except ProjectError as exc:
        return {"id": None, "status": "FAILED", "error_code": exc.code, "system": system}
    return {"id": probe["id"], "status": probe["status"], "error_code": probe.get("error_code"), "system": system}


def lookup(project_id: str, probe_id: str) -> dict[str, object]:
    """The probe's state and, once done, its users; a probe of another project or another kind is not shown."""
    tracker = tracker_of(project_id)
    try:
        probe = project_management_service.get_probe(probe_id)
    except KeyError:
        return {"status": "FAILED", "error_code": "PROBE_NOT_FOUND", "users": []}
    expected = tracker[1] if tracker else None
    reference = str(probe.get("reference") or "")
    if probe.get("action") != "MEMBERS" or expected is None or not (reference == expected or reference.endswith("|" + expected)):
        return {"status": "FAILED", "error_code": "PROBE_NOT_FOUND", "users": []}
    users = []
    if probe["status"] == "DONE" and isinstance(probe.get("result"), list):
        users = [{"id": str(row.get("id")), "name": str(row.get("name") or ""), "username": row.get("username"), "email": row.get("email")}
                 for row in probe["result"] if isinstance(row, dict) and row.get("id")]
    return {"status": probe["status"], "error_code": probe.get("error_code"), "users": users}


def suggest(users: list[dict[str, object]], members: list[WorkforceMember]) -> dict[str, str]:
    """member_id -> tracker user id for every member with exactly one match: by email, then by name, then by the
    email's local part against the username. Ambiguity means no suggestion."""
    out: dict[str, str] = {}
    for member in members:
        email = (member.email_reference or "").strip().lower()
        local = email.split("@", 1)[0] if email else ""
        matches: list[str] = []
        if email:
            matches = [str(user["id"]) for user in users if str(user.get("email") or "").strip().lower() == email]
        if not matches:
            key = _name_key(member.display_name)
            matches = [str(user["id"]) for user in users if key and _name_key(str(user.get("name") or "")) == key]
        if not matches and local:
            matches = [str(user["id"]) for user in users if _plain(str(user.get("username") or "")).replace(" ", "") == _plain(local).replace(" ", "")]
        if len(set(matches)) == 1:
            out[str(member.id)] = matches[0]
    return out


def auto_map(project_id: str, users: list[dict[str, object]], actor_id: str | None = None) -> dict[str, object]:
    """Fill the mapping of every member of the project who has none and matches exactly one tracker user.
    Never overwrites a mapping someone set."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        rows = session.execute(
            select(WorkforceProjectMembership, WorkforceMember).join(WorkforceMember, WorkforceMember.id == WorkforceProjectMembership.member_id)
            .where(WorkforceProjectMembership.project_id == project_id, WorkforceProjectMembership.active.is_(True), WorkforceMember.status == "ACTIVE")
        ).all()
        taken = {str(membership.gitlab_user_external_id) for membership, _ in rows if membership.gitlab_user_external_id}
        unmapped = [(membership, member) for membership, member in rows if not membership.gitlab_user_external_id]
        suggestions = suggest(users, [member for _, member in unmapped])
        filled: list[str] = []
        for membership, member in unmapped:
            user_id = suggestions.get(str(member.id))
            if not user_id or user_id in taken:
                continue
            membership.gitlab_user_external_id, membership.updated_at = user_id, now
            taken.add(user_id)
            filled.append(member.display_name)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="USER" if actor_id else "SYSTEM", actor_id=actor_id or "system",
                event_type="planning.member.tracker-user-matched", entity_type="workforce_member", entity_id=member.id,
                details={"tracker_user": user_id, "by": "auto"}, created_at=now,
            ))
        session.commit()
        return {"filled": len(filled), "names": filled, "unmapped": len(unmapped) - len(filled)}


def set_mapping(project_id: str, member_id: str, tracker_user_id: str | None, actor_id: str) -> bool:
    """A person's choice of tracker user for one member of one project."""
    now = datetime.now(timezone.utc)
    with get_session() as session:
        membership = session.scalar(select(WorkforceProjectMembership).where(
            WorkforceProjectMembership.project_id == project_id, WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.active.is_(True),
        ))
        if membership is None:
            return False
        membership.gitlab_user_external_id, membership.updated_at = (tracker_user_id or "").strip() or None, now
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project_id, actor_type="USER", actor_id=actor_id,
            event_type="planning.member.tracker-user-set", entity_type="workforce_member", entity_id=member_id,
            details={"tracker_user": membership.gitlab_user_external_id}, created_at=now,
        ))
        session.commit()
        return True


def view(project_id: str, users: list[dict[str, object]], issue: str | None = None) -> dict[str, object]:
    """What the planning dialog shows: tracker users with who they map to or could map to, the members still
    without a user, and whom the Issue is already assigned to on the tracker."""
    with get_session() as session:
        rows = session.execute(
            select(WorkforceProjectMembership, WorkforceMember).join(WorkforceMember, WorkforceMember.id == WorkforceProjectMembership.member_id)
            .where(WorkforceProjectMembership.project_id == project_id, WorkforceProjectMembership.active.is_(True), WorkforceMember.status == "ACTIVE")
        ).all()
        mapped = {str(membership.gitlab_user_external_id): str(member.id) for membership, member in rows if membership.gitlab_user_external_id}
        unmapped_members = [member for membership, member in rows if not membership.gitlab_user_external_id]
        suggestions = suggest(users, unmapped_members)
        by_user = {user_id: member_id for member_id, user_id in suggestions.items()}
        assignees: list[str] = []
        if issue:
            snapshot = session.scalar(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.issue_external_id == issue, GitLabIssueSnapshot.is_current.is_(True),
            ).order_by(GitLabIssueSnapshot.fetched_at.desc()))
            assignees = [str(value) for value in (snapshot.assignee_external_ids or [])] if snapshot is not None else []
        return {
            "users": [{
                "id": str(user["id"]), "name": str(user.get("name") or ""), "username": user.get("username"),
                "mapped_member_id": mapped.get(str(user["id"])), "suggested_member_id": by_user.get(str(user["id"])),
            } for user in users],
            "unmapped": [{"member_id": str(member.id), "display_name": member.display_name, "suggested_user_id": suggestions.get(str(member.id))} for member in unmapped_members],
            "issue_assignees": assignees,
        }
