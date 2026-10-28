from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from email import policy
from email.header import decode_header, make_header
from email.message import Message
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
import hashlib
import logging
import re
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import get_session, init_db
from app.models import AuditEvent, EmailMessage, Project, ReportItem, ReportRun, WorkforceMember
from app.modules.projects.service import OTHER_PROJECT_CODE
from app.modules.reports import issue_match
from app.queue.celery_app import celery_app
from app.services.raw_crypto import decrypt, encrypt

logger = logging.getLogger(__name__)


SUBJECT_PATTERN = re.compile(
    r"^DAILY REPORT\s*\|\s*(\d{4}-\d{2}-\d{2})\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$",
    re.IGNORECASE,
)
PROJECT_HEADING = re.compile(
    r"^(?:=+\s*)?(?:DỰ ÁN\s+\d+\s*/\s*\d+\s*:\s*)?([A-Z][A-Z0-9_-]*)\s*\|\s*(.+?)(?:\s*=+)?$",
    re.MULTILINE,
)
COMPACT_TASK = re.compile(
    r"^\[(PLANNED|IN_PROGRESS|PENDING_REVIEW|DONE|BLOCKED|CANCELLED)\]\s*(.*)$",
    re.MULTILINE | re.IGNORECASE,
)
FULL_TASK = re.compile(r"^Nhóm công việc:\s*(.+?)\s*$", re.MULTILINE | re.IGNORECASE)
VALID_STATUSES = {"PLANNED", "IN_PROGRESS", "PENDING_REVIEW", "DONE", "BLOCKED", "CANCELLED"}
PARSE_VERSION = "daily-report-v1"
AI_PARSE_VERSION = "daily-report-ai-v1"
AI_FAILED_PARSE_VERSION = "daily-report-v1-ai-failed"
# Format errors the rule-based parser cannot recover from; mapping errors are not an AI problem.
AI_RESCUE_CODES = {"INVALID_SUBJECT", "INVALID_REPORT_DATE", "PROJECT_SECTION_MISSING", "REPORT_ITEMS_MISSING"}
AI_RESCUE_FAILED_CODE = "REPORT_AI_RESCUE_FAILED"
AI_RESCUE_RETRY_CODE = "REPORT_AI_RESCUE_RETRY"
LOCAL_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
# "[BLOCKED] Vấn đề: Không có" and "[CANCELLED] Công việc: Không có" state that nothing happened.
PLACEHOLDER_TITLE = re.compile(r"^(?:[^:|]{1,40}:\s*)?(?:không có|không|none|n/?a|-+)\.?$", re.IGNORECASE)
REVIEW_CODE = "REPORT_REVIEWED"
DATE_ASSUMED_CODE = "REPORT_DATE_ASSUMED"


def report_codes_of(project: Project) -> list[str]:
    """The other codes a project answers to in reports, normalized the way reported codes are."""
    settings = project.project_settings if isinstance(project.project_settings, dict) else {}
    raw = settings.get("report_codes") or []
    return [re.sub(r"[ _]+", "-", str(code).strip().lower()) for code in raw if str(code).strip()]


def late_cutoff() -> time:
    hour, _, minute = get_settings().report_late_cutoff.partition(":")
    return time(int(hour), int(minute or 0))


def is_late(report_date: date, received_at: datetime) -> bool:
    return received_at.astimezone(LOCAL_TZ) > datetime.combine(report_date, late_cutoff(), tzinfo=LOCAL_TZ)


def review_decision(email: "EmailMessage") -> str | None:
    marker = next((issue for issue in email.parse_errors or [] if issue.get("code") == REVIEW_CODE), None)
    return marker.get("decision") if marker else None


def usable_for_planning(email: "EmailMessage") -> bool:
    """AI-read reports stay out of Planning until the CTO confirms them."""
    return email.parse_version != AI_PARSE_VERSION or review_decision(email) == "CONFIRMED"


@dataclass
class ParseIssue:
    code: str
    severity: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class ParsedReportItem:
    project_code: str
    work_status: str
    title: str
    summary: str
    worked_hours: float | None = None
    remaining_hours: float | None = None
    planned_hours: float | None = None
    progress_percent: int | None = None
    next_step: str | None = None
    gitlab_issue_external_id: str | None = None
    intake_reference: str | None = None
    deadline_text: str | None = None
    dependency: str | None = None
    blocker_detail: str | None = None
    evidence: dict[str, object] = field(default_factory=dict)


@dataclass
class ParsedDailyReport:
    report_date: date | None
    employee_name: str | None
    project_codes: list[str]
    total_hours: float | None
    items: list[ParsedReportItem]
    issues: list[ParseIssue]

    @property
    def status(self) -> str:
        if any(issue.severity == "ERROR" for issue in self.issues):
            return "MALFORMED"
        if self.issues:
            return "WARNING"
        return "VALID"


