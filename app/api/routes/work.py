"""Work tracked inside Intake: the board, its items, their discussion, and the way to an Issue (FR-WRK-01..05, ADR-0066)."""
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from app.api.errors import api_exception
from app.api.security import AuthContext, ensure_project, require_account, require_member
from app.db import get_session
from app.modules.intake.feedback import member_of_user
from app.modules.projects.service import project_catalog_service
from app.modules.work.links import LinkError, issue_link
from app.modules.work.service import DOER_STATUSES, WorkError, work_service
from app.schemas import (
    PostLinkCreate, PostLinkOut, WorkBulkCreate, WorkBulkUpdate, WorkChannelIn, WorkChannelUpdate, WorkCommentCreate, WorkCreate, WorkDetail, WorkLinkCreate,
    WorkMove, WorkOut, WorkUpdate,
)

router = APIRouter(prefix="/work", tags=["work"])

NOT_FOUND = {"WORK_NOT_FOUND"}
CONFLICTS = {"STALE_VERSION", "WORK_LOCKED_BY_ISSUE", "WORK_CLOSED", "STEPS_OPEN"}


def _raise(error: WorkError) -> None:
    code = status.HTTP_409_CONFLICT if error.code in CONFLICTS else status.HTTP_422_UNPROCESSABLE_ENTITY
    raise api_exception(code, error.code, str(error))


def _project_of(reference: str):
    project = project_catalog_service.get_project(reference)
    if project is None or project.status != "ACTIVE":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


def _mine(context: AuthContext, row: dict) -> dict:
    for comment in row.get("comments") or []:
        comment["mine"] = str(comment.get("user_id")) == str(context.user_id)
    for link in row.get("links") or []:
        link["mine"] = str(link.get("added_by")) == str(context.user_id)
    return row


