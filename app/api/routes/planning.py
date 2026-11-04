from typing import Literal
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import select

from app.api.errors import api_exception
from app.api.security import AuthContext, require_account, require_cto, require_member
from app.modules.planning.add_work import add_work_service
from app.modules.planning import scope as planning_scope
from app.modules.planning.day_plans import ProjectOrderError, day_plans, save_project_order
from app.modules.planning.work_status import WorkStatusError, set_work_status
from app.modules.planning.overview import day_overview
from app.modules.planning import mapping as tracker_mapping
from app.modules.planning.people import people_day
from app.modules.planning.snapshot import snapshot_board
from app.modules.planning.week import week_summary
from app.modules.planning.service import PlanningValidationError, planning_service
from app.schemas import (
    PeopleDayOut,
    PlanningOverviewOut,
    TrackerUserMappingRequest,
    TrackerUsersOut,
    WeekSummaryOut,
    PlanningAssignmentUnassign,
    ProjectAgentReadyUpdate,
    ProjectDoneEvidenceUpdate,
    VerificationDecisionRequest,
    CapacityOut,
    CapacityUpdate,
    PlanningApprovalOut,
    PlanningApprovalRequest, PlanningReopenRequest,
    PlanningAssignmentCreate,
    PlanningAssignmentMove,
    PlanningDayStatus,
    PlanningAssignmentOut,
    PlanningCandidateOut,
    PlanningCandidatePromoteRequest,
    PlanningQuickAddRequest,
    PlanningRunCreate,
    WorkStatusUpdate,
    WorkProposalRequest,
    CandidateDoneRequest,
    PlanningRunOut,
    PlanningRunSyncStatusOut,
    PlanningSyncJobOut,
    PlanningProposalAcceptRequest,
    WorkforceMemberCreate,
    PlanningAddWorkOut,
    PlanningAddWorkRequest,
    PlanningProjectOrderOut,
    PlanningProjectOrderUpdate,
    PlanningAssignWaitingRequest,
    PlanningWorkItemOut,
    WorkforceMemberOut,
    WorkforceMemberUpdate,
)


router = APIRouter(prefix="/planning", tags=["planning"])


