from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.errors import api_exception
from app.modules.projects.context import ContextError, empty_pack, project_context_service

from app.api.security import AuthContext, ensure_project, require_cto, require_member
from app.modules.projects.management import ProjectError, project_management_service, project_team_service
from app.modules.private_space.service import private_space_service
from app.modules.projects.service import project_catalog_service
from app.schemas import ProjectBriefOut
from app.schemas import (
    DeliverySwitchOut,
    IntegrationProbeCreate,
    IntegrationProbeOut,
    ProjectBrief,
    ProjectReportCodes,
    ProjectContextOut,
    ProjectContextPaste,
    ProjectContextSuggestionOut,
    ProjectCreate,
    ProjectMemberAdd,
    ProjectMemberAddedOut,
    ProjectMemberCandidateOut,
    ProjectMemberRemovedOut,
    ProjectOut,
    ProjectTeamOut,
    ProjectTeamUpdate,
    ProjectUpdate,
)

router = APIRouter(prefix="/projects", tags=["projects"])

CONFLICTS = {"PROJECT_CODE_TAKEN", "INTAKE_KEY_TAKEN", "GITLAB_PROJECT_ALREADY_LINKED", "GITHUB_PROJECT_ALREADY_LINKED"}


def _raise(error: ProjectError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT if error.code in CONFLICTS else status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": error.code, "message": error.message},
    ) from error


def _out(project_ref: str) -> ProjectOut:
    project = project_catalog_service.get_project(project_ref)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return ProjectOut.model_validate(asdict(project))


def _team_project(project_ref: str, context: AuthContext):
    project = project_catalog_service.get_project(project_ref)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    ensure_project(context, project.id, "Project")
    return project


@router.get("", response_model=list[ProjectOut], openapi_extra={"x-requirement-ids": ["FR-PRJ-01", "FR-PRJ-04"]})
async def list_projects(context: AuthContext = Depends(require_member)) -> list[ProjectOut]:
    # The private space is not a company project: it is reached through /private-space only (ADR-0031).
    private_id = private_space_service.project_id()
    return [
        ProjectOut.model_validate(asdict(project)) for project in project_catalog_service.list_projects()
        if context.allows(project.id) and str(project.id) != private_id
    ]


@router.get("/{project_ref}/context", openapi_extra={"x-requirement-ids": ["FR-CTX-03", "FR-PRJ-04"]})
async def get_project_context(project_ref: str, context: AuthContext = Depends(require_member)) -> dict:
    """The context pack as last read from the project's repository, scored; none yet gives an empty MISSING pack."""
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    snapshot = project_context_service.snapshot(project.id)
    if snapshot is None:
        return ProjectContextOut.model_validate({**empty_pack(project.id), "pending_suggestions": project_context_service.pending_count(project.id)}).model_dump()
    return ProjectContextOut.model_validate(snapshot).model_dump()


@router.get("/{project_ref}/context/suggestions", openapi_extra={"x-requirement-ids": ["FR-CTX-04", "FR-PRJ-04"]})
async def list_project_context_suggestions(project_ref: str, context: AuthContext = Depends(require_member)) -> list[dict]:
    """What agents and people found missing in the pack while working, newest first; the CTO decides on each."""
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    return [ProjectContextSuggestionOut.model_validate(row).model_dump() for row in project_context_service.suggestions(project.id)]


@router.post("/{project_ref}/context/suggestions/{suggestion_id}/{decision}", openapi_extra={"x-requirement-ids": ["FR-CTX-04"]})
async def decide_project_context_suggestion(project_ref: str, suggestion_id: str, decision: str, context: AuthContext = Depends(require_cto)) -> dict:
    """`applied` once the CTO changed the file in the repository, `dismissed` otherwise; Intake itself never edits the pack."""
    project = project_catalog_service.get_project(project_ref)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    if decision not in ("applied", "dismissed"):
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "DECISION_UNKNOWN", "Quyết định phải là applied hoặc dismissed")
    try:
        row = project_context_service.decide(project.id, suggestion_id, status=decision.upper(), actor_id=context.user_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found") from error
    except ContextError as error:
        raise api_exception(status.HTTP_409_CONFLICT, error.code, "Gợi ý này đã được quyết rồi") from error
    return ProjectContextSuggestionOut.model_validate(row).model_dump()


@router.post("/{project_ref}/context/read", status_code=status.HTTP_202_ACCEPTED, openapi_extra={"x-requirement-ids": ["FR-CTX-03"]})
async def read_project_context(project_ref: str, context: AuthContext = Depends(require_member)) -> dict:
    """Ask the repo-reader to read the pack again now."""
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    if project_context_service.main_repo(project.id) is None:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "NO_MAIN_REPO", "Dự án chưa có repo GitLab hoặc GitHub đang bật; dán hồ sơ trực tiếp")
    return {"project_id": str(project.id), "queued": project_context_service.queue_read(project.id)}


