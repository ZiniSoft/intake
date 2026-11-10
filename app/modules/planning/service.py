from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import get_session, init_db
from app.modules.planning import personal as personal_tasks
from app.models import (
    AuditEvent,
    DailyCapacity,
    EmailMessage,
    ExternalLink,
    GitLabIssueSnapshot,
    IntakeItem,
    IssueVerification,
    OutboxEvent,
    PlanningApprovalSnapshot,
    PlanningAssignment,
    PlanningCandidate,
    PlanningRun,
    PlanningSyncJob,
    PlanningWarning,
    Project,
    ProjectIntegration,
    ReportItem,
    SourceMessage,
    WorkforceMember,
    WorkforceProjectMembership,
)
from app.modules.planning.cto import CtoStaffError, cto_member_ids, ensure_cto_member, is_cto_member, link_cto_login
from app.modules.planning.gitlab_read_model import (
    DONE_EVIDENCE_CHOICES,
    LEVEL_ACCEPTED,
    LEVEL_NAMES,
    done_level,
    evidence_summary,
)
from app.modules.reports.service import late_cutoff, normalized_task_title, usable_for_planning
from app.schemas import (
    CapacityUpdate,
    PlanningApprovalRequest,
    PlanningAssignmentCreate,
    PlanningCandidatePromoteRequest,
    PlanningQuickAddRequest,
    PlanningRunCreate,
    WorkforceMemberCreate,
)


PLANNING_SYNC_EVENT = "planning.gitlab-update.requested.v1"
DELIVERY_WORK_TYPES = {"DEVELOPMENT", "REVIEW", "QA"}
MUTABLE_RUN_STATES = {"DRAFT", "REVIEW_REQUIRED"}
# A closed plan: approved, and whatever the GitLab sync made of it. Reopening makes a new revision (FR-PLAN-18).
CLOSED_RUN_STATES = {"APPROVED", "SYNCING", "SYNCED", "SYNC_FAILED", "PARTIAL"}
SYNC_OPEN_STATES = ("PENDING", "RUNNING", "RETRY")
# Warnings that do not stop a plan but must be seen by whoever closes it (ADR-0013).
MISSING_FIELD_WARNINGS = ("GITLAB_MILESTONE_MISSING", "GITLAB_DUE_DATE_MISSING")
# How many closed Issues the CTO is asked to look at per day, and how far back a closed Issue is still offered.
VERIFICATIONS_PER_DAY = 2
VERIFICATION_WINDOW_DAYS = 7
# Report statuses that mean the work continues the next working day.
REPORT_CARRY_OVER_STATUSES = {"PLANNED", "IN_PROGRESS", "PENDING_REVIEW", "BLOCKED"}
REPORT_STATUS_RANK = {"PLANNED": 1, "BLOCKED": 2, "IN_PROGRESS": 3, "PENDING_REVIEW": 4}
# What a placed piece of work can be reported as (FR-MCP-06, FR-PLAN-34); anything but DONE carries over to the next day.
WORK_STATUSES = ("PLANNED", "IN_PROGRESS", "DONE", "BLOCKED")
WORK_STATUS_LABELS = {"PLANNED": "chưa bắt đầu", "IN_PROGRESS": "đang làm", "DONE": "xong", "BLOCKED": "bị chặn"}
CARRY_OVER_REFERENCE = "Kế hoạch "


class PlanningValidationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PlanningSyncContext:
    job_id: str
    planning_run_id: str
    project_external_id: str
    gitlab_issue_external_id: str
    idempotency_key: str
    update_payload: dict[str, object]
    attempt: int
    max_attempts: int


def _number(value: Decimal | float | int | None) -> float | None:
    return None if value is None else float(value)


def _as_utc(value: datetime | None) -> datetime | None:
    """SQLite hands back naive datetimes; they were stored in UTC."""
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