def _visible(context: AuthContext, work_id: str) -> dict:
    """A work item is seen by whoever sees its project: the CTO, the owner, and the people on the project."""
    row = work_service.get(work_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
    ensure_project(context, row["project_id"], "Work item")
    return _mine(context, row)


def _deciders_only(context: AuthContext) -> None:
    if context.role not in ("CTO", "PROJECT_OWNER"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the CTO or a Project Owner changes work items")


@router.get("", response_model=list[WorkOut], openapi_extra={"x-requirement-ids": ["FR-WRK-02"]})
async def list_work(
    project: str = Query(..., min_length=1, max_length=64, description="Project code or id"),
    include_closed: bool = Query(default=False),
    week: date | None = Query(default=None, description="A Monday: the week's channel versions come along (FR-MKT-04)"),
    context: AuthContext = Depends(require_account),
) -> list[dict]:
    row = _project_of(project)
    ensure_project(context, row.id, "Project")
    return [WorkOut.model_validate(item).model_dump() for item in work_service.list(project_id=str(row.id), include_closed=include_closed, week_start=week)]


@router.get("/review", response_model=list[WorkOut], openapi_extra={"x-requirement-ids": ["FR-MKT-05"]})
async def list_for_review(context: AuthContext = Depends(require_member)) -> list[dict]:
    """Everything waiting in Chờ duyệt on the projects the caller manages, newest first."""
    return [WorkOut.model_validate(item).model_dump() for item in work_service.waiting_review(allowed_project_ids=context.project_ids)]


@router.get("/campaigns", response_model=list[dict], openapi_extra={"x-requirement-ids": ["FR-MKT-01"]})
async def list_campaigns(project: str = Query(..., min_length=1, max_length=64), context: AuthContext = Depends(require_account)) -> list[dict]:
    row = _project_of(project)
    ensure_project(context, row.id, "Project")
    return work_service.campaigns(str(row.id))


@router.post("/bulk", response_model=list[dict], status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-MKT-06"]})
async def bulk_create_work(payload: WorkBulkCreate, context: AuthContext = Depends(require_member)) -> list[dict]:
    """Thêm nhiều bài: one line, one post."""
    project = _project_of(payload.project)
    ensure_project(context, project.id, "Project")
    return work_service.bulk_create(project_id=str(project.id), rows=[row.model_dump() for row in payload.rows], actor_id=context.user_id)


@router.post("/bulk-update", response_model=dict, openapi_extra={"x-requirement-ids": ["FR-MKT-06"]})
async def bulk_update_work(payload: WorkBulkUpdate, context: AuthContext = Depends(require_member)) -> dict:
    return work_service.bulk_update(ids=payload.ids, actor_id=context.user_id, member_id=payload.member_id, clear_member=payload.clear_member,
                                    publish_at=payload.publish_at, status=payload.status, allowed_project_ids=context.project_ids)


@router.post("", response_model=WorkOut, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-WRK-01", "FR-WRK-08"]})
async def create_work(payload: WorkCreate, context: AuthContext = Depends(require_member)) -> dict:
    project = _project_of(payload.project)
    ensure_project(context, project.id, "Project")
    try:
        row = work_service.create(
            project_id=str(project.id), title=payload.title, description=payload.description, priority=payload.priority,
            member_id=payload.member_id, due_date=payload.due_date, status=payload.status, actor_id=context.user_id, template=payload.template,
            channel=payload.channel, format=payload.format, campaign=payload.campaign, urgent=payload.urgent,
            channels=[spec.model_dump() for spec in payload.channels],
        )
    except WorkError as error:
        _raise(error)
    return WorkOut.model_validate(row).model_dump()


@router.get("/{work_id}", response_model=WorkDetail, openapi_extra={"x-requirement-ids": ["FR-WRK-02"]})
async def get_work(work_id: str, context: AuthContext = Depends(require_account)) -> dict:
    return WorkDetail.model_validate(_visible(context, work_id)).model_dump()


@router.patch("/{work_id}", response_model=WorkOut, openapi_extra={"x-requirement-ids": ["FR-WRK-01"]})
async def update_work(work_id: str, payload: WorkUpdate, context: AuthContext = Depends(require_member)) -> dict:
    _visible(context, work_id)
    try:
        row = work_service.update(
            work_id, expected_version=payload.expected_version, actor_id=context.user_id, title=payload.title, description=payload.description,
            priority=payload.priority, member_id=payload.member_id, clear_member=payload.clear_member, due_date=payload.due_date, clear_due=payload.clear_due,
            channel=payload.channel, format=payload.format, campaign=payload.campaign, clear_campaign=payload.clear_campaign, urgent=payload.urgent,
        )
    except WorkError as error:
        _raise(error)
    return WorkOut.model_validate(row).model_dump()


@router.post("/{work_id}/move", response_model=WorkOut, openapi_extra={"x-requirement-ids": ["FR-WRK-03", "FR-WRK-09"]})
async def move_work(work_id: str, payload: WorkMove, context: AuthContext = Depends(require_account)) -> dict:
    """The CTO and the owner move anything; a Developer moves only work assigned to them, between the doing columns."""
    row = _visible(context, work_id)
    allowed = None
    if context.role == "DEVELOPER":
        with get_session() as session:
            member = member_of_user(session, context.user_id)
        if member is None or str(member.id) != str(row.get("member_id") or ""):
            raise api_exception(status.HTTP_403_FORBIDDEN, "NOT_YOUR_WORK", "Chỉ người được giao việc này mới chuyển được nó")
        allowed = DOER_STATUSES
    try:
        moved = work_service.move(work_id, expected_version=payload.expected_version, status=payload.status, note=payload.note,
                                  actor_id=context.user_id, allowed_statuses=allowed)
    except WorkError as error:
        _raise(error)
    return WorkOut.model_validate(moved).model_dump()


@router.post("/{work_id}/comments", response_model=WorkDetail, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-WRK-04"]})
async def comment_work(work_id: str, payload: WorkCommentCreate, context: AuthContext = Depends(require_account)) -> dict:
    _visible(context, work_id)
    try:
        row = work_service.comment(work_id, body=payload.body, actor_id=context.user_id)
    except WorkError as error:
        _raise(error)
    return WorkDetail.model_validate(_mine(context, row)).model_dump()


@router.delete("/{work_id}/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-WRK-04"]})
async def delete_work_comment(work_id: str, comment_id: str, context: AuthContext = Depends(require_account)) -> Response:
    _visible(context, work_id)
    try:
        work_service.delete_comment(work_id, comment_id, actor_id=context.user_id, is_cto=context.role == "CTO")
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
    except WorkError as error:
        raise api_exception(status.HTTP_403_FORBIDDEN, error.code, str(error))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{work_id}/channels", response_model=WorkDetail, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-MKT-01"]})
async def add_work_channel(work_id: str, payload: WorkChannelIn, context: AuthContext = Depends(require_member)) -> dict:
    _visible(context, work_id)
    try:
        row = work_service.add_channel(work_id, channel=payload.channel, publish_at=payload.publish_at, language=payload.language, actor_id=context.user_id)
    except WorkError as error:
        _raise(error)
    return WorkDetail.model_validate(_mine(context, row)).model_dump()


