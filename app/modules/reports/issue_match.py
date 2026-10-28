"""Find the Issue behind a reported piece of work (FR-RPT-07, ADR-0054).

People rarely write the Issue number in their report, so the number is looked up from what the system already
knows, in order of trust: the plan of that day for that person, the same person's earlier reports, the open
Issues of the project (the ones assigned to them first), and approved requests that already have an Issue. Two
cases are sure enough to link without asking: the same title the person already reported with an Issue, and a
person with exactly one planned Issue that day reporting exactly one piece of work. Everything else is a
suggestion with a confidence; a person clicks. AI is asked last, only for what the rules could not place, and
its answers never link on their own.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select

from app.db import get_session
from app.models import (
    AuditEvent, EmailMessage, ExternalLink, GitLabIssueSnapshot, IntakeItem, PlanningAssignment, PlanningRun, ReportItem,
    WorkforceProjectMembership,
)

DELIVERY_STATUSES = ("DONE", "IN_PROGRESS", "PENDING_REVIEW", "BLOCKED")
NO_ISSUE_REASONS = ("MEETING", "SUPPORT", "REVIEW", "LEARNING", "OTHER")
SURE = 0.9            # a suggestion at or above this links when the person asks for "all the sure ones"
KEEP = 0.35           # below this a suggestion is noise
MAX_SUGGESTIONS = 3
LOOKBACK = timedelta(days=14)
SOURCE_LABELS = {
    "RULE_PREVIOUS": "cùng việc đã báo cáo trước",
    "RULE_PLAN": "từ kế hoạch ngày",
    "RULE_ISSUE": "Issue đang mở",
    "RULE_INTAKE": "yêu cầu đã duyệt",
    "AI": "AI gợi ý",
}

_STOP = {"va", "cua", "cho", "voi", "la", "de", "tiep", "tuc", "lam", "them", "sua", "phan", "trong", "ve", "the", "and", "for", "to", "of", "the", "a", "an"}


def tokens(text: str | None) -> set[str]:
    """Lowercase, no diacritics, no punctuation, no filler words: enough for Vietnamese task titles."""
    if not text:
        return set()
    plain = unicodedata.normalize("NFD", text)
    plain = "".join(char for char in plain if unicodedata.category(char) != "Mn").replace("đ", "d").replace("Đ", "d").lower()
    words = re.findall(r"[a-z0-9]+", plain)
    return {word for word in words if word not in _STOP and (len(word) > 1 or word.isdigit())}


def similarity(a: str | None, b: str | None) -> float:
    """Between 0 and 1: how much two titles share, forgiving a short title inside a longer one."""
    left, right = tokens(a), tokens(b)
    if not left or not right:
        return 0.0
    shared = len(left & right)
    jaccard = shared / len(left | right)
    containment = shared / min(len(left), len(right))
    return round(max(jaccard, 0.85 * containment), 3)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _issue_titles(session, project_id: str) -> dict[str, str]:
    rows = session.execute(select(GitLabIssueSnapshot.issue_external_id, GitLabIssueSnapshot.title).where(
        GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.is_current.is_(True),
    )).all()
    return {str(issue): title for issue, title in rows}


def _sources(session, report: EmailMessage, project_id: str, member_id: str | None) -> dict[str, list[dict[str, object]]]:
    """Everything an item of this report and project could be matched against."""
    titles = _issue_titles(session, project_id)
    plan: list[dict[str, object]] = []
    if member_id and report.report_date:
        rows = session.execute(
            select(PlanningAssignment.gitlab_issue_external_id)
            .join(PlanningRun, PlanningRun.id == PlanningAssignment.planning_run_id)
            .where(PlanningRun.plan_date == report.report_date, PlanningRun.status != "SUPERSEDED",
                   PlanningAssignment.member_id == member_id, PlanningAssignment.project_id == project_id,
                   PlanningAssignment.gitlab_issue_external_id.is_not(None))
        ).all()
        seen: set[str] = set()
        for (issue,) in rows:
            if issue and issue not in seen:
                seen.add(issue)
                plan.append({"issue": str(issue), "title": titles.get(str(issue), f"Issue #{issue}")})
    previous: list[dict[str, object]] = []
    if member_id and report.report_date:
        rows = session.execute(
            select(ReportItem.gitlab_issue_external_id, ReportItem.title)
            .join(EmailMessage, EmailMessage.id == ReportItem.email_message_id)
            .where(ReportItem.is_current.is_(True), EmailMessage.is_current.is_(True), ReportItem.member_id == member_id,
                   ReportItem.project_id == project_id, ReportItem.gitlab_issue_external_id.is_not(None),
                   EmailMessage.report_date < report.report_date, EmailMessage.report_date >= report.report_date - LOOKBACK)
            .order_by(EmailMessage.report_date.desc())
        ).all()
        for issue, title in rows:
            previous.append({"issue": str(issue), "title": title, "issue_title": titles.get(str(issue))})
    gitlab_user = None
    if member_id:
        gitlab_user = session.scalar(select(WorkforceProjectMembership.gitlab_user_external_id).where(
            WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.project_id == project_id,
        ))
    open_issues: list[dict[str, object]] = []
    for row in session.scalars(select(GitLabIssueSnapshot).where(
        GitLabIssueSnapshot.project_id == project_id, GitLabIssueSnapshot.is_current.is_(True), GitLabIssueSnapshot.state == "opened",
    )).all():
        assignees = [str(value) for value in (row.assignee_external_ids or [])]
        open_issues.append({"issue": str(row.issue_external_id), "title": row.title, "mine": bool(gitlab_user) and str(gitlab_user) in assignees})
    intakes: list[dict[str, object]] = []
    for external_id, title in session.execute(
        select(ExternalLink.external_id, IntakeItem.normalized_title)
        .join(IntakeItem, IntakeItem.id == ExternalLink.intake_id)
        .where(ExternalLink.project_id == project_id, ExternalLink.target_system.in_(("GITLAB", "GITHUB")), IntakeItem.normalized_title.is_not(None))
    ).all():
        intakes.append({"issue": str(external_id), "title": title})
    return {"plan": plan, "previous": previous, "open": open_issues, "intakes": intakes}


def _rank(item_title: str, sources: dict[str, list[dict[str, object]]]) -> list[dict[str, object]]:
    best: dict[str, dict[str, object]] = {}

    def offer(issue: str, title: str | None, source: str, confidence: float) -> None:
        confidence = round(min(confidence, 1.0), 3)
        if confidence < KEEP:
            return
        current = best.get(issue)
        if current is None or float(current["confidence"]) < confidence:
            best[issue] = {"issue": issue, "title": title or f"Issue #{issue}", "source": source, "confidence": confidence}

    for row in sources["previous"]:
        sim = similarity(item_title, str(row["title"]))
        offer(str(row["issue"]), str(row.get("issue_title") or row["title"]), "RULE_PREVIOUS", 1.0 if sim >= 0.95 else 0.5 + 0.45 * sim)
    for row in sources["plan"]:
        sim = similarity(item_title, str(row["title"]))
        offer(str(row["issue"]), str(row["title"]), "RULE_PLAN", 0.6 + 0.35 * sim if sim >= 0.3 else 0.45)
    for row in sources["open"]:
        sim = similarity(item_title, str(row["title"]))
        if sim >= 0.3:
            offer(str(row["issue"]), str(row["title"]), "RULE_ISSUE", (0.4 if row["mine"] else 0.3) + 0.5 * sim)
    for row in sources["intakes"]:
        sim = similarity(item_title, str(row["title"]))
        if sim >= 0.3:
            offer(str(row["issue"]), str(row["title"]), "RULE_INTAKE", 0.3 + 0.5 * sim)
    return sorted(best.values(), key=lambda row: -float(row["confidence"]))[:MAX_SUGGESTIONS]


def _audit(session, item: ReportItem, actor_id: str | None, event: str, details: dict[str, object]) -> None:
    session.add(AuditEvent(
        id=str(uuid4()), project_id=item.project_id, actor_type="USER" if actor_id else "SYSTEM", actor_id=actor_id or "system",
        event_type=event, entity_type="report_item", entity_id=item.id, details=details, created_at=datetime.now(timezone.utc),
    ))


def suggest_for_report(email_id: str) -> dict[str, object]:
    """Rank Issues for every unlinked delivery item of the report; link the sure ones. Returns what is left for AI."""
    with get_session() as session:
        report = session.get(EmailMessage, email_id)
        if report is None:
            return {"items": 0, "linked": 0, "suggested": 0, "for_ai": []}
        items = session.scalars(select(ReportItem).where(
            ReportItem.email_message_id == report.id, ReportItem.is_current.is_(True),
            ReportItem.gitlab_issue_external_id.is_(None), ReportItem.no_issue_reason.is_(None), ReportItem.project_id.is_not(None),
        ).order_by(ReportItem.created_at)).all()
        sources_by_project: dict[str, dict[str, list[dict[str, object]]]] = {}
        delivery_by_project: dict[str, int] = {}
        for item in items:
            if item.work_status in DELIVERY_STATUSES:
                delivery_by_project[str(item.project_id)] = delivery_by_project.get(str(item.project_id), 0) + 1
        linked = suggested = 0
        for_ai: list[str] = []
        for item in items:
            pid = str(item.project_id)
            if pid not in sources_by_project:
                sources_by_project[pid] = _sources(session, report, pid, str(item.member_id) if item.member_id else None)
            sources = sources_by_project[pid]
            ranked = _rank(item.title, sources)
            sure = None
            if ranked and ranked[0]["source"] == "RULE_PREVIOUS" and float(ranked[0]["confidence"]) >= 1.0:
                sure = ranked[0]
            elif (len(sources["plan"]) == 1 and delivery_by_project.get(pid, 0) == 1 and item.work_status in DELIVERY_STATUSES):
                sure = {**sources["plan"][0], "source": "RULE_PLAN", "confidence": 0.95}
                ranked = [sure] + [row for row in ranked if row["issue"] != sure["issue"]][: MAX_SUGGESTIONS - 1]
            item.issue_suggestions = ranked
            if sure is not None:
                item.gitlab_issue_external_id = str(sure["issue"])
                item.issue_link_source = str(sure["source"])
                _audit(session, item, None, "report.item.issue-linked", {"issue": sure["issue"], "source": sure["source"], "confidence": sure["confidence"]})
                linked += 1
            elif ranked:
                suggested += 1
            if sure is None and (not ranked or float(ranked[0]["confidence"]) < 0.6) and item.work_status in DELIVERY_STATUSES:
                for_ai.append(str(item.id))
        session.commit()
        return {"items": len(items), "linked": linked, "suggested": suggested, "for_ai": for_ai}


def ai_context(email_id: str, item_ids: list[str]) -> dict[str, object] | None:
    """What AI gets: the titles of the items still unplaced and the Issues they could belong to. Never the email."""
    with get_session() as session:
        report = session.get(EmailMessage, email_id)
        if report is None:
            return None
        items = [row for row in session.scalars(select(ReportItem).where(ReportItem.id.in_(item_ids), ReportItem.is_current.is_(True))).all()
                 if row.gitlab_issue_external_id is None and row.no_issue_reason is None and row.project_id]
        if not items:
            return None
        issues: dict[str, dict[str, object]] = {}
        for item in items:
            sources = _sources(session, report, str(item.project_id), str(item.member_id) if item.member_id else None)
            for group in ("plan", "open", "intakes"):
                for row in sources[group]:
                    issues.setdefault(f"{item.project_id}:{row['issue']}", {"project_id": str(item.project_id), "issue": str(row["issue"]), "title": str(row["title"]), "from_plan": group == "plan"})
        return {
            "items": [{"id": str(item.id), "project_id": str(item.project_id), "title": item.title, "status": item.work_status} for item in items],
            "issues": list(issues.values()),
        }


def apply_ai_matches(email_id: str, matches: list[dict[str, object]], *, provider: str, model: str) -> int:
    """Merge AI answers into the suggestions. They never link by themselves and never outrank a sure rule."""
    with get_session() as session:
        applied = 0
        for match in matches:
            item = session.get(ReportItem, str(match.get("item_id") or ""))
            if item is None or not item.is_current or item.gitlab_issue_external_id or item.no_issue_reason or str(item.email_message_id) != email_id:
                continue
            issue = str(match.get("issue") or "").strip().lstrip("#")
            if not issue.isdigit():
                continue
            confidence = round(min(max(float(match.get("confidence") or 0), 0.0), 0.85), 3)
            if confidence < KEEP:
                continue
            titles = _issue_titles(session, str(item.project_id))
            current = [row for row in (item.issue_suggestions or []) if str(row.get("issue")) != issue]
            current.append({"issue": issue, "title": titles.get(issue, f"Issue #{issue}"), "source": "AI", "confidence": confidence,
                            "reason": str(match.get("reason") or "")[:200], "model": model, "provider": provider})
            item.issue_suggestions = sorted(current, key=lambda row: -float(row["confidence"]))[:MAX_SUGGESTIONS]
            applied += 1
        session.commit()
        return applied


def link_item(email_id: str, item_id: str, issue: str | None, *, reason: str | None, actor_id: str, source: str | None = None) -> bool:
    """A person's decision: this item is Issue `issue`, or needs no Issue for `reason`, or neither (clear both)."""
    with get_session() as session:
        item = session.get(ReportItem, item_id)
        if item is None or str(item.email_message_id) != email_id or not item.is_current:
            return False
        if issue:
            picked = next((row for row in (item.issue_suggestions or []) if str(row.get("issue")) == issue), None)
            item.gitlab_issue_external_id = issue
            item.issue_link_source = source or (str(picked["source"]) if picked else "MANUAL")
            item.no_issue_reason = None
        elif reason:
            item.gitlab_issue_external_id = None
            item.issue_link_source = None
            item.no_issue_reason = reason
        else:
            item.gitlab_issue_external_id = None
            item.issue_link_source = None
            item.no_issue_reason = None
        item.progress_evidence = {**(item.progress_evidence or {}), "edited_by_cto": True}
        _audit(session, item, actor_id, "report.item.issue-linked" if issue else "report.item.no-issue" if reason else "report.item.issue-cleared",
               {"issue": issue, "reason": reason, "source": item.issue_link_source})
        session.commit()
        return True


