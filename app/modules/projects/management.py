"""Create projects and link them to their delivery tracker.

The API never holds the GitLab or GitHub token. Listing remote projects and checking a link are
"probes": the API stores a request, the integration worker runs it and stores a sanitized result.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session, init_db
from app.models import (
    AuditEvent,
    IntegrationProbe,
    Project,
    ProjectIntegration,
    User,
    UserProjectAccess,
    WorkforceMember,
    WorkforceProjectMembership,
)
from app.modules.projects.service import OTHER_PROJECT_CODE


PROJECT_KINDS = ("IDEA", "NON_CODE", "SOFTWARE")
# Which links each kind needs. None means "not allowed". A software project also needs exactly one
# delivery system: the company GitLab or the customer's GitHub (ADR-0021).
KIND_RULES = {
    "IDEA": {"GITLAB": None, "GITHUB": None},
    "NON_CODE": {"GITLAB": None, "GITHUB": None},
    "SOFTWARE": {"GITLAB": "DELIVERY", "GITHUB": "DELIVERY"},
}
DELIVERY_SYSTEMS = ("GITLAB", "GITHUB")
GITHUB_TOKEN_NAME = re.compile(r"^GITHUB_TOKEN_[A-Z0-9_]{1,40}$")
CODE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
INTAKE_KEY_PATTERN = re.compile(r"^[A-Z]{2,8}$")
PROBE_MAX_AGE = timedelta(minutes=30)
PROBE_TASK = "intake.integration.probe"
PROBE_QUEUE = "integration.sync"


class ProjectError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _clean_reference(system: str, value: str | None) -> str | None:
    reference = (value or "").strip()
    if not reference:
        return None
    if system == "GITLAB":
        # Accept a pasted project URL as well as "group/project".
        reference = re.sub(r"^https?://[^/]+/", "", reference).strip("/")
        reference = re.sub(r"/-/.*$", "", reference).removesuffix(".git")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+(/[A-Za-z0-9_.\-]+)+", reference):
            raise ProjectError("GITLAB_PROJECT_PATH_INVALID", "GitLab project must look like group/project")
    elif system == "GITHUB":
        reference = re.sub(r"^https?://github\.com/", "", reference).strip("/").removesuffix(".git")
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+/[A-Za-z0-9_.\-]+", reference):
            raise ProjectError("GITHUB_REPOSITORY_INVALID", "GitHub repository must look like owner/repository")
    return reference


class ProjectManagementService:
    def __init__(self) -> None:
        init_db()

    # --- probes -----------------------------------------------------------------------------------

    def request_probe(
        self, system: str, action: str, reference: str | None, actor_id: str, publisher=None, token_ref: str | None = None,
    ) -> dict[str, object]:
        if action == "TOKENS" and system != "GITHUB":
            raise ProjectError("PROBE_ACTION_NOT_SUPPORTED", "Only GitHub uses a token per project")
        if action == "TOKENS":
            cleaned = None
        else:
            cleaned = _clean_reference(system, reference) if action in ("CHECK", "MEMBERS") else ((reference or "").strip()[:100] or None)
            if action in ("CHECK", "MEMBERS") and not cleaned:
                raise ProjectError("PROBE_REFERENCE_REQUIRED", "A project reference is required")
            if system == "GITHUB":
                # The worker needs to know which of its tokens to use; only the variable name travels.
                cleaned = _github_reference(token_ref, cleaned)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            probe = IntegrationProbe(
                id=str(uuid4()), system=system, action=action, reference=cleaned, status="PENDING",
                requested_by=actor_id, created_at=now,
            )
            session.add(probe)
            session.commit()
            probe_id = str(probe.id)
        try:
            (publisher or _publish)(probe_id)
        except Exception:
            # A probe is a user-triggered, retriable read: no outbox, the CTO just asks again.
            self.complete_probe(probe_id, error_code="QUEUE_UNAVAILABLE")
        return self.get_probe(probe_id)

    def get_probe(self, probe_id: str) -> dict[str, object]:
        with get_session() as session:
            probe = session.get(IntegrationProbe, probe_id)
            if probe is None:
                raise KeyError(probe_id)
            return {
                "id": str(probe.id), "system": probe.system, "action": probe.action, "reference": probe.reference,
                "status": probe.status, "result": probe.result, "error_code": probe.error_code,
            }

    def probe_request(self, probe_id: str) -> dict[str, str | None] | None:
        with get_session() as session:
            probe = session.get(IntegrationProbe, probe_id)
            if probe is None or probe.status != "PENDING":
                return None
            return {"system": probe.system, "action": probe.action, "reference": probe.reference}

    def complete_probe(self, probe_id: str, *, result: object | None = None, error_code: str | None = None) -> None:
        with get_session() as session:
            probe = session.get(IntegrationProbe, probe_id)
            if probe is None or probe.status != "PENDING":
                return
            probe.status = "FAILED" if error_code else "DONE"
            probe.result = None if error_code else result
            probe.error_code = error_code
            probe.completed_at = datetime.now(timezone.utc)
            session.commit()

    @staticmethod
    def _verified(session, probe_id: str | None, system: str, reference: str) -> dict:
        """A link is only saved after a fresh, successful check of exactly that reference."""
        probe = session.get(IntegrationProbe, probe_id) if probe_id else None
        fresh = probe is not None and probe.completed_at is not None and (
            datetime.now(timezone.utc) - _aware(probe.completed_at) <= PROBE_MAX_AGE
        )
        if (
            probe is None or probe.system != system or probe.action != "CHECK" or probe.status != "DONE"
            or probe.reference != reference or not fresh or not isinstance(probe.result, dict)
        ):
            raise ProjectError(f"{system}_LINK_NOT_VERIFIED", f"Check the {system} connection before saving")
        return probe.result

    # --- projects ---------------------------------------------------------------------------------

    def create(self, payload, actor_id: str) -> str:
        name = " ".join(payload.name.split())
        code = payload.code.strip().lower()
        intake_key = payload.intake_key.strip().upper()
        if not name:
            raise ProjectError("PROJECT_NAME_REQUIRED", "Project name is required")
        if not CODE_PATTERN.match(code):
            raise ProjectError("PROJECT_CODE_INVALID", "Code must be 2-32 lowercase letters, digits or hyphens, starting with a letter")
        if not INTAKE_KEY_PATTERN.match(intake_key):
            raise ProjectError("INTAKE_KEY_INVALID", "Intake key must be 2-8 capital letters")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            if session.scalar(select(Project.id).where(Project.code == code)):
                raise ProjectError("PROJECT_CODE_TAKEN", "Another project already uses this code")
            if session.scalar(select(Project.id).where(Project.intake_key == intake_key)):
                raise ProjectError("INTAKE_KEY_TAKEN", "Another project already uses this Intake key")
            project = Project(
                id=str(uuid4()), code=code, intake_key=intake_key, name=name[:255], kind=payload.kind,
                status="ACTIVE", project_settings={}, created_at=now, updated_at=now,
            )
            session.add(project)
            session.flush()
            links = self._apply_links(session, project, payload, now)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="project.created", entity_type="project", entity_id=project.id,
                details={"code": code, "kind": payload.kind, "links": links}, created_at=now,
            ))
            session.commit()
            return str(project.id)

    def report_codes(self, project_id: str) -> list[str]:
        with get_session() as session:
            project = session.get(Project, project_id)
            value = (project.project_settings or {}).get("report_codes") if project is not None else None
            return [str(code) for code in value] if isinstance(value, list) else []

    def save_report_codes(self, project_id: str, codes: list[str], actor_id: str) -> list[str]:
        """The other codes staff write for this project in daily reports; a report with one of them lands here
        instead of in the catch-all project (FR-EML-12). Upper case, no duplicates, at most 20."""
        now = datetime.now(timezone.utc)
        cleaned = list(dict.fromkeys(code.strip().upper() for code in codes if code and code.strip()))[:20]
        bad = next((code for code in cleaned if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,31}", code)), None)
        if bad:
            raise ValueError(f"REPORT_CODE_INVALID:{bad}:")
        with get_session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise KeyError(project_id)
            taken = {}
            for other in session.scalars(select(Project).where(Project.id != project.id, Project.status == "ACTIVE")).all():
                for code in ((other.project_settings or {}).get("report_codes") or []):
                    taken[str(code).strip().upper()] = other.code
                taken[other.code.upper()] = other.code
            clash = next((code for code in cleaned if code in taken), None)
            if clash:
                raise ValueError(f"REPORT_CODE_TAKEN:{clash}:{taken[clash]}")
            project.project_settings = {**(project.project_settings or {}), "report_codes": cleaned}
            project.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="project.report_codes_updated", entity_type="project", entity_id=project.id,
                details={"codes": cleaned}, created_at=now,
            ))
            session.commit()
        return cleaned

    def brief(self, project_id: str) -> str:
        with get_session() as session:
            project = session.get(Project, project_id)
            value = (project.project_settings or {}).get("brief") if project is not None else None
            return value if isinstance(value, str) else ""

    def save_brief(self, project_id: str, brief: str, actor_id: str) -> str:
        """What the product is, in the team's words. AI reads it with every request of this project (ADR-0032)."""
        now = datetime.now(timezone.utc)
        text = brief.strip()
        with get_session() as session:
            project = session.get(Project, project_id)
            if project is None:
                raise KeyError(project_id)
            # A new dict, so the JSON column is seen as changed.
            project.project_settings = {**(project.project_settings or {}), "brief": text}
            project.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="project.brief_updated", entity_type="project", entity_id=project.id,
                details={"length": len(text)}, created_at=now,
            ))
            session.commit()
        return text

    def update(self, project_ref: str, payload, actor_id: str) -> str:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = session.scalar(select(Project).where(Project.code == project_ref))
            if project is None and len(project_ref) == 36:
                project = session.get(Project, project_ref)
            if project is None:
                raise KeyError(project_ref)
            if payload.name is not None:
                name = " ".join(payload.name.split())
                if not name:
                    raise ProjectError("PROJECT_NAME_REQUIRED", "Project name is required")
                project.name = name[:255]
            if project.code == OTHER_PROJECT_CODE and (
                (payload.kind is not None and payload.kind != project.kind) or payload.status == "INACTIVE"
            ):
                # Daily Report work outside the declared projects is grouped here, so it must stay as it is.
                raise ProjectError("PROJECT_SYSTEM_MANAGED", "The catch-all project keeps its kind and stays active")
            if payload.kind is not None:
                project.kind = payload.kind
            if payload.status is not None:
                project.status = payload.status
            project.updated_at = now
            links = self._apply_links(session, project, payload, now)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="project.updated", entity_type="project", entity_id=project.id,
                details={"kind": project.kind, "status": project.status, "links": links}, created_at=now,
            ))
            session.commit()
            return str(project.id)

    def _apply_links(self, session, project: Project, payload, now: datetime) -> list[str]:
        settings = get_settings()
        rules = KIND_RULES[project.kind]
        existing = {
            mapping.system: mapping for mapping in session.scalars(
                select(ProjectIntegration).where(ProjectIntegration.project_id == project.id)
            ).all()
        }
        requested = {
            "GITLAB": (_clean_reference("GITLAB", payload.gitlab_project_path), payload.gitlab_probe_id),
            "GITHUB": (_clean_reference("GITHUB", payload.github_repository), payload.github_probe_id),
        }
        linked_delivery = {system for system in DELIVERY_SYSTEMS if existing.get(system) and existing[system].project_external_id}
        asked_delivery = {system for system in DELIVERY_SYSTEMS if requested[system][0]}
        if len(asked_delivery) > 1 or (asked_delivery and linked_delivery and asked_delivery != linked_delivery):
            # One source of truth per project; moving between GitLab and GitHub is not supported yet.
            raise ProjectError("DELIVERY_SYSTEM_CONFLICT", "A project has one delivery system: GitLab or GitHub")
        if rules["GITLAB"] == "DELIVERY" and not (asked_delivery or linked_delivery):
            raise ProjectError("DELIVERY_LINK_REQUIRED", "A software project must be linked to GitLab or to a GitHub repository")
        changed: list[str] = []
        for system, (reference, probe_id) in requested.items():
            current = existing.get(system)
            has_link = bool(current and current.project_external_id)
            if reference and rules[system] is None:
                raise ProjectError(f"{system}_NOT_ALLOWED_FOR_KIND", f"A {project.kind} project cannot be linked to {system}")
            if not reference:
                if rules[system] == "REQUIRED" and not has_link:
                    raise ProjectError(f"{system}_LINK_REQUIRED", f"A {project.kind} project must be linked to {system}")
                continue
            if has_link and current.project_external_id == reference:
                continue
            taken = session.scalar(select(ProjectIntegration.project_id).where(
                ProjectIntegration.system == system, ProjectIntegration.project_external_id == reference,
                ProjectIntegration.project_id != project.id,
            ))
            if taken:
                raise ProjectError(f"{system}_PROJECT_ALREADY_LINKED", f"That {system} project is already linked to another project")
            token_ref = None
            if system == "GITHUB":
                token_ref = (payload.github_token_ref or "").strip()
                verified = self._verified(session, probe_id, system, _github_reference(token_ref, reference))
            else:
                verified = self._verified(session, probe_id, system, reference)
            if system == "GITHUB":
                config = {"project_url": verified.get("url"), "project_name": verified.get("name"), "credential_ref": token_ref, "issue_style": "MINIMAL"}
                values = {
                    "base_url": "https://api.github.com", "workspace_external_id": None,
                    "credential_ref": token_ref, "enabled": True,
                }
            else:
                config = {"project_url": verified.get("url"), "project_name": verified.get("name")}
                values = {
                    "base_url": settings.gitlab_base_url, "workspace_external_id": None,
                    "credential_ref": "GITLAB_TOKEN", "enabled": bool(settings.gitlab_integration_enabled),
                }
            if current is None:
                session.add(ProjectIntegration(
                    id=str(uuid4()), project_id=str(project.id), system=system, project_external_id=reference,
                    config=config, created_at=now, updated_at=now, **values,
                ))
            else:
                current.project_external_id = reference
                current.config = {**(current.config or {}), **config}
                current.updated_at = now
                for key, value in values.items():
                    setattr(current, key, value)
            changed.append(system)
        return changed


