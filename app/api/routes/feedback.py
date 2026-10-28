"""Suggestions from members who are not Project Owners, and the owner's word on them (FR-FBK-01..03, ADR-0064)."""
from fastapi import APIRouter, Depends, HTTPException, Query, Response, UploadFile, status

from app.api.errors import api_exception
from app.api.security import AuthContext, ensure_project, require_account, require_member
from app.db import get_session
from app.modules.intake.feedback import MAX_FILES, FeedbackError, feedback_service, member_of_user, projects_of_member
from app.modules.projects.service import project_catalog_service
from app.schemas import FeedbackCreate, FeedbackDecision, FeedbackOut
from app.services.attachment_reader import AttachmentCheckError
from app.services.attachment_service import ALLOWED_MIME_TYPES, MAX_ATTACHMENT_SIZE

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _deciders_only(context: AuthContext) -> None:
    if context.role not in ("CTO", "PROJECT_OWNER"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the CTO or a Project Owner decides on a suggestion")


def _may_suggest(session, context: AuthContext, project) -> tuple[bool, str | None]:
    """Anyone suggests for a project their member is on, or one they manage (ADR-0064): the member's projects
    first, then the account's own scope."""
    member = member_of_user(session, context.user_id)
    member_id = str(member.id) if member else None
    on_it = member is not None and str(project.id) in {str(p.id) for p in projects_of_member(session, member.id)}
    return (on_it or context.allows(project.id)), member_id


def _visible(context: AuthContext, feedback_id: str) -> dict:
    """Mine anywhere; otherwise only in the projects I manage. A Developer sees only their own."""
    row = feedback_service.get(feedback_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    mine = row["user_id"] == context.user_id
    if context.role == "DEVELOPER" and not mine:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Suggestion not found")
    if not mine:
        ensure_project(context, row["project_id"], "Suggestion")
    return row


@router.post("", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-FBK-01"]})
async def create_feedback(payload: FeedbackCreate, context: AuthContext = Depends(require_account)) -> dict:
    """A Developer (or anyone with an account) says a project needs a request; it waits for the owner."""
    project = project_catalog_service.get_project(payload.project)
    if project is None or project.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    with get_session() as session:
        allowed, member_id = _may_suggest(session, context, project)
        if context.role == "DEVELOPER" and member_id is None:
            raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, "MEMBER_UNMAPPED", "Tài khoản chưa gắn nhân sự")
        if not allowed:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        row = feedback_service.create(project_id=project.id, text=payload.text, transport="WEB", user_id=context.user_id, member_id=member_id)
    except FeedbackError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error)) from error
    return FeedbackOut.model_validate(row).model_dump()


@router.post("/{feedback_id}/files", response_model=FeedbackOut, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-FBK-01", "FR-AI-09"]})
async def add_feedback_file(feedback_id: str, file: UploadFile, context: AuthContext = Depends(require_account)) -> dict:
    """A picture or a PDF on a waiting suggestion, checked like a request's attachment."""
    _visible(context, feedback_id)
    if file.content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Unsupported attachment type")
    content = await file.read(MAX_ATTACHMENT_SIZE + 1)
    if len(content) > MAX_ATTACHMENT_SIZE:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Attachment exceeds 5 MB")
    try:
        row = feedback_service.add_file(feedback_id, name=file.filename or "tệp", mime=file.content_type, content=content, actor_user_id=context.user_id)
    except AttachmentCheckError as error:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=error.code) from error
    except FeedbackError as error:
        raise api_exception(status.HTTP_409_CONFLICT if error.code == "ALREADY_DECIDED" else status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error)) from error
    return FeedbackOut.model_validate(row).model_dump()


@router.get("", response_model=list[FeedbackOut], openapi_extra={"x-requirement-ids": ["FR-FBK-02"]})
async def list_feedback(
    project_id: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status", pattern="^(PENDING|ACCEPTED|REJECTED)$"),
    mine: bool = Query(default=False, description="Only what I wrote"),
    limit: int = Query(default=100, ge=1, le=200),
    context: AuthContext = Depends(require_account),
) -> list[dict]:
    """Suggestions in the caller's projects, newest first; a Developer sees only their own."""
    project = project_catalog_service.get_project(project_id) if project_id else None
    if project_id and project is None:
        return []
    if project is not None:
        ensure_project(context, project.id, "Project")
    only_mine = mine or context.role == "DEVELOPER"
    with get_session() as session:
        member = member_of_user(session, context.user_id) if only_mine else None
        member_id = str(member.id) if member else None
    rows = feedback_service.list(
        # Mine may sit in a project I do not manage (one I am on as a member): no project fence on that list.
        allowed_project_ids=None if only_mine else context.project_ids, project_id=project.id if project else None, status=status_filter,
        user_id=context.user_id if only_mine else None, member_id=member_id, limit=limit,
    )
    return [FeedbackOut.model_validate(row).model_dump() for row in rows]


@router.get("/{feedback_id}", response_model=FeedbackOut, openapi_extra={"x-requirement-ids": ["FR-FBK-02"]})
async def get_feedback(feedback_id: str, context: AuthContext = Depends(require_account)) -> dict:
    return FeedbackOut.model_validate(_visible(context, feedback_id)).model_dump()


@router.get("/{feedback_id}/files/{file_id}", openapi_extra={"x-requirement-ids": ["FR-FBK-02"]})
async def get_feedback_file(feedback_id: str, file_id: str, context: AuthContext = Depends(require_account)) -> Response:
    """The picture itself, for the owner to look at before deciding."""
    _visible(context, feedback_id)
    try:
        name, mime, content = feedback_service.file_bytes(feedback_id, file_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found") from error
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)[:120] or "tep"
    return Response(content=content, media_type=mime, headers={"Content-Disposition": f'inline; filename="{safe}"', "Cache-Control": "private, max-age=300"})


@router.post("/{feedback_id}/accept", response_model=FeedbackOut, openapi_extra={"x-requirement-ids": ["FR-FBK-03"]})
async def accept_feedback(feedback_id: str, payload: FeedbackDecision | None = None, context: AuthContext = Depends(require_member)) -> dict:
    """The owner's yes: an Intake on channel FEEDBACK is created with the files, and the AI reads it."""
    _deciders_only(context)
    # Deciding takes the project, not authorship: a suggestion of mine in a project I do not manage is not mine to accept.
    ensure_project(context, _visible(context, feedback_id)["project_id"], "Suggestion")
    try:
        row = feedback_service.accept(feedback_id, actor_id=context.user_id, note=payload.note if payload else None)
    except FeedbackError as error:
        raise api_exception(status.HTTP_409_CONFLICT, error.code, "Góp ý này đã được quyết rồi") from error
    return FeedbackOut.model_validate(row).model_dump()


@router.post("/{feedback_id}/reject", response_model=FeedbackOut, openapi_extra={"x-requirement-ids": ["FR-FBK-03"]})
async def reject_feedback(feedback_id: str, payload: FeedbackDecision, context: AuthContext = Depends(require_member)) -> dict:
    """The owner's no, with the line the person will read."""
    _deciders_only(context)
    ensure_project(context, _visible(context, feedback_id)["project_id"], "Suggestion")
    try:
        row = feedback_service.reject(feedback_id, actor_id=context.user_id, note=payload.note)
    except FeedbackError as error:
        if error.code == "ALREADY_DECIDED":
            raise api_exception(status.HTTP_409_CONFLICT, error.code, "Góp ý này đã được quyết rồi") from error
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, "Ghi một dòng lý do để người góp ý đọc") from error
    return FeedbackOut.model_validate(row).model_dump()


__all__ = ["router", "MAX_FILES"]
