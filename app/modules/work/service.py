"""Work tracked inside Intake instead of an external board (FR-WRK-01..06, ADR-0066).

A work item is what Plane used to hold: non-code work for a content or operations project, or a feature that the
owner and the team must discuss before anyone writes code. It moves across six columns (Cần bàn, Sẵn sàng, Đang
làm, Chờ nghiệm thu, Xong, Bỏ), carries a discussion, and can be turned into a delivery Issue through the normal
approval and sync path. Every move is an audit event; the item's history is read back from those events.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import get_session
from app.models import AuditEvent, IntakeItem, Meeting, MeetingNoteItem, Project, ProjectIntegration, User, WorkChannel, WorkComment, WorkforceMember, WorkforceProjectMembership, WorkItem, WorkLink
from app.modules.work.channels import CHANNEL_CODES, FORMAT_OF_CHANNEL, FORMATS
from app.modules.work.links import links_of
from app.services.raw_crypto import decrypt, encrypt

# APPROVED is "Đã duyệt, chờ đăng" on a marketing board (FR-MKT-01); the software board never shows it.
STATUSES = ("DISCUSS", "READY", "IN_PROGRESS", "ACCEPTANCE", "APPROVED", "DONE", "CANCELLED")
OPEN_STATUSES = ("DISCUSS", "READY", "IN_PROGRESS", "ACCEPTANCE", "APPROVED")
CHANNEL_STATUSES = ("DRAFT", "READY", "PUBLISHED")
MAX_CAMPAIGN = 80
# The columns a Developer may move their own work between: the doing part, not the deciding part.
# A person doing the work may pick it up from Ý tưởng or Sẵn sàng, work on it and hand it in; deciding is the owner's.
DOER_STATUSES = ("DISCUSS", "READY", "IN_PROGRESS", "ACCEPTANCE")
PRIORITIES = ("P0", "P1", "P2", "P3")
DELIVERY_SYSTEMS = ("GITLAB", "GITHUB")
MAX_TITLE = 255
MAX_DESCRIPTION = 20000
# The words of one channel version: long enough for a blog post or the long form of X (25,000).
MAX_CHANNEL_TEXT = 60000
MAX_COMMENT = 5000
MAX_NOTE = 500
MAX_LINK_NOTE = 300
MAX_URL = 1000
MAX_LINKS = 40
HISTORY_LIMIT = 50
CLOSED_WINDOW_DAYS = 30
# Pipelines (FR-WRK-08): the steps a template makes, in order; the last ones need a link (or a reason) before Xong.
TEMPLATES: dict[str, dict[str, object]] = {
    "VIDEO": {"label": "Video", "steps": [
        ("BRIEF", "Brief", False), ("SCRIPT", "Kịch bản", False), ("SHOOT", "Quay", False),
        ("EDIT", "Dựng", False), ("REVIEW", "Duyệt", True), ("PUBLISH", "Đăng", True),
    ]},
}
STEP_LABELS = {code: label for spec in TEMPLATES.values() for code, label, _ in spec["steps"]}


class WorkError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware_utc(value: datetime | None) -> datetime | None:
    """SQLite returns timezone columns as naive UTC values; keep API timestamps unambiguous."""
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def _clean_line(value: str | None, limit: int) -> str:
    return " ".join((value or "").split())[:limit]


def _clean_text(value: str | None, limit: int) -> str:
    return (value or "").strip()[:limit]


class WorkService:
    # --- creating and reading -------------------------------------------------------------------------

    def create(self, *, project_id: str, title: str, description: str | None, priority: str, member_id: str | None,
               due_date: date | None, status: str = "DISCUSS", intake_id: str | None = None, actor_id: str | None,
               actor_type: str = "USER", template: str | None = None, channel: str | None = None, format: str | None = None,
               campaign: str | None = None, urgent: bool = False, channels: list[dict] | None = None) -> dict[str, object]:
        if template is not None and template not in TEMPLATES:
            raise WorkError("TEMPLATE_UNKNOWN", "Unknown template")
        channels = self._clean_channels(channels)
        channel = channel or (channels[0]["channel"] if channels else None)
        if channel is not None and channel not in CHANNEL_CODES:
            raise WorkError("CHANNEL_UNKNOWN", "Unknown channel")
        format = format or (FORMAT_OF_CHANNEL.get(channel or "") if channel else None) or ("POST" if channel else None)
        if format is not None and format not in FORMATS:
            raise WorkError("FORMAT_UNKNOWN", "Unknown format")
        campaign = _clean_line(campaign, MAX_CAMPAIGN) or None
        clean_title = _clean_line(title, MAX_TITLE)
        if not clean_title:
            raise WorkError("TITLE_REQUIRED", "Give the work a title")
        if priority not in PRIORITIES:
            raise WorkError("PRIORITY_INVALID", "Priority must be P0 to P3")
        if status not in OPEN_STATUSES:
            raise WorkError("STATUS_INVALID", "New work starts in an open column")
        with get_session() as session:
            project = session.get(Project, project_id)
            if project is None or project.status != "ACTIVE":
                raise KeyError(project_id)
            if member_id:
                self._check_member(session, project.id, member_id)
            row = self._insert(session, project, title=clean_title, description=_clean_text(description, MAX_DESCRIPTION),
                               priority=priority, member_id=member_id, due_date=due_date, status=status, intake_id=intake_id, actor_id=actor_id,
                               actor_type=actor_type)
            row.channel, row.format, row.campaign, row.urgent = channel, format, campaign, bool(urgent)
            for spec in channels:
                session.add(WorkChannel(id=str(uuid4()), work_id=row.id, channel=spec["channel"], publish_at=spec.get("publish_at"), status="DRAFT",
                                        language=spec.get("language"), created_at=row.created_at, updated_at=row.created_at))
            if template:
                row.template = template
                for order, (code, label, needs_evidence) in enumerate(TEMPLATES[template]["steps"], start=1):
                    child = self._insert(session, project, title=f"{clean_title} · {label}", description="", priority=priority, member_id=None,
                                         due_date=None, status="READY", intake_id=None, actor_id=actor_id, actor_type=actor_type)
                    child.parent_id, child.step, child.step_order, child.evidence_required = row.id, code, order, needs_evidence
            session.commit()
            return self._dict(session, row)

    def _insert(self, session, project: Project, *, title: str, description: str, priority: str, member_id: str | None,
                due_date: date | None, status: str, intake_id: str | None, actor_id: str | None, actor_type: str = "USER") -> WorkItem:
        """One row with the next number of the project; a clash with a parallel insert is retried."""
        now = _now()
        for _attempt in range(3):
            seq = int(session.scalar(select(func.max(WorkItem.seq)).where(WorkItem.project_id == project.id)) or 0) + 1
            row = WorkItem(
                id=str(uuid4()), project_id=project.id, seq=seq, code=f"{project.intake_key}-W-{seq}", title=title,
                description_ciphertext=encrypt(description) if description else None, status=status, priority=priority,
                member_id=member_id, due_date=due_date, intake_id=intake_id, created_by=actor_id, version=1,
                created_at=now, updated_at=now,
            )
            try:
                # A savepoint: a clash only undoes this row, not the approval the caller may be in the middle of.
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                continue
            session.add(AuditEvent(
                id=str(uuid4()), project_id=project.id, actor_type=actor_type, actor_id=actor_id or "system", event_type="work.created",
                entity_type="work", entity_id=row.id, details={"code": row.code, "status": status, "priority": priority, "intake_id": intake_id},
                created_at=now,
            ))
            return row
        raise WorkError("CODE_CLASH", "Could not number the work item; try again")

    def list(self, *, project_id: str, include_closed: bool = False, week_start: date | None = None) -> list[dict[str, object]]:
        with get_session() as session:
            query = select(WorkItem).where(WorkItem.project_id == project_id)
            if not include_closed:
                since = _now() - timedelta(days=CLOSED_WINDOW_DAYS)
                query = query.where((WorkItem.status.in_(OPEN_STATUSES)) | (WorkItem.closed_at >= since))
            rows = list(session.scalars(query.order_by(WorkItem.updated_at.desc())).all())
            if week_start is not None:
                # Tuần này: whatever publishes in that week belongs on the grid, however old or closed the post is.
                start = datetime(week_start.year, week_start.month, week_start.day, tzinfo=timezone.utc) - timedelta(hours=14)
                end = start + timedelta(days=8)
                seen = {row.id for row in rows}
                rows += [row for row in session.scalars(
                    select(WorkItem).join(WorkChannel, WorkChannel.work_id == WorkItem.id)
                    .where(WorkItem.project_id == project_id, WorkChannel.publish_at >= start, WorkChannel.publish_at < end)
                ).all() if row.id not in seen]
            # Every step of a parent on the board comes with it, whatever column the step is in.
            parent_ids = [row.id for row in rows if row.template]
            if parent_ids:
                seen = {row.id for row in rows}
                rows += [row for row in session.scalars(select(WorkItem).where(WorkItem.parent_id.in_(parent_ids))).all() if row.id not in seen]
            ids = [row.id for row in rows]
            counts = dict(session.execute(select(WorkComment.work_id, func.count()).where(WorkComment.work_id.in_(ids)).group_by(WorkComment.work_id)).all()) if rows else {}
            links = dict(session.execute(select(WorkLink.work_id, func.count()).where(WorkLink.work_id.in_(ids)).group_by(WorkLink.work_id)).all()) if rows else {}
            return [self._dict(session, row, comment_count=int(counts.get(row.id, 0)), link_count=int(links.get(row.id, 0))) for row in rows]

    def waiting_review(self, *, allowed_project_ids: frozenset[str] | None) -> list[dict[str, object]]:
        """Posts in Chờ duyệt across the caller's projects, oldest wait first (FR-MKT-05)."""
        with get_session() as session:
            query = select(WorkItem).where(WorkItem.status == "ACCEPTANCE", WorkItem.parent_id.is_(None))
            if allowed_project_ids is not None:
                query = query.where(WorkItem.project_id.in_(list(allowed_project_ids)))
            rows = session.scalars(query.order_by(WorkItem.updated_at)).all()
            return [self._dict(session, row) for row in rows]

    def campaigns(self, project_id: str) -> list[dict[str, object]]:
        """The labels in use on a project and how many posts carry each."""
        with get_session() as session:
            rows = session.execute(
                select(WorkItem.campaign, func.count()).where(WorkItem.project_id == project_id, WorkItem.campaign.is_not(None))
                .group_by(WorkItem.campaign).order_by(func.count().desc())
            ).all()
            return [{"name": name, "count": int(count)} for name, count in rows]

    def bulk_create(self, *, project_id: str, rows: list[dict], actor_id: str) -> list[dict[str, object]]:
        """Thêm nhiều bài: one line, one post; a line that cannot be made is reported, the others still are."""
        out: list[dict[str, object]] = []
        for spec in rows[:50]:
            try:
                made = self.create(
                    project_id=project_id, title=str(spec.get("title") or ""), description=spec.get("description"), priority="P3",
                    member_id=spec.get("member_id"), due_date=None, status="DISCUSS", actor_id=actor_id, campaign=spec.get("campaign"),
                    channels=[{"channel": spec.get("channel"), "publish_at": spec.get("publish_at")}] if spec.get("channel") else None,
                )
                out.append({"title": spec.get("title"), "id": made["id"], "code": made["code"]})
            except (WorkError, KeyError) as error:
                out.append({"title": spec.get("title"), "error": getattr(error, "code", "PROJECT_NOT_FOUND")})
        return out

    def bulk_update(self, *, ids: list[str], actor_id: str, member_id: str | None = None, clear_member: bool = False,
                    publish_at: datetime | None = None, status: str | None = None, allowed_project_ids: frozenset[str] | None = None) -> dict[str, object]:
        """One change on many posts: the person, the publish date (of channel versions not yet out), or the column."""
        changed = 0
        errors: list[dict[str, str]] = []
        for work_id in dict.fromkeys(ids[:100]):
            row = self.get(work_id)
            if row is None or (allowed_project_ids is not None and str(row["project_id"]) not in allowed_project_ids):
                errors.append({"id": work_id, "error": "WORK_NOT_FOUND"})
                continue
            try:
                if member_id or clear_member:
                    row = self.update(work_id, expected_version=int(row["version"]), actor_id=actor_id, member_id=member_id, clear_member=clear_member)
                if publish_at is not None:
                    with get_session() as session:
                        for version in session.scalars(select(WorkChannel).where(WorkChannel.work_id == work_id, WorkChannel.status != "PUBLISHED")).all():
                            version.publish_at, version.updated_at = publish_at, _now()
                        session.commit()
                if status and status != row["status"]:
                    row = self.move(work_id, expected_version=int(row["version"]), status=status, note=None, actor_id=actor_id)
                changed += 1
            except WorkError as error:
                errors.append({"id": work_id, "error": error.code})
        return {"changed": changed, "errors": errors}

    def get(self, work_id: str) -> dict[str, object] | None:
        with get_session() as session:
            row = session.get(WorkItem, work_id)
            if row is None:
                return None
            comments = session.scalars(select(WorkComment).where(WorkComment.work_id == row.id).order_by(WorkComment.created_at)).all()
            links = session.scalars(select(WorkLink).where(WorkLink.work_id == row.id).order_by(WorkLink.created_at)).all()
            events = session.scalars(
                select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == row.id)
                .order_by(AuditEvent.created_at.desc()).limit(HISTORY_LIMIT)
            ).all()
            names = self._names(session, [c.user_id for c in comments] + [e.actor_id for e in events] + [l.added_by for l in links])
            steps = session.scalars(select(WorkItem).where(WorkItem.parent_id == row.id).order_by(WorkItem.step_order)).all() if row.template else []
            return {
                **self._dict(session, row, comment_count=len(comments), link_count=len(links)),
                "steps": [self._dict(session, step) for step in steps],
                "links": [{
                    "id": str(l.id), "url": l.url, "note": l.note, "source": l.source, "added_by": str(l.added_by) if l.added_by else None,
                    "added_by_name": names.get(str(l.added_by)), "created_at": l.created_at,
                } for l in links],
                "comments": [{
                    "id": str(c.id), "user_id": str(c.user_id) if c.user_id else None, "user_name": names.get(str(c.user_id)),
                    "body": decrypt(c.body_ciphertext) or "", "created_at": c.created_at,
                } for c in comments],
                "history": [{
                    "at": e.created_at, "actor_name": names.get(str(e.actor_id)) or ("hệ thống" if e.actor_type == "SYSTEM" else None),
                    "event_type": e.event_type, "details": dict(e.details or {}),
                } for e in events],
            }

    def resolve(self, ref: str) -> str | None:
        """The id behind a code (`SAV-W-12`) or an id, as an agent or a person would type it."""
        ref = (ref or "").strip()
        if not ref:
            return None
        try:
            UUID(ref)
            by_id = True
        except ValueError:
            by_id = False
        with get_session() as session:
            # PostgreSQL refuses a code where a UUID is expected, so only a real id is looked up as one.
            row = session.get(WorkItem, ref) if by_id else session.scalar(select(WorkItem).where(WorkItem.code == ref.upper()))
            return str(row.id) if row is not None else None

    def ref_for_intakes(self, session, intake_ids: list[str]) -> dict[str, dict[str, object]]:
        """The work item each request became, keyed by intake id (for IntakeOut.work_item)."""
        if not intake_ids:
            return {}
        rows = session.scalars(select(WorkItem).where(WorkItem.intake_id.in_(intake_ids)).order_by(WorkItem.created_at)).all()
        return {str(row.intake_id): {"id": str(row.id), "code": row.code, "status": row.status, "project_id": str(row.project_id)} for row in rows}

    # --- changing ---------------------------------------------------------------------------------------

    def update(self, work_id: str, *, expected_version: int, actor_id: str, title: str | None = None, description: str | None = None,
               priority: str | None = None, member_id: str | None = None, clear_member: bool = False, due_date: date | None = None,
               clear_due: bool = False, channel: str | None = None, format: str | None = None, campaign: str | None = None,
               clear_campaign: bool = False, urgent: bool | None = None) -> dict[str, object]:
        with get_session() as session:
            row = self._load(session, work_id, expected_version)
            if row.status in ("DONE", "CANCELLED"):
                raise WorkError("WORK_CLOSED", "A closed work item is not edited; move it back first")
            changed: dict[str, object] = {}
            if title is not None:
                clean = _clean_line(title, MAX_TITLE)
                if not clean:
                    raise WorkError("TITLE_REQUIRED", "Give the work a title")
                if clean != row.title:
                    row.title, changed["title"] = clean, clean
            if description is not None:
                row.description_ciphertext = encrypt(_clean_text(description, MAX_DESCRIPTION)) or None
                changed["description"] = True
            if priority is not None:
                if priority not in PRIORITIES:
                    raise WorkError("PRIORITY_INVALID", "Priority must be P0 to P3")
                if priority != row.priority:
                    row.priority, changed["priority"] = priority, priority
            if clear_member:
                row.member_id, changed["member_id"] = None, None
            elif member_id is not None:
                self._check_member(session, row.project_id, member_id)
                row.member_id, changed["member_id"] = member_id, member_id
            if clear_due:
                row.due_date, changed["due_date"] = None, None
            elif due_date is not None:
                row.due_date, changed["due_date"] = due_date, due_date.isoformat()
            if channel is not None:
                if channel not in CHANNEL_CODES:
                    raise WorkError("CHANNEL_UNKNOWN", "Unknown channel")
                if channel != row.channel:
                    row.channel, changed["channel"] = channel, channel
            if format is not None:
                if format not in FORMATS:
                    raise WorkError("FORMAT_UNKNOWN", "Unknown format")
                if format != row.format:
                    row.format, changed["format"] = format, format
            if clear_campaign:
                row.campaign, changed["campaign"] = None, None
            elif campaign is not None:
                clean_campaign = _clean_line(campaign, MAX_CAMPAIGN) or None
                if clean_campaign != row.campaign:
                    row.campaign, changed["campaign"] = clean_campaign, clean_campaign
            if urgent is not None and bool(urgent) != bool(row.urgent):
                row.urgent, changed["urgent"] = bool(urgent), bool(urgent)
            if changed:
                row.version += 1
                row.updated_at = _now()
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id, event_type="work.updated",
                    entity_type="work", entity_id=row.id, details=changed, created_at=row.updated_at,
                ))
            session.commit()
            return self._dict(session, row)

    def move(self, work_id: str, *, expected_version: int, status: str, note: str | None, actor_id: str,
             allowed_statuses: tuple[str, ...] | None = None, actor_type: str = "USER") -> dict[str, object]:
        """One column to another. Leaving Xong is refused once the work has become an Issue; Bỏ needs a reason."""
        if status not in STATUSES:
            raise WorkError("STATUS_INVALID", "Unknown column")
        clean_note = _clean_text(note, MAX_NOTE)
        with get_session() as session:
            row = self._load(session, work_id, expected_version)
            if row.status == status:
                return self._dict(session, row)
            if row.outcome == "ISSUE":
                raise WorkError("WORK_LOCKED_BY_ISSUE", "This work became an Issue; it is followed there")
            if allowed_statuses is not None and (row.status not in allowed_statuses or status not in allowed_statuses):
                raise WorkError("MOVE_NOT_ALLOWED", "You may only move your own work between Cần bàn, Sẵn sàng, Đang làm and Chờ nghiệm thu")
            if status == "CANCELLED" and len(clean_note) < 3:
                raise WorkError("NOTE_REQUIRED", "Say why the work is dropped")
            evidence_missing = False
            if status == "DONE" and row.evidence_required:
                has_link = session.scalar(select(WorkLink.id).where(WorkLink.work_id == row.id).limit(1)) is not None
                if not has_link and len(clean_note) < 3:
                    raise WorkError("EVIDENCE_REQUIRED", "This step closes with a link (the cut, the post) or a reason why there is none")
                evidence_missing = not has_link
            sent_back = row.status == "ACCEPTANCE" and status in ("READY", "IN_PROGRESS", "DISCUSS")
            if sent_back and len(clean_note) < 3:
                raise WorkError("NOTE_REQUIRED", "Say what has to change before this comes back for acceptance")
            if status == "ACCEPTANCE":
                self._check_lengths(session, row)
            if row.template and status == "DONE":
                open_steps = session.scalar(select(func.count()).select_from(WorkItem).where(WorkItem.parent_id == row.id, WorkItem.status.in_(OPEN_STATUSES)))
                if open_steps:
                    raise WorkError("STEPS_OPEN", f"{open_steps} step(s) are still open; close them first")
            previous = row.status
            now = _now()
            row.status = status
            row.version += 1
            row.updated_at = now
            if status in ("DONE", "CANCELLED"):
                row.closed_at = now
                row.closed_note = clean_note or None
            else:
                row.closed_at = None
                row.closed_note = None
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type=actor_type, actor_id=actor_id,
                event_type="work.cancelled" if status == "CANCELLED" else "work.moved", entity_type="work", entity_id=row.id,
                details={"from": previous, "to": status, "note": clean_note or None, "evidence_missing": evidence_missing or None, "sent_back": sent_back or None},
                created_at=now,
            ))
            if sent_back:
                # The reason a step came back is said where the team reads: the discussion.
                session.add(WorkComment(id=str(uuid4()), work_id=row.id, user_id=actor_id, body_ciphertext=encrypt(f"Trả lại: {clean_note}"), created_at=now))
            if row.template and status == "CANCELLED":
                for step in session.scalars(select(WorkItem).where(WorkItem.parent_id == row.id, WorkItem.status.in_(OPEN_STATUSES))).all():
                    step.status, step.closed_at, step.closed_note, step.version, step.updated_at = "CANCELLED", now, f"Việc mẹ bị bỏ: {clean_note}"[:MAX_NOTE], step.version + 1, now
            if row.parent_id:
                self._follow_steps(session, row.parent_id, actor_id=actor_id, actor_type=actor_type, now=now)
            session.commit()
            return self._dict(session, row)

    @staticmethod
    def _check_lengths(session, row: WorkItem) -> None:
        """A channel version longer than its channel allows does not go for review (FR-MKT-11). A channel with a long
        form (X on a paid account) is held to the long limit; the short limit is a warning on the screen."""
        from app.modules.work.channels import count_chars, list_rules

        versions = session.scalars(select(WorkChannel).where(WorkChannel.work_id == row.id, WorkChannel.text.is_not(None))).all()
        if not versions:
            return
        rules = {rule["code"]: rule for rule in list_rules()}
        for version in versions:
            rule = rules.get(version.channel)
            if rule is None:
                continue
            limit = int(rule.get("long_max_chars") or rule["max_chars"])
            count = count_chars(version.text, rule)
            if count > limit:
                raise WorkError("CHANNEL_TEXT_TOO_LONG", f"{rule['label']}: {count}/{limit} ký tự")

    def _follow_steps(self, session, parent_id: str, *, actor_id: str, actor_type: str, now: datetime) -> None:
        """The parent of a pipeline follows its steps: doing while any step is doing, done when all are closed."""
        parent = session.get(WorkItem, parent_id)
        if parent is None or parent.status == "CANCELLED" or parent.outcome == "ISSUE":
            return
        steps = session.scalars(select(WorkItem).where(WorkItem.parent_id == parent.id)).all()
        if not steps:
            return
        if all(step.status in ("DONE", "CANCELLED") for step in steps):
            wanted = "DONE"
        elif any(step.status in ("IN_PROGRESS", "ACCEPTANCE", "DONE") for step in steps):
            wanted = "IN_PROGRESS"
        else:
            wanted = parent.status if parent.status in ("DISCUSS", "READY") else "READY"
        if wanted == parent.status:
            return
        previous = parent.status
        parent.status, parent.version, parent.updated_at = wanted, parent.version + 1, now
        parent.closed_at = now if wanted == "DONE" else None
        parent.closed_note = "Mọi bước đã xong" if wanted == "DONE" else None
        session.add(AuditEvent(
            id=str(uuid4()), project_id=parent.project_id, actor_type="SYSTEM", actor_id="work-steps", event_type="work.moved", entity_type="work",
            entity_id=parent.id, details={"from": previous, "to": wanted, "note": "theo các bước"}, created_at=now,
        ))

    @staticmethod
    def _clean_channels(channels: list[dict] | None) -> list[dict]:
        out: list[dict] = []
        seen: set[str] = set()
        for spec in channels or []:
            code = str(spec.get("channel") or "").upper()
            if code not in CHANNEL_CODES:
                raise WorkError("CHANNEL_UNKNOWN", "Unknown channel")
            if code in seen:
                continue
            seen.add(code)
            out.append({"channel": code, "publish_at": spec.get("publish_at"), "language": spec.get("language")})
        return out

    def add_channel(self, work_id: str, *, channel: str, publish_at: datetime | None, actor_id: str, language: str | None = None) -> dict[str, object]:
        """One more channel version of a post; the same channel twice is refused."""
        code = (channel or "").upper()
        if code not in CHANNEL_CODES:
            raise WorkError("CHANNEL_UNKNOWN", "Unknown channel")
        now = _now()
        with get_session() as session:
            row = session.get(WorkItem, work_id)
            if row is None:
                raise KeyError(work_id)
            if session.scalar(select(WorkChannel.id).where(WorkChannel.work_id == row.id, WorkChannel.channel == code)) is not None:
                raise WorkError("CHANNEL_EXISTS", "This post already has a version for that channel")
            session.add(WorkChannel(id=str(uuid4()), work_id=row.id, channel=code, publish_at=publish_at, status="DRAFT", language=language, created_at=now, updated_at=now))
            if not row.channel:
                row.channel = code
            row.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id, event_type="work.channel_added",
                entity_type="work", entity_id=row.id, details={"channel": code, "publish_at": publish_at.isoformat() if publish_at else None}, created_at=now,
            ))
            session.commit()
        return self.get(work_id) or {}

    def update_channel(self, work_id: str, channel_id: str, *, actor_id: str, publish_at: datetime | None = None, clear_publish: bool = False,
                       status: str | None = None, published_url: str | None = None, actor_type: str = "USER",
                       text: str | None = None, clear_text: bool = False) -> dict[str, object]:
        """Move a channel version's date, write its words, mark it ready, or say it is out (with the link, or without one and a note in the audit)."""
        now = _now()
        with get_session() as session:
            version = session.get(WorkChannel, channel_id)
            if version is None or str(version.work_id) != str(work_id):
                raise KeyError(channel_id)
            row = session.get(WorkItem, work_id)
            details: dict[str, object] = {"channel": version.channel}
            if clear_text:
                version.text, details["text_chars"] = None, 0
            elif text is not None:
                version.text = _clean_text(text, MAX_CHANNEL_TEXT) or None
                details["text_chars"] = len(version.text or "")
            if clear_publish:
                version.publish_at, details["publish_at"] = None, None
            elif publish_at is not None:
                version.publish_at, details["publish_at"] = publish_at, publish_at.isoformat()
            if published_url is not None:
                address = published_url.strip()
                if address and not address.lower().startswith(("http://", "https://")):
                    raise WorkError("URL_INVALID", "Paste a full http(s) address")
                version.published_url, details["published_url"] = (address or None), (address[:300] or None)
            if status is not None:
                if status not in CHANNEL_STATUSES:
                    raise WorkError("STATUS_INVALID", "Unknown state for a channel version")
                if status == "PUBLISHED" and not version.published_url:
                    details["published_without_url"] = True
                version.status, details["status"] = status, status
            version.updated_at = now
            row.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type=actor_type, actor_id=actor_id,
                event_type="work.published" if status == "PUBLISHED" else "work.channel_updated", entity_type="work", entity_id=row.id, details=details, created_at=now,
            ))
            # A post that is approved and out on every channel is done (FR-MKT-01).
            versions = session.scalars(select(WorkChannel).where(WorkChannel.work_id == row.id)).all()
            if row.status == "APPROVED" and versions and all(v.status == "PUBLISHED" for v in versions):
                row.status, row.closed_at, row.closed_note, row.version = "DONE", now, "Đã đăng trên mọi kênh", row.version + 1
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=row.project_id, actor_type="SYSTEM", actor_id="work-channels", event_type="work.moved", entity_type="work",
                    entity_id=row.id, details={"from": "APPROVED", "to": "DONE", "note": "theo các bản kênh"}, created_at=now,
                ))
            session.commit()
        return self.get(work_id) or {}

    def remove_channel(self, work_id: str, channel_id: str, *, actor_id: str) -> dict[str, object]:
        with get_session() as session:
            version = session.get(WorkChannel, channel_id)
            if version is None or str(version.work_id) != str(work_id):
                raise KeyError(channel_id)
            if version.status == "PUBLISHED":
                raise WorkError("CHANNEL_PUBLISHED", "A version that is out stays on the record")
            row = session.get(WorkItem, work_id)
            session.delete(version)
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id, event_type="work.channel_removed",
                entity_type="work", entity_id=row.id, details={"channel": version.channel}, created_at=_now(),
            ))
            session.commit()
        return self.get(work_id) or {}

    def comment(self, work_id: str, *, body: str, actor_id: str, actor_type: str = "USER") -> dict[str, object]:
        text = _clean_text(body, MAX_COMMENT)
        if len(text) < 2:
            raise WorkError("COMMENT_REQUIRED", "Write the comment")
        now = _now()
        with get_session() as session:
            row = session.get(WorkItem, work_id)
            if row is None:
                raise KeyError(work_id)
            session.add(WorkComment(id=str(uuid4()), work_id=row.id, user_id=actor_id, body_ciphertext=encrypt(text), created_at=now))
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type=actor_type, actor_id=actor_id, event_type="work.commented",
                entity_type="work", entity_id=row.id, details={"length": len(text)}, created_at=now,
            ))
            session.commit()
        return self.get(work_id) or {}

    def add_link(self, work_id: str, *, url: str, note: str | None, actor_id: str, actor_type: str = "USER") -> dict[str, object]:
        """A link to where the work lives outside Intake: the folder, the design, the cut, the published post."""
        address = (url or "").strip()
        if not address.lower().startswith(("http://", "https://")) or len(address) > MAX_URL or any(ch.isspace() for ch in address):
            raise WorkError("URL_INVALID", "Paste a full http(s) address")
        clean_note = _clean_line(note, MAX_LINK_NOTE) or None
        now = _now()
        with get_session() as session:
            row = session.get(WorkItem, work_id)
            if row is None:
                raise KeyError(work_id)
            if int(session.scalar(select(func.count()).select_from(WorkLink).where(WorkLink.work_id == row.id)) or 0) >= MAX_LINKS:
                raise WorkError("TOO_MANY_LINKS", f"At most {MAX_LINKS} links on one work item")
            existing = session.scalar(select(WorkLink).where(WorkLink.work_id == row.id, WorkLink.url == address))
            if existing is None:
                session.add(WorkLink(id=str(uuid4()), work_id=row.id, url=address, note=clean_note, source="AGENT" if actor_type == "AGENT" else "USER",
                                     added_by=actor_id, created_at=now))
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=row.project_id, actor_type=actor_type, actor_id=actor_id, event_type="work.linked",
                    entity_type="work", entity_id=row.id, details={"url": address[:300], "note": clean_note}, created_at=now,
                ))
            elif clean_note and not existing.note:
                existing.note = clean_note
            row.updated_at = now
            session.commit()
        return self.get(work_id) or {}

    def delete_link(self, work_id: str, link_id: str, *, actor_id: str, is_cto: bool) -> None:
        with get_session() as session:
            link = session.get(WorkLink, link_id)
            if link is None or str(link.work_id) != str(work_id):
                raise KeyError(link_id)
            if not is_cto and str(link.added_by) != str(actor_id):
                raise WorkError("NOT_YOURS", "Only the person who added the link, or the CTO, removes it")
            session.delete(link)
            session.commit()

    def delete_comment(self, work_id: str, comment_id: str, *, actor_id: str, is_cto: bool) -> None:
        with get_session() as session:
            comment = session.get(WorkComment, comment_id)
            if comment is None or str(comment.work_id) != str(work_id):
                raise KeyError(comment_id)
            if not is_cto and str(comment.user_id) != str(actor_id):
                raise WorkError("NOT_YOURS", "Only the person who wrote the comment, or the CTO, removes it")
            session.delete(comment)
            session.commit()

    # --- from and to requests -----------------------------------------------------------------------------

    def from_intake(self, session, item: IntakeItem, *, priority: str, actor_id: str | None) -> WorkItem:
        """The work item a request becomes when approved for the WORK route; called inside the approval transaction.
        A request approved again after a reopen gets its earlier (dropped) item back instead of a second one."""
        existing = session.scalars(select(WorkItem).where(WorkItem.intake_id == item.id).order_by(WorkItem.created_at.desc())).first()
        now = _now()
        if existing is not None:
            if existing.status == "CANCELLED" and existing.outcome is None:
                existing.status, existing.closed_at, existing.closed_note = "DISCUSS", None, None
                existing.priority = priority
                existing.title = _clean_line(item.normalized_title, MAX_TITLE) or existing.title
                existing.version += 1
                existing.updated_at = now
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=item.project_id, actor_type="USER", actor_id=actor_id or "system", event_type="work.moved",
                    entity_type="work", entity_id=existing.id, details={"from": "CANCELLED", "to": "DISCUSS", "note": "Intake được duyệt lại"}, created_at=now,
                ))
            return existing
        project = session.get(Project, item.project_id)
        return self._insert(session, project, title=_clean_line(item.normalized_title, MAX_TITLE) or item.public_id,
                            description=_clean_text(item.normalized_summary, MAX_DESCRIPTION), priority=priority, member_id=None, due_date=None,
                            status="DISCUSS", intake_id=str(item.id), actor_id=actor_id)

    def cancel_for_intake(self, session, intake_id: str, *, reason: str, actor_id: str | None) -> list[str]:
        """A reopened request takes its open work item with it, unless that item is on its way to an Issue."""
        dropped: list[str] = []
        now = _now()
        for row in session.scalars(select(WorkItem).where(WorkItem.intake_id == intake_id, WorkItem.status.in_(OPEN_STATUSES))).all():
            if row.outcome is not None:
                continue
            previous = row.status
            row.status, row.closed_at, row.closed_note = "CANCELLED", now, f"Intake được mở lại: {reason}"[:MAX_NOTE]
            row.version += 1
            row.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id or "system", event_type="work.cancelled",
                entity_type="work", entity_id=row.id, details={"from": previous, "to": "CANCELLED", "note": row.closed_note}, created_at=now,
            ))
            dropped.append(row.code)
        return dropped

    def request_issue(self, work_id: str, *, actor_id: str) -> dict[str, object]:
        """Turn the work into a delivery Issue: its request (made on the spot if it has none) is approved for the
        delivery tracker and queued for sync; the item closes as an Issue once the worker reports back."""
        from app.modules.planning.add_work import add_work_service
        from app.modules.planning.service import PlanningValidationError
        from app.schemas import IntakeCreate
        from app.services.intake_service import intake_store

        with get_session() as session:
            row = session.get(WorkItem, work_id)
            if row is None:
                raise KeyError(work_id)
            if row.status in ("DONE", "CANCELLED") or row.outcome is not None:
                raise WorkError("WORK_CLOSED", "Only open work becomes an Issue")
            project = session.get(Project, row.project_id)
            if project is None or project.kind != "SOFTWARE":
                raise WorkError("PROJECT_NOT_SOFTWARE", "Only a software project has a delivery tracker")
            has_delivery = session.scalar(select(ProjectIntegration.id).where(
                ProjectIntegration.project_id == project.id, ProjectIntegration.system.in_(DELIVERY_SYSTEMS),
                ProjectIntegration.enabled.is_(True), ProjectIntegration.project_external_id.is_not(None),
            )) is not None
            if not has_delivery:
                raise WorkError("DELIVERY_SYNC_DISABLED", "Sync to this project's GitLab or GitHub is not enabled, so an Issue cannot be created")
            code, title, description, priority, intake_id, project_code = row.code, row.title, decrypt(row.description_ciphertext) or "", row.priority, row.intake_id, project.code
        if not intake_id:
            created = intake_store.create(IntakeCreate(project_id=project_code, channel="MANUAL", raw_text=f"{title}\n\n{description}" if description else title))
            with get_session() as session:
                item = session.get(IntakeItem, created.id)
                # The owner wrote this work and decides it here; it does not wait for AI normalization.
                item.normalized_title, item.normalized_summary = title[:255], description or title
                item.item_type, item.suggested_priority, item.proposed_route = "TASK", priority, "GITLAB"
                item.status = "PENDING_APPROVAL"
                item.updated_at = _now()
                session.get(WorkItem, work_id).intake_id = item.id
                session.commit()
            intake_id = str(created.id)
        now = _now()
        with get_session() as session:
            row = session.get(WorkItem, work_id)
            row.outcome = "ISSUE_PENDING"
            row.version += 1
            row.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), project_id=row.project_id, actor_type="USER", actor_id=actor_id, event_type="work.issue_requested",
                entity_type="work", entity_id=row.id, details={"intake_id": intake_id}, created_at=now,
            ))
            session.commit()
        try:
            add_work_service.issue_for_intake(intake_id, priority=priority, reason=f"Chuyển thành Issue từ Việc {code}", actor_id=actor_id, source="WORK")
        except PlanningValidationError as exc:
            with get_session() as session:
                row = session.get(WorkItem, work_id)
                row.outcome = None
                row.updated_at = _now()
                session.commit()
            raise WorkError(exc.code, str(exc)) from exc
        return self.get(work_id) or {}

    def issue_created(self, intake_id: str, *, system: str, external_id: str, url: str | None) -> int:
        """The worker made the Issue: the work item that asked for it closes as an Issue. A re-sync of an Issue that
        already existed, or a request that never came from a work item, changes nothing here."""
        now = _now()
        with get_session() as session:
            rows = session.scalars(select(WorkItem).where(WorkItem.intake_id == intake_id, WorkItem.outcome == "ISSUE_PENDING")).all()
            for row in rows:
                previous = row.status
                row.issue_system, row.issue_external_id, row.issue_url = system, external_id, url
                row.outcome, row.status, row.closed_at = "ISSUE", "DONE", now
                row.closed_note = f"Đã thành Issue #{external_id}"
                row.version += 1
                row.updated_at = now
                session.add(AuditEvent(
                    id=str(uuid4()), project_id=row.project_id, actor_type="SYSTEM", actor_id="integration-worker", event_type="work.issue_created",
                    entity_type="work", entity_id=row.id, details={"from": previous, "to": "DONE", "system": system, "external_id": external_id, "url": url},
                    created_at=now,
                ))
            session.commit()
            return len(rows)

    # --- helpers -----------------------------------------------------------------------------------------

    @staticmethod
    def _load(session, work_id: str, expected_version: int) -> WorkItem:
        row = session.get(WorkItem, work_id)
        if row is None:
            raise KeyError(work_id)
        if row.version != expected_version:
            raise WorkError("STALE_VERSION", "The work item changed; reload before saving")
        return row

    @staticmethod
    def _check_member(session, project_id: str, member_id: str) -> None:
        on_project = session.scalar(select(WorkforceProjectMembership.id).where(
            WorkforceProjectMembership.project_id == project_id, WorkforceProjectMembership.member_id == member_id,
            WorkforceProjectMembership.active.is_(True),
        )) is not None
        if not on_project:
            raise WorkError("MEMBER_NOT_IN_PROJECT", "The person is not on this project")

    @staticmethod
    def _names(session, ids: list[str | None]) -> dict[str, str]:
        # Audit actors are user ids, or names such as "integration-worker"; only ids are looked up (PostgreSQL refuses the rest).
        wanted = []
        for value in ids:
            try:
                UUID(str(value))
            except (ValueError, TypeError):
                continue
            wanted.append(str(value))
        if not wanted:
            return {}
        rows = session.scalars(select(User).where(User.id.in_(list(set(wanted))))).all()
        return {str(user.id): user.display_name or user.auth_subject for user in rows}

    @staticmethod
    def _dict(session, row: WorkItem, *, comment_count: int | None = None, link_count: int | None = None) -> dict[str, object]:
        project = session.get(Project, row.project_id)
        member = session.get(WorkforceMember, row.member_id) if row.member_id else None
        creator = session.get(User, row.created_by) if row.created_by else None
        intake = session.get(IntakeItem, row.intake_id) if row.intake_id else None
        if comment_count is None:
            comment_count = int(session.scalar(select(func.count()).select_from(WorkComment).where(WorkComment.work_id == row.id)) or 0)
        if link_count is None:
            link_count = int(session.scalar(select(func.count()).select_from(WorkLink).where(WorkLink.work_id == row.id)) or 0)
        steps_total = steps_done = 0
        if row.template:
            counts = session.execute(select(WorkItem.status, func.count()).where(WorkItem.parent_id == row.id).group_by(WorkItem.status)).all()
            steps_total = sum(int(n) for _, n in counts)
            steps_done = sum(int(n) for status, n in counts if status in ("DONE", "CANCELLED"))
        parent = session.get(WorkItem, row.parent_id) if row.parent_id else None
        meeting = session.scalar(select(Meeting).join(MeetingNoteItem, MeetingNoteItem.meeting_id == Meeting.id).where(MeetingNoteItem.intake_id == row.intake_id)) if row.intake_id else None
        versions = session.scalars(select(WorkChannel).where(WorkChannel.work_id == row.id).order_by(WorkChannel.publish_at.nulls_last(), WorkChannel.created_at)).all()
        pending = [_aware_utc(v.publish_at) for v in versions if v.status != "PUBLISHED" and v.publish_at is not None]
        short_links = links_of(session, [str(v.id) for v in versions]) if versions else {}
        return {
            "id": str(row.id), "code": row.code, "project_id": str(row.project_id), "project_code": project.code if project else None,
            "project_name": project.name if project else None, "project_kind": project.kind if project else None,
            "has_delivery": project is not None and session.scalar(select(ProjectIntegration.id).where(
                ProjectIntegration.project_id == project.id, ProjectIntegration.system.in_(DELIVERY_SYSTEMS),
                ProjectIntegration.enabled.is_(True), ProjectIntegration.project_external_id.is_not(None),
            )) is not None,
            "title": row.title, "description": decrypt(row.description_ciphertext) or "", "status": row.status, "priority": row.priority,
            "member_id": str(row.member_id) if row.member_id else None, "member_name": member.display_name if member else None,
            "due_date": row.due_date, "intake_id": str(row.intake_id) if row.intake_id else None,
            "intake_public_id": intake.public_id if intake else None, "intake_status": intake.status if intake else None,
            "issue_system": row.issue_system, "issue_external_id": row.issue_external_id, "issue_url": row.issue_url,
            "outcome": row.outcome, "issue_pending": row.outcome == "ISSUE_PENDING", "closed_note": row.closed_note,
            "comment_count": comment_count, "link_count": link_count, "version": row.version,
            "template": row.template, "steps_total": steps_total, "steps_done": steps_done,
            "parent_id": str(row.parent_id) if row.parent_id else None, "parent_code": parent.code if parent else None,
            "step": row.step, "step_label": STEP_LABELS.get(row.step or ""), "step_order": row.step_order, "evidence_required": bool(row.evidence_required),
            "meeting_id": str(meeting.id) if meeting else None, "meeting_title": meeting.title if meeting else None, "meeting_at": meeting.started_at if meeting else None,
            "channel": row.channel, "format": row.format, "campaign": row.campaign, "urgent": bool(row.urgent),
            "channels": [{"id": str(v.id), "channel": v.channel, "publish_at": _aware_utc(v.publish_at), "status": v.status, "published_url": v.published_url, "language": v.language,
                          "text": v.text, "short_link": short_links.get(str(v.id))} for v in versions],
            "next_publish_at": min(pending) if pending else None,
            "created_by": str(row.created_by) if row.created_by else None,
            "created_by_name": (creator.display_name or creator.auth_subject) if creator else None,
            "created_at": row.created_at, "updated_at": row.updated_at, "closed_at": row.closed_at,
        }


work_service = WorkService()