class PlanningService:
    def __init__(self) -> None:
        init_db()

    @staticmethod
    def _resolve_project(session, value: str) -> Project:
        project = None
        try:
            UUID(value)
            project = session.get(Project, value)
        except ValueError:
            project = session.scalar(select(Project).where(Project.code == value))
        if project is None or project.status != "ACTIVE":
            raise PlanningValidationError("PROJECT_NOT_ACTIVE", "Project does not exist or is inactive")
        return project

    def create_member(self, payload: WorkforceMemberCreate, actor_id: str) -> dict[str, object]:
        if payload.timezone != "Asia/Ho_Chi_Minh":
            raise PlanningValidationError("UNSUPPORTED_TIMEZONE", "Pilot planning timezone must be Asia/Ho_Chi_Minh")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            member = WorkforceMember(
                id=str(uuid4()),
                display_name=payload.display_name.strip(),
                email_reference=payload.email_reference.strip().lower() if payload.email_reference else None,
                status="ACTIVE",
                timezone=payload.timezone,
                default_weekday_hours=payload.default_weekday_hours,
                created_at=now,
                updated_at=now,
            )
            session.add(member)
            link_cto_login(session, member, now)
            seen_projects: set[str] = set()
            for mapping_payload in payload.project_mappings:
                project = self._resolve_project(session, mapping_payload.project_id)
                project_id = str(project.id)
                if project_id in seen_projects:
                    raise PlanningValidationError("DUPLICATE_PROJECT_MAPPING", "Project mapping is duplicated")
                seen_projects.add(project_id)
                session.add(
                    WorkforceProjectMembership(
                        id=str(uuid4()),
                        member_id=member.id,
                        project_id=project_id,
                        gitlab_user_external_id=mapping_payload.gitlab_user_external_id.strip(),
                        role=mapping_payload.role.strip() if mapping_payload.role else None,
                        active=True,
                        created_at=now,
                        updated_at=now,
                    )
                )
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    actor_type="USER",
                    actor_id=actor_id,
                    event_type="planning.member.created",
                    entity_type="workforce_member",
                    entity_id=member.id,
                    details={"project_ids": sorted(seen_projects)},
                    created_at=now,
                )
            )
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise PlanningValidationError("MEMBER_CONFLICT", "Workforce member or mapping already exists") from exc
            return self._member_dict(session, member)

    def add_myself(self, user_id: str, actor_id: str) -> dict[str, object]:
        """The CTO's own staff record, made or linked in one click (FR-PLAN-37); a second click returns the same."""
        with get_session() as session:
            try:
                member = ensure_cto_member(session, user_id, actor_id)
            except CtoStaffError as exc:
                raise PlanningValidationError(exc.code, exc.message) from exc
            session.commit()
            return self._member_dict(session, member)

    def list_members(self, include_inactive: bool = False) -> list[dict[str, object]]:
        with get_session() as session:
            query = select(WorkforceMember).order_by(WorkforceMember.display_name)
            if not include_inactive:
                query = query.where(WorkforceMember.status == "ACTIVE")
            return [self._member_dict(session, member) for member in session.scalars(query).all()]

    def update_member(self, member_id: str, payload, actor_id: str) -> dict[str, object]:
        """Replace a member's details and project assignments; a project left out is switched off, not deleted."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            member = session.get(WorkforceMember, member_id)
            if member is None:
                raise KeyError(member_id)
            member.display_name = " ".join(payload.display_name.split())
            member.email_reference = payload.email_reference.strip().lower() if (payload.email_reference or "").strip() else None
            member.default_weekday_hours = payload.default_weekday_hours
            member.status = payload.status
            member.updated_at = now
            existing = {
                str(row.project_id): row for row in session.scalars(
                    select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member.id)
                ).all()
            }
            wanted: dict[str, object] = {}
            for mapping_payload in payload.project_mappings:
                project = self._resolve_project(session, mapping_payload.project_id)
                if str(project.id) in wanted:
                    raise PlanningValidationError("DUPLICATE_PROJECT_MAPPING", "Project mapping is duplicated")
                gitlab_user = (mapping_payload.gitlab_user_external_id or "").strip() or None
                if gitlab_user and project.kind != "SOFTWARE":  # the column also holds a GitHub user ID
                    raise PlanningValidationError("GITLAB_USER_NOT_APPLICABLE", "Only software projects have a GitLab user")
                wanted[str(project.id)] = (gitlab_user, (mapping_payload.role or "").strip() or None)
            for project_id, (gitlab_user, role) in wanted.items():
                row = existing.get(project_id)
                if row is None:
                    session.add(WorkforceProjectMembership(
                        id=str(uuid4()), member_id=member.id, project_id=project_id,
                        gitlab_user_external_id=gitlab_user, role=role, active=True, created_at=now, updated_at=now,
                    ))
                else:
                    row.gitlab_user_external_id, row.role, row.active, row.updated_at = gitlab_user, role, True, now
            owned = {str(value) for value in session.scalars(select(Project.id).where(Project.owner_member_id == member.id)).all()}
            if payload.status != "ACTIVE" and owned:
                raise PlanningValidationError("MEMBER_OWNS_PROJECT", "Choose another Project Owner before deactivating this person")
            for project_id, row in existing.items():
                if project_id not in wanted and row.active:
                    if project_id in owned:
                        raise PlanningValidationError("MEMBER_OWNS_PROJECT", "The Project Owner stays a member; change the owner on the project first")
                    row.active, row.updated_at = False, now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="planning.member.updated",
                entity_type="workforce_member", entity_id=member.id,
                details={"project_ids": sorted(wanted), "status": payload.status}, created_at=now,
            ))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise PlanningValidationError("MEMBER_CONFLICT", "Another member already uses this email") from exc
            return self._member_dict(session, member)

    @staticmethod
    def _member_dict(session, member: WorkforceMember) -> dict[str, object]:
        mappings = session.scalars(
            select(WorkforceProjectMembership)
            .where(WorkforceProjectMembership.member_id == member.id)
            .order_by(WorkforceProjectMembership.project_id)
        ).all()
        return {
            "id": str(member.id),
            "display_name": member.display_name,
            "email_reference": member.email_reference,
            "status": member.status,
            "timezone": member.timezone,
            "default_weekday_hours": float(member.default_weekday_hours),
            "telegram_linked": bool(member.telegram_chat_id),
            "telegram_username": member.telegram_username,
            "telegram_invite_pending": bool(member.telegram_invite_code),
            "is_cto": is_cto_member(session, member),
            "project_mappings": [
                {
                    "project_id": str(mapping.project_id),
                    "gitlab_user_external_id": mapping.gitlab_user_external_id,
                    "role": mapping.role,
                    "active": mapping.active,
                }
                for mapping in mappings
            ],
        }

    @staticmethod
    def _default_base(member: WorkforceMember, work_date: date) -> float:
        return float(member.default_weekday_hours) if work_date.weekday() < 5 else 0.0

    def list_capacities(self, work_date: date, project_ref: str | None = None) -> list[dict[str, object]]:
        """Capacity of the people who can be planned in a scope: one project's team, or every software project's.

        A person's hours are for the whole day. Hours already planned for projects outside the scope are
        shown and subtracted, without saying what that other work is.
        """
        with get_session() as session:
            if project_ref:
                projects = [self._resolve_project(session, project_ref)]
            else:
                projects = list(session.scalars(select(Project).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE")).all())
            scope = [str(project.id) for project in projects]
            member_ids = {str(value) for value in session.scalars(select(WorkforceProjectMembership.member_id).where(
                WorkforceProjectMembership.project_id.in_(scope), WorkforceProjectMembership.active.is_(True),
            )).all()} if scope else set()
            owner_id = str(projects[0].owner_member_id) if project_ref and projects[0].owner_member_id else None
            members = [member for member in session.scalars(
                select(WorkforceMember).where(WorkforceMember.status == "ACTIVE").order_by(WorkforceMember.display_name)
            ).all() if str(member.id) in member_ids]
            members.sort(key=lambda member: (str(member.id) != owner_id, member.display_name.lower()))
            stored = {
                str(row.member_id): row
                for row in session.scalars(select(DailyCapacity).where(DailyCapacity.work_date == work_date)).all()
            }
            rows = []
            cto_ids = cto_member_ids(session)
            for member in members:
                row = self._capacity_dict(session, member, work_date, stored.get(str(member.id)))
                elsewhere = self._hours_elsewhere(session, str(member.id), work_date, scope)
                row.update({
                    "is_owner": str(member.id) == owner_id, "is_cto": str(member.id) in cto_ids, "planned_elsewhere_hours": elsewhere,
                    "planned_elsewhere": self._hours_elsewhere_by_project(session, str(member.id), work_date, scope),
                    "remaining_hours": max(float(row["available_hours"]) - elsewhere, 0.0),
                })
                rows.append(row)
            return rows

    @staticmethod
    def _hours_elsewhere(session, member_id: str, plan_date: date, scope: list, exclude_run_id: str | None = None) -> float:
        """Hours a person already has that day in plans for projects outside `scope`."""
        query = (
            select(func.coalesce(func.sum(PlanningAssignment.planned_hours), 0))
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(
                PlanningRun.plan_date == plan_date, PlanningRun.status != "SUPERSEDED",
                PlanningAssignment.member_id == member_id,
            )
        )
        if scope:
            query = query.where(PlanningAssignment.project_id.notin_([str(value) for value in scope]))
        if exclude_run_id:
            query = query.where(PlanningRun.id != exclude_run_id)
        return float(session.scalar(query) or 0)

    @staticmethod
    def _hours_elsewhere_by_project(session, member_id: str, plan_date: date, scope: list, exclude_run_id: str | None = None) -> list[dict[str, object]]:
        """The same hours, named: which other project's plan has them (FR-PLAN-28). Only the project's name and
        the hours leave that plan; its work stays with its own team."""
        query = (
            select(PlanningAssignment.project_id, func.coalesce(func.sum(PlanningAssignment.planned_hours), 0))
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(PlanningRun.plan_date == plan_date, PlanningRun.status != "SUPERSEDED", PlanningAssignment.member_id == member_id)
            .group_by(PlanningAssignment.project_id)
        )
        if scope:
            query = query.where(PlanningAssignment.project_id.notin_([str(value) for value in scope]))
        if exclude_run_id:
            query = query.where(PlanningRun.id != exclude_run_id)
        rows = session.execute(query).all()
        names = {str(project.id): project.name for project in session.scalars(select(Project).where(Project.id.in_([str(pid) for pid, _ in rows]))).all()} if rows else {}
        return [
            {"project_id": str(project_id), "project_name": names.get(str(project_id), "Dự án khác"), "hours": round(float(hours or 0), 2)}
            for project_id, hours in sorted(rows, key=lambda pair: names.get(str(pair[0]), "").casefold())
            if float(hours or 0) > 0
        ]

    def update_capacity(
        self,
        member_id: str,
        work_date: date,
        payload: CapacityUpdate,
        actor_id: str,
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            member = session.get(WorkforceMember, member_id)
            if member is None or member.status != "ACTIVE":
                raise KeyError(member_id)
            row = session.scalar(
                select(DailyCapacity)
                .where(DailyCapacity.member_id == member_id, DailyCapacity.work_date == work_date)
                .with_for_update()
            )
            current_version = row.version if row else 0
            if payload.expected_version != current_version:
                raise PlanningValidationError("CAPACITY_VERSION_CONFLICT", "Capacity changed; reload before saving")
            base = self._default_base(member, work_date)
            if payload.override_hours is not None and not (payload.reason or "").strip():
                raise PlanningValidationError("OVERRIDE_REASON_REQUIRED", "Capacity override requires a reason")
            effective = payload.override_hours if payload.override_hours is not None else base
            deductions = payload.meeting_hours + payload.review_hours + payload.support_hours + payload.fixed_hours
            available = round(effective - deductions, 2)
            if available < 0:
                raise PlanningValidationError("CAPACITY_NEGATIVE", "Capacity deductions exceed confirmed work hours")
            if row is None:
                row = DailyCapacity(
                    id=str(uuid4()),
                    member_id=member_id,
                    work_date=work_date,
                    version=1,
                    created_at=now,
                )
                session.add(row)
            else:
                row.version += 1
            row.base_hours = base
            row.override_hours = payload.override_hours
            row.meeting_hours = payload.meeting_hours
            row.review_hours = payload.review_hours
            row.support_hours = payload.support_hours
            row.fixed_hours = payload.fixed_hours
            row.available_hours = available
            row.override_reason = payload.reason.strip() if payload.reason else None
            row.updated_by = actor_id
            row.updated_at = now
            session.add(
                AuditEvent(
                    id=str(uuid4()),
                    actor_type="USER",
                    actor_id=actor_id,
                    event_type="planning.capacity.updated",
                    entity_type="daily_capacity",
                    entity_id=row.id,
                    details={"member_id": member_id, "work_date": work_date.isoformat(), "version": row.version},
                    created_at=now,
                )
            )
            session.commit()
            return self._capacity_dict(session, member, work_date, row)

    def _capacity_dict(
        self,
        session,
        member: WorkforceMember,
        work_date: date,
        row: DailyCapacity | None,
    ) -> dict[str, object]:
        """A person's hours for the day. Their own tasks (FR-PER-02) come off `available_hours` as `personal_hours`,
        shown as a number only: what the tasks are stays with the person."""
        base = self._default_base(member, work_date)
        personal = personal_tasks.reserved_hours(session, str(member.id), work_date)
        if row is None:
            return {
                "member_id": str(member.id), "display_name": member.display_name, "work_date": work_date,
                "base_hours": base, "override_hours": None, "meeting_hours": 0.0, "review_hours": 0.0,
                "support_hours": 0.0, "fixed_hours": 0.0, "personal_hours": personal, "available_hours": max(base - personal, 0.0),
                "override_reason": None, "version": 0,
            }
        return {
            "member_id": str(member.id), "display_name": member.display_name, "work_date": work_date,
            "base_hours": _number(row.base_hours), "override_hours": _number(row.override_hours),
            "meeting_hours": _number(row.meeting_hours), "review_hours": _number(row.review_hours),
            "support_hours": _number(row.support_hours), "fixed_hours": _number(row.fixed_hours),
            "personal_hours": personal, "available_hours": max(_number(row.available_hours) - personal, 0.0), "override_reason": row.override_reason,
            "version": row.version,
        }

    def create_run(self, payload: PlanningRunCreate, actor_id: str) -> dict[str, object]:
        if payload.timezone != "Asia/Ho_Chi_Minh":
            raise PlanningValidationError("UNSUPPORTED_TIMEZONE", "Pilot planning timezone must be Asia/Ho_Chi_Minh")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            if payload.project_ids:
                projects = [self._resolve_project(session, project_id) for project_id in payload.project_ids]
                if any(project.kind != "SOFTWARE" for project in projects):
                    # Planning assignments must reference a GitLab Issue, so only software projects are planned.
                    raise PlanningValidationError("PROJECT_NOT_PLANNABLE", "Only software projects, which have GitLab, are planned")
            else:
                projects = session.scalars(select(Project).where(
                    Project.status == "ACTIVE", Project.kind == "SOFTWARE",
                ).order_by(Project.id)).all()
            project_ids = sorted({str(project.id) for project in projects})
            if not project_ids:
                raise PlanningValidationError("PLANNING_SCOPE_EMPTY", "Planning scope has no active project")
            scope_hash = _canonical_hash(project_ids)
            existing = session.scalar(
                select(PlanningRun).where(
                    PlanningRun.plan_date == payload.plan_date,
                    PlanningRun.scope_hash == scope_hash,
                    PlanningRun.status != "SUPERSEDED",
                ).order_by(PlanningRun.revision.desc())
            )
            if existing is not None:
                # Reports confirmed, and requests given an Issue, after the run was created still reach it while it can be edited.
                if existing.status in MUTABLE_RUN_STATES and (self._add_report_candidates(session, existing) + self._add_intake_candidates(session, existing) + self._add_carry_over_candidates(session, existing)):
                    existing.status = "REVIEW_REQUIRED"
                    existing.version += 1
                    existing.updated_at = now
                if existing.status in MUTABLE_RUN_STATES:
                    self._pick_verifications(session, existing)
                session.commit()
                return self._run_dict(session, existing)
            run = PlanningRun(
                id=str(uuid4()), plan_date=payload.plan_date, timezone=payload.timezone,
                project_scope=project_ids, scope_hash=scope_hash, status="DRAFT", version=1, revision=1,
                source_snapshot_at=now, created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(run)
            session.flush()
            self._add_report_warnings(session, run)
            self._add_source_conflicts(session, run)
            generated = self._generate_proposals(session, run)
            report_candidates = self._add_report_candidates(session, run)
            intake_candidates = self._add_intake_candidates(session, run)
            carried = self._add_carry_over_candidates(session, run)
            picked = self._pick_verifications(session, run)
            if generated or report_candidates or intake_candidates or carried:
                run.status = "REVIEW_REQUIRED"
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id,
                event_type="planning.run.created", entity_type="planning_run", entity_id=run.id,
                details={
                    "plan_date": payload.plan_date.isoformat(),
                    "project_ids": project_ids,
                    "generated_assignments": generated,
                    "report_candidates": report_candidates,
                    "intake_candidates": intake_candidates,
                    "carried_over": carried,
                    "verifications": picked,
                },
                created_at=now,
            ))
            session.commit()
            return self._run_dict(session, run)

    # ---- Spot checks of closed Issues (FR-PLAN-22) ------------------------------------------------------------

    @staticmethod
    def _done_evidence_of(session, project_id: str) -> str:
        project = session.get(Project, project_id)
        value = str(((project.project_settings if project else None) or {}).get("done_evidence") or "COMMIT")
        return value if value in DONE_EVIDENCE_CHOICES else "COMMIT"

    def _pick_verifications(self, session, run: PlanningRun) -> int:
        """One or two Issues closed lately, for the CTO to look at today: the ones with the least behind them first,
        then the project looked at least recently. An Issue is offered once; a run that has its picks keeps them."""
        if session.scalar(select(IssueVerification.id).where(IssueVerification.planning_run_id == run.id)):
            return 0
        scope = list(run.project_scope)
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=VERIFICATION_WINDOW_DAYS)
        offered = {
            (str(row.project_id), row.issue_external_id)
            for row in session.scalars(select(IssueVerification).where(IssueVerification.project_id.in_(scope))).all()
        }
        last_look: dict[str, datetime] = {}
        for row in session.scalars(select(IssueVerification).where(IssueVerification.project_id.in_(scope))).all():
            created = row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=timezone.utc)
            last_look[str(row.project_id)] = max(last_look.get(str(row.project_id), since), created)
        rules = {project_id: self._done_evidence_of(session, project_id) for project_id in scope}
        candidates = []
        for issue in session.scalars(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.project_id.in_(scope), GitLabIssueSnapshot.is_current.is_(True),
            GitLabIssueSnapshot.state == "closed", GitLabIssueSnapshot.closed_at.is_not(None), GitLabIssueSnapshot.closed_at >= since,
        )).all():
            key = (str(issue.project_id), issue.issue_external_id)
            if key in offered:
                continue
            level = done_level(issue.state, issue.evidence, rules[str(issue.project_id)])
            closed = issue.closed_at if issue.closed_at.tzinfo else issue.closed_at.replace(tzinfo=timezone.utc)
            candidates.append((level, last_look.get(str(issue.project_id), since), -closed.timestamp(), issue))
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        picked = 0
        for level, _, _, issue in candidates[:VERIFICATIONS_PER_DAY]:
            session.add(IssueVerification(
                id=str(uuid4()), project_id=issue.project_id, issue_external_id=issue.issue_external_id,
                planning_run_id=run.id, evidence_level=level, decision="PENDING", created_at=now,
            ))
            picked += 1
        if picked:
            session.flush()
        return picked

    def _verification_dicts(self, session, run: PlanningRun) -> list[dict[str, object]]:
        rows = session.scalars(select(IssueVerification).where(
            IssueVerification.planning_run_id == run.id,
        ).order_by(IssueVerification.evidence_level, IssueVerification.created_at)).all()
        if not rows:
            return []
        members = {
            (str(m.project_id), m.gitlab_user_external_id): str(m.member_id)
            for m in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.gitlab_user_external_id.is_not(None))).all()
        }
        out = []
        for row in rows:
            issue = self._current_gitlab_issue(session, str(row.project_id), row.issue_external_id)
            rule = self._done_evidence_of(session, str(row.project_id))
            link = session.scalar(select(ExternalLink).where(
                ExternalLink.project_id == row.project_id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")),
                ExternalLink.external_id == row.issue_external_id,
            ))
            intake = session.get(IntakeItem, link.intake_id) if link is not None else None
            acceptance = [str(item) for item in ((intake.normalized_details or {}).get("acceptance") or []) if str(item).strip()] if intake else []
            accepted = row.decision == "ACCEPTED"
            level = done_level(issue.state, issue.evidence, rule, accepted) if issue is not None else (LEVEL_ACCEPTED if accepted else row.evidence_level)
            assignees = list(issue.assignee_external_ids or []) if issue is not None else []
            out.append({
                "id": str(row.id), "planning_run_id": str(row.planning_run_id) if row.planning_run_id else None,
                "project_id": str(row.project_id), "issue_external_id": row.issue_external_id,
                "title": issue.title if issue is not None else f"Issue #{row.issue_external_id}",
                "web_url": issue.web_url if issue is not None else None,
                "closed_at": issue.closed_at if issue is not None else None,
                "closed_by_member_id": members.get((str(row.project_id), issue.closed_by_external_id)) if issue is not None and issue.closed_by_external_id else None,
                "assignee_member_id": next((members[(str(row.project_id), a)] for a in assignees if (str(row.project_id), a) in members), None),
                "level": level, "level_name": LEVEL_NAMES.get(level, str(level)), "done_evidence": rule,
                "evidence": evidence_summary(issue.evidence if issue is not None else None),
                "evidence_fetched_at": issue.evidence_fetched_at if issue is not None else None,
                "intake_id": str(intake.id) if intake else None, "intake_public_id": intake.public_id if intake else None,
                "acceptance": acceptance[:12], "decision": row.decision, "reason": row.reason, "decided_at": row.decided_at,
            })
        return out

    def decide_verification(self, run_id: str, verification_id: str, decision: str, expected_version: int, reason: str | None, actor_id: str) -> dict[str, object]:
        """The CTO looked: the Issue is done, or it is not. "Not" sends it back to the day's waiting list and warns
        the person who had it; the Issue on GitLab is not reopened from here (ADR-0045)."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.get(PlanningRun, run_id)
            row = session.get(IssueVerification, verification_id)
            if run is None or row is None or str(row.planning_run_id) != str(run.id):
                raise KeyError("verification")
            if run.version != expected_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run version changed")
            if row.decision != "PENDING":
                raise PlanningValidationError("VERIFICATION_DECIDED", "This Issue was already looked at")
            if decision == "REJECTED" and not (reason or "").strip():
                raise PlanningValidationError("REASON_REQUIRED", "Say what is not done yet")
            issue = self._current_gitlab_issue(session, str(row.project_id), row.issue_external_id)
            row.decision, row.reason, row.decided_by, row.decided_at = decision, (reason or "").strip() or None, actor_id, now
            if decision == "REJECTED" and issue is not None:
                member_id = None
                for a in issue.assignee_external_ids or []:
                    member_id = session.scalar(select(WorkforceProjectMembership.member_id).where(
                        WorkforceProjectMembership.project_id == row.project_id, WorkforceProjectMembership.gitlab_user_external_id == a,
                    ))
                    if member_id:
                        break
                key_hash = hashlib.sha256(f"verification:{row.id}".encode("utf-8")).hexdigest()
                if run.status in MUTABLE_RUN_STATES and not session.scalar(select(PlanningCandidate.id).where(PlanningCandidate.idempotency_key_hash == key_hash)):
                    session.add(PlanningCandidate(
                        id=str(uuid4()), planning_run_id=run.id, project_id=row.project_id, member_id=member_id,
                        intake_id=None, assignment_id=None, source_type="VERIFICATION", source_reference=f"Issue #{row.issue_external_id}",
                        gitlab_issue_external_id=row.issue_external_id,
                        title=f"Làm lại: {issue.title}"[:255],
                        summary=f"CTO xem lại ngày {now.date().isoformat()}: chưa xong. {row.reason or ''}".strip(),
                        status="READY", proposed_priority=self._priority_from_labels(issue.labels),
                        requested_hours=None, target_slot=None, idempotency_key_hash=key_hash, request_hash=None,
                        created_by=actor_id, created_at=now, updated_at=now,
                    ))
                session.add(PlanningWarning(
                    id=str(uuid4()), planning_run_id=run.id, assignment_id=None, member_id=member_id, project_id=row.project_id,
                    code="ISSUE_NOT_DONE_AFTER_CLOSE", severity="WARNING",
                    source_values={"issue": row.issue_external_id, "reason": row.reason},
                    message=f"Issue #{row.issue_external_id} was closed but the CTO found it not done: {row.reason}",
                    created_at=now,
                ))
                if run.status in MUTABLE_RUN_STATES:
                    run.status = "REVIEW_REQUIRED"
            run.version += 1
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id,
                event_type="planning.issue.verified", entity_type="planning_run", entity_id=run.id,
                details={"issue": row.issue_external_id, "decision": decision, "level_at_pick": row.evidence_level, "reason": row.reason},
                created_at=now,
            ))
            session.commit()
            return self._run_dict(session, run)

    def set_agent_ready(self, project_ref: str, value: bool, actor_id: str) -> dict[str, object]:
        """The repo of this project is set up for an agent (CLAUDE.md, a test command, seed data): a point on the
        readiness score of every request of the project (FR-MCP-04)."""
        with get_session() as session:
            project = self._resolve_project(session, project_ref)
            settings = dict(project.project_settings or {})
            settings["agent_ready"] = bool(value)
            project.project_settings = settings
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="planning.agent-ready.changed", entity_type="project", entity_id=project.id,
                details={"agent_ready": bool(value)}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            return {"project_id": str(project.id), "agent_ready": bool(value)}

    def set_done_evidence(self, project_ref: str, value: str, actor_id: str) -> dict[str, object]:
        if value not in DONE_EVIDENCE_CHOICES:
            raise PlanningValidationError("DONE_EVIDENCE_UNKNOWN", "Unknown done-evidence rule")
        with get_session() as session:
            project = self._resolve_project(session, project_ref)
            settings = dict(project.project_settings or {})
            settings["done_evidence"] = value
            project.project_settings = settings
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="planning.done-evidence.changed", entity_type="project", entity_id=project.id,
                details={"done_evidence": value}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            return {"project_id": str(project.id), "done_evidence": value}

    def set_acceptance_policy(self, project_ref: str, value: str, actor_id: str) -> dict[str, object]:
        if value not in ("CTO_ALWAYS", "PO_FINAL_LOW_RISK"):
            raise PlanningValidationError("ACCEPTANCE_POLICY_UNKNOWN", "Unknown acceptance policy")
        with get_session() as session:
            project = self._resolve_project(session, project_ref)
            settings = dict(project.project_settings or {})
            before = settings.get("acceptance_policy") or "CTO_ALWAYS"
            settings["acceptance_policy"] = value
            project.project_settings = settings
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="planning.acceptance-policy.changed", entity_type="project", entity_id=project.id,
                details={"from": before, "to": value}, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            return {"project_id": str(project.id), "acceptance_policy": value}

    @staticmethod
    def _expected_report_date(session, member: WorkforceMember, plan_date: date) -> date | None:
        # The CTO reports to nobody: no Daily Report is expected from their own staff record (FR-PLAN-37).
        if is_cto_member(session, member):
            return None
        for days_back in range(1, 8):
            candidate = plan_date - timedelta(days=days_back)
            capacity = session.scalar(select(DailyCapacity).where(
                DailyCapacity.member_id == member.id,
                DailyCapacity.work_date == candidate,
            ))
            if capacity is not None:
                if float(capacity.available_hours) > 0:
                    return candidate
                continue
            if candidate.weekday() < 5 and float(member.default_weekday_hours) > 0:
                return candidate
        return None

    def _add_report_warnings(self, session, run: PlanningRun) -> None:
        memberships = session.scalars(select(WorkforceProjectMembership).where(
            WorkforceProjectMembership.project_id.in_(run.project_scope),
            WorkforceProjectMembership.active.is_(True),
        )).all()
        in_scope_member_ids = {str(membership.member_id) for membership in memberships}
        members = session.scalars(select(WorkforceMember).where(
            WorkforceMember.status == "ACTIVE",
        )).all()
        latest_expected_date: date | None = None
        for member in members:
            if str(member.id) not in in_scope_member_ids:
                continue
            expected_date = self._expected_report_date(session, member, run.plan_date)
            if expected_date is None:
                continue
            if latest_expected_date is None or expected_date > latest_expected_date:
                latest_expected_date = expected_date
            if not member.email_reference:
                self._warning(
                    session, run, member, "REPORT_IDENTITY_UNMAPPED",
                    "Workforce member has no report email mapping", {"expected_report_date": expected_date.isoformat()},
                )
                continue
            report = session.scalar(select(EmailMessage).where(
                EmailMessage.member_id == member.id,
                EmailMessage.report_date == expected_date,
                EmailMessage.is_current.is_(True),
            ).order_by(EmailMessage.revision.desc()))
            if report is None:
                self._warning(
                    session, run, member, "REPORT_MISSING",
                    "Expected Daily Report is missing; GitLab remains the planning source of truth",
                    {"expected_report_date": expected_date.isoformat()},
                )
                continue
            if not usable_for_planning(report):
                self._warning(
                    session, run, member, "REPORT_AI_UNREVIEWED",
                    "Daily Report was read by AI and awaits CTO review; its items are not used for planning",
                    {"report_id": str(report.id), "expected_report_date": expected_date.isoformat()},
                )
                continue
            if report.status == "MALFORMED":
                self._warning(
                    session, run, member, "REPORT_MALFORMED",
                    "Daily Report is malformed; parsed fields are advisory and GitLab remains authoritative",
                    {"report_id": str(report.id), "issues": report.parse_errors or []},
                )
            if report.is_late:
                self._warning(
                    session, run, member, "REPORT_LATE",
                    f"Daily Report arrived after the {late_cutoff():%H:%M} cutoff",
                    {"report_id": str(report.id), "received_at": report.received_at.isoformat()},
                )
        if latest_expected_date is not None:
            run.report_cutoff_at = datetime.combine(
                latest_expected_date, late_cutoff(), tzinfo=ZoneInfo("Asia/Ho_Chi_Minh")
            ).astimezone(timezone.utc)

    def _add_source_conflicts(self, session, run: PlanningRun) -> None:
        snapshots = session.scalars(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.project_id.in_(run.project_scope),
            GitLabIssueSnapshot.is_current.is_(True),
        )).all()
        by_issue = {(str(row.project_id), row.issue_external_id): row for row in snapshots}
        fetched_values = [row.fetched_at for row in snapshots]
        run.gitlab_snapshot_at = max(fetched_values) if fetched_values else None
        members = session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE")).all()
        for member in members:
            expected_date = self._expected_report_date(session, member, run.plan_date)
            if expected_date is None:
                continue
            rows = session.execute(
                select(ReportItem, EmailMessage)
                .join(EmailMessage, EmailMessage.id == ReportItem.email_message_id)
                .where(
                    ReportItem.member_id == member.id,
                    ReportItem.is_current.is_(True),
                    EmailMessage.report_date == expected_date,
                    EmailMessage.is_current.is_(True),
                )
            ).all()
            for item, email in rows:
                if not usable_for_planning(email):
                    continue
                if item.blocker:
                    self._warning(
                        session, run, member, "REPORT_BLOCKER",
                        f"Daily Report contains a blocker for '{item.title}'",
                        {"report_id": str(email.id), "gitlab_issue": item.gitlab_issue_external_id},
                    )
                if not item.gitlab_issue_external_id or not item.project_id:
                    continue
                snapshot = by_issue.get((str(item.project_id), item.gitlab_issue_external_id))
                if snapshot is None:
                    self._warning(
                        session, run, member, "GITLAB_REFERENCE_NOT_FOUND",
                        f"GitLab Issue #{item.gitlab_issue_external_id} from Daily Report is absent from the current read model",
                        {"report_status": item.work_status, "gitlab_issue": item.gitlab_issue_external_id},
                    )
                    continue
                if item.work_status == "DONE" and snapshot.state != "closed":
                    self._warning(
                        session, run, member, "EMAIL_DONE_GITLAB_OPEN",
                        f"Email marks Issue #{item.gitlab_issue_external_id} DONE but GitLab is still {snapshot.state}; GitLab wins",
                        {"email_status": item.work_status, "gitlab_state": snapshot.state},
                    )
                if item.work_status in {"PLANNED", "IN_PROGRESS", "PENDING_REVIEW"} and snapshot.state == "closed":
                    self._warning(
                        session, run, member, "EMAIL_ACTIVE_GITLAB_CLOSED",
                        f"Email keeps Issue #{item.gitlab_issue_external_id} active but GitLab is closed; GitLab wins",
                        {"email_status": item.work_status, "gitlab_state": snapshot.state},
                    )

    @staticmethod
    def _priority_from_labels(labels: list) -> str:
        lowered = {str(label).lower() for label in labels}
        for priority in ("P0", "P1", "P2", "P3"):
            if f"priority:{priority.lower()}" in lowered:
                return priority
        return "P3"

    def _generate_proposals(self, session, run: PlanningRun) -> int:
        snapshots = session.scalars(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.project_id.in_(run.project_scope),
            GitLabIssueSnapshot.is_current.is_(True),
            GitLabIssueSnapshot.state == "opened",
        )).all()
        if not snapshots:
            return 0
        memberships = session.scalars(select(WorkforceProjectMembership).where(
            WorkforceProjectMembership.project_id.in_(run.project_scope),
            WorkforceProjectMembership.active.is_(True),
            WorkforceProjectMembership.gitlab_user_external_id.is_not(None),
        )).all()
        # Milestone and due date are only required where the plan is written back, which is GitLab.
        read_only_projects = self._github_projects(session, run.project_scope)
        generated = 0
        planned_issues = {
            (str(row.project_id), row.gitlab_issue_external_id)
            for row in session.scalars(select(PlanningAssignment).where(
                PlanningAssignment.planning_run_id == run.id,
                PlanningAssignment.gitlab_issue_external_id.is_not(None),
            )).all()
        }
        for membership in memberships:
            member = session.get(WorkforceMember, membership.member_id)
            if member is None or member.status != "ACTIVE":
                continue
            capacity_row = session.scalar(select(DailyCapacity).where(
                DailyCapacity.member_id == member.id,
                DailyCapacity.work_date == run.plan_date,
            ))
            capacity = float(self._capacity_dict(session, member, run.plan_date, capacity_row)["available_hours"])
            # Someone who works on several projects only has the hours other projects' plans left over.
            capacity -= self._hours_elsewhere(session, str(member.id), run.plan_date, list(run.project_scope), str(run.id))
            available = min(capacity, 8.0)
            if available <= 0:
                continue
            candidates = [
                issue for issue in snapshots
                if str(issue.project_id) == str(membership.project_id)
                and str(membership.gitlab_user_external_id) in {str(value) for value in issue.assignee_external_ids}
                and (str(issue.project_id), issue.issue_external_id) not in planned_issues
            ]
            if not candidates:
                continue
            report_rows = session.execute(
                select(ReportItem, EmailMessage)
                .join(EmailMessage, EmailMessage.id == ReportItem.email_message_id)
                .where(
                    ReportItem.member_id == member.id,
                    ReportItem.is_current.is_(True),
                    EmailMessage.is_current.is_(True),
                    EmailMessage.report_date < run.plan_date,
                )
                .order_by(EmailMessage.report_date.desc(), EmailMessage.received_at.desc())
            ).all()
            report_by_issue: dict[str, ReportItem] = {}
            for report_item, report_email in report_rows:
                if not usable_for_planning(report_email):
                    continue
                if report_item.gitlab_issue_external_id and report_item.gitlab_issue_external_id not in report_by_issue:
                    report_by_issue[report_item.gitlab_issue_external_id] = report_item
            far_future = date(9999, 12, 31)
            candidates.sort(key=lambda issue: (
                0 if issue.issue_external_id in report_by_issue else 1,
                ("P0", "P1", "P2", "P3").index(self._priority_from_labels(issue.labels)),
                issue.due_date or far_future,
                issue.issue_external_id,
            ))
            issue = candidates[0]
            report_item = report_by_issue.get(issue.issue_external_id)
            estimate = None
            if report_item is not None:
                estimate = _number(report_item.remaining_hours) or _number(report_item.planned_hours)
            planned = min(4.0, available, estimate if estimate and estimate > 0 else available)
            priority = self._priority_from_labels(issue.labels)
            assignment = PlanningAssignment(
                id=str(uuid4()), planning_run_id=run.id, project_id=issue.project_id, member_id=member.id,
                slot="MORNING", work_type="DEVELOPMENT", is_primary=True, planned_hours=planned,
                source_type="GITLAB", source_reference=issue.web_url or f"GitLab #{issue.issue_external_id}",
                gitlab_issue_external_id=issue.issue_external_id,
                proposed_priority=priority, approved_priority=None,
                proposed_assignee_external_id=str(membership.gitlab_user_external_id),
                approved_assignee_external_id=None,
                proposed_milestone_external_id=issue.milestone_external_id,
                approved_milestone_external_id=None,
                proposed_due_date=issue.due_date, approved_due_date=None,
                dependency_state="BLOCKED" if report_item and report_item.blocker else None,
                source_state=issue.state, override_reason=None, version=1,
                created_at=run.created_at, updated_at=run.created_at,
            )
            session.add(assignment)
            session.flush()
            planned_issues.add((str(issue.project_id), issue.issue_external_id))
            generated += 1
            if str(issue.project_id) in read_only_projects:
                continue
            if not issue.milestone_external_id:
                self._warning(
                    session, run, member, "GITLAB_MILESTONE_MISSING",
                    f"Issue #{issue.issue_external_id} has no milestone; acknowledge before closing the plan",
                    {"gitlab_issue": issue.issue_external_id},
                )
            if not issue.due_date:
                self._warning(
                    session, run, member, "GITLAB_DUE_DATE_MISSING",
                    f"Issue #{issue.issue_external_id} has no due date; acknowledge before closing the plan",
                    {"gitlab_issue": issue.issue_external_id},
                )
        return generated

    def _tidy_report_candidates(self, session, run: PlanningRun, current_hashes: set[str], now: datetime) -> set[tuple[str, str]]:
        """Waiting entries from reports that no longer stand: one from a report that was read again (its item is
        no longer current), or a second line for the same person and task name. They move to "đã bỏ qua" with a
        note; what was already placed on someone is not touched. Returns the (member, name) pairs still waiting."""
        waiting = session.scalars(select(PlanningCandidate).where(
            PlanningCandidate.planning_run_id == run.id, PlanningCandidate.source_type == "REPORT",
            PlanningCandidate.status.in_(("READY", "PENDING_TRIAGE")),
        ).order_by(PlanningCandidate.created_at, PlanningCandidate.id)).all()
        kept: dict[tuple[str, str], PlanningCandidate] = {}
        for candidate in waiting:
            if candidate.idempotency_key_hash and candidate.idempotency_key_hash not in current_hashes:
                candidate.status, candidate.updated_at = "REJECTED", now
                candidate.summary = f"Bỏ vì báo cáo đã được đọc lại · {candidate.summary or ''}"[:2000]
                continue
            key = (str(candidate.member_id), normalized_task_title(candidate.title))
            other = kept.get(key)
            if other is None:
                kept[key] = candidate
                continue
            # The line furthest along, then the one asking more hours, stays.
            def rank(row: PlanningCandidate) -> tuple[int, float]:
                status = (row.summary or "").split("·", 1)[0].replace("Trạng thái báo cáo:", "").strip()
                return (REPORT_STATUS_RANK.get(status, 0), float(row.requested_hours or 0))
            loser, winner = (candidate, other) if rank(other) >= rank(candidate) else (other, candidate)
            kept[key] = winner
            loser.status, loser.updated_at = "REJECTED", now
            loser.summary = f"Trùng với dòng cùng tên · {loser.summary or ''}"[:2000]
        return set(kept)

    def _add_report_candidates(self, session, run: PlanningRun) -> int:
        """Turn unfinished items of the latest usable Daily Report into candidates the CTO can assign.

        Items without a GitLab Issue are included; they wait in triage until an Issue is linked. One line per
        person and task name: a task written twice, or a report read again, does not make two entries.
        """
        scope = set(run.project_scope)
        planned = {
            (str(assignment.member_id), assignment.gitlab_issue_external_id)
            for assignment in session.scalars(select(PlanningAssignment).where(
                PlanningAssignment.planning_run_id == run.id,
            )).all()
        }
        added = 0
        now = datetime.now(timezone.utc)
        members = session.scalars(select(WorkforceMember).where(WorkforceMember.status == "ACTIVE")).all()
        # Every report item that stands today, by the key its waiting entry would carry.
        expected: dict[str, date] = {}
        current_hashes: set[str] = set()
        for member in members:
            expected_date = self._expected_report_date(session, member, run.plan_date)
            if expected_date is None:
                continue
            expected[str(member.id)] = expected_date
            for item_id in session.scalars(select(ReportItem.id).join(EmailMessage, EmailMessage.id == ReportItem.email_message_id).where(
                ReportItem.member_id == member.id, ReportItem.is_current.is_(True), EmailMessage.report_date == expected_date, EmailMessage.is_current.is_(True),
            )).all():
                current_hashes.add(hashlib.sha256(f"report-item:{run.id}:{item_id}".encode("utf-8")).hexdigest())
        held_names = self._tidy_report_candidates(session, run, current_hashes, now)
        for member in members:
            expected_date = expected.get(str(member.id))
            if expected_date is None:
                continue
            rows = session.execute(
                select(ReportItem, EmailMessage)
                .join(EmailMessage, EmailMessage.id == ReportItem.email_message_id)
                .where(
                    ReportItem.member_id == member.id,
                    ReportItem.is_current.is_(True),
                    EmailMessage.report_date == expected_date,
                    EmailMessage.is_current.is_(True),
                )
                .order_by(ReportItem.created_at, ReportItem.id)
            ).all()
            for item, email in rows:
                if not usable_for_planning(email) or item.work_status not in REPORT_CARRY_OVER_STATUSES:
                    continue
                if not item.project_id or str(item.project_id) not in scope:
                    continue
                issue_id = self._normalize_issue_reference(item.gitlab_issue_external_id or "") or None
                if issue_id and (str(member.id), issue_id) in planned:
                    continue
                key_hash = hashlib.sha256(f"report-item:{run.id}:{item.id}".encode("utf-8")).hexdigest()
                if session.scalar(select(PlanningCandidate.id).where(PlanningCandidate.idempotency_key_hash == key_hash)):
                    continue
                name_key = (str(member.id), normalized_task_title(item.title))
                if name_key in held_names:
                    continue
                held_names.add(name_key)
                issue = self._current_gitlab_issue(session, str(item.project_id), issue_id) if issue_id else None
                plannable = issue is not None and issue.state == "opened"
                hours = _number(item.remaining_hours) or _number(item.planned_hours)
                summary = " · ".join(part for part in (
                    f"Trạng thái báo cáo: {item.work_status}",
                    f"Bước tiếp: {item.next_step.strip().lstrip('-• ')}" if (item.next_step or "").strip() else None,
                    "Có blocker" if item.blocker else None,
                ) if part)
                session.add(PlanningCandidate(
                    id=str(uuid4()), planning_run_id=run.id, project_id=item.project_id, member_id=member.id,
                    intake_id=None, assignment_id=None, source_type="REPORT",
                    source_reference=f"Daily Report {expected_date.isoformat()}",
                    gitlab_issue_external_id=issue_id if plannable else None,
                    title=item.title[:255], summary=summary,
                    status="READY" if plannable else "PENDING_TRIAGE",
                    proposed_priority=self._priority_from_labels(issue.labels) if plannable else None,
                    requested_hours=hours if hours and 0 < hours <= 24 else None, target_slot=None,
                    idempotency_key_hash=key_hash, request_hash=None,
                    created_by=run.created_by, created_at=run.created_at, updated_at=run.created_at,
                ))
                added += 1
        if added:
            session.flush()
        return added

    def _add_carry_over_candidates(self, session, run: PlanningRun) -> int:
        """Work placed on the project's latest earlier day and not reported done comes back to wait, marked as a
        continuation with the same Issue, priority, hours and the person who had it (FR-PLAN-34). An Issue closed on
        the tracker in the meantime is done whatever the plan says."""
        planned = {
            (str(assignment.project_id), assignment.gitlab_issue_external_id)
            for assignment in session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id)).all()
        }
        held = {
            (str(candidate.project_id), candidate.gitlab_issue_external_id)
            for candidate in session.scalars(select(PlanningCandidate).where(PlanningCandidate.planning_run_id == run.id)).all()
            if candidate.gitlab_issue_external_id
        }
        # Said to be done and waiting for the CTO's acceptance (a report, "Đã làm rồi"), or accepted: not carried back (FR-PLAN-34).
        awaiting = self._settled_issues(session, [str(p) for p in run.project_scope])
        now = datetime.now(timezone.utc)
        added = 0
        for project_id in run.project_scope:
            previous = session.scalar(select(PlanningRun).where(
                PlanningRun.plan_date < run.plan_date, PlanningRun.scope_hash == _canonical_hash([str(project_id)]), PlanningRun.status != "SUPERSEDED",
            ).order_by(PlanningRun.plan_date.desc(), PlanningRun.revision.desc()))
            if previous is None:
                continue
            rows = [
                assignment for assignment in session.scalars(select(PlanningAssignment).where(
                    PlanningAssignment.planning_run_id == previous.id, PlanningAssignment.gitlab_issue_external_id.is_not(None),
                ).order_by(PlanningAssignment.slot, PlanningAssignment.created_at)).all()
                if assignment.work_type in DELIVERY_WORK_TYPES and (assignment.work_status or "PLANNED") != "DONE"
            ]
            if not rows:
                continue
            views = {row["id"]: row for row in self._with_intakes(session, rows)}
            for assignment in rows:
                key = (str(project_id), assignment.gitlab_issue_external_id)
                if key in planned or key in held or key in awaiting:
                    continue
                issue = self._current_gitlab_issue(session, str(project_id), assignment.gitlab_issue_external_id)
                if issue is not None and issue.state != "opened":
                    continue
                key_hash = hashlib.sha256(f"carry:{run.id}:{assignment.id}".encode("utf-8")).hexdigest()
                if session.scalar(select(PlanningCandidate.id).where(PlanningCandidate.idempotency_key_hash == key_hash)):
                    continue
                view = views[str(assignment.id)]
                title = view.get("title")
                if not title:
                    earlier = session.scalar(select(PlanningCandidate).where(PlanningCandidate.assignment_id == assignment.id))
                    title = earlier.title if earlier is not None else assignment.source_reference
                label = WORK_STATUS_LABELS.get(assignment.work_status or "PLANNED", "chưa xong")
                summary = f"Làm tiếp từ {previous.plan_date.strftime('%d/%m')}: {label}" + (f" · {assignment.work_status_note}" if assignment.work_status_note else "")
                session.add(PlanningCandidate(
                    id=str(uuid4()), planning_run_id=run.id, project_id=assignment.project_id, member_id=assignment.member_id,
                    intake_id=view.get("intake_id"), assignment_id=None, source_type="GITLAB",
                    source_reference=f"{CARRY_OVER_REFERENCE}{previous.plan_date.isoformat()}",
                    gitlab_issue_external_id=assignment.gitlab_issue_external_id,
                    title=str(title)[:255], summary=summary[:2000], status="READY",
                    proposed_priority=assignment.approved_priority or assignment.proposed_priority,
                    requested_hours=assignment.planned_hours, target_slot=None,
                    idempotency_key_hash=key_hash, request_hash=None, created_by=run.created_by, created_at=now, updated_at=now,
                ))
                held.add(key)
                added += 1
        if added:
            session.flush()
        return added

    def _add_intake_candidates(self, session, run: PlanningRun) -> int:
        """Requests that were approved and given an Issue, and that nobody has taken yet, wait here to be assigned.

        An Issue made today is not in the GitLab read model until the next refresh. Intake made it, so it is known to
        exist: a provisional row stands in until the refresh replaces it with the real one.
        """
        scope = list(run.project_scope)
        links = session.scalars(select(ExternalLink).where(
            ExternalLink.project_id.in_(scope), ExternalLink.target_system.in_(("GITLAB", "GITHUB")),
        ).order_by(ExternalLink.created_at)).all()
        if not links:
            return 0
        planned = {
            (str(assignment.project_id), assignment.gitlab_issue_external_id)
            for assignment in session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id)).all()
        }
        waiting = session.scalars(select(PlanningCandidate).where(PlanningCandidate.planning_run_id == run.id)).all()
        held_intakes = {str(candidate.intake_id) for candidate in waiting if candidate.intake_id}
        held_issues = {(str(candidate.project_id), candidate.gitlab_issue_external_id) for candidate in waiting if candidate.gitlab_issue_external_id}
        # Said to be done and waiting for the CTO's acceptance, or accepted already: not offered to the plan again (FR-PLAN-34).
        held_issues |= self._settled_issues(session, scope)
        now = datetime.now(timezone.utc)
        added = 0
        for link in links:
            intake = session.get(IntakeItem, link.intake_id)
            if intake is None or intake.status == "REJECTED" or intake.duplicate_of_id is not None or str(intake.id) in held_intakes:
                continue
            issue_id = self._normalize_issue_reference(link.external_id)
            key = (str(link.project_id), issue_id)
            if not issue_id or key in planned or key in held_issues:
                continue
            issue = self._current_gitlab_issue(session, str(link.project_id), issue_id)
            if issue is None:
                # Only an Issue made since the read model was last loaded can be missing from it; an older one that
                # is missing was deleted or moved, and is not offered.
                loaded = session.scalar(select(func.max(AuditEvent.created_at)).where(
                    AuditEvent.project_id == link.project_id, AuditEvent.event_type == "planning.gitlab-read-model.refreshed",
                    AuditEvent.created_at <= now,
                ))
                created = link.created_at if link.created_at.tzinfo else link.created_at.replace(tzinfo=timezone.utc)
                if loaded is not None and (loaded if loaded.tzinfo else loaded.replace(tzinfo=timezone.utc)) > created:
                    continue
                issue = GitLabIssueSnapshot(
                    id=str(uuid4()), project_id=link.project_id, issue_external_id=issue_id,
                    title=(intake.normalized_title or intake.public_id)[:512], state="opened",
                    labels=[f"priority:{intake.approved_priority.lower()}"] if intake.approved_priority else [],
                    assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None, web_url=link.url,
                    payload_hash=hashlib.sha256(f"intake-link:{link.id}".encode("utf-8")).hexdigest(),
                    is_current=True, fetched_at=now, last_seen_at=now,
                )
                session.add(issue)
                session.flush()
            # Closed means done; an assignee means someone already has it and it reaches the plan through them.
            if issue.state != "opened" or issue.assignee_external_ids:
                continue
            key_hash = hashlib.sha256(f"intake:{run.id}:{intake.id}".encode("utf-8")).hexdigest()
            if session.scalar(select(PlanningCandidate.id).where(PlanningCandidate.idempotency_key_hash == key_hash)):
                continue
            system = "GitHub" if link.target_system == "GITHUB" else "GitLab"
            session.add(PlanningCandidate(
                id=str(uuid4()), planning_run_id=run.id, project_id=link.project_id, member_id=None,
                intake_id=intake.id, assignment_id=None, source_type="INTAKE", source_reference=intake.public_id,
                gitlab_issue_external_id=issue_id,
                title=(intake.normalized_title or intake.public_id)[:255],
                summary=f"Yêu cầu Intake đã có Issue · {system} #{issue_id} · chưa ai nhận",
                status="READY", proposed_priority=intake.approved_priority or self._priority_from_labels(issue.labels),
                requested_hours=None, target_slot=None, idempotency_key_hash=key_hash, request_hash=None,
                created_by=run.created_by, created_at=now, updated_at=now,
            ))
            held_intakes.add(str(intake.id))
            held_issues.add(key)
            added += 1
        if added:
            session.flush()
        return added

    @staticmethod
    def _github_projects(session, project_ids) -> set[str]:
        return {str(value) for value in session.scalars(select(ProjectIntegration.project_id).where(
            ProjectIntegration.project_id.in_(list(project_ids)), ProjectIntegration.system == "GITHUB",
            ProjectIntegration.project_external_id.is_not(None),
        )).all()}

    def accept_proposals(self, run_id: str, expected_version: int, actor_id: str) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            if run.version != expected_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before accepting proposals")
            assignments = session.scalars(select(PlanningAssignment).where(
                PlanningAssignment.planning_run_id == run.id,
            )).all()
            if not assignments:
                raise PlanningValidationError("PLANNING_EMPTY", "Planning run has no proposals")
            accepted = 0
            for assignment in assignments:
                if assignment.work_type not in DELIVERY_WORK_TYPES:
                    continue
                assignment.approved_priority = assignment.proposed_priority
                assignment.approved_assignee_external_id = assignment.proposed_assignee_external_id
                assignment.approved_milestone_external_id = assignment.proposed_milestone_external_id
                assignment.approved_due_date = assignment.proposed_due_date
                assignment.version += 1
                assignment.updated_at = now
                accepted += 1
            run.version += 1
            run.status = "REVIEW_REQUIRED"
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id,
                event_type="planning.proposals.accepted", entity_type="planning_run", entity_id=run.id,
                details={"accepted_assignments": accepted, "run_version": run.version}, created_at=now,
            ))
            session.commit()
            return self._run_dict(session, run)

    @staticmethod
    def _warning(
        session,
        run: PlanningRun,
        member: WorkforceMember,
        code: str,
        message: str,
        source_values: dict[str, object],
    ) -> None:
        session.add(PlanningWarning(
            id=str(uuid4()), planning_run_id=run.id, assignment_id=None,
            member_id=member.id, project_id=None, code=code, severity="WARNING",
            source_values=source_values, message=message, created_at=datetime.now(timezone.utc),
        ))

    @staticmethod
    def _candidate_dict(candidate: PlanningCandidate) -> dict[str, object]:
        return {
            "id": str(candidate.id),
            "planning_run_id": str(candidate.planning_run_id),
            "project_id": str(candidate.project_id),
            "member_id": str(candidate.member_id) if candidate.member_id else None,
            "intake_id": str(candidate.intake_id) if candidate.intake_id else None,
            "assignment_id": str(candidate.assignment_id) if candidate.assignment_id else None,
            "source_type": candidate.source_type,
            "source_reference": candidate.source_reference,
            "gitlab_issue_external_id": candidate.gitlab_issue_external_id,
            "title": candidate.title,
            "summary": candidate.summary,
            "status": candidate.status,
            "proposed_priority": candidate.proposed_priority,
            "requested_hours": _number(candidate.requested_hours),
            "target_slot": candidate.target_slot,
            "created_at": candidate.created_at,
        }

    @staticmethod
    def _normalize_issue_reference(value: str) -> str:
        reference = value.strip()
        if "/issues/" in reference:
            reference = reference.rstrip("/").rsplit("/", 1)[-1]
        return reference.lstrip("#")

    @staticmethod
    def _ensure_issue_not_planned(session, run_id: str, project_id: str, issue_id: str) -> None:
        existing = session.scalar(select(PlanningAssignment.id).where(
            PlanningAssignment.planning_run_id == run_id,
            PlanningAssignment.project_id == project_id,
            PlanningAssignment.gitlab_issue_external_id == issue_id,
        ))
        if existing is not None:
            raise PlanningValidationError("ISSUE_ALREADY_PLANNED", "Issue is already assigned in this daily plan")

    @staticmethod
    def _accepted_verifications(session, scope: list[str]) -> list[IssueVerification]:
        """Issues the CTO said were done, newest decision first per Issue."""
        return session.scalars(select(IssueVerification).where(
            IssueVerification.project_id.in_(scope), IssueVerification.decision == "ACCEPTED",
        ).order_by(IssueVerification.decided_at.desc())).all()

    def accepted_at_by_issue(self, session, scope: list[str]) -> dict[tuple[str, str], datetime]:
        """When the CTO accepted each Issue of the scope, newest decision per Issue; empty scope gives nothing."""
        out: dict[tuple[str, str], datetime] = {}
        if scope:
            for verification in self._accepted_verifications(session, scope):
                out.setdefault((str(verification.project_id), verification.issue_external_id), verification.decided_at)
        return out

    def _settled_issues(self, session, scope: list[str]) -> set[tuple[str, str]]:
        """Issues the plan must not offer again: said to be done and waiting for the CTO, or accepted by the CTO.

        Acceptance closes the Issue on the tracker, but that write runs later and can fail, so the read model may keep
        the Issue "opened" for a while or for good (INT-26W43-001). The CTO's word is what counts: an accepted Issue
        stays out unless the tracker shows it touched after the decision and still open, which means someone reopened it.
        """
        settled = {
            (str(row.project_id), row.issue_external_id)
            for row in session.scalars(select(IssueVerification).where(IssueVerification.project_id.in_(scope), IssueVerification.decision == "PENDING")).all()
        }
        latest: dict[tuple[str, str], IssueVerification] = {}
        for row in self._accepted_verifications(session, scope):
            latest.setdefault((str(row.project_id), row.issue_external_id), row)
        for key, row in latest.items():
            issue = self._current_gitlab_issue(session, key[0], key[1])
            decided = _as_utc(row.decided_at)
            touched = _as_utc(issue.external_updated_at) if issue is not None else None
            reopened = issue is not None and issue.state == "opened" and decided is not None and touched is not None and touched > decided
            if not reopened:
                settled.add(key)
        return settled

    @staticmethod
    def _current_gitlab_issue(session, project_id: str, issue_id: str) -> GitLabIssueSnapshot | None:
        return session.scalar(select(GitLabIssueSnapshot).where(
            GitLabIssueSnapshot.project_id == project_id,
            GitLabIssueSnapshot.issue_external_id == issue_id,
            GitLabIssueSnapshot.is_current.is_(True),
        ).order_by(GitLabIssueSnapshot.fetched_at.desc()))

    def quick_add(
        self,
        run_id: str,
        payload: PlanningQuickAddRequest,
        actor_id: str,
        idempotency_key: str | None = None,
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        request_value = {"planning_run_id": run_id, **payload.model_dump(mode="json")}
        request_hash = _canonical_hash(request_value)
        key_hash = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest() if idempotency_key else None
        with get_session() as session:
            if key_hash:
                existing = session.scalar(select(PlanningCandidate).where(
                    PlanningCandidate.idempotency_key_hash == key_hash,
                ))
                if existing is not None:
                    if existing.request_hash != request_hash:
                        raise PlanningValidationError(
                            "IDEMPOTENCY_KEY_REUSED", "Idempotency key was already used with a different request"
                        )
                    return self._candidate_dict(existing)

            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            if run.version != payload.expected_run_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before saving")
            project = self._resolve_project(session, payload.project_id)
            if str(project.id) not in set(run.project_scope):
                raise PlanningValidationError("PROJECT_OUTSIDE_PLANNING_SCOPE", "Project is outside planning scope")

            source_type = payload.mode
            source_reference = ""
            title = ""
            summary: str | None = None
            intake: IntakeItem | None = None
            issue: GitLabIssueSnapshot | None = None
            issue_id: str | None = None

            if payload.mode == "EXISTING":
                if not payload.source_system or not (payload.reference or "").strip():
                    raise PlanningValidationError(
                        "QUICK_ADD_REFERENCE_REQUIRED", "Existing-item Quick Add requires source_system and reference"
                    )
                source_type = payload.source_system
                source_reference = payload.reference.strip()
                if payload.source_system == "GITLAB":
                    issue_id = self._normalize_issue_reference(source_reference)
                    issue = self._current_gitlab_issue(session, str(project.id), issue_id)
                    if issue is None:
                        raise PlanningValidationError(
                            "GITLAB_ISSUE_NOT_FOUND", "GitLab Issue is absent from the current read model"
                        )
                    if issue.state != "opened":
                        raise PlanningValidationError("GITLAB_ISSUE_CLOSED", "Closed GitLab Issue cannot be planned")
                    title = issue.title[:255]
                    summary = issue.title
                elif payload.source_system == "INTAKE":
                    try:
                        UUID(source_reference)
                        intake = session.get(IntakeItem, source_reference)
                    except ValueError:
                        intake = session.scalar(select(IntakeItem).where(
                            IntakeItem.public_id == source_reference,
                        ))
                    if intake is None or str(intake.project_id) != str(project.id):
                        raise PlanningValidationError("INTAKE_NOT_FOUND", "Intake item was not found in the selected project")
                    title = (intake.normalized_title or intake.public_id)[:255]
                    summary = intake.normalized_summary
                if intake is not None:
                    gitlab_link = session.scalar(select(ExternalLink).where(
                        ExternalLink.intake_id == intake.id,
                        ExternalLink.target_system == "GITLAB",
                    ).order_by(ExternalLink.created_at.desc()))
                    if gitlab_link is not None:
                        issue_id = self._normalize_issue_reference(gitlab_link.external_id)
                        linked_issue = self._current_gitlab_issue(session, str(project.id), issue_id)
                        if linked_issue is not None and linked_issue.state == "opened":
                            issue = linked_issue
            elif payload.mode in {"FORM", "PASTE"}:
                content = (payload.content or "").strip()
                if payload.mode == "FORM":
                    title = (payload.title or "").strip()
                    if not title:
                        raise PlanningValidationError("QUICK_ADD_TITLE_REQUIRED", "Quick form requires a title")
                    summary = content or None
                    raw_text = title if not content else f"{title}\n\n{content}"
                else:
                    if not content:
                        raise PlanningValidationError("QUICK_ADD_CONTENT_REQUIRED", "Paste Quick Add requires content")
                    title = ((payload.title or content.splitlines()[0]).strip() or "New request")[:255]
                    summary = content
                    raw_text = content
                from app.services.intake_service import IntakeStore
                from app.services.raw_crypto import encrypt

                intake = IntakeItem(
                    id=str(uuid4()),
                    public_id=IntakeStore._next_public_id(session, project, now),
                    project_id=project.id,
                    channel=payload.channel,
                    item_type="UNCLEAR",
                    status="NEW",
                    normalized_title=title[:255],
                    normalized_summary=summary or raw_text,
                    version=1,
                    created_by=actor_id,
                    created_at=now,
                    updated_at=now,
                )
                session.add(intake)
                session.add(SourceMessage(
                    id=str(uuid4()), intake_id=intake.id, channel=payload.channel,
                    raw_content_ciphertext=encrypt(raw_text), received_at=now,
                    purge_after=now + timedelta(days=90), created_at=now,
                ))
                source_reference = intake.public_id
            else:
                raise PlanningValidationError("QUICK_ADD_MODE_INVALID", "Unsupported Quick Add mode")

            candidate = PlanningCandidate(
                id=str(uuid4()), planning_run_id=run.id, project_id=project.id,
                intake_id=intake.id if intake else None, assignment_id=None, member_id=None,
                source_type=source_type, source_reference=source_reference,
                gitlab_issue_external_id=issue_id if issue else None,
                title=title[:255], summary=summary,
                status="READY" if issue else "PENDING_TRIAGE",
                proposed_priority=self._priority_from_labels(issue.labels) if issue else None,
                requested_hours=payload.requested_hours, target_slot=payload.target_slot,
                idempotency_key_hash=key_hash, request_hash=request_hash if key_hash else None,
                created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(candidate)
            run.status = "REVIEW_REQUIRED"
            run.version += 1
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="planning.candidate.created", entity_type="planning_candidate", entity_id=candidate.id,
                details={"planning_run_id": str(run.id), "source_type": source_type, "status": candidate.status},
                created_at=now,
            ))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                if key_hash:
                    existing = session.scalar(select(PlanningCandidate).where(
                        PlanningCandidate.idempotency_key_hash == key_hash,
                    ))
                    if existing is not None and existing.request_hash == request_hash:
                        return self._candidate_dict(existing)
                raise PlanningValidationError("QUICK_ADD_CONFLICT", "Quick Add could not be saved") from exc
            return self._candidate_dict(candidate)

    def promote_candidate(
        self,
        run_id: str,
        candidate_id: str,
        payload: PlanningCandidatePromoteRequest,
        actor_id: str,
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            candidate = session.scalar(select(PlanningCandidate).where(
                PlanningCandidate.id == candidate_id,
                PlanningCandidate.planning_run_id == run.id,
            ).with_for_update())
            if candidate is None:
                raise PlanningValidationError("PLANNING_CANDIDATE_NOT_FOUND", "Planning candidate was not found")
            if candidate.status == "ASSIGNED":
                return self._candidate_dict(candidate)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            if run.version != payload.expected_run_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before saving")
            if payload.work_type not in DELIVERY_WORK_TYPES:
                raise PlanningValidationError("DELIVERY_WORK_TYPE_REQUIRED", "Candidate promotion requires delivery work type")

            issue_id = self._normalize_issue_reference(
                payload.gitlab_issue_external_id or candidate.gitlab_issue_external_id or ""
            )
            if not issue_id:
                raise PlanningValidationError(
                    "GITLAB_ISSUE_REQUIRED", "Candidate must be linked to a GitLab Issue before promotion"
                )
            issue = self._current_gitlab_issue(session, str(candidate.project_id), issue_id)
            if issue is None:
                raise PlanningValidationError(
                    "GITLAB_ISSUE_NOT_FOUND", "GitLab Issue is absent from the current read model"
                )
            if issue.state != "opened":
                raise PlanningValidationError("GITLAB_ISSUE_CLOSED", "Closed GitLab Issue cannot be planned")
            # The Issue is already a line of this plan (another Intake or report led to it): the waiting entry joins that
            # line instead of being refused, and no second line is made (INT-26W44-001).
            planned = session.scalar(select(PlanningAssignment).where(
                PlanningAssignment.planning_run_id == run.id,
                PlanningAssignment.project_id == candidate.project_id,
                PlanningAssignment.gitlab_issue_external_id == issue_id,
            ))
            if planned is not None:
                candidate.assignment_id = planned.id
                candidate.member_id = planned.member_id
                candidate.gitlab_issue_external_id = issue_id
                candidate.status = "ASSIGNED"
                candidate.target_slot = planned.slot
                candidate.updated_at = now
                run.version += 1
                run.updated_at = now
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=candidate.project_id, actor_type="USER", actor_id=actor_id,
                    event_type="planning.candidate.merged", entity_type="planning_candidate", entity_id=candidate.id,
                    details={"planning_run_id": str(run.id), "assignment_id": planned.id, "gitlab_issue": issue_id},
                    created_at=now,
                ))
                session.commit()
                return self._candidate_dict(candidate)
            member = session.get(WorkforceMember, payload.member_id)
            if member is None or member.status != "ACTIVE":
                raise PlanningValidationError("MEMBER_NOT_ACTIVE", "Workforce member does not exist or is inactive")
            membership = session.scalar(select(WorkforceProjectMembership).where(
                WorkforceProjectMembership.member_id == member.id,
                WorkforceProjectMembership.project_id == candidate.project_id,
                WorkforceProjectMembership.active.is_(True),
            ))
            if membership is None or not membership.gitlab_user_external_id:
                raise PlanningValidationError("GITLAB_ASSIGNEE_REQUIRED", "Member has no GitLab mapping for this project")

            assignments = session.scalars(select(PlanningAssignment).where(
                PlanningAssignment.planning_run_id == run.id,
                PlanningAssignment.member_id == member.id,
            )).all()
            capacity_row = session.scalar(select(DailyCapacity).where(
                DailyCapacity.member_id == member.id, DailyCapacity.work_date == run.plan_date,
            ))
            capacity = self._capacity_dict(session, member, run.plan_date, capacity_row)
            total_hours = sum(float(item.planned_hours) for item in assignments) + payload.planned_hours
            slot_hours = sum(
                float(item.planned_hours) for item in assignments if item.slot == payload.slot
            ) + payload.planned_hours
            has_override = bool((payload.override_reason or "").strip())
            elsewhere = self._hours_elsewhere(session, str(member.id), run.plan_date, list(run.project_scope), str(run.id))
            if total_hours + elsewhere > float(capacity["available_hours"]) and not has_override:
                raise PlanningValidationError("OVER_CAPACITY", "Assignment exceeds available daily capacity")
            if slot_hours > 4 and not has_override:
                raise PlanningValidationError("SLOT_OVER_CAPACITY", "Assignment exceeds four hours in the selected slot")
            if payload.is_primary and payload.work_type == "DEVELOPMENT":
                primary_issues = {
                    item.gitlab_issue_external_id for item in assignments
                    if item.is_primary and item.work_type == "DEVELOPMENT"
                }
                if primary_issues and issue_id not in primary_issues and not has_override:
                    raise PlanningValidationError(
                        "MULTIPLE_PRIMARY_DOING", "Member already has a different primary development Issue"
                    )

            priority = self._priority_from_labels(issue.labels)
            assignment = PlanningAssignment(
                id=str(uuid4()), planning_run_id=run.id, project_id=candidate.project_id, member_id=member.id,
                slot=payload.slot, work_type=payload.work_type, is_primary=payload.is_primary,
                planned_hours=payload.planned_hours, source_type=candidate.source_type,
                source_reference=candidate.source_reference, gitlab_issue_external_id=issue_id,
                proposed_priority=priority, approved_priority=None,
                proposed_assignee_external_id=str(membership.gitlab_user_external_id),
                approved_assignee_external_id=None,
                proposed_milestone_external_id=issue.milestone_external_id,
                approved_milestone_external_id=None,
                proposed_due_date=issue.due_date, approved_due_date=None,
                source_state=issue.state,
                override_reason=payload.override_reason.strip() if payload.override_reason else None,
                version=1, created_at=now, updated_at=now,
            )
            session.add(assignment)
            session.flush()
            candidate.member_id = member.id
            candidate.assignment_id = assignment.id
            candidate.gitlab_issue_external_id = issue_id
            candidate.proposed_priority = priority
            candidate.status = "ASSIGNED"
            candidate.target_slot = payload.slot
            if candidate.requested_hours is None:
                candidate.requested_hours = payload.planned_hours
            candidate.updated_at = now
            for code, message in (
                ("GITLAB_MILESTONE_MISSING", f"Issue #{issue_id} has no milestone; acknowledge before closing the plan"),
                ("GITLAB_DUE_DATE_MISSING", f"Issue #{issue_id} has no due date; acknowledge before closing the plan"),
            ):
                missing = issue.milestone_external_id is None if code.endswith("MILESTONE_MISSING") else issue.due_date is None
                if missing:
                    session.add(PlanningWarning(
                        id=str(uuid4()), planning_run_id=run.id, assignment_id=assignment.id,
                        member_id=member.id, project_id=candidate.project_id, code=code, severity="WARNING",
                        source_values={"gitlab_issue": issue_id}, message=message, created_at=now,
                    ))
            run.status = "REVIEW_REQUIRED"
            run.version += 1
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=candidate.project_id, actor_type="USER", actor_id=actor_id,
                event_type="planning.candidate.promoted", entity_type="planning_candidate", entity_id=candidate.id,
                details={"planning_run_id": str(run.id), "assignment_id": assignment.id, "gitlab_issue": issue_id},
                created_at=now,
            ))
            session.commit()
            return self._candidate_dict(candidate)

    def get_run(self, run_id: str) -> dict[str, object]:
        with get_session() as session:
            run = session.get(PlanningRun, run_id)
            if run is None:
                raise KeyError(run_id)
            # A day that was already open when Issues got closed still gets its spot checks when it is looked at.
            if run.status in MUTABLE_RUN_STATES and self._pick_verifications(session, run):
                session.commit()
            return self._run_dict(session, run)

    def day_status(self, plan_date: date, project_id: str | None) -> dict[str, object]:
        """Where the plan of one day stands, without opening one: the home page asks, and asking must not create a plan."""
        with get_session() as session:
            if project_id:
                project_ids = [str(self._resolve_project(session, project_id).id)]
            else:
                project_ids = sorted(str(value) for value in session.scalars(select(Project.id).where(
                    Project.status == "ACTIVE", Project.kind == "SOFTWARE",
                )).all())
            run = session.scalar(select(PlanningRun).where(
                PlanningRun.plan_date == plan_date, PlanningRun.scope_hash == _canonical_hash(project_ids),
                PlanningRun.status != "SUPERSEDED",
            ).order_by(PlanningRun.revision.desc())) if project_ids else None
            if run is None:
                return {"plan_date": plan_date, "run_id": None, "status": None, "assigned": 0, "waiting": 0}
            assigned = session.scalar(select(func.count()).select_from(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id)) or 0
            waiting = session.scalar(select(func.count()).select_from(PlanningCandidate).where(
                PlanningCandidate.planning_run_id == run.id, PlanningCandidate.status.in_(("PENDING_TRIAGE", "READY")),
            )) or 0
            return {"plan_date": plan_date, "run_id": str(run.id), "status": run.status, "assigned": int(assigned), "waiting": int(waiting)}

    def move_assignment(
        self,
        run_id: str,
        assignment_id: str,
        slot: str,
        expected_run_version: int,
        actor_id: str,
        *,
        member_id: str | None = None,
        override_reason: str | None = None,
        allow_override: bool = False,
    ) -> dict[str, object]:
        """Move one assignment to another person's morning or afternoon cell while the plan is editable."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            if run.version != expected_run_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before saving")
            assignment = session.scalar(select(PlanningAssignment).where(
                PlanningAssignment.id == assignment_id, PlanningAssignment.planning_run_id == run.id,
            ))
            if assignment is None:
                raise PlanningValidationError("PLANNING_ASSIGNMENT_NOT_FOUND", "Planning assignment was not found")
            target_member_id = member_id or str(assignment.member_id)
            changes_member = str(assignment.member_id) != target_member_id
            if assignment.slot != slot or changes_member:
                target = session.get(WorkforceMember, target_member_id)
                if target is None or target.status != "ACTIVE":
                    raise PlanningValidationError("MEMBER_NOT_ACTIVE", "Workforce member does not exist or is inactive")
                membership = None
                if changes_member:
                    membership = session.scalar(select(WorkforceProjectMembership).where(
                        WorkforceProjectMembership.member_id == target.id,
                        WorkforceProjectMembership.project_id == assignment.project_id,
                        WorkforceProjectMembership.active.is_(True),
                    ))
                    if membership is None:
                        raise PlanningValidationError("MEMBER_NOT_IN_PROJECT", "Member is not active in this project")
                    if assignment.work_type in DELIVERY_WORK_TYPES and not membership.gitlab_user_external_id:
                        raise PlanningValidationError("GITLAB_ASSIGNEE_REQUIRED", "Member has no GitLab mapping for this project")

                target_assignments = session.scalars(select(PlanningAssignment).where(
                    PlanningAssignment.planning_run_id == run.id,
                    PlanningAssignment.member_id == target.id,
                    PlanningAssignment.id != assignment.id,
                )).all()
                requested_override = (override_reason or "").strip()
                if requested_override and not allow_override:
                    raise PlanningValidationError("PLANNING_OVERRIDE_FORBIDDEN", "Only a planner may override capacity limits")
                has_override = bool(requested_override or (assignment.override_reason or "").strip())
                slot_hours = sum(float(item.planned_hours) for item in target_assignments if item.slot == slot)
                if slot_hours + float(assignment.planned_hours) > 4 and not has_override:
                    raise PlanningValidationError("SLOT_OVER_CAPACITY", "Assignment exceeds four hours in the selected slot")
                if changes_member:
                    capacity_row = session.scalar(select(DailyCapacity).where(
                        DailyCapacity.member_id == target.id, DailyCapacity.work_date == run.plan_date,
                    ))
                    capacity = self._capacity_dict(session, target, run.plan_date, capacity_row)
                    elsewhere = self._hours_elsewhere(session, str(target.id), run.plan_date, list(run.project_scope), str(run.id))
                    total_hours = sum(float(item.planned_hours) for item in target_assignments) + float(assignment.planned_hours)
                    if total_hours + elsewhere > float(capacity["available_hours"]) and not has_override:
                        raise PlanningValidationError("OVER_CAPACITY", "Assignment exceeds available daily capacity")
                    if assignment.is_primary and assignment.work_type == "DEVELOPMENT":
                        primary_issues = {
                            item.gitlab_issue_external_id for item in target_assignments
                            if item.is_primary and item.work_type == "DEVELOPMENT"
                        }
                        if primary_issues and assignment.gitlab_issue_external_id not in primary_issues and not has_override:
                            raise PlanningValidationError("MULTIPLE_PRIMARY_DOING", "Member already has a different primary development Issue")

                previous_slot = assignment.slot
                previous_member_id = str(assignment.member_id)
                assignment.slot = slot
                assignment.member_id = target.id
                if requested_override:
                    assignment.override_reason = requested_override
                if changes_member and assignment.work_type in DELIVERY_WORK_TYPES:
                    assert membership is not None and membership.gitlab_user_external_id
                    external_id = str(membership.gitlab_user_external_id)
                    assignment.proposed_assignee_external_id = external_id
                    if assignment.approved_assignee_external_id is not None:
                        assignment.approved_assignee_external_id = external_id
                assignment.version += 1
                assignment.updated_at = now
                candidate = session.scalar(select(PlanningCandidate).where(PlanningCandidate.assignment_id == assignment.id))
                if candidate is not None:
                    candidate.member_id = target.id
                    candidate.target_slot = slot
                    candidate.updated_at = now
                for warning in session.scalars(select(PlanningWarning).where(
                    PlanningWarning.planning_run_id == run.id,
                    PlanningWarning.assignment_id == assignment.id,
                )).all():
                    warning.member_id = target.id
                run.version += 1
                run.updated_at = now
                session.add(AuditEvent(
                    id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="planning.assignment.moved",
                    entity_type="planning_assignment", entity_id=assignment.id,
                    details={
                        "run_id": str(run.id), "from": previous_slot, "to": slot,
                        "from_member_id": previous_member_id, "to_member_id": str(target.id),
                        "override_reason": requested_override or None,
                    }, created_at=now,
                ))
                session.commit()
            return self._run_dict(session, run)

    def unassign(self, run_id: str, assignment_id: str, expected_run_version: int, actor_id: str) -> dict[str, object]:
        """Take a placed piece of work out of the day and put it back on the waiting list, so something more urgent
        can have the hours. The Issue, its priority and its hours are kept on the candidate; the person is not."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            if run.version != expected_run_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before saving")
            assignment = session.scalar(select(PlanningAssignment).where(
                PlanningAssignment.id == assignment_id, PlanningAssignment.planning_run_id == run.id,
            ))
            if assignment is None:
                raise PlanningValidationError("PLANNING_ASSIGNMENT_NOT_FOUND", "Planning assignment was not found")
            issue_id = assignment.gitlab_issue_external_id
            priority = assignment.approved_priority or assignment.proposed_priority
            candidate = session.scalar(select(PlanningCandidate).where(PlanningCandidate.assignment_id == assignment.id))
            if candidate is not None:
                # The work came through the waiting list: it goes back to where it was, unassigned.
                candidate.status, candidate.assignment_id, candidate.member_id, candidate.target_slot = "READY", None, None, None
                candidate.proposed_priority = priority or candidate.proposed_priority
                candidate.updated_at = now
            else:
                issue = self._current_gitlab_issue(session, str(assignment.project_id), issue_id) if issue_id else None
                link = session.scalar(select(ExternalLink).where(
                    ExternalLink.project_id == assignment.project_id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")),
                    ExternalLink.external_id == issue_id,
                )) if issue_id else None
                intake = session.get(IntakeItem, link.intake_id) if link is not None else None
                key_hash = hashlib.sha256(f"unassign:{assignment.id}".encode("utf-8")).hexdigest()
                candidate = session.scalar(select(PlanningCandidate).where(PlanningCandidate.idempotency_key_hash == key_hash))
                if candidate is None:
                    candidate = PlanningCandidate(
                        id=str(uuid4()), planning_run_id=run.id, project_id=assignment.project_id, member_id=None,
                        intake_id=intake.id if intake is not None else None, assignment_id=None,
                        source_type=assignment.source_type if assignment.source_type in ("GITLAB", "INTAKE", "FORM", "PASTE", "REPORT", "VERIFICATION") else "INTAKE",
                        source_reference=assignment.source_reference, gitlab_issue_external_id=issue_id,
                        title=((issue.title if issue is not None else None) or (intake.normalized_title if intake is not None else None) or assignment.source_reference)[:255],
                        summary="Đưa về chờ phân công từ kế hoạch ngày", status="READY", proposed_priority=priority,
                        requested_hours=assignment.planned_hours, target_slot=None, idempotency_key_hash=key_hash, request_hash=None,
                        created_by=actor_id, created_at=now, updated_at=now,
                    )
                    session.add(candidate)
                else:
                    candidate.status, candidate.member_id, candidate.assignment_id, candidate.updated_at = "READY", None, None, now
            for warning in session.scalars(select(PlanningWarning).where(PlanningWarning.assignment_id == assignment.id)).all():
                session.delete(warning)
            session.delete(assignment)
            run.version += 1
            run.status = "REVIEW_REQUIRED"
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="planning.assignment.unassigned",
                entity_type="planning_run", entity_id=run.id,
                details={"assignment_id": assignment_id, "member_id": str(assignment.member_id), "gitlab_issue": issue_id, "candidate_id": str(candidate.id)},
                created_at=now,
            ))
            session.commit()
            return self._run_dict(session, run)

    def add_assignment(self, run_id: str, payload: PlanningAssignmentCreate, actor_id: str) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            if run.version != payload.expected_run_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before saving")
            project = self._resolve_project(session, payload.project_id)
            if str(project.id) not in set(run.project_scope):
                raise PlanningValidationError("PROJECT_OUTSIDE_PLANNING_SCOPE", "Project is outside planning scope")
            member = session.get(WorkforceMember, payload.member_id)
            if member is None or member.status != "ACTIVE":
                raise PlanningValidationError("MEMBER_NOT_ACTIVE", "Workforce member does not exist or is inactive")
            membership = session.scalar(select(WorkforceProjectMembership).where(
                WorkforceProjectMembership.member_id == member.id,
                WorkforceProjectMembership.project_id == project.id,
                WorkforceProjectMembership.active.is_(True),
            ))
            issue_id = self._normalize_issue_reference(payload.gitlab_issue_external_id or "") or None
            if payload.work_type in DELIVERY_WORK_TYPES and not issue_id:
                raise PlanningValidationError("GITLAB_ISSUE_REQUIRED", "Delivery assignment requires a GitLab Issue")
            if issue_id:
                self._ensure_issue_not_planned(session, str(run.id), str(project.id), issue_id)
            assignee_id = payload.approved_assignee_external_id
            if assignee_id is None and membership is not None:
                assignee_id = membership.gitlab_user_external_id
            assignments = session.scalars(select(PlanningAssignment).where(
                PlanningAssignment.planning_run_id == run.id,
                PlanningAssignment.member_id == member.id,
            )).all()
            capacity_row = session.scalar(select(DailyCapacity).where(
                DailyCapacity.member_id == member.id, DailyCapacity.work_date == run.plan_date,
            ))
            capacity = self._capacity_dict(session, member, run.plan_date, capacity_row)
            total_hours = sum(float(item.planned_hours) for item in assignments) + payload.planned_hours
            slot_hours = sum(float(item.planned_hours) for item in assignments if item.slot == payload.slot) + payload.planned_hours
            has_override = bool((payload.override_reason or "").strip())
            elsewhere = self._hours_elsewhere(session, str(member.id), run.plan_date, list(run.project_scope), str(run.id))
            if total_hours + elsewhere > float(capacity["available_hours"]) and not has_override:
                raise PlanningValidationError("OVER_CAPACITY", "Assignment exceeds available daily capacity")
            if slot_hours > 4 and not has_override:
                raise PlanningValidationError("SLOT_OVER_CAPACITY", "Assignment exceeds four hours in the selected slot")
            if payload.is_primary and payload.work_type == "DEVELOPMENT":
                primary_issues = {item.gitlab_issue_external_id for item in assignments if item.is_primary and item.work_type == "DEVELOPMENT"}
                if primary_issues and issue_id not in primary_issues and not has_override:
                    raise PlanningValidationError("MULTIPLE_PRIMARY_DOING", "Member already has a different primary development Issue")
            assignment = PlanningAssignment(
                id=str(uuid4()), planning_run_id=run.id, project_id=project.id, member_id=member.id,
                slot=payload.slot, work_type=payload.work_type, is_primary=payload.is_primary,
                planned_hours=payload.planned_hours, source_type=payload.source_type,
                source_reference=payload.source_reference, gitlab_issue_external_id=issue_id,
                approved_priority=payload.approved_priority, approved_assignee_external_id=assignee_id,
                approved_milestone_external_id=payload.approved_milestone_external_id,
                approved_due_date=payload.approved_due_date, dependency_state=payload.dependency_state,
                source_state=payload.source_state,
                override_reason=payload.override_reason.strip() if payload.override_reason else None,
                version=1, created_at=now, updated_at=now,
            )
            session.add(assignment)
            run.status = "REVIEW_REQUIRED"
            run.version += 1
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id,
                event_type="planning.assignment.created", entity_type="planning_assignment", entity_id=assignment.id,
                details={"planning_run_id": run.id, "slot": payload.slot, "planned_hours": payload.planned_hours},
                created_at=now,
            ))
            session.commit()
            return self._assignment_dict(assignment)

    def approve(self, run_id: str, payload: PlanningApprovalRequest, actor_id: str) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                existing = session.scalar(select(PlanningApprovalSnapshot).where(
                    PlanningApprovalSnapshot.planning_run_id == run.id,
                    PlanningApprovalSnapshot.run_version == payload.expected_version,
                ))
                if existing is not None:
                    return self._approval_dict(session, run, existing)
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Planning run is already approved")
            if run.version != payload.expected_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before approval")
            assignments = session.scalars(select(PlanningAssignment).where(
                PlanningAssignment.planning_run_id == run.id,
            ).order_by(PlanningAssignment.project_id, PlanningAssignment.gitlab_issue_external_id, PlanningAssignment.slot)).all()
            if not assignments:
                raise PlanningValidationError("PLANNING_EMPTY", "Planning run has no assignments")
            critical_warnings = session.scalars(select(PlanningWarning).where(
                PlanningWarning.planning_run_id == run.id,
                PlanningWarning.severity == "CRITICAL",
                PlanningWarning.acknowledged_at.is_(None),
            )).all()
            acknowledged = set(payload.acknowledged_warning_ids)
            if any(str(w.id) not in acknowledged for w in critical_warnings):
                raise PlanningValidationError("CRITICAL_WARNING_UNACKNOWLEDGED", "Critical warnings must be acknowledged")
            # A missing milestone or due date is a warning the person closing the plan must have seen (ADR-0013),
            # not a reason to refuse the plan; the tracker update then sends only the fields that have a value.
            field_warnings = session.scalars(select(PlanningWarning).where(
                PlanningWarning.planning_run_id == run.id, PlanningWarning.code.in_(MISSING_FIELD_WARNINGS), PlanningWarning.acknowledged_at.is_(None),
            )).all()
            if any(str(w.id) not in acknowledged for w in field_warnings):
                raise PlanningValidationError("WARNING_UNACKNOWLEDGED", "Đánh dấu đã xem cảnh báo thiếu milestone hoặc hạn chót ở \"Cảnh báo cần xem\" rồi chốt lại")
            issue_payloads: dict[tuple[str, str], dict[str, object]] = {}
            serialized_assignments: list[dict[str, object]] = []
            # Delivery in a customer's GitHub: the plan is approved and kept here, nothing is written back.
            read_only_projects = self._github_projects(session, run.project_scope)
            for assignment in assignments:
                if assignment.work_type in DELIVERY_WORK_TYPES:
                    if not assignment.gitlab_issue_external_id:
                        raise PlanningValidationError("GITLAB_ISSUE_REQUIRED", "Delivery assignment requires a GitLab Issue")
                    if not assignment.approved_assignee_external_id:
                        raise PlanningValidationError("GITLAB_ASSIGNEE_REQUIRED", "GitLab assignee mapping is required")
                    if str(assignment.project_id) in read_only_projects:
                        serialized_assignments.append(self._assignment_dict(assignment))
                        continue
                    key = (str(assignment.project_id), assignment.gitlab_issue_external_id)
                    update_payload: dict[str, object] = {
                        "issue_external_id": assignment.gitlab_issue_external_id,
                        "assignee_external_id": assignment.approved_assignee_external_id,
                    }
                    if assignment.approved_milestone_external_id:
                        update_payload["milestone_external_id"] = assignment.approved_milestone_external_id
                    if assignment.approved_due_date:
                        update_payload["due_date"] = assignment.approved_due_date.isoformat()
                    if key in issue_payloads and issue_payloads[key] != update_payload:
                        raise PlanningValidationError("ISSUE_UPDATE_CONFLICT", "GitLab Issue has conflicting approved fields across slots")
                    issue_payloads[key] = update_payload
                serialized_assignments.append(self._assignment_dict(assignment))
            snapshot_payload = {
                "planning_run_id": str(run.id), "plan_date": run.plan_date.isoformat(), "timezone": run.timezone,
                "project_ids": list(run.project_scope), "assignments": serialized_assignments,
            }
            snapshot = PlanningApprovalSnapshot(
                id=str(uuid4()), planning_run_id=run.id, run_version=run.version, approved_by=actor_id,
                approved_at=now, payload=snapshot_payload, payload_hash=_canonical_hash(snapshot_payload),
                warning_acknowledgements={"ids": sorted(acknowledged)},
                override_reason=payload.override_reason.strip() if payload.override_reason else None,
                created_at=now,
            )
            session.add(snapshot)
            session.flush()
            # A reopened plan writes only what changed since the last successful sync of the plan it replaces.
            already_synced = self._synced_issue_payloads(session, run)
            to_sync = {key: payload for key, payload in issue_payloads.items() if already_synced.get(key) != payload}
            for (project_id, issue_id), update_payload in to_sync.items():
                job_id = str(uuid4())
                job_key = f"planning:{snapshot.id}:{project_id}:{issue_id}"
                session.add(PlanningSyncJob(
                    id=job_id, planning_snapshot_id=snapshot.id, project_id=project_id,
                    gitlab_issue_external_id=issue_id, status="PENDING", idempotency_key=job_key,
                    request_payload_hash=_canonical_hash(update_payload), after_state=update_payload,
                    attempt=0, max_attempts=5, created_at=now, updated_at=now,
                ))
                session.add(OutboxEvent(
                    id=str(uuid4()), aggregate_type="planning_sync_job", aggregate_id=job_id,
                    project_id=project_id, event_type=PLANNING_SYNC_EVENT,
                    payload={"planning_sync_job_id": job_id}, status="NEW",
                    dedupe_key=f"planning-sync-dispatch:{job_id}", attempt=0, created_at=now,
                ))
            for warning in [*critical_warnings, *field_warnings]:
                if str(warning.id) in acknowledged:
                    warning.acknowledged_by = actor_id
                    warning.acknowledged_at = now
            run.status = "SYNCING" if to_sync else "APPROVED"
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id,
                event_type="planning.run.approved", entity_type="planning_run", entity_id=run.id,
                details={"snapshot_id": snapshot.id, "job_count": len(to_sync), "unchanged": len(issue_payloads) - len(to_sync)}, created_at=now,
            ))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise PlanningValidationError("PLANNING_APPROVAL_CONFLICT", "Planning approval already exists") from exc
            return self._approval_dict(session, run, snapshot)

    @staticmethod
    def _sync_job_dict(job: PlanningSyncJob) -> dict[str, object]:
        return {
            "id": str(job.id),
            "project_id": str(job.project_id),
            "gitlab_issue_external_id": job.gitlab_issue_external_id,
            "status": job.status,
            "attempt": job.attempt,
            "max_attempts": job.max_attempts,
            "error_code": job.error_code,
            "next_attempt_at": job.next_attempt_at,
            "updated_at": job.updated_at,
        }

    def list_sync_jobs(self, run_id: str) -> dict[str, object]:
        with get_session() as session:
            run = session.get(PlanningRun, run_id)
            if run is None:
                raise KeyError(run_id)
            snapshot = session.scalar(select(PlanningApprovalSnapshot).where(
                PlanningApprovalSnapshot.planning_run_id == run.id,
            ).order_by(PlanningApprovalSnapshot.created_at.desc()))
            if snapshot is None:
                return {
                    "planning_run_id": str(run.id), "snapshot_id": None,
                    "status": run.status, "jobs": [],
                }
            jobs = session.scalars(select(PlanningSyncJob).where(
                PlanningSyncJob.planning_snapshot_id == snapshot.id,
            ).order_by(PlanningSyncJob.project_id, PlanningSyncJob.gitlab_issue_external_id)).all()
            return {
                "planning_run_id": str(run.id), "snapshot_id": str(snapshot.id),
                "status": run.status, "jobs": [self._sync_job_dict(job) for job in jobs],
            }

    def retry_sync_job(self, run_id: str, job_id: str, actor_id: str) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = session.scalar(
                select(PlanningSyncJob)
                .join(PlanningApprovalSnapshot, PlanningApprovalSnapshot.id == PlanningSyncJob.planning_snapshot_id)
                .where(
                    PlanningSyncJob.id == job_id,
                    PlanningApprovalSnapshot.planning_run_id == run_id,
                )
                .with_for_update()
            )
            if job is None:
                raise KeyError(job_id)
            if job.status != "FAILED" or job.attempt >= job.max_attempts:
                raise PlanningValidationError(
                    "PLANNING_SYNC_NOT_RETRYABLE",
                    "Only failed GitLab sync jobs with attempts remaining can be retried",
                )
            job.status = "PENDING"
            job.next_attempt_at = None
            job.lease_expires_at = None
            job.error_code = None
            job.error_detail_redacted = None
            job.updated_at = now
            retry_sequence = job.attempt + 1
            session.add(OutboxEvent(
                id=str(uuid4()), aggregate_type="planning_sync_job", aggregate_id=job.id,
                project_id=job.project_id, event_type=PLANNING_SYNC_EVENT,
                payload={"planning_sync_job_id": str(job.id)}, status="NEW",
                dedupe_key=f"planning-sync-retry:{job.id}:{retry_sequence}",
                attempt=0, created_at=now,
            ))
            self._refresh_run_status(session, job.planning_snapshot_id)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=job.project_id, actor_type="USER", actor_id=actor_id,
                event_type="planning.gitlab-update.retry-requested",
                entity_type="planning_sync_job", entity_id=job.id,
                details={"planning_run_id": run_id, "next_attempt": retry_sequence}, created_at=now,
            ))
            session.commit()
            return self._sync_job_dict(job)

    def claim_sync_job(self, job_id: str, worker_id: str) -> PlanningSyncContext | None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = session.scalar(select(PlanningSyncJob).where(PlanningSyncJob.id == job_id).with_for_update())
            if job is None or job.status in {"SUCCEEDED", "FAILED"}:
                return None
            if job.status == "RUNNING" and job.lease_expires_at and job.lease_expires_at > now:
                return None
            if job.next_attempt_at is not None and job.next_attempt_at > now:
                return None
            if job.attempt >= job.max_attempts:
                job.status = "FAILED"
                job.error_code = "PLANNING_SYNC_ATTEMPTS_EXHAUSTED"
                job.lease_expires_at = None
                job.updated_at = now
                self._refresh_run_status(session, job.planning_snapshot_id)
                session.commit()
                return None
            snapshot = session.get(PlanningApprovalSnapshot, job.planning_snapshot_id)
            if snapshot is None:
                raise PlanningValidationError("PLANNING_SNAPSHOT_MISSING", "Planning approval snapshot is missing")
            run = session.get(PlanningRun, snapshot.planning_run_id)
            mapping = session.scalar(select(ProjectIntegration).where(
                ProjectIntegration.project_id == job.project_id,
                ProjectIntegration.system == "GITLAB",
            ))
            if run is None or mapping is None or not mapping.enabled or not mapping.project_external_id:
                raise PlanningValidationError("GITLAB_MAPPING_DISABLED", "GitLab project mapping is not enabled")
            update_payload = job.after_state if isinstance(job.after_state, dict) else {}
            required = {"issue_external_id", "assignee_external_id"}
            if not required.issubset(update_payload) or not all(update_payload.get(key) for key in required):
                raise PlanningValidationError("PLANNING_SYNC_PAYLOAD_INVALID", "Planning GitLab update payload is incomplete")
            job.status = "RUNNING"
            job.attempt += 1
            job.next_attempt_at = None
            job.lease_expires_at = now + timedelta(seconds=300)
            job.error_code = None
            job.error_detail_redacted = None
            job.updated_at = now
            session.commit()
            return PlanningSyncContext(
                job_id=str(job.id),
                planning_run_id=str(run.id),
                project_external_id=mapping.project_external_id,
                gitlab_issue_external_id=job.gitlab_issue_external_id,
                idempotency_key=job.idempotency_key,
                update_payload=update_payload,
                attempt=job.attempt,
                max_attempts=job.max_attempts,
            )

    def mark_sync_retry(self, job_id: str, error_code: str, delay_seconds: int) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = session.get(PlanningSyncJob, job_id)
            if job is None or job.status == "SUCCEEDED":
                return
            job.status = "RETRY"
            job.error_code = error_code[:128]
            job.error_detail_redacted = error_code[:255]
            job.next_attempt_at = now + timedelta(seconds=delay_seconds)
            job.lease_expires_at = None
            job.updated_at = now
            self._refresh_run_status(session, job.planning_snapshot_id)
            session.commit()

    def fail_sync(self, job_id: str, error_code: str) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = session.get(PlanningSyncJob, job_id)
            if job is None or job.status == "SUCCEEDED":
                return
            job.status = "FAILED"
            job.error_code = error_code[:128]
            job.error_detail_redacted = error_code[:255]
            job.next_attempt_at = None
            job.lease_expires_at = None
            job.updated_at = now
            self._refresh_run_status(session, job.planning_snapshot_id)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=job.project_id, actor_type="SYSTEM",
                actor_id="integration-worker", event_type="planning.gitlab-update.failed",
                entity_type="planning_sync_job", entity_id=job.id,
                details={"error_code": error_code[:128]}, created_at=now,
            ))
            session.commit()

    def complete_sync(self, job_id: str, before_state: dict[str, object], after_state: dict[str, object]) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            job = session.scalar(select(PlanningSyncJob).where(PlanningSyncJob.id == job_id).with_for_update())
            if job is None or job.status == "SUCCEEDED":
                return
            job.status = "SUCCEEDED"
            job.before_state = before_state
            job.after_state = after_state
            job.next_attempt_at = None
            job.lease_expires_at = None
            job.error_code = None
            job.error_detail_redacted = None
            job.updated_at = now
            self._refresh_run_status(session, job.planning_snapshot_id)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=job.project_id, actor_type="SYSTEM",
                actor_id="integration-worker", event_type="planning.gitlab-update.succeeded",
                entity_type="planning_sync_job", entity_id=job.id,
                details={"gitlab_issue_external_id": job.gitlab_issue_external_id}, created_at=now,
            ))
            session.commit()

    @staticmethod
    def _synced_issue_payloads(session, run: PlanningRun) -> dict[tuple[str, str], dict[str, object] | None]:
        """What GitLab already has for each Issue of the plans this one replaces: the after_state of jobs that
        succeeded, walking back through the superseded chain; an Issue whose last job failed maps to None so it is
        sent again."""
        found: dict[tuple[str, str], dict[str, object] | None] = {}
        previous_id = run.supersedes_run_id
        hops = 0
        while previous_id and hops < 12:
            hops += 1
            previous = session.get(PlanningRun, previous_id)
            if previous is None:
                break
            snapshot = session.scalar(select(PlanningApprovalSnapshot).where(
                PlanningApprovalSnapshot.planning_run_id == previous.id,
            ).order_by(PlanningApprovalSnapshot.approved_at.desc()))
            if snapshot is not None:
                for job in session.scalars(select(PlanningSyncJob).where(PlanningSyncJob.planning_snapshot_id == snapshot.id)).all():
                    key = (str(job.project_id), job.gitlab_issue_external_id)
                    if key in found:
                        continue
                    found[key] = job.after_state if job.status == "SUCCEEDED" and isinstance(job.after_state, dict) else None
            previous_id = previous.supersedes_run_id
        return found

    def reopen(self, run_id: str, expected_version: int, actor_id: str) -> dict[str, object]:
        """A closed plan becomes a new revision that can be edited; the closed one stays as it was, marked superseded
        (FR-PLAN-18). Work, hours, priorities, what people reported on their work and the warnings already seen all
        carry over. While a GitLab sync of the closed plan is still running, wait."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_OPEN", "Kế hoạch này đang mở, sửa trực tiếp được")
            if run.status == "SUPERSEDED":
                raise PlanningValidationError("PLANNING_RUN_SUPERSEDED", "Kế hoạch này đã được thay bằng bản mới hơn")
            if run.status not in CLOSED_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", f"Kế hoạch ở trạng thái {run.status} không mở lại được")
            if run.version != expected_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before reopening")
            snapshot = session.scalar(select(PlanningApprovalSnapshot).where(
                PlanningApprovalSnapshot.planning_run_id == run.id,
            ).order_by(PlanningApprovalSnapshot.approved_at.desc()))
            if snapshot is not None and session.scalar(select(PlanningSyncJob.id).where(
                PlanningSyncJob.planning_snapshot_id == snapshot.id, PlanningSyncJob.status.in_(SYNC_OPEN_STATES),
            )):
                raise PlanningValidationError("PLANNING_SYNC_IN_PROGRESS", "Đang ghi kế hoạch lên GitLab; đợi xong rồi mở lại")
            fresh = PlanningRun(
                id=str(uuid4()), plan_date=run.plan_date, timezone=run.timezone, project_scope=list(run.project_scope), scope_hash=run.scope_hash,
                status="REVIEW_REQUIRED", version=1, revision=run.revision + 1, source_snapshot_at=now, report_cutoff_at=run.report_cutoff_at,
                gitlab_snapshot_at=run.gitlab_snapshot_at, supersedes_run_id=run.id, created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(fresh)
            session.flush()
            new_ids: dict[str, str] = {}
            for old in session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id)).all():
                copy = PlanningAssignment(
                    id=str(uuid4()), planning_run_id=fresh.id, project_id=old.project_id, member_id=old.member_id, slot=old.slot, work_type=old.work_type,
                    is_primary=old.is_primary, planned_hours=old.planned_hours, source_type=old.source_type, source_reference=old.source_reference,
                    gitlab_issue_external_id=old.gitlab_issue_external_id, proposed_priority=old.proposed_priority, approved_priority=old.approved_priority,
                    proposed_assignee_external_id=old.proposed_assignee_external_id, approved_assignee_external_id=old.approved_assignee_external_id,
                    proposed_milestone_external_id=old.proposed_milestone_external_id, approved_milestone_external_id=old.approved_milestone_external_id,
                    proposed_due_date=old.proposed_due_date, approved_due_date=old.approved_due_date, dependency_state=old.dependency_state,
                    source_state=old.source_state, override_reason=old.override_reason, version=1,
                    work_status=old.work_status, work_status_at=old.work_status_at, work_status_note=old.work_status_note, created_at=now, updated_at=now,
                )
                session.add(copy)
                new_ids[str(old.id)] = copy.id
            session.flush()
            for old in session.scalars(select(PlanningCandidate).where(PlanningCandidate.planning_run_id == run.id)).all():
                session.add(PlanningCandidate(
                    id=str(uuid4()), planning_run_id=fresh.id, project_id=old.project_id, member_id=old.member_id, intake_id=old.intake_id,
                    assignment_id=new_ids.get(str(old.assignment_id)) if old.assignment_id else None, source_type=old.source_type,
                    source_reference=old.source_reference, gitlab_issue_external_id=old.gitlab_issue_external_id,
                    title=old.title, summary=old.summary, status=old.status, proposed_priority=old.proposed_priority, requested_hours=old.requested_hours,
                    target_slot=old.target_slot, idempotency_key_hash=None, request_hash=old.request_hash, created_by=old.created_by, created_at=now, updated_at=now,
                ))
            for old in session.scalars(select(PlanningWarning).where(PlanningWarning.planning_run_id == run.id)).all():
                session.add(PlanningWarning(
                    id=str(uuid4()), planning_run_id=fresh.id, assignment_id=new_ids.get(str(old.assignment_id)) if old.assignment_id else None,
                    member_id=old.member_id, project_id=old.project_id, code=old.code, severity=old.severity, source_values=old.source_values,
                    message=old.message, acknowledged_by=old.acknowledged_by, acknowledged_at=old.acknowledged_at, created_at=now,
                ))
            for pick in session.scalars(select(IssueVerification).where(IssueVerification.planning_run_id == run.id, IssueVerification.decision == "PENDING")).all():
                pick.planning_run_id = fresh.id
            run.status = "SUPERSEDED"
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="planning.run.reopened", entity_type="planning_run", entity_id=fresh.id,
                details={"supersedes_run_id": str(run.id), "revision": fresh.revision, "assignments": len(new_ids)}, created_at=now,
            ))
            session.commit()
            return self._run_dict(session, fresh)

    @staticmethod
    def _refresh_run_status(session, snapshot_id: str) -> None:
        snapshot = session.get(PlanningApprovalSnapshot, snapshot_id)
        if snapshot is None:
            return
        run = session.get(PlanningRun, snapshot.planning_run_id)
        if run is None:
            return
        statuses = list(session.scalars(select(PlanningSyncJob.status).where(
            PlanningSyncJob.planning_snapshot_id == snapshot_id,
        )).all())
        if statuses and all(value == "SUCCEEDED" for value in statuses):
            run.status = "SYNCED"
        elif "FAILED" in statuses and "SUCCEEDED" in statuses:
            run.status = "PARTIAL"
        elif statuses and all(value == "FAILED" for value in statuses):
            run.status = "SYNC_FAILED"
        else:
            run.status = "SYNCING"
        run.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _assignment_dict(assignment: PlanningAssignment) -> dict[str, object]:
        return {
            "id": str(assignment.id), "project_id": str(assignment.project_id), "member_id": str(assignment.member_id),
            "slot": assignment.slot, "work_type": assignment.work_type, "is_primary": assignment.is_primary,
            "planned_hours": float(assignment.planned_hours), "source_type": assignment.source_type,
            "source_reference": assignment.source_reference,
            "gitlab_issue_external_id": assignment.gitlab_issue_external_id,
            "proposed_priority": assignment.proposed_priority,
            "approved_priority": assignment.approved_priority,
            "proposed_assignee_external_id": assignment.proposed_assignee_external_id,
            "approved_assignee_external_id": assignment.approved_assignee_external_id,
            "proposed_milestone_external_id": assignment.proposed_milestone_external_id,
            "approved_milestone_external_id": assignment.approved_milestone_external_id,
            "proposed_due_date": assignment.proposed_due_date.isoformat() if assignment.proposed_due_date else None,
            "approved_due_date": assignment.approved_due_date.isoformat() if assignment.approved_due_date else None,
            "dependency_state": assignment.dependency_state,
            "source_state": assignment.source_state,
            "override_reason": assignment.override_reason, "version": assignment.version,
            "work_status": assignment.work_status or "PLANNED",
            "work_status_at": assignment.work_status_at.isoformat() if assignment.work_status_at else None,
            "work_status_note": assignment.work_status_note,
        }

    def _with_intakes(self, session, assignments) -> list[dict[str, object]]:
        """Assignments, each with the Intake its Issue came from, so the plan links back to the request."""
        issue_ids = {item.gitlab_issue_external_id for item in assignments if item.gitlab_issue_external_id}
        origin: dict[tuple[str, str], tuple[str, str]] = {}
        titles: dict[tuple[str, str], str] = {}
        urls: dict[tuple[str, str], str | None] = {}
        if issue_ids:
            for link, intake in session.execute(
                select(ExternalLink, IntakeItem).join(IntakeItem, IntakeItem.id == ExternalLink.intake_id).where(
                    ExternalLink.target_system.in_(("GITLAB", "GITHUB")), ExternalLink.external_id.in_(sorted(issue_ids)),
                )
            ).all():
                key = (str(link.project_id), link.external_id)
                origin[key] = (str(intake.id), intake.public_id)
                if link.url:
                    urls.setdefault(key, link.url)
        if issue_ids:
            for issue in session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.issue_external_id.in_(sorted(issue_ids)), GitLabIssueSnapshot.is_current.is_(True),
            )):
                titles[(str(issue.project_id), issue.issue_external_id)] = issue.title
                urls[(str(issue.project_id), issue.issue_external_id)] = issue.web_url
        # When the CTO accepted the Issue behind a placed item: the plan keeps the item as the record of the day, and
        # every screen draws it as accepted instead of as work still to do (INT-26W43-001).
        accepted = self.accepted_at_by_issue(session, sorted({str(item.project_id) for item in assignments if item.gitlab_issue_external_id}))
        rows = []
        for item in assignments:
            row = self._assignment_dict(item)
            key = (str(item.project_id), item.gitlab_issue_external_id or "")
            found = origin.get(key)
            row["intake_id"], row["intake_public_id"] = found if found else (None, None)
            row["title"] = titles.get(key)
            row["issue_url"] = urls.get(key)
            row["accepted_at"] = accepted.get(key) if item.gitlab_issue_external_id else None
            rows.append(row)
        return rows

    def _with_candidate_links(self, session, candidates) -> list[dict[str, object]]:
        """Waiting entries, each with the code of its Intake and the link of its Issue, so a Project Owner can open
        either and see the work behind the line (FR-PLAN-33)."""
        rows = [self._candidate_dict(item) for item in candidates]
        intake_ids = {row["intake_id"] for row in rows if row["intake_id"]}
        intakes = {str(item.id): item for item in session.scalars(select(IntakeItem).where(IntakeItem.id.in_(sorted(intake_ids)))).all()} if intake_ids else {}
        codes = {key: item.public_id for key, item in intakes.items()}
        issue_ids = {row["gitlab_issue_external_id"] for row in rows if row["gitlab_issue_external_id"]}
        urls: dict[tuple[str, str], str | None] = {}
        if issue_ids:
            for link in session.scalars(select(ExternalLink).where(
                ExternalLink.target_system.in_(("GITLAB", "GITHUB")), ExternalLink.external_id.in_(sorted(issue_ids)),
            )).all():
                urls.setdefault((str(link.project_id), link.external_id), link.url)
            for issue in session.scalars(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.issue_external_id.in_(sorted(issue_ids)), GitLabIssueSnapshot.is_current.is_(True),
            )).all():
                if issue.web_url:
                    urls[(str(issue.project_id), issue.issue_external_id)] = issue.web_url
        # When the CTO accepted the Issue behind a line, so the screen takes "waiting for acceptance" down (INT-26W43-001).
        accepted_at: dict[tuple[str, str], datetime] = {}
        project_ids = sorted({str(row["project_id"]) for row in rows if row["gitlab_issue_external_id"]})
        if project_ids:
            for verification in self._accepted_verifications(session, project_ids):
                accepted_at.setdefault((str(verification.project_id), verification.issue_external_id), verification.decided_at)
        for row in rows:
            row["intake_public_id"] = codes.get(str(row["intake_id"])) if row["intake_id"] else None
            row["issue_url"] = urls.get((str(row["project_id"]), str(row["gitlab_issue_external_id"]))) if row["gitlab_issue_external_id"] else None
            row["accepted_at"] = accepted_at.get((str(row["project_id"]), str(row["gitlab_issue_external_id"]))) if row["gitlab_issue_external_id"] else None
            # The date the line shows: when the Intake was created, or when this entry was listed for anything else.
            intake = intakes.get(str(row["intake_id"])) if row["intake_id"] else None
            row["origin_at"] = intake.created_at if intake is not None else row.get("created_at")
        return rows

    def _run_dict(self, session, run: PlanningRun) -> dict[str, object]:
        assignments = session.scalars(select(PlanningAssignment).where(
            PlanningAssignment.planning_run_id == run.id,
        ).order_by(PlanningAssignment.member_id, PlanningAssignment.slot, PlanningAssignment.created_at)).all()
        candidates = session.scalars(select(PlanningCandidate).where(
            PlanningCandidate.planning_run_id == run.id,
        ).order_by(PlanningCandidate.created_at, PlanningCandidate.id)).all()
        warnings = session.scalars(select(PlanningWarning).where(
            PlanningWarning.planning_run_id == run.id,
        ).order_by(PlanningWarning.severity, PlanningWarning.created_at)).all()
        return {
            "id": str(run.id), "plan_date": run.plan_date, "timezone": run.timezone,
            "project_ids": list(run.project_scope), "status": run.status, "version": run.version,
            "revision": run.revision, "supersedes_run_id": str(run.supersedes_run_id) if run.supersedes_run_id else None, "source_snapshot_at": run.source_snapshot_at,
            "assignments": self._with_intakes(session, assignments),
            "candidates": self._with_candidate_links(session, candidates),
            "verifications": self._verification_dicts(session, run),
            "warnings": [{
                "id": str(w.id), "code": w.code, "severity": w.severity, "message": w.message,
                "member_id": str(w.member_id) if w.member_id else None,
                "project_id": str(w.project_id) if w.project_id else None,
                "assignment_id": str(w.assignment_id) if w.assignment_id else None,
                "acknowledged_at": w.acknowledged_at,
            } for w in warnings],
        }

    @staticmethod
    def _approval_dict(session, run: PlanningRun, snapshot: PlanningApprovalSnapshot) -> dict[str, object]:
        jobs = session.scalars(select(PlanningSyncJob).where(
            PlanningSyncJob.planning_snapshot_id == snapshot.id,
        ).order_by(PlanningSyncJob.project_id, PlanningSyncJob.gitlab_issue_external_id)).all()
        return {
            "planning_run_id": str(run.id), "snapshot_id": str(snapshot.id), "status": run.status,
            "jobs": [PlanningService._sync_job_dict(job) for job in jobs],
        }


planning_service = PlanningService()
