from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.api.security import AuthContext, require_cto, require_member
from app.db import get_session
from app.modules.intake.approval_stats import approval_sources
from app.modules.intake.decisions import list_decisions
from app.modules.intake.routing import route_approvals
from app.schemas import ApprovalDecisionOut, ApprovalDecisionPage, ApprovalSourceWeek, IntakePage
from app.services.intake_service import intake_store

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get(
    "/decisions",
    response_model=ApprovalDecisionPage,
    openapi_extra={"x-requirement-ids": ["FR-APR-15", "FR-APR-04", "FR-APR-05", "FR-APR-08"]},
)
async def list_approval_decisions(
    project_id: str | None = Query(default=None),
    days: int = Query(default=7, ge=1, le=365, description="Window ending now; ignored when `before` is given"),
    before: datetime | None = Query(default=None, description="Read decisions older than this moment (from `next_before`)"),
    limit: int = Query(default=50, ge=1, le=200),
    context: AuthContext = Depends(require_member),
) -> ApprovalDecisionPage:
    """What was decided lately, newest first, in the caller's projects: a decision leaves the queue, not the record."""
    since = None if before is not None else datetime.now(timezone.utc) - timedelta(days=days)
    with get_session() as session:
        rows = list_decisions(session, context.project_ids, project_id, since, before, limit)
    return ApprovalDecisionPage(
        items=[ApprovalDecisionOut.model_validate(row) for row in rows],
        next_before=rows[-1]["at"] if len(rows) == limit else None,
        since=since,
    )


@router.get(
    "",
    response_model=IntakePage,
    openapi_extra={"x-requirement-ids": ["FR-APR-01", "FR-UI-02", "FR-APR-14"]},
)
async def list_approval_queue(
    project_id: str | None = Query(default=None),
    owner: Literal["CTO", "PO"] | None = Query(default=None, description="Keep only the requests that are this role's to decide"),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None, max_length=2048),
    context: AuthContext = Depends(require_member),
) -> IntakePage:
    page = intake_store.list_page(
        allowed_project_ids=context.project_ids,
        project_id=project_id,
        item_status="PENDING_APPROVAL",
        limit=limit,
        cursor=cursor,
        sort_by="updated_at",
        sort_order="asc",
    )
    with get_session() as session:
        route_approvals(session, page.items)
    if owner is not None:
        # The filter applies to the page that was read; the cursor still walks the whole queue.
        page.items = [item for item in page.items if item.approval_owner == owner]
    return page


@router.get(
    "/sources",
    response_model=list[ApprovalSourceWeek],
    openapi_extra={"x-requirement-ids": ["FR-APR-07"]},
)
async def list_approval_sources(
    weeks: int = Query(default=4, ge=1, le=12),
    _: AuthContext = Depends(require_cto),
) -> list[ApprovalSourceWeek]:
    return [ApprovalSourceWeek.model_validate(row) for row in approval_sources(weeks)]