def _number(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _field(block: str, label: str) -> str | None:
    match = re.search(rf"^{re.escape(label)}:\s*(.+?)\s*$", block, re.MULTILINE | re.IGNORECASE)
    if not match:
        return None
    value = match.group(1).strip()
    return None if value.lower() in {"không có", "không xác định"} else value


def _hours(block: str, planned: bool = False) -> float | None:
    patterns = (
        (r"Thời gian dự kiến:\s*([0-9]+(?:[.,][0-9]+)?)\s*giờ",)
        if planned
        else (
            r"Thời gian(?: thực hiện| đã thực hiện)?\s*:\s*([0-9]+(?:[.,][0-9]+)?)\s*giờ",
            r"\|\s*Thời gian:\s*([0-9]+(?:[.,][0-9]+)?)\s*giờ",
        )
    )
    for pattern in patterns:
        match = re.search(pattern, block, re.IGNORECASE)
        if match:
            return _number(match.group(1))
    return None


def _clean_reference(value: str) -> str | None:
    cleaned = value.strip()
    return None if cleaned.lower() in {"không có", "không xác định"} else cleaned[:512]


def _parse_task(project_code: str, status: str, title: str, block: str) -> ParsedReportItem:
    status = status.upper()
    compact_title = title.split("|", 1)[0].strip() or status.title()
    progress_match = re.search(r"Tiến độ:\s*(\d{1,3})\s*%", block, re.IGNORECASE)
    remaining_match = re.search(
        r"Thời gian còn lại dự kiến:\s*([0-9]+(?:[.,][0-9]+)?)\s*giờ", block, re.IGNORECASE
    )
    gitlab_match = re.search(r"GitLab\s*#\s*([A-Za-z0-9._-]+)", block, re.IGNORECASE)
    if gitlab_match is None:
        # The team also writes "Issue #19: …", "[#8 KIN-26W41-007] …", "#19 …" at the head of the title, or
        # "Issue: https://gitlab…/issues/17" (or /work_items/17); the number alone is the reference.
        gitlab_match = (
            re.search(r"\bIssue\s*#\s*(\d+)\b", block, re.IGNORECASE)
            or re.search(r"\bIssue:\s*\S*/(?:issues|work_items)/(\d+)\b", block, re.IGNORECASE)
            or re.match(r"\s*\[?#(\d+)\b", compact_title)
        )
        if gitlab_match is not None:
            compact_title = re.sub(
                r"^\s*\[?(?:Issue\s*)?#\s*\d+(?:\s+[A-Z]{2,5}-\d{2}W\d{2}-\d{3})?\]?\s*[:\-–]?\s*", "", compact_title, flags=re.IGNORECASE,
            ).strip() or compact_title
    intake_match = re.search(r"Intake:\s*([^|\r\n]+)", block, re.IGNORECASE)
    if intake_match is None:
        # A request code in the title ("[#8 KIN-26W41-007]") names the Intake request too.
        intake_match = re.search(r"\b([A-Z]{2,5}-\d{2}W\d{2}-\d{3})\b", title)
    deadline_match = re.search(r"Deadline/Milestone:\s*([^\r\n]+)", block, re.IGNORECASE)
    dependency_match = re.search(r"Dependency:\s*([^\r\n]+)", block, re.IGNORECASE)
    links = re.findall(r"https://[^\s|]+", block)
    return ParsedReportItem(
        project_code=project_code,
        work_status=status,
        title=compact_title[:512],
        summary=compact_title,
        worked_hours=None if status == "PLANNED" else _hours(block),
        planned_hours=_hours(block, planned=True) if status == "PLANNED" else None,
        remaining_hours=_number(remaining_match.group(1)) if remaining_match else None,
        progress_percent=int(progress_match.group(1)) if progress_match else None,
        next_step=_field(block, "Bước tiếp theo"),
        gitlab_issue_external_id=gitlab_match.group(1) if gitlab_match else None,
        intake_reference=_clean_reference(intake_match.group(1)) if intake_match else None,
        deadline_text=_clean_reference(deadline_match.group(1)) if deadline_match else None,
        dependency=_clean_reference(dependency_match.group(1)) if dependency_match else None,
        blocker_detail=_field(block, "Vấn đề") if status == "BLOCKED" else None,
        evidence={"links": links},
    )


# How far along a status is: the line kept when a task is written twice is the one furthest along.
STATUS_RANK = {"CANCELLED": 0, "PLANNED": 1, "BLOCKED": 2, "IN_PROGRESS": 3, "PENDING_REVIEW": 4, "DONE": 5}


def normalized_task_title(title: str) -> str:
    """The name of a task as a key: case, spacing, list bullets and trailing punctuation do not make two tasks."""
    text = re.sub(r"\s+", " ", (title or "").strip().lstrip("-•*· ").strip()).lower()
    return text.rstrip(".;:,!").strip()


def merge_repeated_tasks(items: list) -> list:
    """A task written twice in one report (today's line and tomorrow's line, or two sections) is one task: the
    line furthest along stays, worked hours add up, the rest fills in from the other line (FR-EML-04)."""
    kept: dict[tuple[str, str], object] = {}
    order: list[tuple[str, str]] = []
    for item in items:
        key = (str(getattr(item, "project_code", "") or "").upper(), normalized_task_title(getattr(item, "title", "")))
        if not key[1]:
            key = (key[0], f"#{id(item)}")
        current = kept.get(key)
        if current is None:
            kept[key] = item
            order.append(key)
            continue
        first, second = (current, item) if STATUS_RANK.get(str(getattr(current, "work_status", "")), 0) >= STATUS_RANK.get(str(getattr(item, "work_status", "")), 0) else (item, current)
        worked = [value for value in (getattr(first, "worked_hours", None), getattr(second, "worked_hours", None)) if value is not None]
        if worked and hasattr(first, "worked_hours"):
            first.worked_hours = round(sum(float(value) for value in worked), 2)
        for name in ("planned_hours", "remaining_hours", "progress_percent"):
            if hasattr(first, name):
                values = [value for value in (getattr(first, name, None), getattr(second, name, None)) if value is not None]
                if values:
                    setattr(first, name, max(values))
        for name in ("next_step", "gitlab_issue_external_id", "gitlab_issue", "intake_reference", "deadline_text", "dependency", "blocker_detail"):
            if hasattr(first, name) and not getattr(first, name, None) and getattr(second, name, None):
                setattr(first, name, getattr(second, name))
        if hasattr(first, "evidence") and isinstance(getattr(first, "evidence", None), dict):
            links = list(dict.fromkeys(list(first.evidence.get("links") or []) + list((getattr(second, "evidence", None) or {}).get("links") or [])))
            if links:
                first.evidence = {**first.evidence, "links": links}
        kept[key] = first
    return [kept[key] for key in order]


def _items_in_project(project_code: str, segment: str) -> list[ParsedReportItem]:
    compact = list(COMPACT_TASK.finditer(segment))
    if compact:
        return [
            _parse_task(
                project_code,
                match.group(1),
                match.group(2),
                segment[match.start():(compact[index + 1].start() if index + 1 < len(compact) else len(segment))],
            )
            for index, match in enumerate(compact)
            if not PLACEHOLDER_TITLE.match(match.group(2).split("|", 1)[0].strip())
        ]
    full = list(FULL_TASK.finditer(segment))
    items: list[ParsedReportItem] = []
    for index, match in enumerate(full):
        end = full[index + 1].start() if index + 1 < len(full) else len(segment)
        block = segment[match.start():end]
        status_match = re.search(r"^Trạng thái:\s*([A-Z_]+)\s*$", block, re.MULTILINE | re.IGNORECASE)
        if PLACEHOLDER_TITLE.match(match.group(1).strip()):
            continue
        if status_match and status_match.group(1).upper() in VALID_STATUSES:
            items.append(_parse_task(project_code, status_match.group(1), match.group(1), block))
    return items


SIGNATURE_DELIMITER = re.compile(r"^--[ \t]*\r?$", re.MULTILINE)
REPORT_CONTENT_AFTER = re.compile(r"^\s*\[[^\]\n]{2,40}\]|^Nhóm công việc:|Tổng thời gian", re.MULTILINE | re.IGNORECASE)


def split_signature(body: str) -> tuple[str, str | None]:
    """Split a report body at the standard "--" signature line.

    The stored email is never changed. A "--" line followed by more report content is not a signature.
    """
    for delimiter in SIGNATURE_DELIMITER.finditer(body):
        rest = body[delimiter.end():]
        if not rest.strip() or PROJECT_HEADING.search(rest) or REPORT_CONTENT_AFTER.search(rest):
            continue
        return body[:delimiter.start()].rstrip(), rest.strip()
    return body, None


def parse_daily_report(subject: str, body: str) -> ParsedDailyReport:
    issues: list[ParseIssue] = []
    subject_match = SUBJECT_PATTERN.match(subject.strip())
    report_date: date | None = None
    employee_name: str | None = None
    project_codes: list[str] = []
    if subject_match:
        try:
            report_date = date.fromisoformat(subject_match.group(1))
        except ValueError:
            issues.append(ParseIssue("INVALID_REPORT_DATE", "ERROR", "Subject report date is invalid"))
        employee_name = subject_match.group(2).strip()
        project_codes = [code.strip().upper() for code in subject_match.group(3).split(",") if code.strip()]
    else:
        issues.append(ParseIssue("INVALID_SUBJECT", "ERROR", "Subject must follow the DAILY REPORT contract"))

    total_match = re.search(
        r"Tổng thời gian(?: làm việc)?\s*:\s*([0-9]+(?:[.,][0-9]+)?)\s*giờ", body, re.IGNORECASE
    )
    total_hours = _number(total_match.group(1)) if total_match else None
    if total_hours is None:
        issues.append(ParseIssue("TOTAL_HOURS_MISSING", "WARNING", "Total worked hours are missing"))

    headings = list(PROJECT_HEADING.finditer(body))
    items: list[ParsedReportItem] = []
    body_codes: list[str] = []
    for index, heading in enumerate(headings):
        code = heading.group(1).upper()
        body_codes.append(code)
        end = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        items.extend(_items_in_project(code, body[heading.end():end]))
    items = merge_repeated_tasks(items)
    if not headings:
        issues.append(ParseIssue("PROJECT_SECTION_MISSING", "ERROR", "No project section was found"))
    if project_codes and set(project_codes) != set(body_codes):
        issues.append(ParseIssue("PROJECT_SCOPE_MISMATCH", "WARNING", "Subject and body project codes differ"))
    if not items:
        issues.append(ParseIssue("REPORT_ITEMS_MISSING", "ERROR", "No work item was parsed"))

    for item in items:
        if item.work_status == "DONE" and item.progress_percent != 100:
            issues.append(ParseIssue("DONE_PROGRESS_INVALID", "WARNING", f"DONE item '{item.title}' must be 100%"))
        if item.work_status in {"DONE", "IN_PROGRESS", "PENDING_REVIEW"} and not item.gitlab_issue_external_id:
            issues.append(ParseIssue("GITLAB_REFERENCE_MISSING", "WARNING", f"Delivery item '{item.title}' has no GitLab Issue"))
    worked_total = sum(item.worked_hours or 0 for item in items)
    if total_hours is not None and abs(worked_total - total_hours) > 0.25:
        issues.append(ParseIssue("TOTAL_HOURS_MISMATCH", "WARNING", "Item hours do not match the report total"))
    return ParsedDailyReport(report_date, employee_name, project_codes, total_hours, items, issues)


class DailyReportService:
    def __init__(self) -> None:
        init_db()

    @staticmethod
    def _resolve_project(session, code: str) -> Project | None:
        # "Acme Web", "acme_web" and "ACME-WEB" all name a sub-area of the same project.
        normalized = re.sub(r"[ _]+", "-", code.strip().lower())
        if normalized == "internal":
            return None
        projects = session.scalars(select(Project).where(Project.status == "ACTIVE")).all()
        pilot = [project for project in projects if project.code.lower() != OTHER_PROJECT_CODE]
        matched = next((project for project in pilot if (
            normalized == project.code.lower()
            or normalized.startswith(f"{project.code.lower()}-")
            or normalized == project.name.lower()
            or normalized.startswith(f"{project.name.lower()}-")
        )), None)
        if matched is None:
            # The codes people write that are not the project's own: "AISE" for the chatbot project, say (FR-EML-12).
            matched = next((project for project in pilot if any(
                normalized == alias or normalized.startswith(f"{alias}-") for alias in report_codes_of(project)
            )), None)
        # Work reported outside the pilot projects is grouped under the catch-all project.
        return matched or next((project for project in projects if project.code.lower() == OTHER_PROJECT_CODE), None)

    def ingest(
        self,
        *,
        mailbox: str,
        uid_validity: str,
        uid: str,
        message_id: str | None,
        sender_address: str,
        sender_name: str | None,
        subject: str,
        body: str,
        received_at: datetime,
    ) -> dict[str, object]:
        parsed = parse_daily_report(subject, body)
        now = datetime.now(timezone.utc)
        received_at = received_at.astimezone(timezone.utc)
        content_hash = hashlib.sha256(f"{subject}\n{body}".encode("utf-8")).hexdigest()
        with get_session() as session:
            existing = session.scalar(select(EmailMessage).where(
                EmailMessage.mailbox == mailbox,
                EmailMessage.uid_validity == uid_validity,
                EmailMessage.uid == uid,
            ))
            if existing is not None:
                return self._email_dict(session, existing, duplicate=True)
            if message_id:
                existing = session.scalar(select(EmailMessage).where(
                    EmailMessage.mailbox == mailbox,
                    EmailMessage.message_id == message_id,
                ).order_by(EmailMessage.received_at.desc()))
                if existing is not None:
                    return self._email_dict(session, existing, duplicate=True)

            member = session.scalar(select(WorkforceMember).where(
                func.lower(WorkforceMember.email_reference) == sender_address.strip().lower(),
                WorkforceMember.status == "ACTIVE",
            ))
            if member is None and parsed.employee_name:
                member = session.scalar(select(WorkforceMember).where(
                    func.lower(WorkforceMember.display_name) == parsed.employee_name.lower(),
                    WorkforceMember.status == "ACTIVE",
                ))
            issues = list(parsed.issues)
            report_date = parsed.report_date
            if report_date is None:
                # A resend can only replace the earlier email when both carry a date.
                report_date = received_at.astimezone(LOCAL_TZ).date()
                issues.append(ParseIssue(DATE_ASSUMED_CODE, "WARNING", "Report date was not found; the received date is used"))
            if member is None:
                issues.append(ParseIssue("REPORT_MEMBER_UNMAPPED", "ERROR", "Sender is not mapped to an active workforce member"))

            resolved_projects: dict[str, Project | None] = {}
            for code in parsed.project_codes:
                project = self._resolve_project(session, code)
                resolved_projects[code] = project
                if project is None and code != "INTERNAL":
                    issues.append(ParseIssue("REPORT_PROJECT_UNMAPPED", "ERROR", f"Project code '{code}' is not mapped"))
            previous = None
            revision = 1
            if member is not None:
                previous = session.scalar(select(EmailMessage).where(
                    EmailMessage.member_id == member.id,
                    EmailMessage.report_date == report_date,
                    EmailMessage.is_current.is_(True),
                ).order_by(EmailMessage.revision.desc()))
                if previous is not None:
                    revision = previous.revision + 1
                    previous.is_current = False
                    session.execute(update(ReportItem).where(
                        ReportItem.email_message_id == previous.id,
                    ).values(is_current=False))

            late = is_late(report_date, received_at)
            status = "MALFORMED" if any(issue.severity == "ERROR" for issue in issues) else (
                "WARNING" if issues else "VALID"
            )
            unique_projects = {str(project.id) for project in resolved_projects.values() if project is not None}
            email_row = EmailMessage(
                id=str(uuid4()),
                project_id=next(iter(unique_projects)) if len(unique_projects) == 1 else None,
                member_id=str(member.id) if member else None,
                supersedes_email_id=str(previous.id) if previous else None,
                mailbox=mailbox, uid_validity=uid_validity, uid=uid, message_id=message_id,
                sender_address=sender_address.strip().lower(), sender_name=sender_name,
                report_date=report_date, subject_ciphertext=encrypt(subject), body_ciphertext=encrypt(body),
                content_hash=content_hash,
                parsed_summary=f"{len(parsed.items)} items; {len(issues)} issues",
                parse_version=PARSE_VERSION, parse_errors=[issue.as_dict() for issue in issues], status=status,
                revision=revision, is_current=True, is_late=late, received_at=received_at,
                purge_after=now + timedelta(days=get_settings().raw_retention_days), created_at=now,
            )
            session.add(email_row)
            session.flush()
            for position, item in enumerate(parsed.items):
                # Body sections may use a code the subject does not list (ACME vs ACME-WEB).
                if item.project_code not in resolved_projects:
                    resolved_projects[item.project_code] = self._resolve_project(session, item.project_code)
                project = resolved_projects[item.project_code]
                session.add(ReportItem(
                    id=str(uuid4()), report_run_id=None, email_message_id=email_row.id, intake_id=None,
                    project_id=str(project.id) if project else None, member_id=str(member.id) if member else None,
                    source_type="EMAIL", source_reference=message_id or f"imap:{uid_validity}:{uid}",
                    category="PLAN" if item.work_status == "PLANNED" else "DELIVERY",
                    work_status=item.work_status, title=item.title, summary=item.summary,
                    worked_hours=item.worked_hours, remaining_hours=item.remaining_hours,
                    planned_hours=item.planned_hours, progress_percent=item.progress_percent,
                    next_step=item.next_step, gitlab_issue_external_id=item.gitlab_issue_external_id,
                    plane_reference=None, intake_reference=item.intake_reference,
                    deadline_text=item.deadline_text, dependency=item.dependency,
                    progress_evidence={**item.evidence, "reported_project_code": item.project_code},
                    blocker=item.work_status == "BLOCKED",
                    blocker_detail=item.blocker_detail, revision=revision, is_current=True,
                    created_at=now + timedelta(microseconds=position),
                ))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                existing = session.scalar(select(EmailMessage).where(
                    EmailMessage.mailbox == mailbox,
                    EmailMessage.uid_validity == uid_validity,
                    EmailMessage.uid == uid,
                ))
                if existing is None:
                    raise
                return self._email_dict(session, existing, duplicate=True)
            email_id = str(email_row.id)
        self.suggest_issues(email_id)
        with get_session() as session:
            return self._email_dict(session, session.get(EmailMessage, email_id), duplicate=False)

    @staticmethod
    def suggest_issues(email_id: str, *, ask_ai: bool = True) -> dict[str, object]:
        """Find the Issue behind each unlinked item (FR-RPT-07): the rules now, AI later for what they could not place.
        A failure here must never lose the report, so it only logs."""
        try:
            outcome = issue_match.suggest_for_report(email_id)
        except Exception as exc:  # noqa: BLE001 - the report is already saved; a matching fault is not a reason to fail it
            logger.warning("issue suggestions failed for report %s: %s", email_id, exc)
            return {"items": 0, "linked": 0, "suggested": 0, "for_ai": [], "error": type(exc).__name__}
        try:
            from app.modules.planning import acceptance  # late import: acceptance reads reports, reports must not import it at load
            acceptance.collect()
        except Exception as exc:  # noqa: BLE001 - acceptance can be collected later by the morning job
            logger.warning("acceptance collect after report %s failed: %s", email_id, exc)
        if ask_ai and outcome["for_ai"]:
            try:
                celery_app.send_task("intake.reports.issue-suggest", args=[email_id, outcome["for_ai"]], queue="ai.normalize")
                outcome["ai_queued"] = True
            except Exception as exc:  # noqa: BLE001 - no broker (tests, a worker down) only means no AI suggestions
                logger.warning("could not queue AI issue suggestions for report %s: %s", email_id, exc)
                outcome["ai_queued"] = False
        return outcome

    def known_uids(self, mailbox: str, uid_validity: str) -> set[str]:
        with get_session() as session:
            return set(session.scalars(select(EmailMessage.uid).where(
                EmailMessage.mailbox == mailbox, EmailMessage.uid_validity == uid_validity,
            )).all())

    def record_ai_rescue_attempt(self, email_id: str, code: str, max_attempts: int) -> bool:
        """Count a transient AI failure. Returns True when the attempt budget is exhausted."""
        with get_session() as session:
            row = session.get(EmailMessage, email_id)
            if row is None or row.parse_version != PARSE_VERSION:
                return True
            previous = next((issue for issue in row.parse_errors or [] if issue.get("code") == AI_RESCUE_RETRY_CODE), None)
            attempts = int(previous.get("attempts", 0)) + 1 if previous else 1
            if attempts < max(max_attempts, 1):
                issues = [issue for issue in row.parse_errors or [] if issue.get("code") != AI_RESCUE_RETRY_CODE]
                issues.append({
                    "code": AI_RESCUE_RETRY_CODE, "severity": "WARNING", "attempts": attempts,
                    "message": f"AI extraction failed ({code}); it will be retried at the next scan",
                })
                row.parse_errors = issues
                session.commit()
                return False
        self.record_ai_rescue_failure(email_id, code)
        return True

    def pending_ai_rescues(self, limit: int = 10) -> list[str]:
        with get_session() as session:
            rows = session.scalars(select(EmailMessage).where(
                EmailMessage.status == "MALFORMED",
                EmailMessage.parse_version == PARSE_VERSION,
                EmailMessage.is_current.is_(True),
                EmailMessage.purged_at.is_(None),
            ).order_by(EmailMessage.received_at)).all()
            eligible = [
                str(row.id) for row in rows
                if any(issue.get("code") in AI_RESCUE_CODES for issue in row.parse_errors or [])
            ]
            return eligible[:max(limit, 0)]

    def ai_rescue_source(self, email_id: str) -> str | None:
        with get_session() as session:
            row = session.get(EmailMessage, email_id)
            if (
                row is None or row.parse_version != PARSE_VERSION or row.status != "MALFORMED"
                or not row.is_current or row.purged_at is not None
            ):
                return None
            # The signature holds personal contact details and is not needed to read the report.
            content, _ = split_signature(decrypt(row.body_ciphertext) or "")
            return f"Subject: {decrypt(row.subject_ciphertext) or ''}\n\n{content}"

    def apply_ai_rescue(self, email_id: str, extraction, *, provider: str, model: str) -> dict[str, object] | None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.get(EmailMessage, email_id)
            if row is None or row.parse_version != PARSE_VERSION or row.status != "MALFORMED" or not row.is_current:
                return None
            issues = [
                {**issue, "severity": "WARNING"} if issue.get("code") in AI_RESCUE_CODES else issue
                for issue in row.parse_errors or []
                if issue.get("code") not in {"REPORT_PROJECT_UNMAPPED", AI_RESCUE_FAILED_CODE, AI_RESCUE_RETRY_CODE}
            ]
            issues.append({
                "code": "REPORT_AI_PARSED", "severity": "WARNING",
                "message": f"Work items were extracted by AI ({provider}/{model}); CTO review is required",
            })

            if row.member_id is None and extraction.employee_name:
                member = session.scalar(select(WorkforceMember).where(
                    func.lower(WorkforceMember.display_name) == extraction.employee_name.strip().lower(),
                    WorkforceMember.status == "ACTIVE",
                ))
                if member is not None:
                    row.member_id = str(member.id)
                    issues = [issue for issue in issues if issue.get("code") != "REPORT_MEMBER_UNMAPPED"]

            assumed = any(issue.get("code") == DATE_ASSUMED_CODE for issue in issues)
            date_changed = bool(
                extraction.report_date is not None and extraction.report_date != row.report_date
                and (row.report_date is None or (assumed and row.supersedes_email_id is None))
            )
            if date_changed:
                row.report_date = extraction.report_date
                row.is_late = is_late(extraction.report_date, row.received_at)
            if extraction.report_date is not None and extraction.report_date == row.report_date:
                issues = [issue for issue in issues if issue.get("code") != DATE_ASSUMED_CODE]
            superseded_by_newer = False
            if date_changed and row.member_id is not None:
                other = session.scalar(select(EmailMessage).where(
                    EmailMessage.member_id == row.member_id,
                    EmailMessage.report_date == row.report_date,
                    EmailMessage.is_current.is_(True),
                    EmailMessage.id != row.id,
                ).order_by(EmailMessage.revision.desc()))
                if other is not None and other.received_at > row.received_at:
                    # A later email for the same day already exists; this one becomes history.
                    superseded_by_newer = True
                    other.supersedes_email_id = str(row.id)
                    row.is_current = False
                elif other is not None:
                    other.is_current = False
                    session.execute(update(ReportItem).where(
                        ReportItem.email_message_id == other.id,
                    ).values(is_current=False))
                    row.supersedes_email_id = str(other.id)
                    row.revision = other.revision + 1

            session.execute(update(ReportItem).where(
                ReportItem.email_message_id == row.id,
            ).values(is_current=False))
            project_ids: set[str] = set()
            unmapped: set[str] = set()
            for position, item in enumerate(merge_repeated_tasks(list(extraction.items))):
                project = self._resolve_project(session, item.project_code)
                if project is None and item.project_code.strip().lower() != "internal":
                    unmapped.add(item.project_code.strip())
                if project is not None:
                    project_ids.add(str(project.id))
                session.add(ReportItem(
                    id=str(uuid4()), report_run_id=None, email_message_id=row.id, intake_id=None,
                    project_id=str(project.id) if project else None, member_id=row.member_id,
                    source_type="EMAIL", source_reference=row.message_id or f"imap:{row.uid_validity}:{row.uid}",
                    category="PLAN" if item.work_status == "PLANNED" else "DELIVERY",
                    work_status=item.work_status, title=item.title.strip(), summary=item.title.strip(),
                    worked_hours=item.worked_hours, remaining_hours=None, planned_hours=item.planned_hours,
                    progress_percent=item.progress_percent, next_step=item.next_step,
                    gitlab_issue_external_id=item.gitlab_issue, intake_reference=None,
                    deadline_text=None, dependency=None,
                    progress_evidence={
                        "parsed_by": "AI", "provider": provider, "model": model,
                        "reported_project_code": item.project_code.strip(),
                    },
                    blocker=item.work_status == "BLOCKED", blocker_detail=item.blocker_detail,
                    revision=row.revision, is_current=not superseded_by_newer,
                    created_at=now + timedelta(microseconds=position),
                ))
            for code in sorted(unmapped):
                issues.append({
                    "code": "REPORT_PROJECT_UNMAPPED", "severity": "ERROR",
                    "message": f"Project code '{code}' is not mapped",
                })
            if len(project_ids) == 1:
                row.project_id = next(iter(project_ids))
            row.parse_version = AI_PARSE_VERSION
            row.parse_errors = issues
            row.parsed_summary = f"{len(extraction.items)} items by AI; {len(issues)} issues"
            row.status = "MALFORMED" if any(issue.get("severity") == "ERROR" for issue in issues) else "WARNING"
            session.commit()
        self.suggest_issues(email_id)
        with get_session() as session:
            return self._email_dict(session, session.get(EmailMessage, email_id), duplicate=False)

    def record_ai_rescue_failure(self, email_id: str, code: str) -> None:
        with get_session() as session:
            row = session.get(EmailMessage, email_id)
            if row is None or row.parse_version != PARSE_VERSION:
                return
            issues = [
                issue for issue in row.parse_errors or []
                if issue.get("code") not in {AI_RESCUE_FAILED_CODE, AI_RESCUE_RETRY_CODE}
            ]
            issues.append({
                "code": AI_RESCUE_FAILED_CODE, "severity": "WARNING",
                "message": f"AI could not extract this report ({code}); manual review is required",
            })
            row.parse_errors = issues
            row.parse_version = AI_FAILED_PARSE_VERSION
            session.commit()

    def ingest_rfc822(self, *, mailbox: str, uid_validity: str, uid: str, raw_message: bytes) -> dict[str, object]:
        message = BytesParser(policy=policy.default).parsebytes(raw_message)
        sender_name, sender_address = parseaddr(str(message.get("From", "")))
        subject = str(make_header(decode_header(str(message.get("Subject", "")))))
        return self.ingest(
            mailbox=mailbox, uid_validity=uid_validity, uid=uid,
            message_id=str(message.get("Message-ID")) if message.get("Message-ID") else None,
            sender_address=sender_address, sender_name=sender_name or None,
            subject=subject, body=_plain_body(message), received_at=_received_at(message),
        )

    def list_reports(self, *, report_date: date | None = None, member_id: str | None = None, allowed_project_ids: frozenset[str] | None = None) -> list[dict[str, object]]:
        with get_session() as session:
            query = select(EmailMessage).where(EmailMessage.is_current.is_(True))
            if report_date:
                query = query.where(EmailMessage.report_date == report_date)
            if member_id:
                query = query.where(EmailMessage.member_id == member_id)
            rows = session.scalars(query.order_by(EmailMessage.report_date.desc(), EmailMessage.received_at.desc())).all()
            return [self._email_dict(session, row, duplicate=False, allowed_project_ids=allowed_project_ids) for row in rows]

    @staticmethod
    def _other_project_id(session) -> str | None:
        project = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
        return str(project.id) if project is not None else None

    @classmethod
    def _item_visible(cls, item: ReportItem, allowed_project_ids: frozenset[str] | None, other_id: str | None) -> bool:
        """A Project Owner sees the items of their projects, and the ones with no project at all (to take them);
        work grouped under the catch-all "other" project belongs to nobody's team and stays with the CTO, who
        routes it to a project or gives that project a report code (FR-ID-08, since 2026-10-15)."""
        del other_id
        if allowed_project_ids is None:
            return True
        if item.project_id is None:
            return True
        return str(item.project_id) in allowed_project_ids

    def item_project(self, email_id: str, item_id: str) -> tuple[bool, str | None] | None:
        """(exists, project_id) of one item of one report."""
        with get_session() as session:
            item = session.get(ReportItem, item_id)
            if item is None or str(item.email_message_id) != email_id or not item.is_current:
                return None
            return True, str(item.project_id) if item.project_id else None

    def item_visible(self, email_id: str, item_id: str, allowed_project_ids: frozenset[str] | None) -> bool:
        with get_session() as session:
            item = session.get(ReportItem, item_id)
            if item is None or str(item.email_message_id) != email_id or not item.is_current:
                return False
            return self._item_visible(item, allowed_project_ids, self._other_project_id(session))

    def report_detail(self, email_id: str, allowed_project_ids: frozenset[str] | None = None) -> dict[str, object] | None:
        with get_session() as session:
            row = session.get(EmailMessage, email_id)
            if row is None:
                return None
            projects = {str(project.id): project.name for project in session.scalars(select(Project)).all()}
            other_id = self._other_project_id(session)
            items = [item for item in session.scalars(select(ReportItem).where(
                ReportItem.email_message_id == row.id, ReportItem.is_current.is_(True),
            ).order_by(ReportItem.created_at, ReportItem.id)).all() if self._item_visible(item, allowed_project_ids, other_id)]
            return {
                **self._email_dict(session, row, duplicate=False, allowed_project_ids=allowed_project_ids),
                "items": [{
                    "id": str(item.id), "project_name": projects.get(str(item.project_id)) if item.project_id else None,
                    "reported_project_code": (item.progress_evidence or {}).get("reported_project_code"),
                    "work_status": item.work_status, "title": item.title,
                    "worked_hours": float(item.worked_hours) if item.worked_hours is not None else None,
                    "planned_hours": float(item.planned_hours) if item.planned_hours is not None else None,
                    "progress_percent": item.progress_percent, "gitlab_issue": item.gitlab_issue_external_id,
                    "next_step": item.next_step, "blocker_detail": item.blocker_detail,
                    "parsed_by": "AI" if (item.progress_evidence or {}).get("parsed_by") == "AI" else "RULES",
                    "edited": bool((item.progress_evidence or {}).get("edited_by_cto")),
                    "issue_suggestions": item.issue_suggestions or [],
                    "issue_link_source": item.issue_link_source, "no_issue_reason": item.no_issue_reason,
                } for item in items],
            }

    def report_source(self, email_id: str, actor_id: str) -> dict[str, object] | None:
        with get_session() as session:
            row = session.get(EmailMessage, email_id)
            if row is None:
                return None
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id,
                event_type="report.raw.read", entity_type="email_message", entity_id=row.id,
                details=None, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
            body = decrypt(row.body_ciphertext)
            content, signature = split_signature(body) if body else (body, None)
            return {
                "id": str(row.id), "purged": row.purged_at is not None,
                "subject": decrypt(row.subject_ciphertext), "body": content, "signature": signature,
            }

    def review_report(self, email_id: str, decision: str, actor_id: str) -> dict[str, object] | None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.get(EmailMessage, email_id)
            if row is None:
                return None
            issues = [issue for issue in row.parse_errors or [] if issue.get("code") != REVIEW_CODE]
            issues.append({
                "code": REVIEW_CODE, "severity": "INFO", "decision": decision, "reviewed_at": now.isoformat(),
                "message": "CTO confirmed the extracted items" if decision == "CONFIRMED" else "CTO rejected the extracted items",
            })
            row.parse_errors = issues
            if decision == "REJECTED":
                # Rejected items must not reach snapshots or Planning; the email itself stays for the record.
                session.execute(update(ReportItem).where(
                    ReportItem.email_message_id == row.id,
                ).values(is_current=False))
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id,
                event_type="report.reviewed", entity_type="email_message", entity_id=row.id,
                details={"decision": decision}, created_at=now,
            ))
            session.commit()
        return self.report_detail(email_id)

    def update_item(self, email_id: str, item_id: str, changes: dict[str, object], actor_id: str) -> dict[str, object] | None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            item = session.get(ReportItem, item_id)
            if item is None or str(item.email_message_id) != email_id or not item.is_current:
                return None
            if "project_code" in changes:
                code = changes.pop("project_code")
                project = session.scalar(select(Project).where(Project.code == code, Project.status == "ACTIVE")) if code else None
                if code and project is None:
                    raise ValueError("PROJECT_NOT_ACTIVE")
                item.project_id = str(project.id) if project else None
            if "gitlab_issue" in changes:
                issue = changes.pop("gitlab_issue")
                if issue != item.gitlab_issue_external_id:
                    item.issue_link_source = "MANUAL" if issue else None
                item.gitlab_issue_external_id = issue
                if issue:
                    item.no_issue_reason = None
            for field_name, value in changes.items():
                setattr(item, field_name, value)
            if "title" in changes:
                item.summary = item.title
            item.blocker = item.work_status == "BLOCKED"
            item.category = "PLAN" if item.work_status == "PLANNED" else "DELIVERY"
            item.progress_evidence = {**(item.progress_evidence or {}), "edited_by_cto": True}
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id,
                event_type="report.item.updated", entity_type="report_item", entity_id=item.id,
                details={"fields": sorted(changes) }, created_at=now,
            ))
            session.commit()
        return self.report_detail(email_id)

    def remove_item(self, email_id: str, item_id: str, actor_id: str) -> dict[str, object] | None:
        with get_session() as session:
            item = session.get(ReportItem, item_id)
            if item is None or str(item.email_message_id) != email_id or not item.is_current:
                return None
            item.is_current = False
            session.add(AuditEvent(
                id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id,
                event_type="report.item.removed", entity_type="report_item", entity_id=item.id,
                details=None, created_at=datetime.now(timezone.utc),
            ))
            session.commit()
        return self.report_detail(email_id)

    def create_snapshot(self, report_date: date) -> dict[str, object]:
        period_start = datetime.combine(report_date, time.min, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        period_end = datetime.combine(report_date, time.max, tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        with get_session() as session:
            existing = session.scalar(select(ReportRun).where(
                ReportRun.kind == "DAILY_REPORT_ALL",
                ReportRun.period_start == period_start,
                ReportRun.period_end == period_end,
            ).order_by(ReportRun.created_at.desc()))
            if existing is not None:
                return self._snapshot_dict(session, existing, duplicate=True)
            run = ReportRun(
                id=str(uuid4()), project_id=None, kind="DAILY_REPORT_ALL",
                period_start=period_start, period_end=period_end, snapshot_at=now,
                status="FINAL", created_at=now,
            )
            session.add(run)
            session.flush()
            email_ids = [str(email.id) for email in session.scalars(select(EmailMessage).where(
                EmailMessage.report_date == report_date,
                EmailMessage.is_current.is_(True),
            )).all() if usable_for_planning(email)]
            if email_ids:
                session.execute(update(ReportItem).where(
                    ReportItem.email_message_id.in_(email_ids),
                    ReportItem.is_current.is_(True),
                ).values(report_run_id=run.id))
            session.commit()
            return self._snapshot_dict(session, run, duplicate=False)

    @staticmethod
    def _snapshot_dict(session, run: ReportRun, *, duplicate: bool) -> dict[str, object]:
        item_count = session.scalar(select(func.count()).select_from(ReportItem).where(
            ReportItem.report_run_id == run.id,
        )) or 0
        return {
            "id": str(run.id), "kind": run.kind, "status": run.status,
            "period_start": run.period_start.isoformat(), "period_end": run.period_end.isoformat(),
            "snapshot_at": run.snapshot_at.isoformat(), "item_count": int(item_count), "duplicate": duplicate,
        }

    @staticmethod
    def _email_dict(session, row: EmailMessage, *, duplicate: bool, allowed_project_ids: frozenset[str] | None = None) -> dict[str, object]:
        items = session.scalars(select(ReportItem).where(ReportItem.email_message_id == row.id, ReportItem.is_current.is_(True))).all()
        other_id = DailyReportService._other_project_id(session) if allowed_project_ids is not None else None
        visible = [item for item in items if DailyReportService._item_visible(item, allowed_project_ids, other_id)]
        item_count = len(visible)
        hidden = len(items) - len(visible)
        unlinked = sum(1 for item in visible if not item.gitlab_issue_external_id and not item.no_issue_reason and item.work_status in issue_match.DELIVERY_STATUSES)
        # Confirming or rejecting an email decides for every project in it: a Project Owner may only when it is all theirs.
        can_review = allowed_project_ids is None or all(item.project_id is not None and str(item.project_id) in allowed_project_ids for item in items)
        member = session.get(WorkforceMember, row.member_id) if row.member_id else None
        return {
            "member_name": member.display_name if member else None, "sender_address": row.sender_address,
            "parsed_by": "AI" if row.parse_version == AI_PARSE_VERSION else "RULES",
            "review_decision": review_decision(row),
            "usable_for_planning": usable_for_planning(row),
            "id": str(row.id), "member_id": str(row.member_id) if row.member_id else None,
            "report_date": row.report_date, "status": row.status, "revision": row.revision,
            "is_current": row.is_current, "is_late": row.is_late, "received_at": row.received_at,
            "item_count": int(item_count), "unlinked_items": int(unlinked), "hidden_items": int(hidden), "can_review": bool(can_review),
            "issues": row.parse_errors or [], "duplicate": duplicate,
        }


def _received_at(message: Message) -> datetime:
    try:
        value = parsedate_to_datetime(str(message.get("Date", "")))
        if value.tzinfo is None:
            value = value.replace(tzinfo=LOCAL_TZ)
        return value.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return datetime.now(timezone.utc)


def _plain_body(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            if part.get_content_type() == "text/plain" and part.get_content_disposition() != "attachment":
                return str(part.get_content())
        return ""
    return str(message.get_content()) if message.get_content_type() == "text/plain" else ""


daily_report_service = DailyReportService()
