from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.errors import api_exception
from app.api.security import AuthContext, require_cto, require_member
from app.modules.planning import scope as planning_scope
from app.modules.planning import acceptance
from app.modules.reports import issue_match
from app.modules.reports.mailbox import MailboxScanError, mailbox_scan_service
from app.modules.reports.service import daily_report_service
from app.schemas import (
    DailyReportItemIssueRequest,
    IssueSuggestionOutcome,
    DailyReportDetailOut,
    DailyReportIngestRequest,
    DailyReportItemUpdate,
    DailyReportOut,
    DailyReportReviewRequest,
    DailyReportSourceOut,
    MailboxStatusOut,
)


router = APIRouter(prefix="/reports", tags=["reports"])


def _own_report(context: AuthContext, report_id: str) -> None:
    """A Project Owner reaches a report only when its sender is on one of their teams."""
    if context.project_ids is None:
        return
    member = planning_scope.report_member(report_id)
    if member is None or member not in planning_scope.team_member_ids(context.project_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")


def _own_item(context: AuthContext, report_id: str, item_id: str) -> None:
    """A Project Owner touches only the items they can see: their projects' and the unclaimed ones (FR-ID-08)."""
    _own_report(context, report_id)
    if context.project_ids is not None and not daily_report_service.item_visible(report_id, item_id, context.project_ids):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report item not found")


def _detail(context: AuthContext, report_id: str) -> DailyReportDetailOut:
    detail = daily_report_service.report_detail(report_id, context.project_ids)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")
    return DailyReportDetailOut.model_validate(detail)


@router.post(
    "/daily/ingest",
    response_model=DailyReportOut,
    status_code=status.HTTP_201_CREATED,
    openapi_extra={"x-requirement-ids": ["FR-EML-01", "FR-EML-02", "FR-EML-04"]},
)
async def ingest_daily_report(
    payload: DailyReportIngestRequest,
    _: AuthContext = Depends(require_cto),
) -> DailyReportOut:
    return DailyReportOut.model_validate(daily_report_service.ingest(**payload.model_dump()))


@router.get(
    "/mailbox",
    response_model=MailboxStatusOut,
    openapi_extra={"x-requirement-ids": ["FR-EML-12", "FR-EML-14"]},
)
async def get_mailbox_status(_: AuthContext = Depends(require_cto)) -> MailboxStatusOut:
    return MailboxStatusOut.model_validate(mailbox_scan_service.status())


@router.post(
    "/mailbox/scan",
    response_model=MailboxStatusOut,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-EML-14", "FR-EML-01"]},
)
async def scan_mailbox_now(context: AuthContext = Depends(require_cto)) -> MailboxStatusOut:
    try:
        return MailboxStatusOut.model_validate(mailbox_scan_service.request(context.user_id))
    except MailboxScanError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail={"error": exc.code, "message": "Mailbox scanning is turned off"}) from exc


@router.get(
    "/daily",
    response_model=list[DailyReportOut],
    openapi_extra={"x-requirement-ids": ["FR-EML-03", "FR-EML-04", "FR-ID-08"]},
)
async def list_daily_reports(
    report_date: date | None = Query(default=None),
    member_id: str | None = Query(default=None),
    context: AuthContext = Depends(require_member),
) -> list[DailyReportOut]:
    rows = daily_report_service.list_reports(report_date=report_date, member_id=member_id, allowed_project_ids=context.project_ids)
    if context.project_ids is not None:
        # A Project Owner sees the reports of the people on their own teams, and only those with something of theirs in them.
        team = planning_scope.team_member_ids(context.project_ids)
        # A report whose every item belongs to other projects stays out; one the machine read nothing from still shows.
        rows = [row for row in rows if row.get("member_id") in team and (int(row.get("item_count") or 0) > 0 or int(row.get("hidden_items") or 0) == 0)]
    return [DailyReportOut.model_validate(item) for item in rows]


@router.get(
    "/daily/{report_id}",
    response_model=DailyReportDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-RPT-05", "FR-ID-08"]},
)
async def get_daily_report(report_id: str, context: AuthContext = Depends(require_member)) -> DailyReportDetailOut:
    _own_report(context, report_id)
    return _detail(context, report_id)