@router.patch("/{work_id}/channels/{channel_id}", response_model=WorkDetail, openapi_extra={"x-requirement-ids": ["FR-MKT-01"]})
async def update_work_channel(work_id: str, channel_id: str, payload: WorkChannelUpdate, context: AuthContext = Depends(require_account)) -> dict:
    """The CTO and the owner change anything; the person the post is assigned to says it is out, with the link."""
    row = _visible(context, work_id)
    if context.role == "DEVELOPER":
        with get_session() as session:
            member = member_of_user(session, context.user_id)
        if member is None or str(member.id) != str(row.get("member_id") or ""):
            raise api_exception(status.HTTP_403_FORBIDDEN, "NOT_YOUR_WORK", "Chỉ người được giao bài này mới ghi được")
        if payload.publish_at is not None or payload.clear_publish:
            raise api_exception(status.HTTP_403_FORBIDDEN, "NOT_YOUR_WORK", "Ngày đăng do Project Owner đặt")
    try:
        updated = work_service.update_channel(work_id, channel_id, actor_id=context.user_id, publish_at=payload.publish_at, clear_publish=payload.clear_publish,
                                              status=payload.status, published_url=payload.published_url, text=payload.text, clear_text=payload.clear_text)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel version not found")
    except WorkError as error:
        _raise(error)
    return WorkDetail.model_validate(_mine(context, updated)).model_dump()


@router.post("/{work_id}/channels/{channel_id}/link", response_model=PostLinkOut, openapi_extra={"x-requirement-ids": ["FR-MKT-12"]})
async def issue_short_link(work_id: str, channel_id: str, payload: PostLinkCreate, context: AuthContext = Depends(require_member)) -> dict:
    """The short link of a channel version: Intake redirects it, with UTM tags, and counts the clicks. Asking again keeps the code."""
    _visible(context, work_id)
    try:
        row = issue_link(work_id, channel_id, target_url=payload.target_url, actor_id=context.user_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel version not found")
    except LinkError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error))
    return PostLinkOut.model_validate(row).model_dump()


@router.delete("/{work_id}/channels/{channel_id}", response_model=WorkDetail, openapi_extra={"x-requirement-ids": ["FR-MKT-01"]})
async def remove_work_channel(work_id: str, channel_id: str, context: AuthContext = Depends(require_member)) -> dict:
    _visible(context, work_id)
    try:
        row = work_service.remove_channel(work_id, channel_id, actor_id=context.user_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel version not found")
    except WorkError as error:
        _raise(error)
    return WorkDetail.model_validate(_mine(context, row)).model_dump()


@router.post("/{work_id}/links", response_model=WorkDetail, status_code=status.HTTP_201_CREATED, openapi_extra={"x-requirement-ids": ["FR-WRK-07"]})
async def link_work(work_id: str, payload: WorkLinkCreate, context: AuthContext = Depends(require_account)) -> dict:
    """Where the work lives outside Intake: a folder, a design, a cut, a published post. Anyone who sees the work adds one."""
    _visible(context, work_id)
    try:
        row = work_service.add_link(work_id, url=payload.url, note=payload.note, actor_id=context.user_id)
    except WorkError as error:
        _raise(error)
    return WorkDetail.model_validate(_mine(context, row)).model_dump()


@router.delete("/{work_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra={"x-requirement-ids": ["FR-WRK-07"]})
async def unlink_work(work_id: str, link_id: str, context: AuthContext = Depends(require_account)) -> Response:
    _visible(context, work_id)
    try:
        work_service.delete_link(work_id, link_id, actor_id=context.user_id, is_cto=context.role == "CTO")
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Link not found")
    except WorkError as error:
        raise api_exception(status.HTTP_403_FORBIDDEN, error.code, str(error))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{work_id}/issue", response_model=WorkDetail, openapi_extra={"x-requirement-ids": ["FR-WRK-05"]})
async def work_to_issue(work_id: str, context: AuthContext = Depends(require_member)) -> dict:
    """Decide the work for the delivery tracker: its request is approved (or redirected) for GitLab or GitHub and queued."""
    _visible(context, work_id)
    _deciders_only(context)
    try:
        row = work_service.request_issue(work_id, actor_id=context.user_id)
    except WorkError as error:
        _raise(error)
    return WorkDetail.model_validate(_mine(context, row)).model_dump()