@router.put("/{project_ref}/context", openapi_extra={"x-requirement-ids": ["FR-CTX-03"]})
async def paste_project_context(project_ref: str, payload: ProjectContextPaste, context: AuthContext = Depends(require_member)) -> dict:
    """A project without a repository Intake can read: the pack pasted in, same shape, same score."""
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    stored = project_context_service.store(project.id, source="PASTED", content=payload.content, sha=None, actor_id=context.user_id)
    return ProjectContextOut.model_validate(stored).model_dump()


@router.post("/{project_ref}/context/approve", openapi_extra={"x-requirement-ids": ["FR-CTX-03"]})
async def approve_project_context(project_ref: str, context: AuthContext = Depends(require_cto)) -> dict:
    """The CTO's word on the pack as it stands; a later change in the repository asks for it again."""
    project = project_catalog_service.get_project(project_ref)
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        return ProjectContextOut.model_validate(project_context_service.approve(project.id, context.user_id)).model_dump()
    except KeyError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "CONTEXT_EMPTY", "Chưa có hồ sơ để duyệt") from error


@router.get("/{project_ref}/report-codes", response_model=ProjectReportCodes, openapi_extra={"x-requirement-ids": ["FR-EML-12", "FR-PRJ-04"]})
async def get_project_report_codes(project_ref: str, context: AuthContext = Depends(require_member)) -> ProjectReportCodes:
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    return ProjectReportCodes(codes=project_management_service.report_codes(project.id))


@router.put("/{project_ref}/report-codes", response_model=ProjectReportCodes, openapi_extra={"x-requirement-ids": ["FR-EML-12", "FR-PRJ-04"]})
async def save_project_report_codes(project_ref: str, payload: ProjectReportCodes, context: AuthContext = Depends(require_member)) -> ProjectReportCodes:
    """The CTO, or the Project Owner of this project, names the other codes reports use for it."""
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    try:
        return ProjectReportCodes(codes=project_management_service.save_report_codes(project.id, payload.codes, context.user_id))
    except ValueError as error:
        kind, code, holder = str(error).split(":", 2)
        if kind == "REPORT_CODE_INVALID":
            raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "REPORT_CODE_INVALID", f"Mã {code} chỉ gồm chữ, số, gạch nối, gạch dưới, chấm (tối đa 32 ký tự)") from error
        raise api_exception(status.HTTP_409_CONFLICT, "REPORT_CODE_TAKEN", f"Mã {code} đã thuộc dự án {holder}") from error


def _brief_out(project) -> ProjectBriefOut:
    """The stored brief, and which source AI reads for this project right now (FR-CTX-05)."""
    pack = project_context_service.prompt_context(str(project.id))
    return ProjectBriefOut(
        brief=project_management_service.brief(project.id), ai_source="PACK" if pack else "BRIEF",
        pack_approved_at=pack["approved_at"] if pack else None, pack_sections=list(pack["sections"]) if pack else [],
    )


@router.get("/{project_ref}/brief", response_model=ProjectBriefOut, openapi_extra={"x-requirement-ids": ["FR-AI-12", "FR-CTX-05", "FR-PRJ-04"]})
async def get_project_brief(project_ref: str, context: AuthContext = Depends(require_member)) -> ProjectBriefOut:
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    return _brief_out(project)


@router.put("/{project_ref}/brief", response_model=ProjectBriefOut, openapi_extra={"x-requirement-ids": ["FR-AI-12", "FR-CTX-05", "FR-PRJ-04", "NFR-SEC-03"]})
async def save_project_brief(project_ref: str, payload: ProjectBrief, context: AuthContext = Depends(require_member)) -> ProjectBriefOut:
    """The CTO, or the Project Owner of this project, describes the product for AI. Sent to the AI provider with each request."""
    project = project_catalog_service.get_project(project_ref)
    ensure_project(context, project.id if project else None, "Project")
    project_management_service.save_brief(project.id, payload.brief, context.user_id)
    return _brief_out(project)


@router.post(
    "", response_model=ProjectOut, status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-01", "FR-PRJ-03", "FR-PRJ-06", "FR-PRJ-07"]},
)
async def create_project(payload: ProjectCreate, context: AuthContext = Depends(require_cto)) -> ProjectOut:
    try:
        return _out(project_management_service.create(payload, context.user_id))
    except ProjectError as error:
        _raise(error)