def link_sure(email_id: str, actor_id: str, threshold: float = SURE, project_ids: frozenset[str] | None = None) -> int:
    """Link every unlinked item whose best suggestion is at or above the threshold (only the given projects' items when set)."""
    with get_session() as session:
        query = select(ReportItem).where(
            ReportItem.email_message_id == email_id, ReportItem.is_current.is_(True),
            ReportItem.gitlab_issue_external_id.is_(None), ReportItem.no_issue_reason.is_(None),
        )
        if project_ids is not None:
            query = query.where(ReportItem.project_id.in_(sorted(project_ids)))
        items = session.scalars(query).all()
        linked = 0
        for item in items:
            best = max((row for row in (item.issue_suggestions or [])), key=lambda row: float(row.get("confidence") or 0), default=None)
            if best is None or float(best["confidence"]) < threshold:
                continue
            item.gitlab_issue_external_id = str(best["issue"])
            item.issue_link_source = str(best["source"])
            _audit(session, item, actor_id, "report.item.issue-linked", {"issue": best["issue"], "source": best["source"], "confidence": best["confidence"], "bulk": True})
            linked += 1
        session.commit()
        return linked


def reports_with_unlinked(days: int, project_ids: frozenset[str] | None = None) -> list[str]:
    """Current reports of the last `days` days that still hold delivery items without an Issue or a reason."""
    since = datetime.now(timezone.utc).date() - timedelta(days=days)
    with get_session() as session:
        query = (
            select(EmailMessage.id).distinct()
            .join(ReportItem, ReportItem.email_message_id == EmailMessage.id)
            .where(EmailMessage.is_current.is_(True), EmailMessage.report_date >= since, ReportItem.is_current.is_(True),
                   ReportItem.gitlab_issue_external_id.is_(None), ReportItem.no_issue_reason.is_(None),
                   ReportItem.work_status.in_(DELIVERY_STATUSES))
        )
        if project_ids is not None:
            query = query.where(ReportItem.project_id.in_(sorted(project_ids)))
        return [str(value) for value in session.scalars(query).all()]
