from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.security import AuthContext, require_account
from app.modules.planning import personal
from app.modules.planning.overview import LOCAL_TZ
from app.schemas import PersonalDelegateIn, PersonalMatrixOut, PersonalTaskIn, PersonalTaskOut, PersonalTaskUpdate

router = APIRouter(prefix="/personal-tasks", tags=["personal"])
REQUIREMENTS = {"x-requirement-ids": ["FR-PER-01", "FR-PER-02", "FR-PER-04", "FR-PER-05", "FR-PER-06"]}


def _raise(error: personal.PersonalTaskError) -> None:
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": error.code, "message": error.message}) from error


@router.get("", response_model=list[PersonalTaskOut], openapi_extra=REQUIREMENTS)
async def list_personal_tasks(
    start: date | None = Query(default=None, alias="from"), end: date | None = Query(default=None, alias="to"),
    context: AuthContext = Depends(require_account),
) -> list[PersonalTaskOut]:
    """The caller's own tasks in a date range; default today and the next seven days."""
    from datetime import datetime
    today = datetime.now(LOCAL_TZ).date()
    start = start or today
    end = end or start + timedelta(days=7)
    if end < start or (end - start).days > 92:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail={"code": "RANGE_INVALID", "message": "from..to must be at most 92 days"})
    return [PersonalTaskOut.model_validate(row) for row in personal.list_tasks(context.user_id, start, end)]


@router.get("/matrix", response_model=PersonalMatrixOut, openapi_extra=REQUIREMENTS)
async def personal_matrix(week_of: date | None = Query(default=None), context: AuthContext = Depends(require_account)) -> PersonalMatrixOut:
    """The week's matrix with the undated and the left-over tasks, and the numbers above it."""
    return PersonalMatrixOut.model_validate(personal.matrix(context.user_id, week_of))


@router.get("/archived", response_model=list[PersonalTaskOut], openapi_extra=REQUIREMENTS)
async def archived_personal_tasks(context: AuthContext = Depends(require_account)) -> list[PersonalTaskOut]:
    """What the drop quadrant put away; a PATCH with archived=false brings one back."""
    return [PersonalTaskOut.model_validate(row) for row in personal.list_archived(context.user_id)]


@router.post("", response_model=PersonalTaskOut, status_code=status.HTTP_201_CREATED, openapi_extra=REQUIREMENTS)
async def create_personal_task(payload: PersonalTaskIn, context: AuthContext = Depends(require_account)) -> PersonalTaskOut:
    try:
        return PersonalTaskOut.model_validate(personal.create_task(
            context.user_id, title=payload.title, task_date=payload.task_date, hours=payload.hours,
            start_time=payload.start_time, remind_at=payload.remind_at, note=payload.note, important=payload.important, urgent=payload.urgent,
            repeat_rule=payload.repeat_rule,
        ))
    except personal.PersonalTaskError as error:
        _raise(error)


@router.patch("/{task_id}", response_model=PersonalTaskOut, openapi_extra=REQUIREMENTS)
async def update_personal_task(task_id: str, payload: PersonalTaskUpdate, context: AuthContext = Depends(require_account)) -> PersonalTaskOut:
    try:
        updated = personal.update_task(context.user_id, task_id, **payload.model_dump(exclude_unset=True))
    except personal.PersonalTaskError as error:
        _raise(error)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return PersonalTaskOut.model_validate(updated)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, openapi_extra=REQUIREMENTS)
async def delete_personal_task(task_id: str, context: AuthContext = Depends(require_account)) -> None:
    if not personal.delete_task(context.user_id, task_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


@router.post("/{task_id}/delegate", response_model=PersonalTaskOut, openapi_extra=REQUIREMENTS)
async def delegate_personal_task(task_id: str, payload: PersonalDelegateIn, context: AuthContext = Depends(require_account)) -> PersonalTaskOut:
    """Hand a task to a staff member as support work in their day plan. The CTO gives to anyone; a Project Owner
    inside their own projects; a Developer gives nothing (FR-PER-06)."""
    if context.role == "DEVELOPER":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail={"code": "FORBIDDEN", "message": "Developer không giao việc"})
    if context.project_ids is not None and payload.project_id not in context.project_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    try:
        made = personal.delegate(context.user_id, task_id, member_id=payload.member_id, project_id=payload.project_id, task_date=payload.task_date, hours=payload.hours, actor_name=context.display_name or context.email)
    except personal.PersonalTaskError as error:
        _raise(error)
    if not made:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    return PersonalTaskOut.model_validate(made)