@router.get(
    "/daily/{report_id}/raw",
    response_model=DailyReportSourceOut,
    openapi_extra={"x-requirement-ids": ["FR-RPT-05", "FR-ID-04", "NFR-SEC-03", "FR-ID-08"]},
)
async def get_daily_report_source(report_id: str, context: AuthContext = Depends(require_member)) -> DailyReportSourceOut:
    _own_report(context, report_id)
    source = daily_report_service.report_source(report_id, context.user_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")
    return DailyReportSourceOut.model_validate(source)


@router.post(
    "/daily/{report_id}/review",
    response_model=DailyReportDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-RPT-05", "NFR-SEC-03", "FR-ID-08"]},
)
async def review_daily_report(
    report_id: str,
    payload: DailyReportReviewRequest,
    context: AuthContext = Depends(require_member),
) -> DailyReportDetailOut:
    _own_report(context, report_id)
    current = _detail(context, report_id)
    if not current.can_review:
        raise api_exception(status.HTTP_403_FORBIDDEN, "REPORT_MIXED_PROJECTS", "Thư có việc ở dự án khác; CTO xác nhận hoặc loại thư này")
    detail = daily_report_service.review_report(report_id, payload.decision, context.user_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Daily report not found")
    return _detail(context, report_id)


@router.patch(
    "/daily/{report_id}/items/{item_id}",
    response_model=DailyReportDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-RPT-05", "NFR-SEC-03", "FR-ID-08"]},
)
async def update_daily_report_item(
    report_id: str,
    item_id: str,
    payload: DailyReportItemUpdate,
    context: AuthContext = Depends(require_member),
) -> DailyReportDetailOut:
    _own_item(context, report_id, item_id)
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("title") is None and "title" in changes or changes.get("work_status") is None and "work_status" in changes:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Title and status cannot be empty")
    if context.project_ids is not None and "project_code" in changes:
        # A Project Owner may claim an item for their own project only.
        target = planning_scope.project_ids([changes["project_code"]]) if changes.get("project_code") else [None]
        if not target or target[0] is None or not context.allows(target[0]):
            raise api_exception(status.HTTP_403_FORBIDDEN, "PROJECT_NOT_ALLOWED", "Chỉ chuyển việc về dự án của mình")
    try:
        detail = daily_report_service.update_item(report_id, item_id, changes, context.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report item not found")
    return _detail(context, report_id)


@router.post(
    "/daily/{report_id}/items/{item_id}/issue",
    response_model=DailyReportDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-RPT-07", "NFR-SEC-03", "FR-ID-08"]},
)
async def set_daily_report_item_issue(
    report_id: str,
    item_id: str,
    payload: DailyReportItemIssueRequest,
    context: AuthContext = Depends(require_member),
) -> DailyReportDetailOut:
    """A person decides: this work is Issue n, or needs no Issue (a meeting, support, a review, learning), or neither."""
    _own_item(context, report_id, item_id)
    if not issue_match.link_item(report_id, item_id, payload.gitlab_issue, reason=payload.no_issue_reason, actor_id=context.user_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report item not found")
    if payload.gitlab_issue:
        acceptance.collect()
    return _detail(context, report_id)


@router.post(
    "/daily/{report_id}/link-sure",
    response_model=DailyReportDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-RPT-07", "NFR-SEC-03", "FR-ID-08"]},
)
async def link_sure_daily_report_items(report_id: str, context: AuthContext = Depends(require_member)) -> DailyReportDetailOut:
    """Take every suggestion the machine is sure of in this report at once."""
    _own_report(context, report_id)
    _detail(context, report_id)
    if issue_match.link_sure(report_id, context.user_id, project_ids=context.project_ids):
        acceptance.collect()
    return _detail(context, report_id)


@router.post(
    "/daily/{report_id}/suggest-issues",
    response_model=IssueSuggestionOutcome,
    openapi_extra={"x-requirement-ids": ["FR-RPT-07", "FR-ID-08"]},
)
async def suggest_daily_report_issues(report_id: str, context: AuthContext = Depends(require_member)) -> IssueSuggestionOutcome:
    """Look again for the Issues behind this report's unlinked items, now that plans or the Issue list may have changed."""
    _own_report(context, report_id)
    _detail(context, report_id)
    return IssueSuggestionOutcome.model_validate(daily_report_service.suggest_issues(report_id))


@router.post(
    "/issue-suggestions/backfill",
    response_model=IssueSuggestionOutcome,
    openapi_extra={"x-requirement-ids": ["FR-RPT-07"]},
)
async def backfill_issue_suggestions(days: int = Query(default=14, ge=1, le=90), _: AuthContext = Depends(require_cto)) -> IssueSuggestionOutcome:
    """Run the matching over every recent report that still has unlinked work: for the first week of use."""
    totals = {"items": 0, "linked": 0, "suggested": 0, "for_ai": [], "reports": 0}
    for email_id in issue_match.reports_with_unlinked(days):
        outcome = daily_report_service.suggest_issues(email_id)
        totals["reports"] += 1
        for key in ("items", "linked", "suggested"):
            totals[key] += int(outcome.get(key, 0))
        totals["for_ai"].extend(outcome.get("for_ai", []))
    return IssueSuggestionOutcome.model_validate(totals)


@router.delete(
    "/daily/{report_id}/items/{item_id}",
    response_model=DailyReportDetailOut,
    openapi_extra={"x-requirement-ids": ["FR-RPT-05", "NFR-SEC-03", "FR-ID-08"]},
)
async def remove_daily_report_item(
    report_id: str,
    item_id: str,
    context: AuthContext = Depends(require_member),
) -> DailyReportDetailOut:
    _own_item(context, report_id, item_id)
    detail = daily_report_service.remove_item(report_id, item_id, context.user_id)
    if detail is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report item not found")
    return _detail(context, report_id)