class ProjectTeamService:
    """Who works on a project: exactly one Project Owner and any number of members, all from the staff list.

    The owner is the only one who logs in. Choosing an owner creates or unlocks their account and grants
    the project; replacing them removes the grant, and an account that owns no project any more is locked.
    """

    @staticmethod
    def _project(session, project_ref: str) -> Project:
        project = session.scalar(select(Project).where(Project.code == project_ref))
        if project is None and len(project_ref) == 36:
            project = session.get(Project, project_ref)
        if project is None:
            raise KeyError(project_ref)
        return project

    def get(self, project_ref: str) -> dict[str, object]:
        with get_session() as session:
            return self._view(session, self._project(session, project_ref))

    @staticmethod
    def _view(session, project: Project) -> dict[str, object]:
        rows = session.execute(
            select(WorkforceProjectMembership, WorkforceMember)
            .join(WorkforceMember, WorkforceMember.id == WorkforceProjectMembership.member_id)
            .where(
                WorkforceProjectMembership.project_id == project.id,
                WorkforceProjectMembership.active.is_(True),
                WorkforceMember.status == "ACTIVE",
            )
            .order_by(WorkforceMember.display_name)
        ).all()
        accounts = {str(user.member_id): user for user in session.scalars(select(User).where(User.member_id.is_not(None))).all()}
        owner_id = str(project.owner_member_id) if project.owner_member_id else None
        members = []
        for membership, member in rows:
            account = accounts.get(str(member.id))
            members.append({
                "member_id": str(member.id), "display_name": member.display_name, "email": member.email_reference,
                "is_owner": str(member.id) == owner_id, "delivery_user_id": membership.gitlab_user_external_id,
                "account_subject": account.auth_subject if account else None,
                "account_active": bool(account and account.is_active),
            })
        members.sort(key=lambda row: (not row["is_owner"], str(row["display_name"]).lower()))
        return {"project_id": str(project.id), "project_code": project.code, "owner_member_id": owner_id, "members": members}

    def set(self, project_ref: str, owner_member_id: str | None, member_ids: list[str], actor_id: str) -> dict[str, object]:
        from app.modules.identity.service import IdentityError, identity_service

        now = datetime.now(timezone.utc)
        with get_session() as session:
            project = self._project(session, project_ref)
            wanted = list(dict.fromkeys(str(value) for value in member_ids))
            # The owner also works on the project.
            if owner_member_id and str(owner_member_id) not in wanted:
                wanted.insert(0, str(owner_member_id))
            staff = {str(row.id): row for row in session.scalars(select(WorkforceMember).where(WorkforceMember.id.in_(wanted))).all()} if wanted else {}
            for member_id in wanted:
                if member_id not in staff or staff[member_id].status != "ACTIVE":
                    raise ProjectError("MEMBER_NOT_ACTIVE", "A chosen staff member does not exist or is inactive")

            existing = {str(row.member_id): row for row in session.scalars(
                select(WorkforceProjectMembership).where(WorkforceProjectMembership.project_id == project.id)
            ).all()}
            for member_id in wanted:
                row = existing.get(member_id)
                if row is None:
                    session.add(WorkforceProjectMembership(
                        id=str(uuid4()), member_id=member_id, project_id=project.id, gitlab_user_external_id=None,
                        role=None, active=True, created_at=now, updated_at=now,
                    ))
                elif not row.active:
                    row.active, row.updated_at = True, now
            for member_id, row in existing.items():
                if member_id not in wanted and row.active:
                    row.active, row.updated_at = False, now

            issued: dict[str, str] | None = None
            previous = str(project.owner_member_id) if project.owner_member_id else None
            new_owner = str(owner_member_id) if owner_member_id else None
            if previous != new_owner:
                if previous:
                    self._release(session, previous, project, now)
                if new_owner:
                    try:
                        user, password = identity_service.owner_account(session, staff[new_owner], actor_id)
                    except IdentityError as error:
                        raise ProjectError(error.code, error.message) from error
                    if user.role != "CTO" and session.get(UserProjectAccess, (user.id, project.id)) is None:
                        session.add(UserProjectAccess(user_id=user.id, project_id=project.id, granted_by=actor_id))
                    if password:
                        issued = {"subject": user.auth_subject, "display_name": user.display_name, "temporary_password": password}
                project.owner_member_id = new_owner
            project.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="project.team_changed", entity_type="project", entity_id=project.id,
                details={"owner_member_id": new_owner, "previous_owner_member_id": previous, "member_ids": wanted}, created_at=now,
            ))
            session.commit()
            return {**self._view(session, project), "issued": issued}

    @staticmethod
    def _release(session, member_id: str, project: Project, now: datetime) -> None:
        """Take a project away from its former owner; lock the account when it owns nothing any more."""
        user = session.scalar(select(User).where(User.member_id == member_id))
        if user is None:
            return
        grant = session.get(UserProjectAccess, (user.id, project.id))
        if grant is not None:
            session.delete(grant)
            session.flush()
        still_owns = session.scalar(select(Project.id).where(Project.owner_member_id == member_id, Project.id != project.id))
        if not still_owns and user.role != "CTO":
            user.is_active = False
            user.updated_at = now


def _github_reference(token_ref: str | None, reference: str | None) -> str:
    token = (token_ref or "").strip()
    if not GITHUB_TOKEN_NAME.match(token):
        raise ProjectError("GITHUB_TOKEN_NAME_INVALID", "Choose the token for this repository (a GITHUB_TOKEN_* variable)")
    return f"{token}|{reference or ''}"


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; PostgreSQL returns aware ones.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _publish(probe_id: str) -> None:
    from app.queue.celery_app import celery_app

    celery_app.send_task(PROBE_TASK, args=[probe_id], queue=PROBE_QUEUE)


project_management_service = ProjectManagementService()

project_team_service = ProjectTeamService()