def _not_found(what: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _own_run(context: AuthContext, run_id: str) -> None:
    """A Project Owner reaches a plan only when every project in it is theirs; otherwise it does not exist."""
    if context.project_ids is None:
        return
    scope = planning_scope.run_projects(run_id)
    if not scope or not set(scope) <= context.project_ids:
        raise _not_found("Planning run")


def _own_scope(context: AuthContext, project_ids: list[str]) -> None:
    if context.project_ids is None:
        return
    resolved = planning_scope.project_ids(project_ids)
    if not resolved or not all(project_id is not None and context.allows(project_id) for project_id in resolved):
        raise _not_found("Project")


def _own_project(context: AuthContext, project_id: str | None) -> str | None:
    _own_scope(context, [project_id] if project_id else [])
    return project_id


def _own_member(context: AuthContext, member_id: str) -> None:
    if context.project_ids is not None and member_id not in planning_scope.team_member_ids(context.project_ids):
        raise _not_found("Workforce member")


def _raise_planning_error(exc: PlanningValidationError) -> None:
    conflict_codes = {
        "CAPACITY_VERSION_CONFLICT",
        "PLANNING_VERSION_CONFLICT",
        "PLANNING_RUN_IMMUTABLE",
        "PLANNING_APPROVAL_CONFLICT",
        "IDEMPOTENCY_KEY_REUSED",
        "QUICK_ADD_CONFLICT",
        "VERIFICATION_DECIDED",
    }
    status_code = status.HTTP_409_CONFLICT if exc.code in conflict_codes else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise api_exception(status_code, exc.code, str(exc)) from exc


@router.post(
    "/members",
    response_model=WorkforceMemberOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-02", "FR-PLAN-14"]},
)
async def create_member(
    payload: WorkforceMemberCreate,
    context: AuthContext = Depends(require_cto),
) -> WorkforceMemberOut:
    try:
        return WorkforceMemberOut.model_validate(planning_service.create_member(payload, context.user_id))
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.get(
    "/members",
    response_model=list[WorkforceMemberOut],
    openapi_extra={"x-requirement-ids": ["FR-PLAN-02", "FR-PLAN-14", "FR-ID-08"]},
)
async def list_members(include_inactive: bool = False, context: AuthContext = Depends(require_member)) -> list[WorkforceMemberOut]:
    if context.project_ids is None:
        rows = planning_service.list_members(include_inactive)
    else:
        team = planning_scope.team_member_ids(context.project_ids)
        rows = [
            {**row, "project_mappings": [mapping for mapping in row["project_mappings"] if context.allows(mapping["project_id"])]}
            for row in planning_service.list_members(False) if row["id"] in team
        ]
    return [WorkforceMemberOut.model_validate(row) for row in rows]


@router.post(
    "/members/me",
    response_model=WorkforceMemberOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-37"]},
)
async def add_myself(context: AuthContext = Depends(require_cto)) -> WorkforceMemberOut:
    """The CTO's own staff record, made or linked in one click; the same record comes back on a second click."""
    try:
        return WorkforceMemberOut.model_validate(planning_service.add_myself(context.user_id, context.user_id))
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.put(
    "/members/{member_id}",
    response_model=WorkforceMemberOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-02", "FR-PLAN-14", "FR-PRJ-08"]},
)
async def update_member(
    member_id: str,
    payload: WorkforceMemberUpdate,
    context: AuthContext = Depends(require_cto),
) -> WorkforceMemberOut:
    try:
        return WorkforceMemberOut.model_validate(planning_service.update_member(member_id, payload, context.user_id))
    except KeyError as exc:
        raise api_exception(status.HTTP_404_NOT_FOUND, "MEMBER_NOT_FOUND", "Workforce member was not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.get(
    "/capacities/{work_date}",
    response_model=list[CapacityOut],
    openapi_extra={"x-requirement-ids": ["FR-PLAN-02", "FR-PLAN-03", "FR-PLAN-15", "FR-ID-08"]},
)
async def list_capacities(
    work_date: date,
    project_id: str | None = None,
    context: AuthContext = Depends(require_member),
) -> list[CapacityOut]:
    project_id = _own_project(context, project_id)
    try:
        return [CapacityOut.model_validate(item) for item in planning_service.list_capacities(work_date, project_id)]
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.put(
    "/capacities/{work_date}/{member_id}",
    response_model=CapacityOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-02", "FR-PLAN-03", "FR-PLAN-15", "FR-ID-08"]},
)
async def update_capacity(
    work_date: date,
    member_id: str,
    payload: CapacityUpdate,
    context: AuthContext = Depends(require_member),
) -> CapacityOut:
    _own_member(context, member_id)
    try:
        return CapacityOut.model_validate(
            planning_service.update_capacity(member_id, work_date, payload, context.user_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workforce member not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs",
    response_model=PlanningRunOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-01", "FR-PLAN-06", "FR-ID-08"]},
)
async def create_run(
    payload: PlanningRunCreate,
    context: AuthContext = Depends(require_member),
) -> PlanningRunOut:
    _own_scope(context, payload.project_ids)
    try:
        return PlanningRunOut.model_validate(planning_service.create_run(payload, context.user_id))
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.get(
    "/week/{week_start}",
    response_model=WeekSummaryOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-29", "FR-PLAN-30"]},
)
async def get_week_summary(week_start: date, context: AuthContext = Depends(require_member)) -> WeekSummaryOut:
    """The week in counts: planned, reported, really done, and where the process waited. Any day of the week picks it."""
    return WeekSummaryOut.model_validate(week_summary(week_start, context.project_ids, cto_user_id=context.user_id if context.role == "CTO" else None))


@router.post(
    "/board-snapshots/{snapshot_date}",
    openapi_extra={"x-requirement-ids": ["FR-PLAN-30"]},
)
async def write_board_snapshot(snapshot_date: date, _: AuthContext = Depends(require_cto)) -> dict[str, object]:
    """Keep the board of that day now instead of waiting for 23:55 (the CTO, after fixing data)."""
    return snapshot_board(snapshot_date)


@router.get(
    "/people/{plan_date}",
    response_model=PeopleDayOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-28"]},
)
async def get_people_day(plan_date: date, context: AuthContext = Depends(require_member)) -> PeopleDayOut:
    """Everyone's planned hours across every project's plan for the day, against the hours they have; a Project
    Owner gets the people on their teams (FR-PLAN-28)."""
    return PeopleDayOut.model_validate(people_day(plan_date, context.project_ids))


def _live_copy(session, assignment):
    """A page opened before the plan was reopened still holds the ids of the superseded run; reopening copies each
    assignment under a new id, so follow the chain forward and land the status on the copy that is live."""
    from sqlalchemy import select

    from app.models import PlanningAssignment, PlanningRun

    current = assignment
    for _ in range(20):
        run = session.get(PlanningRun, current.planning_run_id)
        if run is None or run.status != "SUPERSEDED":
            return current
        successor = session.scalar(select(PlanningRun).where(PlanningRun.supersedes_run_id == run.id))
        if successor is None:
            return current
        match = session.scalar(select(PlanningAssignment).where(
            PlanningAssignment.planning_run_id == successor.id, PlanningAssignment.project_id == current.project_id,
            PlanningAssignment.member_id == current.member_id, PlanningAssignment.slot == current.slot,
            PlanningAssignment.work_type == current.work_type, PlanningAssignment.source_reference == current.source_reference,
        ))
        if match is None:
            raise api_exception(status.HTTP_404_NOT_FOUND, "PLANNING_ASSIGNMENT_NOT_FOUND", "Planning assignment was not found")
        current = match
    return current


@router.patch("/runs/{run_id}/assignments/{assignment_id}/work-status", openapi_extra={"x-requirement-ids": ["FR-PLAN-34", "FR-MCP-06", "FR-ID-08"]})
async def set_assignment_work_status(run_id: str, assignment_id: str, payload: WorkStatusUpdate, context: AuthContext = Depends(require_account)) -> dict:
    """Where a placed piece of work stands, said on the web: the CTO for anyone, a Project Owner within their projects,
    a Developer for their own work. A closed plan still takes a status; "done" with an Issue goes to acceptance."""
    from app.db import get_session
    from app.models import PlanningAssignment, User

    with get_session() as session:
        assignment = session.get(PlanningAssignment, assignment_id)
        if assignment is None or str(assignment.planning_run_id) != run_id:
            raise api_exception(status.HTTP_404_NOT_FOUND, "PLANNING_ASSIGNMENT_NOT_FOUND", "Planning assignment was not found")
        assignment = _live_copy(session, assignment)
        if context.role == "PROJECT_OWNER" and (context.project_ids is None or str(assignment.project_id) not in context.project_ids):
            raise api_exception(status.HTTP_404_NOT_FOUND, "PLANNING_ASSIGNMENT_NOT_FOUND", "Planning assignment was not found")
        if context.role == "DEVELOPER":
            user = session.get(User, context.user_id)
            if user is None or not user.member_id or str(user.member_id) != str(assignment.member_id):
                raise api_exception(status.HTTP_404_NOT_FOUND, "PLANNING_ASSIGNMENT_NOT_FOUND", "Planning assignment was not found")
        try:
            result = set_work_status(session, assignment, payload.status, payload.note, context.user_id, evidence=[link.model_dump() for link in payload.evidence])
        except WorkStatusError as error:
            raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error
        session.commit()
        return result


@router.post("/proposals", status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-PLAN-35", "FR-ID-08"]})
async def propose_work(payload: WorkProposalRequest, context: AuthContext = Depends(require_account)) -> dict:
    """A member proposes work for a day in one of their projects; it waits for the Project Owner (FR-PLAN-35)."""
    from app.db import get_session
    from app.models import User, WorkforceMember

    with get_session() as session:
        user = session.get(User, context.user_id)
        member = session.get(WorkforceMember, user.member_id) if user is not None and user.member_id else None
        if member is None:
            raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "MEMBER_UNMAPPED", "Tài khoản này chưa gắn với nhân sự nào; nhờ CTO gắn ở Cài đặt > Người dùng")
        member_id = str(member.id)
    project_id = _proposal_project(context, member_id, payload.project)
    try:
        return add_work_service.propose_work(
            project_id, member_id, payload.plan_date, actor_id=context.user_id, text=payload.text, issue=payload.issue,
            intake_ref=payload.intake, hours=payload.hours, slot=payload.slot,
        )
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


def _proposal_project(context: AuthContext, member_id: str, ref: str) -> str:
    """The project a proposal goes to: one the caller may use, and for a Developer one they are on."""
    from app.db import get_session
    from app.models import WorkforceProjectMembership

    project_id = _project_for(context, ref)
    if context.role == "DEVELOPER":
        with get_session() as session:
            on_team = session.scalar(select(WorkforceProjectMembership.id).where(
                WorkforceProjectMembership.project_id == project_id, WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.active.is_(True),
            ))
        if on_team is None:
            raise _not_found("Project")
    return project_id


@router.get("/my-day/{plan_date}", openapi_extra={"x-requirement-ids": ["FR-PLAN-34", "FR-MCP-06"]})
async def get_my_day(plan_date: date, context: AuthContext = Depends(require_account)) -> dict:
    """The caller's own work for a day, as the agent's get_my_day gives it: the Developer's page on the web."""
    from app.modules.mcp import tools as mcp_tools

    try:
        return mcp_tools.get_my_day(context, {"date": plan_date.isoformat()})
    except mcp_tools.ToolError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error


@router.get("/day-plans/{plan_date}", openapi_extra={"x-requirement-ids": ["FR-PLAN-33", "FR-ID-08"]})
async def get_day_plans(plan_date: date, context: AuthContext = Depends(require_member)) -> dict:
    """Read-only: every software project's plan for the day as it stands, with who has work, who is free and what
    waits to be placed. The "all projects" view of Daily Planning; never opens a plan."""
    return day_plans(plan_date, context.project_ids, context.user_id)


@router.put(
    "/project-order",
    response_model=PlanningProjectOrderOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-33", "FR-ID-08"]},
)
async def put_project_order(
    payload: PlanningProjectOrderUpdate, context: AuthContext = Depends(require_member),
) -> PlanningProjectOrderOut:
    try:
        saved = save_project_order(context.user_id, context.project_ids, payload.mode, payload.project_ids)
    except ProjectOrderError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, str(error), "Thứ tự dự án không hợp lệ hoặc có dự án ngoài phạm vi của bạn") from error
    return PlanningProjectOrderOut.model_validate(saved)


@router.get(
    "/overview/{plan_date}",
    response_model=PlanningOverviewOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-23", "FR-ID-08", "FR-APR-14", "FR-PLAN-27", "FR-UI-15"]},
)
async def get_day_overview(plan_date: date, context: AuthContext = Depends(require_member)) -> PlanningOverviewOut:
    """Read-only: one row per project with whether the day can be reviewed on complete data. Never opens a plan."""
    return PlanningOverviewOut.model_validate(day_overview(plan_date, context.project_ids, cto_user_id=context.user_id if context.role == "CTO" else None))


@router.get(
    "/days/{plan_date}",
    response_model=PlanningDayStatus,
    openapi_extra={"x-requirement-ids": ["FR-UI-12", "FR-ID-08"]},
)
async def get_day_status(
    plan_date: date, project_id: str | None = Query(default=None), context: AuthContext = Depends(require_member),
) -> PlanningDayStatus:
    """Read-only: whether the day has a plan and how far it is. Never opens one."""
    _own_project(context, project_id)
    try:
        return PlanningDayStatus.model_validate(planning_service.day_status(plan_date, project_id))
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.get(
    "/runs/{run_id}",
    response_model=PlanningRunOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-01", "FR-PLAN-04", "FR-PLAN-06", "FR-ID-08"]},
)
async def get_run(run_id: str, context: AuthContext = Depends(require_member)) -> PlanningRunOut:
    _own_run(context, run_id)
    try:
        return PlanningRunOut.model_validate(planning_service.get_run(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc


@router.post(
    "/runs/{run_id}/assignments",
    response_model=PlanningAssignmentOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-04", "FR-PLAN-05", "FR-PLAN-09", "FR-PLAN-14", "FR-ID-08"]},
)
async def add_assignment(
    run_id: str,
    payload: PlanningAssignmentCreate,
    context: AuthContext = Depends(require_member),
) -> PlanningAssignmentOut:
    _own_run(context, run_id)
    try:
        return PlanningAssignmentOut.model_validate(
            planning_service.add_assignment(run_id, payload, context.user_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/assignments/{assignment_id}/unassign",
    response_model=PlanningRunOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-04", "FR-PLAN-16", "FR-ID-08"]},
)
async def unassign_assignment(
    run_id: str,
    assignment_id: str,
    payload: PlanningAssignmentUnassign,
    context: AuthContext = Depends(require_member),
) -> PlanningRunOut:
    """Something more urgent came up: the placed work goes back to the waiting list while the day is still open."""
    _own_run(context, run_id)
    try:
        return PlanningRunOut.model_validate(
            planning_service.unassign(run_id, assignment_id, payload.expected_run_version, context.user_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/assignments/{assignment_id}/move",
    response_model=PlanningRunOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-04", "FR-PLAN-14", "FR-ID-08"]},
)
async def move_assignment(
    run_id: str,
    assignment_id: str,
    payload: PlanningAssignmentMove,
    context: AuthContext = Depends(require_member),
) -> PlanningRunOut:
    _own_run(context, run_id)
    try:
        return PlanningRunOut.model_validate(
            planning_service.move_assignment(
                run_id,
                assignment_id,
                payload.slot,
                payload.expected_run_version,
                context.user_id,
                member_id=payload.member_id,
                override_reason=payload.override_reason,
                allow_override=context.role in ("CTO", "PROJECT_OWNER"),
            )
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.get(
    "/runs/{run_id}/work-items",
    response_model=list[PlanningWorkItemOut],
    openapi_extra={"x-requirement-ids": ["FR-PLAN-08", "FR-PLAN-16", "FR-ID-08"]},
)
async def search_work_items(
    run_id: str,
    search: str | None = Query(default=None, max_length=255),
    candidate_id: str | None = Query(default=None, max_length=36),
    context: AuthContext = Depends(require_member),
) -> list[PlanningWorkItemOut]:
    _own_run(context, run_id)
    try:
        return [PlanningWorkItemOut.model_validate(row) for row in add_work_service.search(run_id, search, candidate_id=candidate_id)]
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc


@router.post(
    "/runs/{run_id}/work",
    response_model=PlanningAddWorkOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-08", "FR-PLAN-09", "FR-PLAN-16", "FR-ID-08"]},
)
async def add_work(
    run_id: str,
    payload: PlanningAddWorkRequest,
    context: AuthContext = Depends(require_member),
) -> PlanningAddWorkOut:
    _own_run(context, run_id)
    try:
        return PlanningAddWorkOut.model_validate(add_work_service.add(run_id, payload, context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run or project not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/candidates/{candidate_id}/assign",
    response_model=PlanningAddWorkOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-08", "FR-PLAN-09", "FR-PLAN-16", "FR-ID-08"]},
)
async def assign_waiting_work(
    run_id: str,
    candidate_id: str,
    payload: PlanningAssignWaitingRequest,
    context: AuthContext = Depends(require_member),
) -> PlanningAddWorkOut:
    _own_run(context, run_id)
    try:
        return PlanningAddWorkOut.model_validate(add_work_service.assign_waiting(run_id, candidate_id, payload, context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/verifications/{verification_id}/{decision}",
    response_model=PlanningRunOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-22", "FR-ID-08"]},
)
async def decide_issue_verification(
    run_id: str,
    verification_id: str,
    decision: Literal["accept", "reject"],
    payload: VerificationDecisionRequest,
    context: AuthContext = Depends(require_cto),
) -> PlanningRunOut:
    """The CTO looked at a closed Issue: done, or not done (with a reason)."""
    try:
        return PlanningRunOut.model_validate(planning_service.decide_verification(
            run_id, verification_id, "ACCEPTED" if decision == "accept" else "REJECTED", payload.expected_version, payload.reason, context.user_id,
        ))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Verification not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


def _project_for(context: AuthContext, project_ref: str) -> str:
    """The project's id, when the caller may reach it (a Project Owner only their own)."""
    resolved = planning_scope.project_ids([project_ref])
    project_id = resolved[0] if resolved else None
    if project_id is None or not context.allows(project_id):
        raise _not_found("Project")
    return str(project_id)


@router.post(
    "/projects/{project_ref}/tracker-users/lookup",
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-32", "FR-PLAN-14"]},
)
async def start_tracker_users_lookup(project_ref: str, context: AuthContext = Depends(require_member)) -> dict[str, object]:
    """Ask the integration worker for the tracker's users (the API keeps no tracker token); poll the GET with the probe id."""
    project_id = _project_for(context, project_ref)
    started = tracker_mapping.start_lookup(project_id, context.user_id)
    if started is None:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "TRACKER_NOT_CONFIGURED", "Dự án chưa bật GitLab hay GitHub")
    return {"probe_id": started["id"], "status": started["status"], "error_code": started.get("error_code"), "system": started["system"]}


@router.get(
    "/projects/{project_ref}/tracker-users",
    response_model=TrackerUsersOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-32", "FR-PLAN-14"]},
)
async def list_tracker_users(
    project_ref: str, probe: str = Query(..., max_length=64), issue: str | None = Query(default=None, max_length=255), context: AuthContext = Depends(require_member),
) -> TrackerUsersOut:
    """The tracker's users beside the team once the probe is done: who maps to whom, who could, and whom the Issue is assigned to there."""
    project_id = _project_for(context, project_ref)
    found = tracker_mapping.lookup(project_id, probe)
    shown = tracker_mapping.view(project_id, list(found["users"]), issue)
    return TrackerUsersOut.model_validate({**shown, "status": found["status"], "error_code": found.get("error_code")})


@router.post(
    "/projects/{project_ref}/tracker-users/auto-map",
    openapi_extra={"x-requirement-ids": ["FR-PLAN-32", "FR-PLAN-14"]},
)
async def auto_map_tracker_users(project_ref: str, probe: str = Query(..., max_length=64), context: AuthContext = Depends(require_member)) -> dict[str, object]:
    """Fill every missing mapping that matches exactly one tracker user by email or name, from a finished probe."""
    project_id = _project_for(context, project_ref)
    found = tracker_mapping.lookup(project_id, probe)
    if found["status"] != "DONE":
        raise api_exception(status.HTTP_409_CONFLICT, "PROBE_NOT_DONE", "Danh sách người dùng của tracker chưa về")
    return tracker_mapping.auto_map(project_id, list(found["users"]), actor_id=context.user_id)


@router.put(
    "/projects/{project_ref}/members/{member_id}/tracker-user",
    openapi_extra={"x-requirement-ids": ["FR-PLAN-32", "FR-PLAN-14"]},
)
async def set_tracker_user(project_ref: str, member_id: str, payload: TrackerUserMappingRequest, context: AuthContext = Depends(require_member)) -> dict[str, object]:
    """A Project Owner or the CTO names the tracker user of one member of this project."""
    project_id = _project_for(context, project_ref)
    if not tracker_mapping.set_mapping(project_id, member_id, payload.gitlab_user_external_id, context.user_id):
        raise _not_found("Membership")
    return {"project_id": project_id, "member_id": member_id, "gitlab_user_external_id": (payload.gitlab_user_external_id or "").strip() or None}


@router.put(
    "/projects/{project_ref}/agent-ready",
    openapi_extra={"x-requirement-ids": ["FR-MCP-04"]},
)
async def set_project_agent_ready(project_ref: str, payload: ProjectAgentReadyUpdate, context: AuthContext = Depends(require_cto)) -> dict[str, object]:
    """The repo of this project is ready for an agent: CLAUDE.md, a test command, seed data."""
    try:
        return planning_service.set_agent_ready(project_ref, payload.agent_ready, context.user_id)
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.put(
    "/projects/{project_ref}/done-evidence",
    openapi_extra={"x-requirement-ids": ["FR-PLAN-22"]},
)
async def set_project_done_evidence(project_ref: str, payload: ProjectDoneEvidenceUpdate, context: AuthContext = Depends(require_cto)) -> dict[str, object]:
    """What this project accepts as the trace of code behind a closed Issue: a commit that mentions it, or a merged MR."""
    try:
        return planning_service.set_done_evidence(project_ref, payload.done_evidence, context.user_id)
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/candidates/{candidate_id}/done",
    openapi_extra={"x-requirement-ids": ["FR-PLAN-34", "FR-PLAN-31", "FR-ID-08"]},
)
async def waiting_work_done_elsewhere(run_id: str, candidate_id: str, payload: CandidateDoneRequest, context: AuthContext = Depends(require_member)) -> dict:
    """A waiting entry that was already done outside the plan: noted, taken off the list, its Issue offered for acceptance."""
    _own_run(context, run_id)
    try:
        return add_work_service.mark_done_elsewhere(run_id, candidate_id, payload.note, context.user_id)
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/candidates/{candidate_id}/{action}",
    response_model=PlanningCandidateOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-16", "FR-ID-08"]},
)
async def dismiss_or_restore_waiting_work(
    run_id: str,
    candidate_id: str,
    action: Literal["dismiss", "restore"],
    context: AuthContext = Depends(require_member),
) -> PlanningCandidateOut:
    _own_run(context, run_id)
    try:
        return PlanningCandidateOut.model_validate(add_work_service.set_dismissed(run_id, candidate_id, action == "dismiss", context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/quick-add",
    response_model=PlanningCandidateOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-04", "FR-PLAN-05", "FR-PLAN-14"]},
)
async def quick_add(
    run_id: str,
    payload: PlanningQuickAddRequest,
    context: AuthContext = Depends(require_cto),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PlanningCandidateOut:
    try:
        return PlanningCandidateOut.model_validate(
            planning_service.quick_add(run_id, payload, context.user_id, idempotency_key)
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/quick-add/{candidate_id}/promote",
    response_model=PlanningCandidateOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-04", "FR-PLAN-05", "FR-PLAN-09", "FR-PLAN-14"]},
)
async def promote_candidate(
    run_id: str,
    candidate_id: str,
    payload: PlanningCandidatePromoteRequest,
    context: AuthContext = Depends(require_cto),
) -> PlanningCandidateOut:
    try:
        return PlanningCandidateOut.model_validate(
            planning_service.promote_candidate(run_id, candidate_id, payload, context.user_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/accept-proposals",
    response_model=PlanningRunOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-04", "FR-PLAN-06", "FR-PLAN-10"]},
)
async def accept_proposals(
    run_id: str,
    payload: PlanningProposalAcceptRequest,
    context: AuthContext = Depends(require_member),
) -> PlanningRunOut:
    _own_run(context, run_id)
    try:
        return PlanningRunOut.model_validate(
            planning_service.accept_proposals(run_id, payload.expected_version, context.user_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/reopen",
    response_model=PlanningRunOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-18", "FR-PLAN-25"]},
)
async def reopen_run(
    run_id: str,
    payload: PlanningReopenRequest,
    context: AuthContext = Depends(require_member),
) -> PlanningRunOut:
    """A closed plan reopened as a new revision; the closed one is kept and marked superseded (FR-PLAN-18)."""
    _own_run(context, run_id)
    try:
        return PlanningRunOut.model_validate(planning_service.reopen(run_id, payload.expected_version, context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.post(
    "/runs/{run_id}/approve",
    response_model=PlanningApprovalOut,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-10", "FR-PLAN-11", "FR-PLAN-12", "FR-PLAN-13"]},
)
async def approve_run(
    run_id: str,
    payload: PlanningApprovalRequest,
    context: AuthContext = Depends(require_member),
) -> PlanningApprovalOut:
    """The CTO, or the Project Owner of the project the plan is for, closes the plan (FR-PLAN-25)."""
    _own_run(context, run_id)
    try:
        return PlanningApprovalOut.model_validate(planning_service.approve(run_id, payload, context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)


@router.get(
    "/runs/{run_id}/sync-jobs",
    response_model=PlanningRunSyncStatusOut,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-12", "FR-PLAN-13", "FR-UI-05"]},
)
async def list_sync_jobs(
    run_id: str,
    context: AuthContext = Depends(require_member),
) -> PlanningRunSyncStatusOut:
    _own_run(context, run_id)
    try:
        return PlanningRunSyncStatusOut.model_validate(planning_service.list_sync_jobs(run_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning run not found") from exc


@router.post(
    "/runs/{run_id}/sync-jobs/{job_id}/retry",
    response_model=PlanningSyncJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-PLAN-12", "FR-PLAN-13", "FR-UI-05"]},
)
async def retry_sync_job(
    run_id: str,
    job_id: str,
    context: AuthContext = Depends(require_cto),
) -> PlanningSyncJobOut:
    try:
        return PlanningSyncJobOut.model_validate(
            planning_service.retry_sync_job(run_id, job_id, context.user_id)
        )
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Planning sync job not found") from exc
    except PlanningValidationError as exc:
        _raise_planning_error(exc)