@router.post(
    "/integration-probes", response_model=IntegrationProbeOut, status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-03", "FR-PRJ-07", "NFR-SEC-03"]},
)
async def request_integration_probe(payload: IntegrationProbeCreate, context: AuthContext = Depends(require_cto)) -> IntegrationProbeOut:
    try:
        return IntegrationProbeOut.model_validate(project_management_service.request_probe(
            payload.system, payload.action, payload.reference, context.user_id, token_ref=payload.token_ref,
        ))
    except ProjectError as error:
        _raise(error)


@router.get(
    "/integration-probes/{probe_id}", response_model=IntegrationProbeOut,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-07"]},
)
async def get_integration_probe(probe_id: str, _: AuthContext = Depends(require_cto)) -> IntegrationProbeOut:
    try:
        return IntegrationProbeOut.model_validate(project_management_service.get_probe(probe_id))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Probe not found") from error


@router.get(
    "/{project_ref}/team", response_model=ProjectTeamOut,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-10", "FR-PRJ-11", "FR-ID-07"]},
)
async def get_project_team(project_ref: str, context: AuthContext = Depends(require_member)) -> ProjectTeamOut:
    _team_project(project_ref, context)
    try:
        return ProjectTeamOut.model_validate(project_team_service.get(project_ref))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from error


@router.put(
    "/{project_ref}/team", response_model=ProjectTeamOut,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-10", "FR-ID-06", "FR-ID-07", "NFR-SEC-03"]},
)
async def set_project_team(project_ref: str, payload: ProjectTeamUpdate, context: AuthContext = Depends(require_cto)) -> ProjectTeamOut:
    try:
        return ProjectTeamOut.model_validate(project_team_service.set(
            project_ref, payload.owner_member_id, payload.member_ids, context.user_id,
        ))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from error
    except ProjectError as error:
        _raise(error)


@router.get(
    "/{project_ref}/team/candidates", response_model=list[ProjectMemberCandidateOut],
    openapi_extra={"x-requirement-ids": ["FR-PRJ-11", "FR-ID-07", "NFR-SEC-03"]},
)
async def get_project_member_candidates(
    project_ref: str, context: AuthContext = Depends(require_member),
) -> list[ProjectMemberCandidateOut]:
    _team_project(project_ref, context)
    return [ProjectMemberCandidateOut.model_validate(row) for row in project_team_service.candidates(project_ref)]


@router.post(
    "/{project_ref}/team/members", response_model=ProjectMemberAddedOut,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-11", "FR-ID-07", "NFR-SEC-03"]},
)
async def add_project_member(
    project_ref: str, payload: ProjectMemberAdd, context: AuthContext = Depends(require_member),
) -> ProjectMemberAddedOut:
    _team_project(project_ref, context)
    try:
        return ProjectMemberAddedOut.model_validate(
            project_team_service.add_member(project_ref, payload.member_id, context.user_id)
        )
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from error
    except ProjectError as error:
        _raise(error)


@router.delete(
    "/{project_ref}/team/members/{member_id}", response_model=ProjectMemberRemovedOut,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-11", "FR-ID-06", "NFR-SEC-03"]},
)
async def remove_project_member(
    project_ref: str, member_id: str, context: AuthContext = Depends(require_member),
) -> ProjectMemberRemovedOut:
    # A Project Owner may take a person off their own project (ADR-0072); another project answers 404.
    _team_project(project_ref, context)
    try:
        return ProjectMemberRemovedOut.model_validate(
            project_team_service.remove_member(project_ref, member_id, context.user_id)
        )
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from error
    except ProjectError as error:
        _raise(error)


@router.get(
    "/{project_ref}/delivery-switch", response_model=DeliverySwitchOut,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-13"]},
)
async def preview_delivery_switch(project_ref: str, context: AuthContext = Depends(require_cto)) -> DeliverySwitchOut:
    # What a switch to GitHub leaves behind on GitLab, shown before the CTO confirms.
    try:
        return DeliverySwitchOut.model_validate(project_management_service.switch_preview(project_ref))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from error
    except ProjectError as error:
        _raise(error)


@router.patch(
    "/{project_ref}", response_model=ProjectOut,
    openapi_extra={"x-requirement-ids": ["FR-PRJ-01", "FR-PRJ-03", "FR-PRJ-06", "FR-PRJ-07", "FR-PRJ-13"]},
)
async def update_project(project_ref: str, payload: ProjectUpdate, context: AuthContext = Depends(require_cto)) -> ProjectOut:
    try:
        return _out(project_management_service.update(project_ref, payload, context.user_id))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found") from error
    except ProjectError as error:
        _raise(error)
