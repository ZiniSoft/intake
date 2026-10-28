"""Add work to an open Planning Run in one step (ADR-0024).

Work that already has an Issue is assigned straight away. Work that has none goes through the normal
approval and sync path, started here by the CTO with a reason, and is assigned once the Issue exists.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import or_, select

from app.db import get_session
from app.models import (
    ApprovalSnapshot,
    ExternalLink,
    GitLabIssueSnapshot,
    IntakeItem,
    PlanningAssignment,
    PlanningCandidate,
    PlanningRun,
    Project,
    ProjectIntegration,
    WorkforceProjectMembership,
    User,
    WorkforceMember,
)
from app.modules.planning.overview import LOCAL_TZ
from app.modules.planning.service import MUTABLE_RUN_STATES, PlanningValidationError, _canonical_hash, planning_service
from app.modules.reports.service import normalized_task_title

# The note of a waiting entry that was done outside the plan starts with this; the UI reads it back.
DONE_ELSEWHERE_PREFIX = "Đã làm xong ngoài kế hoạch: "
from app.schemas import IntakeCreate, IntakeDecision, PlanningCandidatePromoteRequest, PlanningQuickAddRequest

DELIVERY_SYSTEMS = ("GITLAB", "GITHUB")


# Words that say nothing about what an Issue is about.
_FILLER = {"và", "của", "cho", "các", "một", "này", "trên", "trong", "với", "theo", "the", "and", "for", "from", "with", "issue", "task", "fix", "bug"}


def _title_words(title: str | None) -> set[str]:
    """The words of a title worth comparing: lower case, three letters or more, without filler and reference codes."""
    text = re.sub(r"\[[^\]]*\]|#\d+", " ", (title or "").casefold())
    return {word for word in re.findall(r"[^\W\d_]{3,}", text) if word not in _FILLER}


class AddWorkService:
    # --- finding existing work ----------------------------------------------------------------------

    def search(self, run_id: str, text: str | None, limit: int = 20, candidate_id: str | None = None) -> list[dict[str, object]]:
        """Open Issues and not-yet-delivered Intakes of the run's projects, to pick instead of typing an ID.

        With candidate_id (a waiting entry being scheduled) the Issues of its project come back most likely first:
        those assigned to the person the entry is from, then those whose title shares words with it.
        """
        needle = (text or "").strip().lstrip("#")
        with get_session() as session:
            run = session.get(PlanningRun, run_id)
            if run is None:
                raise KeyError(run_id)
            scope = list(run.project_scope)
            names = {str(row.id): row.name for row in session.scalars(select(Project).where(Project.id.in_(scope))).all()}
            planned = {
                (str(row.project_id), row.gitlab_issue_external_id)
                for row in session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id)).all()
            }
            # Who an Issue is assigned to, as people of the staff list rather than tracker accounts.
            people: dict[tuple[str, str], tuple[str, str]] = {}
            for membership, member in session.execute(
                select(WorkforceProjectMembership, WorkforceMember)
                .join(WorkforceMember, WorkforceMember.id == WorkforceProjectMembership.member_id)
                .where(WorkforceProjectMembership.project_id.in_(scope), WorkforceProjectMembership.gitlab_user_external_id.is_not(None))
            ).all():
                people[(str(membership.project_id), str(membership.gitlab_user_external_id))] = (str(member.id), member.display_name)
            candidate = session.scalar(select(PlanningCandidate).where(
                PlanningCandidate.id == candidate_id, PlanningCandidate.planning_run_id == run.id,
            )) if candidate_id else None
            wanted_words = _title_words(candidate.title) if candidate is not None else set()

            issues = select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id.in_([candidate.project_id] if candidate is not None else scope),
                GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.state == "opened",
            )
            if needle:
                issues = issues.where(or_(GitLabIssueSnapshot.title.ilike(f"%{needle}%"), GitLabIssueSnapshot.issue_external_id == needle))
            # To rank, more than one page is read; what goes back is still one page.
            found = session.scalars(issues.order_by(GitLabIssueSnapshot.external_updated_at.desc().nullslast()).limit(200 if candidate is not None else limit)).all()
            rows: list[dict[str, object]] = []
            for issue in found:
                assignees = [people.get((str(issue.project_id), str(external))) for external in (issue.assignee_external_ids or [])]
                assignee_ids = {person[0] for person in assignees if person}
                shared = len(wanted_words & _title_words(issue.title))
                mine = candidate is not None and candidate.member_id is not None and str(candidate.member_id) in assignee_ids
                similar = bool(wanted_words) and shared >= min(2, len(wanted_words))
                rows.append({
                    "kind": "ISSUE", "project_id": str(issue.project_id), "project_name": names.get(str(issue.project_id)),
                    "issue_external_id": issue.issue_external_id, "intake_id": None, "public_id": None, "title": issue.title,
                    "priority": planning_service._priority_from_labels(issue.labels),
                    "already_planned": (str(issue.project_id), issue.issue_external_id) in planned, "needs_issue": False,
                    "url": issue.web_url, "assignee_names": [person[1] for person in assignees if person],
                    "unknown_assignees": sum(1 for person in assignees if person is None),
                    "milestone": issue.milestone_title, "due_date": issue.due_date,
                    "suggested": "PERSON" if mine else "TITLE" if similar else None,
                    "assigned_to_other": bool(issue.assignee_external_ids) and not mine and candidate is not None,
                    "_rank": (0 if mine else 1, -shared),
                })
            if candidate is not None:
                # Stable sort: within a rank the most recently updated stays first. Issues already in today's plan go last.
                rows.sort(key=lambda row: (row["already_planned"], row["suggested"] is None, *row["_rank"]))
                rows = rows[:max(limit, 30)]
            for row in rows:
                row.pop("_rank")
            if candidate is not None:
                return rows

            intakes = select(IntakeItem).where(
                IntakeItem.project_id.in_(scope), IntakeItem.status.in_(("PENDING_APPROVAL", "APPROVED", "SYNC_PENDING", "SYNCED")),
            )
            if needle:
                intakes = intakes.where(or_(IntakeItem.normalized_title.ilike(f"%{needle}%"), IntakeItem.public_id.ilike(f"%{needle}%")))
            known_issues = {(row["project_id"], row["issue_external_id"]) for row in rows}
            for item in session.scalars(intakes.order_by(IntakeItem.updated_at.desc()).limit(limit)).all():
                link = session.scalar(select(ExternalLink).where(
                    ExternalLink.intake_id == item.id, ExternalLink.target_system.in_(DELIVERY_SYSTEMS),
                ).order_by(ExternalLink.created_at.desc()))
                if link is not None and (str(item.project_id), link.external_id) in known_issues:
                    continue  # the Issue itself is already in the list
                if link is None and item.status != "PENDING_APPROVAL":
                    continue  # Historical external decision or pending delivery sync: not plannable from here.
                rows.append({
                    "kind": "INTAKE", "project_id": str(item.project_id), "project_name": names.get(str(item.project_id)),
                    "issue_external_id": link.external_id if link else None, "intake_id": str(item.id), "public_id": item.public_id,
                    "title": item.normalized_title or item.public_id,
                    "priority": item.approved_priority or item.suggested_priority,
                    "already_planned": bool(link and (str(item.project_id), link.external_id) in planned), "needs_issue": link is None,
                })
            return rows[:limit]

    # --- adding -------------------------------------------------------------------------------------

    def add(self, run_id: str, payload, actor_id: str) -> dict[str, object]:
        wants_assignment = bool(payload.member_id)
        if wants_assignment and not (payload.slot and payload.planned_hours):
            raise PlanningValidationError("ASSIGNMENT_INCOMPLETE", "Choose the slot and the hours for the person doing the work")

        if payload.source == "ISSUE":
            if not (payload.issue_external_id or "").strip():
                raise PlanningValidationError("WORK_REFERENCE_REQUIRED", "Choose the Issue to add")
            candidate = planning_service.quick_add(run_id, PlanningQuickAddRequest(
                expected_run_version=payload.expected_run_version, mode="EXISTING", project_id=payload.project_id,
                source_system="GITLAB", reference=payload.issue_external_id, requested_hours=payload.planned_hours, target_slot=payload.slot,
            ), actor_id)
            return self._assign_now(run_id, candidate, payload, actor_id) if wants_assignment else self._result("WAITING_ASSIGNMENT", candidate)

        if payload.source == "INTAKE":
            intake_id = (payload.intake_id or "").strip()
            if not intake_id:
                raise PlanningValidationError("WORK_REFERENCE_REQUIRED", "Choose the Intake to add")
            with get_session() as session:
                item = session.get(IntakeItem, intake_id)
                if item is None:
                    raise PlanningValidationError("INTAKE_NOT_FOUND", "Intake item was not found")
                has_issue = session.scalar(select(ExternalLink.id).where(
                    ExternalLink.intake_id == item.id, ExternalLink.target_system.in_(DELIVERY_SYSTEMS),
                )) is not None
            if has_issue:
                candidate = planning_service.quick_add(run_id, PlanningQuickAddRequest(
                    expected_run_version=payload.expected_run_version, mode="EXISTING", project_id=payload.project_id,
                    source_system="INTAKE", reference=intake_id, requested_hours=payload.planned_hours, target_slot=payload.slot,
                ), actor_id)
                if candidate.get("gitlab_issue_external_id") and wants_assignment:
                    return self._assign_now(run_id, candidate, payload, actor_id)
                return self._result("WAITING_ASSIGNMENT", candidate)
            return self._create_issue_then_plan(run_id, intake_id, payload, actor_id)

        # A request that exists nowhere yet.
        title = " ".join((payload.title or "").split())
        if not title:
            raise PlanningValidationError("WORK_TITLE_REQUIRED", "Give the new work a title")
        from app.services.intake_service import intake_store

        # Everything that can refuse the request is checked before an Intake is created.
        self._reason(payload)
        self._check_run(run_id, payload.expected_run_version, payload.project_id)
        content = (payload.content or "").strip()
        created = intake_store.create(IntakeCreate(
            project_id=payload.project_id, channel=payload.channel, raw_text=f"{title}\n\n{content}" if content else title,
        ))
        with get_session() as session:
            item = session.get(IntakeItem, created.id)
            # The CTO wrote this request and decides it here; it does not wait for AI normalization.
            item.normalized_title, item.normalized_summary = title[:255], content or title
            item.item_type, item.suggested_priority, item.proposed_route = payload.item_type, payload.priority, "GITLAB"
            item.status = "PENDING_APPROVAL"
            item.updated_at = datetime.now(timezone.utc)
            session.commit()
        return self._create_issue_then_plan(run_id, str(created.id), payload, actor_id)

    @staticmethod
    def _check_run(run_id: str, expected_version: int, project_ref: str) -> None:
        with get_session() as session:
            run = session.get(PlanningRun, run_id)
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            if run.version != expected_version:
                raise PlanningValidationError("PLANNING_VERSION_CONFLICT", "Planning run changed; reload before saving")
            project = planning_service._resolve_project(session, project_ref)
            if str(project.id) not in set(run.project_scope):
                raise PlanningValidationError("PROJECT_OUTSIDE_PLANNING_SCOPE", "Project is outside planning scope")
            has_delivery = session.scalar(select(ProjectIntegration.id).where(
                ProjectIntegration.project_id == project.id, ProjectIntegration.system.in_(DELIVERY_SYSTEMS),
                ProjectIntegration.enabled.is_(True), ProjectIntegration.project_external_id.is_not(None),
            )) is not None
            if not has_delivery:
                raise PlanningValidationError("DELIVERY_SYNC_DISABLED", "Sync to this project's GitLab or GitHub is not enabled, so an Issue cannot be created")

    @staticmethod
    def _reason(payload) -> str:
        reason = " ".join((payload.reason or "").split())
        if len(reason) < 5:
            raise PlanningValidationError("ADD_WORK_REASON_REQUIRED", "Say why this work goes into today's plan without the usual review")
        return reason

    def _create_issue_then_plan(self, run_id: str, intake_id: str, payload, actor_id: str) -> dict[str, object]:
        """Approve the Intake for delivery and queue its sync; the plan picks the Issue up when it exists."""
        self._start_issue(run_id, intake_id, payload, actor_id)
        # The caller's version was checked before the Intake was approved. Another Issue finishing meanwhile moves the
        # version; listing the already approved request must not fail then, or it is left approved without a plan line.
        with get_session() as session:
            version = session.get(PlanningRun, run_id).version
        candidate = planning_service.quick_add(run_id, PlanningQuickAddRequest(
            expected_run_version=version, mode="EXISTING", project_id=payload.project_id,
            source_system="INTAKE", reference=intake_id, requested_hours=payload.planned_hours, target_slot=payload.slot,
        ), actor_id)
        if payload.member_id:
            with get_session() as session:
                row = session.get(PlanningCandidate, candidate["id"])
                # Remembered so the work is assigned as soon as the Issue exists.
                row.member_id = payload.member_id
                session.commit()
            candidate["member_id"] = payload.member_id
        return self._result("CREATING_ISSUE", candidate)

    def _start_issue(self, run_id: str, intake_id: str, payload, actor_id: str) -> None:
        reason = self._reason(payload)
        self._check_run(run_id, payload.expected_run_version, payload.project_id)
        self.issue_for_intake(intake_id, priority=payload.priority, reason=f"Thêm vào kế hoạch trong ngày: {reason}", actor_id=actor_id, source="PLANNING")

    def issue_for_intake(self, intake_id: str, *, priority: str, reason: str, actor_id: str, source: str) -> None:
        """Decide the request for the delivery tracker and queue its sync, with no day plan involved: a request
        waiting for approval is approved; one standing as approved for WORK is redirected (FR-WRK-05)."""
        from app.modules.integrations.service import SyncValidationError, integration_service
        from app.services.intake_service import intake_store

        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                raise PlanningValidationError("INTAKE_NOT_READY", "Only an Intake that is waiting for approval can be added this way")
            status, route, version = item.status, item.approved_route, item.version
        try:
            if status == "APPROVED" and route == "WORK":
                intake_store.redirect_to_delivery(intake_id, priority=priority, reason=reason, actor_id=actor_id, source=source)
            elif status == "PENDING_APPROVAL":
                intake_store.approve(intake_id, IntakeDecision(
                    approved_route="GITLAB", approved_priority=priority, reason=reason, expected_version=version,
                ), actor_id=actor_id, source=source)
            else:
                raise PlanningValidationError("INTAKE_NOT_READY", "Only an Intake that is waiting for approval can be added this way")
        except RuntimeError as exc:
            raise PlanningValidationError("INTAKE_NOT_READY", f"The Intake could not be approved ({exc})") from exc
        with get_session() as session:
            snapshot_id = str(session.scalar(select(ApprovalSnapshot.id).where(
                ApprovalSnapshot.intake_id == intake_id, ApprovalSnapshot.invalidated_at.is_(None),
            ).order_by(ApprovalSnapshot.created_at.desc())))
        try:
            integration_service.queue_snapshot(snapshot_id, actor_id)
        except SyncValidationError as exc:
            raise PlanningValidationError(exc.code, str(exc)) from exc

    # --- work that is already waiting in the run ------------------------------------------------------

    def assign_waiting(self, run_id: str, candidate_id: str, payload, actor_id: str) -> dict[str, object]:
        """Schedule a waiting entry: link an existing Issue, or have one created, and assign it."""
        with get_session() as session:
            candidate = session.scalar(select(PlanningCandidate).where(
                PlanningCandidate.id == candidate_id, PlanningCandidate.planning_run_id == run_id,
            ))
            if candidate is None:
                raise PlanningValidationError("PLANNING_CANDIDATE_NOT_FOUND", "Planning candidate was not found")
            if candidate.status == "ASSIGNED":
                return self._result("PLANNED", planning_service._candidate_dict(candidate))
            current = planning_service._candidate_dict(candidate)
            project_id, intake_id = str(candidate.project_id), str(candidate.intake_id) if candidate.intake_id else None
            title, summary = candidate.title, candidate.summary
        issue_id = (payload.issue_external_id or current.get("gitlab_issue_external_id") or "").strip().lstrip("#")

        if payload.issue_mode == "EXISTING":
            if not issue_id:
                raise PlanningValidationError("WORK_REFERENCE_REQUIRED", "Choose the Issue this work belongs to")
            main = self._is_main_task(run_id, payload.member_id, issue_id)
            try:
                assigned = planning_service.promote_candidate(run_id, candidate_id, PlanningCandidatePromoteRequest(
                    expected_run_version=payload.expected_run_version, member_id=payload.member_id, gitlab_issue_external_id=issue_id,
                    slot=payload.slot, planned_hours=payload.planned_hours, is_primary=main, override_reason=payload.override_reason,
                ), actor_id)
            except PlanningValidationError as exc:
                if exc.code in ("PLANNING_VERSION_CONFLICT", "PLANNING_RUN_IMMUTABLE", "PLANNING_CANDIDATE_NOT_FOUND"):
                    raise
                return {**self._result("WAITING_ASSIGNMENT", current), "assignment_error": exc.code}
            return {**self._result("PLANNED", assigned), "added_as_secondary": not main}

        # No Issue yet: create one through the normal approval and sync path.
        from app.services.intake_service import intake_store

        request = _IssueRequest(payload, project_id)
        self._reason(request)
        self._check_run(run_id, payload.expected_run_version, project_id)
        if intake_id is None:
            created = intake_store.create(IntakeCreate(project_id=project_id, channel="MANUAL", raw_text=f"{title}\n\n{summary}" if summary else title))
            intake_id = str(created.id)
            with get_session() as session:
                item = session.get(IntakeItem, intake_id)
                item.normalized_title, item.normalized_summary = title[:255], summary or title
                item.item_type, item.suggested_priority, item.proposed_route = payload.item_type, payload.priority, "GITLAB"
                item.status = "PENDING_APPROVAL"
                item.updated_at = datetime.now(timezone.utc)
                session.commit()
        self._start_issue(run_id, intake_id, request, actor_id)
        with get_session() as session:
            row = session.get(PlanningCandidate, candidate_id)
            row.intake_id, row.member_id = intake_id, payload.member_id
            row.target_slot, row.requested_hours = payload.slot, payload.planned_hours
            row.updated_at = datetime.now(timezone.utc)
            session.commit()
            return self._result("CREATING_ISSUE", planning_service._candidate_dict(row))

    def set_dismissed(self, run_id: str, candidate_id: str, dismissed: bool, actor_id: str) -> dict[str, object]:
        """Hide a waiting entry from this day's plan, or bring it back. Tomorrow's run starts fresh."""
        from app.models import AuditEvent

        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", "Approved planning run cannot be edited")
            candidate = session.scalar(select(PlanningCandidate).where(
                PlanningCandidate.id == candidate_id, PlanningCandidate.planning_run_id == run.id,
            ))
            if candidate is None:
                raise PlanningValidationError("PLANNING_CANDIDATE_NOT_FOUND", "Planning candidate was not found")
            if candidate.status == "ASSIGNED":
                raise PlanningValidationError("CANDIDATE_ALREADY_PLANNED", "This work is already in the plan")
            if candidate.status == "DONE_ELSEWHERE":
                raise PlanningValidationError("CANDIDATE_DONE_ELSEWHERE", "This work was recorded as done outside the plan; it waits for acceptance, not for the plan")
            candidate.status = "REJECTED" if dismissed else ("READY" if candidate.gitlab_issue_external_id else "PENDING_TRIAGE")
            candidate.updated_at = now
            run.version += 1
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=candidate.project_id, actor_type="USER", actor_id=actor_id,
                event_type="planning.candidate.dismissed" if dismissed else "planning.candidate.restored",
                entity_type="planning_candidate", entity_id=candidate.id, details={"planning_run_id": str(run.id)}, created_at=now,
            ))
            session.commit()
            return planning_service._candidate_dict(candidate)

    def propose_work(self, project_id: str, member_id: str, plan_date: date, *, actor_id: str, text: str | None = None, issue: str | None = None,
                     intake_ref: str | None = None, hours: float | None = None, slot: str | None = None, channel: str = "WEB") -> dict[str, object]:
        """A member says "I could do this on that day" (FR-PLAN-35): an open Issue, an Intake with an Issue, or just
        words. It lands on the day's plan of the project as a waiting entry with the member's name, for the Project
        Owner to place or set aside. The plan is opened if it does not exist; a closed plan refuses."""
        from app.models import AuditEvent
        from app.schemas import PlanningRunCreate

        now = datetime.now(timezone.utc)
        text = (text or "").strip()
        issue_id = planning_service._normalize_issue_reference((issue or "").strip().lstrip("#")) if issue and issue.strip() else None
        with get_session() as session:
            project = session.get(Project, project_id)
            if project is None or project.status != "ACTIVE" or project.kind != "SOFTWARE":
                raise PlanningValidationError("PROJECT_NOT_PLANNABLE", "Only software projects are planned")
            member = session.get(WorkforceMember, member_id)
            if member is None:
                raise PlanningValidationError("MEMBER_REQUIRED", "Member not found")
            run = session.scalar(select(PlanningRun).where(
                PlanningRun.plan_date == plan_date, PlanningRun.scope_hash == _canonical_hash([str(project.id)]), PlanningRun.status != "SUPERSEDED",
            ).order_by(PlanningRun.revision.desc()))
            run_id = str(run.id) if run is not None else None
            member_name, project_name, project_code = member.display_name, project.name, project.code
        if run_id is None:
            run_id = str(planning_service.create_run(PlanningRunCreate(plan_date=plan_date, project_ids=[project_id]), actor_id)["id"])
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run.status not in MUTABLE_RUN_STATES:
                raise PlanningValidationError("PLANNING_RUN_IMMUTABLE", f"Kế hoạch {plan_date:%d/%m} của {project_name} đã chốt; đề xuất cho ngày khác")
            title: str | None = None
            intake_id: str | None = None
            if intake_ref and intake_ref.strip():
                ref = intake_ref.strip()
                intake = session.scalar(select(IntakeItem).where(IntakeItem.public_id == ref, IntakeItem.project_id == project_id)) or (
                    session.get(IntakeItem, ref) if len(ref) == 36 else None
                )
                if intake is None or str(intake.project_id) != str(project_id):
                    raise PlanningValidationError("INTAKE_NOT_FOUND", "Không thấy yêu cầu này trong dự án")
                intake_id = str(intake.id)
                title = intake.normalized_title or intake.public_id
                link = session.scalar(select(ExternalLink).where(
                    ExternalLink.intake_id == intake.id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")),
                ).order_by(ExternalLink.created_at.desc()))
                if link is not None and not issue_id:
                    issue_id = planning_service._normalize_issue_reference(link.external_id)
            if issue_id:
                snapshot = planning_service._current_gitlab_issue(session, str(project_id), issue_id)
                if snapshot is None:
                    raise PlanningValidationError("GITLAB_ISSUE_NOT_FOUND", f"Issue #{issue_id} không có trong danh sách Issue của dự án")
                if snapshot.state != "opened":
                    raise PlanningValidationError("GITLAB_ISSUE_CLOSED", f"Issue #{issue_id} đã đóng")
                title = title or snapshot.title
                taken = session.scalar(select(PlanningAssignment.id).where(
                    PlanningAssignment.planning_run_id == run.id, PlanningAssignment.gitlab_issue_external_id == issue_id,
                ))
                if taken is not None:
                    raise PlanningValidationError("CANDIDATE_ALREADY_PLANNED", f"Issue #{issue_id} đã nằm trong kế hoạch ngày đó")
            if not title:
                if len(text) < 3:
                    raise PlanningValidationError("PROPOSAL_TEXT_REQUIRED", "Ghi việc muốn làm, hoặc số Issue, hoặc mã Intake")
                title = text[:255]
            key_hash = hashlib.sha256(f"proposal:{run.id}:{member_id}:{issue_id or normalized_task_title(title)}".encode("utf-8")).hexdigest()
            existing = session.scalar(select(PlanningCandidate).where(PlanningCandidate.idempotency_key_hash == key_hash))
            if existing is not None:
                result = planning_service._candidate_dict(existing)
                result.update({"created": False, "run_id": str(run.id), "project_name": project_name, "project_code": project_code, "plan_date": plan_date})
                return result
            summary = f"Đề xuất của {member_name}" + (f" qua {channel}" if channel != "WEB" else "") + (f": {text}" if text and text != title else "")
            candidate = PlanningCandidate(
                id=str(uuid4()), planning_run_id=run.id, project_id=project_id, member_id=member_id, intake_id=intake_id, assignment_id=None,
                source_type="FORM", source_reference=f"Đề xuất của {member_name}", gitlab_issue_external_id=issue_id,
                title=title[:255], summary=summary[:2000], status="READY" if issue_id else "PENDING_TRIAGE", proposed_priority=None,
                requested_hours=hours, target_slot=slot, idempotency_key_hash=key_hash, request_hash=None,
                created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(candidate)
            run.version += 1
            run.status = "REVIEW_REQUIRED"
            run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project_id, actor_type="USER", actor_id=actor_id, event_type="planning.work.proposed",
                entity_type="planning_candidate", entity_id=candidate.id,
                details={"planning_run_id": str(run.id), "member_id": member_id, "issue": issue_id, "intake_id": intake_id, "channel": channel}, created_at=now,
            ))
            session.commit()
            result = planning_service._candidate_dict(candidate)
            result.update({"created": True, "run_id": str(run.id), "project_name": project_name, "project_code": project_code, "plan_date": plan_date})
            return result

    def mark_done_elsewhere(self, run_id: str, candidate_id: str, note: str, actor_id: str) -> dict[str, object]:
        """A waiting entry that was in fact done already, outside the plan (FR-PLAN-34): it leaves the waiting list
        with the note kept on it, and its Issue, if any, goes to acceptance so the CTO can confirm and close it.
        A closed plan takes this too; nothing placed changes."""
        from app.models import AuditEvent
        from app.modules.planning.work_status import offer_issue

        note = (note or "").strip()
        if len(note) < 3:
            raise PlanningValidationError("NOTE_REQUIRED", "Say who did it and when, so the record stands")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            run = session.scalar(select(PlanningRun).where(PlanningRun.id == run_id).with_for_update())
            if run is None:
                raise KeyError(run_id)
            candidate = session.scalar(select(PlanningCandidate).where(
                PlanningCandidate.id == candidate_id, PlanningCandidate.planning_run_id == run.id,
            ))
            if candidate is None:
                raise PlanningValidationError("PLANNING_CANDIDATE_NOT_FOUND", "Planning candidate was not found")
            if candidate.status == "ASSIGNED":
                raise PlanningValidationError("CANDIDATE_ALREADY_PLANNED", "This work is already in the plan")
            # Its own state, not "dismissed": it does not come back tomorrow and cannot be restored to the waiting list.
            candidate.status = "DONE_ELSEWHERE"
            candidate.summary = f"{DONE_ELSEWHERE_PREFIX}{note}"[:2000]
            candidate.updated_at = now
            queued = False
            if candidate.gitlab_issue_external_id:
                actor = session.get(User, actor_id)
                who = (actor.display_name or actor.auth_subject) if actor is not None else "người xếp việc"
                queued = offer_issue(
                    session, str(candidate.project_id), candidate.gitlab_issue_external_id, str(candidate.member_id) if candidate.member_id else None, run.plan_date, now,
                    note=f"{note} ({who}, {now.astimezone(LOCAL_TZ):%d/%m/%Y})",
                )
            if run.status in MUTABLE_RUN_STATES:
                run.version += 1
                run.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=candidate.project_id, actor_type="USER", actor_id=actor_id,
                event_type="planning.candidate.done-elsewhere", entity_type="planning_candidate", entity_id=candidate.id,
                details={"planning_run_id": str(run.id), "issue": candidate.gitlab_issue_external_id, "note": note, "acceptance_queued": queued}, created_at=now,
            ))
            session.commit()
            result = planning_service._candidate_dict(candidate)
            result["acceptance_queued"] = queued
            return result

    @staticmethod
    def _is_main_task(run_id: str, member_id: str, issue_id: str | None) -> bool:
        """A person has one main development Issue per day; work added next to it is secondary work."""
        with get_session() as session:
            other = session.scalar(select(PlanningAssignment.id).where(
                PlanningAssignment.planning_run_id == run_id, PlanningAssignment.member_id == member_id,
                PlanningAssignment.is_primary.is_(True), PlanningAssignment.work_type == "DEVELOPMENT",
                PlanningAssignment.gitlab_issue_external_id != (issue_id or ""),
            ))
            return other is None

    def _assign_now(self, run_id: str, candidate: dict[str, object], payload, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            version = session.get(PlanningRun, run_id).version
        main = self._is_main_task(run_id, payload.member_id, candidate.get("gitlab_issue_external_id") or payload.issue_external_id)
        try:
            assigned = planning_service.promote_candidate(run_id, str(candidate["id"]), PlanningCandidatePromoteRequest(
                expected_run_version=version, member_id=payload.member_id, slot=payload.slot, planned_hours=payload.planned_hours,
                is_primary=main, override_reason=payload.override_reason,
            ), actor_id)
        except PlanningValidationError as exc:
            # The work is in the run; only the assignment needs another look.
            return {**self._result("WAITING_ASSIGNMENT", candidate), "assignment_error": exc.code}
        return {**self._result("PLANNED", assigned), "added_as_secondary": not main}

    @staticmethod
    def _result(state: str, candidate: dict[str, object]) -> dict[str, object]:
        return {"state": state, "candidate": candidate, "assignment_error": None, "added_as_secondary": False}

    # --- called by the integration worker -------------------------------------------------------------

    def issue_created(self, intake_id: str, project_id: str, issue_id: str, url: str | None) -> int:
        """A delivery Issue now exists for an Intake: make it plannable today and finish waiting assignments."""
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is None:
                return 0
            current = session.scalar(select(GitLabIssueSnapshot).where(
                GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.issue_external_id == issue_id,
                GitLabIssueSnapshot.is_current.is_(True),
            ))
            if current is None:
                priority = (item.approved_priority or item.suggested_priority or "P3").lower()
                # The next scheduled refresh replaces this row with the tracker's own data.
                session.add(GitLabIssueSnapshot(
                    id=str(uuid4()), project_id=project_id, issue_external_id=issue_id, title=(item.normalized_title or item.public_id)[:512],
                    state="opened", labels=[f"priority:{priority}"], assignee_external_ids=[], milestone_external_id=None,
                    milestone_title=None, due_date=None, web_url=url, external_updated_at=now,
                    payload_hash=hashlib.sha256(f"intake-created:{project_id}:{issue_id}".encode()).hexdigest(),
                    is_current=True, fetched_at=now, last_seen_at=now,
                ))
            waiting = session.execute(
                select(PlanningCandidate, PlanningRun).join(PlanningRun, PlanningRun.id == PlanningCandidate.planning_run_id)
                .where(
                    PlanningCandidate.intake_id == intake_id, PlanningCandidate.assignment_id.is_(None),
                    PlanningCandidate.status.in_(("PENDING_TRIAGE", "READY")), PlanningRun.status.in_(tuple(MUTABLE_RUN_STATES)),
                )
            ).all()
            todo = []
            for candidate, run in waiting:
                candidate.gitlab_issue_external_id = issue_id
                candidate.status = "READY"
                candidate.proposed_priority = item.approved_priority or item.suggested_priority
                candidate.updated_at = now
                if candidate.member_id and candidate.target_slot and candidate.requested_hours:
                    todo.append((str(run.id), str(candidate.id), str(candidate.member_id), candidate.target_slot, float(candidate.requested_hours), str(run.created_by)))
            session.commit()
        assigned = 0
        for run_id, candidate_id, member_id, slot, hours, actor_id in todo:
            with get_session() as session:
                version = session.get(PlanningRun, run_id).version
            try:
                planning_service.promote_candidate(run_id, candidate_id, PlanningCandidatePromoteRequest(
                    expected_run_version=version, member_id=member_id, slot=slot, planned_hours=hours,
                    is_primary=self._is_main_task(run_id, member_id, issue_id),
                ), actor_id)
                assigned += 1
            except PlanningValidationError as exc:
                with get_session() as session:
                    row = session.get(PlanningCandidate, candidate_id)
                    row.summary = f"{row.summary or ''}\nChưa tự phân công được ({exc.code}); hãy phân công ở thẻ này.".strip()
                    session.commit()
        return assigned


class _IssueRequest:
    """The fields the issue-creation path reads, taken from an assignment request for a waiting entry."""

    def __init__(self, payload, project_id: str) -> None:
        self.reason, self.priority, self.project_id = payload.reason, payload.priority, project_id
        self.expected_run_version = payload.expected_run_version


add_work_service = AddWorkService()
