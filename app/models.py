from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


ID = Uuid(as_uuid=False)
JSON_DOCUMENT = JSON().with_variant(JSONB(), "postgresql")
CASE_INSENSITIVE_TEXT = String(320).with_variant(CITEXT(), "postgresql")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApiToken(Base):
    """A personal token a person gave to an agent; hashed, shown once, revocable (FR-MCP-01)."""

    __tablename__ = "api_tokens"
    __table_args__ = (Index("ix_api_tokens_user", "user_id"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base):
    __tablename__ = "users"
    # DEVELOPER: a team member whose login exists for a personal token; an agent reads their plan and reports for them.
    __table_args__ = (CheckConstraint("role IN ('CTO', 'PROJECT_OWNER', 'DEVELOPER')", name="ck_users_role"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    auth_subject: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(CASE_INSENSITIVE_TEXT, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="PROJECT_OWNER", nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    mfa_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Enrollment is staged separately so starting or abandoning replacement cannot disable the active factor.
    mfa_pending_secret_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    mfa_pending_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Set when the CTO issues a temporary password; cleared when the user chooses their own.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Embedded in browser access tokens. Incrementing it invalidates every older signed session after a reset.
    auth_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # The staff member this login belongs to, when it was created by making them a Project Owner.
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id"), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserProjectAccess(Base):
    """The projects a Project Owner may work in. The CTO needs no rows: the CTO sees every project."""

    __tablename__ = "user_project_access"

    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    granted_by: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MFARecoveryCode(Base):
    __tablename__ = "mfa_recovery_codes"
    __table_args__ = (UniqueConstraint("user_id", "code_hash", name="uq_mfa_recovery_user_hash"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    code_hash: Mapped[str] = mapped_column(Text, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserSession(Base):
    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_active", "user_id", "expires_at", postgresql_where=text("revoked_at IS NULL")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PasswordResetRequest(Base):
    """A short-lived, single-use reset link. Only its SHA-256 digest is stored."""

    __tablename__ = "password_reset_requests"
    __table_args__ = (
        Index("ix_password_reset_user_time", "user_id", "created_at"),
        Index("ix_password_reset_active", "expires_at", postgresql_where=text("used_at IS NULL")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    send_error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class UserPlanningProjectOrder(Base):
    """One person's preferred order for the all-projects Daily Planning view."""

    __tablename__ = "user_planning_project_orders"
    __table_args__ = (
        CheckConstraint("sort_mode IN ('PRIORITY', 'CUSTOM')", name="ck_user_planning_project_orders_mode"),
    )

    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    sort_mode: Mapped[str] = mapped_column(String(16), default="PRIORITY", nullable=False)
    project_ids: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    code: Mapped[str] = mapped_column(CASE_INSENSITIVE_TEXT, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    customer_metadata: Mapped[dict | None] = mapped_column("metadata", JSON_DOCUMENT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_projects_status"),
        CheckConstraint("kind IN ('IDEA', 'NON_CODE', 'SOFTWARE')", name="ck_projects_kind"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    customer_id: Mapped[str | None] = mapped_column(ID, ForeignKey("customers.id"), nullable=True)
    code: Mapped[str] = mapped_column(CASE_INSENSITIVE_TEXT, unique=True, nullable=False)
    intake_key: Mapped[str] = mapped_column(String(8), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # IDEA/NON_CODE use Intake work; SOFTWARE also has GitLab/GitHub delivery and is the only kind Planning covers.
    kind: Mapped[str] = mapped_column(String(16), default="SOFTWARE", nullable=False)
    # The one staff member who is this project's Project Owner; None means only the CTO decides.
    owner_member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    project_settings: Mapped[dict | None] = mapped_column("settings", JSON_DOCUMENT, nullable=True)
    # The Telegram group that gets this project's reminders (FR-NTF-02).
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_chat_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The topic inside that group when the group is split into topics; None means the whole group (or General).
    telegram_thread_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IntakeCounter(Base):
    __tablename__ = "intake_counters"
    __table_args__ = (
        CheckConstraint("iso_week BETWEEN 1 AND 53", name="ck_intake_counters_week"),
        CheckConstraint("last_value BETWEEN 1 AND 999", name="ck_intake_counters_value"),
    )

    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    iso_year: Mapped[int] = mapped_column(Integer, primary_key=True)
    iso_week: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_value: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ProjectIntegration(Base):
    __tablename__ = "project_integrations"
    __table_args__ = (
        UniqueConstraint("project_id", "system", name="uq_project_integrations_project_system"),
        CheckConstraint("system IN ('GITLAB', 'GITHUB')", name="ck_project_integrations_system"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    system: Mapped[str] = mapped_column(String(32), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    workspace_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    project_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    config: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class GitLabIssueSnapshot(Base):
    __tablename__ = "gitlab_issue_snapshots"
    __table_args__ = (
        UniqueConstraint("project_id", "issue_external_id", "payload_hash", name="uq_gitlab_issue_snapshot_hash"),
        Index("ix_gitlab_issue_current", "project_id", "state", "is_current"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    issue_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    global_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    labels: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False)
    assignee_external_ids: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False)
    milestone_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    milestone_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    web_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_by_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Traces of code behind a closed Issue, read after the fact: merge requests, commits that mention it, the last
    # pipeline. Kept outside the payload hash: it is looked up, not part of the Issue (FR-PLAN-22).
    evidence: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    evidence_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IntakeWorkLog(Base):
    """One piece of work done about a request, by a person or an agent, and the CTO's call on it (FR-MCP-03)."""

    __tablename__ = "intake_work_log"
    __table_args__ = (
        CheckConstraint("review_decision IN ('PENDING', 'CONFIRMED', 'RETURNED')", name="ck_intake_work_log_decision"),
        Index("ix_intake_work_log_intake", "intake_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    review_decision: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IssueVerification(Base):
    """A closed Issue the CTO was asked to look at: what the evidence was then, and what the CTO decided."""

    __tablename__ = "issue_verifications"
    __table_args__ = (
        CheckConstraint("decision IN ('PENDING', 'ACCEPTED', 'REJECTED')", name="ck_issue_verifications_decision"),
        Index("ix_issue_verifications_issue", "project_id", "issue_external_id"),
        Index("ix_issue_verifications_run", "planning_run_id"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    issue_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    planning_run_id: Mapped[str | None] = mapped_column(ID, ForeignKey("planning_runs.id", ondelete="SET NULL"), nullable=True)
    evidence_level: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decision: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    decided_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Acceptance as its own queue (FR-PLAN-31): where it came from, who reported it, the day it entered the CTO's
    # sample, what the Project Owner said, and what happened on the tracker after the CTO accepted.
    source: Mapped[str] = mapped_column(String(16), default="CLOSED", server_default="CLOSED", nullable=False)
    report_item_id: Mapped[str | None] = mapped_column(ID, ForeignKey("report_items.id", ondelete="SET NULL"), nullable=True)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="SET NULL"), nullable=True)
    reported_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    picked_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    po_decision: Mapped[str | None] = mapped_column(String(16), nullable=True)
    po_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    po_decided_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    po_decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Whose word made the acceptance final: CTO, or PO when the project's policy let the Project Owner close it (FR-PLAN-41).
    final_by: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sync_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # What the person who set the work aside as "done already" wrote (FR-PLAN-34); goes onto the Issue with the acceptance.
    source_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Accepted with nothing behind it: why the acceptor still said yes (FR-PLAN-36).
    evidence_missing_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IntakeItem(Base):
    __tablename__ = "intake_items"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_intake_items_version"),
        Index("ix_intake_project_status_updated", "project_id", "status", text("updated_at DESC"), text("id DESC")),
        Index("ix_intake_project_created", "project_id", text("created_at DESC"), text("id DESC")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    public_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    create_idempotency_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    create_request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    customer_id: Mapped[str | None] = mapped_column(ID, ForeignKey("customers.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), default="UNCLEAR", nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="NEW", nullable=False)
    normalized_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    normalized_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # where, steps, expected, subtasks, acceptance, open_questions, related (ADR-0032). None when there is nothing to add.
    normalized_details: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    # What the CTO tells whoever fixes this: where to look, how to reproduce, what not to touch (FR-MCP-03).
    fix_hints: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set only by the CTO: acceptance of this work always comes back to the CTO (FR-PLAN-39).
    needs_cto_acceptance: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"), nullable=False)
    suggested_priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    approved_priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    proposed_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approved_route: Mapped[str | None] = mapped_column(String(32), nullable=True)
    current_extraction_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    duplicate_of_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id"), nullable=True)
    defer_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SourceMessage(Base):
    __tablename__ = "source_messages"
    __table_args__ = (
        Index("ix_source_messages_intake_created", "intake_id", "created_at"),
        Index("ix_source_messages_content_hash", "content_hash"),
        Index("ix_source_messages_purge", "purge_after", postgresql_where=text("purged_at IS NULL")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sender_reference_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Attachment(Base):
    __tablename__ = "attachments"
    __table_args__ = (
        Index("ix_attachments_intake_created", "intake_id", "created_at"),
        Index("ix_attachments_sha256", "sha256"),
        Index("ix_attachments_purge", "purge_after", postgresql_where=text("purged_at IS NULL")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(ID, ForeignKey("source_messages.id"), nullable=True)
    object_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    original_name_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    declared_mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    detected_mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_state: Mapped[str] = mapped_column(String(32), default="QUARANTINE", nullable=False)
    scan_status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    ocr_status: Mapped[str] = mapped_column(String(32), default="NONE", nullable=False)
    # What the vision model read from the file (ADR-0061): kept encrypted like the source, with which model and when.
    ocr_text_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    ocr_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ocr_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    @property
    def mime_type(self) -> str | None:
        return self.detected_mime_type or self.declared_mime_type


class ProcessingRun(Base):
    __tablename__ = "processing_runs"
    __table_args__ = (
        CheckConstraint("attempt >= 0 AND max_attempts > 0", name="ck_processing_runs_attempts"),
        Index("ix_processing_runs_intake_created", "intake_id", "created_at"),
        Index("ix_processing_runs_dispatch", "status", "next_attempt_at", "created_at", postgresql_where=text("status IN ('QUEUED', 'RETRY')")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False)
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    parent_run_id: Mapped[str | None] = mapped_column(ID, ForeignKey("processing_runs.id"), nullable=True)
    job_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="QUEUED", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    output_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_metadata: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceFragment(Base):
    __tablename__ = "evidence_fragments"
    __table_args__ = (
        UniqueConstraint("processing_run_id", "fragment_order", name="uq_evidence_run_order"),
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_evidence_confidence"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    processing_run_id: Mapped[str] = mapped_column(ID, ForeignKey("processing_runs.id", ondelete="CASCADE"), nullable=False)
    attachment_id: Mapped[str | None] = mapped_column(ID, ForeignKey("attachments.id"), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(ID, ForeignKey("source_messages.id"), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fragment_order: Mapped[int] = mapped_column(Integer, nullable=False)
    content_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    bounding_box: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    extractor: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AIExtraction(Base):
    __tablename__ = "ai_extractions"
    __table_args__ = (
        CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_ai_extractions_confidence"),
        Index("ix_ai_extractions_intake_created", "intake_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    processing_run_id: Mapped[str] = mapped_column(ID, ForeignKey("processing_runs.id"), nullable=False)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    model_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    input_policy: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    token_usage: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    fallback_reason: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DuplicateCandidate(Base):
    __tablename__ = "duplicate_candidates"
    __table_args__ = (
        UniqueConstraint("intake_id", "candidate_type", "candidate_reference", name="uq_duplicate_candidate"),
        CheckConstraint("score IS NULL OR (score >= 0 AND score <= 1)", name="ck_duplicate_score"),
        Index("ix_duplicate_candidates_intake_decision", "intake_id", "decision"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    candidate_type: Mapped[str] = mapped_column(String(32), nullable=False)
    candidate_reference: Mapped[str] = mapped_column(String(255), nullable=False)
    match_method: Mapped[str] = mapped_column(String(32), nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    decision: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ApprovalAction(Base):
    __tablename__ = "approval_actions"
    __table_args__ = (Index("ix_approval_actions_intake_created", "intake_id", "created_at"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # QUEUE: decided in the approval queue. PLANNING: approved while adding work to a day plan (ADR-0024).
    source: Mapped[str] = mapped_column(String(16), default="QUEUE", server_default="QUEUE", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ApprovalSnapshot(Base):
    __tablename__ = "approval_snapshots"
    __table_args__ = (Index("ix_approval_snapshots_intake_created", "intake_id", "created_at"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    approval_action_id: Mapped[str] = mapped_column(ID, ForeignKey("approval_actions.id"), unique=True, nullable=False)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    item_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_route: Mapped[str] = mapped_column(String(32), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class SyncJob(Base):
    __tablename__ = "sync_jobs"
    __table_args__ = (
        UniqueConstraint("approval_snapshot_id", "target_system", name="uq_sync_jobs_snapshot_target"),
        CheckConstraint("attempt >= 0 AND max_attempts > 0", name="ck_sync_jobs_attempts"),
        Index("ix_sync_jobs_intake_created", "intake_id", text("created_at DESC")),
        Index("ix_sync_jobs_dispatch", "status", "next_attempt_at", "created_at", postgresql_where=text("status IN ('PENDING', 'RETRY')")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    approval_snapshot_id: Mapped[str] = mapped_column(ID, ForeignKey("approval_snapshots.id"), nullable=False)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    target_system: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    request_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    response_metadata: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ExternalLink(Base):
    __tablename__ = "external_links"
    __table_args__ = (
        UniqueConstraint("project_id", "target_system", "external_id", name="uq_external_link_target"),
        Index("ix_external_links_intake_target", "intake_id", "target_system", text("created_at DESC")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    sync_job_id: Mapped[str] = mapped_column(ID, ForeignKey("sync_jobs.id"), unique=True, nullable=False)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    target_system: Mapped[str] = mapped_column(String(32), nullable=False)
    external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("ix_outbox_events_dispatch", "status", "next_attempt_at", "created_at", postgresql_where=text("status IN ('NEW', 'RETRY', 'FAILED')")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(ID, nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="NEW", nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_detail_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class EmailMessage(Base):
    __tablename__ = "email_messages"
    __table_args__ = (
        UniqueConstraint("mailbox", "uid_validity", "uid", name="uq_email_mailbox_uid"),
        Index("ix_email_messages_message_id", "message_id"),
        Index("ix_email_report_member_date", "member_id", "report_date", "is_current"),
        CheckConstraint("revision > 0", name="ck_email_messages_revision"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id"), nullable=True)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id"), nullable=True)
    supersedes_email_id: Mapped[str | None] = mapped_column(ID, ForeignKey("email_messages.id"), nullable=True)
    mailbox: Mapped[str] = mapped_column(String(320), nullable=False)
    uid_validity: Mapped[str] = mapped_column(String(64), nullable=False)
    uid: Mapped[str] = mapped_column(String(64), nullable=False)
    message_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    sender_address: Mapped[str] = mapped_column(CASE_INSENSITIVE_TEXT, nullable=False)
    sender_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    subject_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parsed_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_version: Mapped[str] = mapped_column(String(32), default="daily-report-v1", nullable=False)
    parse_errors: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="NEW", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_late: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ReportRun(Base):
    __tablename__ = "report_runs"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ReportItem(Base):
    __tablename__ = "report_items"
    __table_args__ = (
        CheckConstraint("revision > 0", name="ck_report_items_revision"),
        CheckConstraint(
            "progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)",
            name="ck_report_items_progress",
        ),
        CheckConstraint(
            "worked_hours IS NULL OR worked_hours >= 0", name="ck_report_items_worked_hours"
        ),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    report_run_id: Mapped[str | None] = mapped_column(ID, ForeignKey("report_runs.id", ondelete="CASCADE"), nullable=True)
    email_message_id: Mapped[str | None] = mapped_column(ID, ForeignKey("email_messages.id", ondelete="CASCADE"), nullable=True)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id"), nullable=True)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    work_status: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    worked_hours: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    remaining_hours: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    planned_hours: Mapped[float | None] = mapped_column(Numeric(5, 2), nullable=True)
    progress_percent: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    gitlab_issue_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    plane_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    intake_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deadline_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dependency: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_evidence: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    blocker: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    blocker_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Where the Issue number came from, what the machine suggested, and why no Issue is needed (FR-RPT-07).
    issue_suggestions: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    issue_link_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    no_issue_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkforceMember(Base):
    __tablename__ = "workforce_members"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_workforce_members_status"),
        CheckConstraint("default_weekday_hours >= 0 AND default_weekday_hours <= 24", name="ck_workforce_default_hours"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email_reference: Mapped[str | None] = mapped_column(CASE_INSENSITIVE_TEXT, unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh", nullable=False)
    default_weekday_hours: Mapped[float] = mapped_column(Numeric(4, 2), default=8, nullable=False)
    # The person's private chat with the bot, joined through a one-time invite (FR-NTF-03).
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    telegram_invite_code: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    telegram_linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkforceProjectMembership(Base):
    __tablename__ = "workforce_project_memberships"
    __table_args__ = (
        UniqueConstraint("member_id", "project_id", name="uq_workforce_membership_member_project"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    member_id: Mapped[str] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    gitlab_user_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class DailyCapacity(Base):
    __tablename__ = "daily_capacities"
    __table_args__ = (
        UniqueConstraint("member_id", "work_date", name="uq_daily_capacity_member_date"),
        CheckConstraint(
            "base_hours >= 0 AND base_hours <= 24 AND "
            "(override_hours IS NULL OR (override_hours >= 0 AND override_hours <= 24)) AND "
            "meeting_hours >= 0 AND review_hours >= 0 AND support_hours >= 0 AND fixed_hours >= 0 AND "
            "available_hours >= 0 AND available_hours <= 24",
            name="ck_daily_capacity_hours",
        ),
        CheckConstraint("version > 0", name="ck_daily_capacity_version"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    member_id: Mapped[str] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="CASCADE"), nullable=False)
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    base_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    override_hours: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    meeting_hours: Mapped[float] = mapped_column(Numeric(4, 2), default=0, nullable=False)
    review_hours: Mapped[float] = mapped_column(Numeric(4, 2), default=0, nullable=False)
    support_hours: Mapped[float] = mapped_column(Numeric(4, 2), default=0, nullable=False)
    fixed_hours: Mapped[float] = mapped_column(Numeric(4, 2), default=0, nullable=False)
    available_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    updated_by: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PlanningRun(Base):
    __tablename__ = "planning_runs"
    __table_args__ = (
        UniqueConstraint("plan_date", "scope_hash", "revision", name="uq_planning_run_date_scope_revision"),
        CheckConstraint("version > 0 AND revision > 0", name="ck_planning_run_versions"),
        CheckConstraint(
            "status IN ('DRAFT', 'REVIEW_REQUIRED', 'APPROVED', 'SYNCING', 'SYNCED', 'PARTIAL', 'SYNC_FAILED', 'SUPERSEDED')",
            name="ck_planning_run_status",
        ),
        Index("ix_planning_run_date_status", text("plan_date DESC"), "status", text("id DESC")),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    plan_date: Mapped[date] = mapped_column(Date, nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Ho_Chi_Minh", nullable=False)
    project_scope: Mapped[list] = mapped_column(JSON_DOCUMENT, nullable=False)
    scope_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    report_cutoff_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    gitlab_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_run_id: Mapped[str | None] = mapped_column(ID, ForeignKey("planning_runs.id"), nullable=True)
    created_by: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PlanningAssignment(Base):
    __tablename__ = "planning_assignments"
    __table_args__ = (
        CheckConstraint("slot IN ('MORNING', 'AFTERNOON')", name="ck_planning_assignment_slot"),
        CheckConstraint(
            "work_type IN ('DEVELOPMENT', 'REVIEW', 'QA', 'SUPPORT', 'MEETING', 'FIXED')",
            name="ck_planning_assignment_work_type",
        ),
        CheckConstraint("planned_hours > 0 AND planned_hours <= 24", name="ck_planning_assignment_hours"),
        CheckConstraint("version > 0", name="ck_planning_assignment_version"),
        Index("ix_planning_assignment_member_slot", "planning_run_id", "member_id", "slot"),
        Index(
            "uq_planning_assignment_run_project_issue",
            "planning_run_id", "project_id", "gitlab_issue_external_id",
            unique=True,
            postgresql_where=text("gitlab_issue_external_id IS NOT NULL"),
            sqlite_where=text("gitlab_issue_external_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    planning_run_id: Mapped[str] = mapped_column(ID, ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    member_id: Mapped[str] = mapped_column(ID, ForeignKey("workforce_members.id"), nullable=False)
    slot: Mapped[str] = mapped_column(String(16), nullable=False)
    work_type: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    planned_hours: Mapped[float] = mapped_column(Numeric(4, 2), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    gitlab_issue_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposed_priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    approved_priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    proposed_assignee_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_assignee_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposed_milestone_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approved_milestone_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    proposed_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    approved_due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    dependency_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # What the person doing it last said about it (FR-MCP-06): PLANNED, IN_PROGRESS, DONE or BLOCKED.
    work_status: Mapped[str] = mapped_column(String(16), default="PLANNED", nullable=False)
    work_status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    work_status_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IntegrationProbe(Base):
    """A request to list or check GitLab/GitHub projects, run by the integration worker."""

    __tablename__ = "integration_probes"
    __table_args__ = (
        CheckConstraint("system IN ('GITLAB', 'GITHUB')", name="ck_integration_probe_system"),
        CheckConstraint("action IN ('LIST', 'CHECK', 'MEMBERS', 'TOKENS', 'ACCESS')", name="ck_integration_probe_action"),
        CheckConstraint("status IN ('PENDING', 'DONE', 'FAILED')", name="ck_integration_probe_status"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    system: Mapped[str] = mapped_column(String(16), nullable=False)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    result: Mapped[dict | list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BackupRun(Base):
    """Outcome of one backup. Written by the backup container, read for the System tab."""

    __tablename__ = "backup_runs"
    __table_args__ = (CheckConstraint("status IN ('DONE', 'FAILED')", name="ck_backup_run_status"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    table_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    object_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MailboxScan(Base):
    """One scan of the Daily Report mailbox, on schedule or asked for by the CTO; run by the IMAP worker."""

    __tablename__ = "mailbox_scans"
    __table_args__ = (
        CheckConstraint("trigger IN ('SCHEDULED', 'MANUAL')", name="ck_mailbox_scan_trigger"),
        CheckConstraint("status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED')", name="ck_mailbox_scan_status"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    requested_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PlanningCandidate(Base):
    __tablename__ = "planning_candidates"
    __table_args__ = (
        CheckConstraint(
            "source_type IN ('GITLAB', 'INTAKE', 'PLANE', 'FORM', 'PASTE', 'REPORT', 'VERIFICATION')",
            name="ck_planning_candidate_source_type",
        ),
        CheckConstraint(
            "status IN ('PENDING_TRIAGE', 'READY', 'ASSIGNED', 'REJECTED', 'DONE_ELSEWHERE')",
            name="ck_planning_candidate_status",
        ),
        CheckConstraint(
            "target_slot IS NULL OR target_slot IN ('MORNING', 'AFTERNOON')",
            name="ck_planning_candidate_target_slot",
        ),
        CheckConstraint(
            "requested_hours IS NULL OR (requested_hours > 0 AND requested_hours <= 24)",
            name="ck_planning_candidate_hours",
        ),
        Index("ix_planning_candidate_run_status", "planning_run_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    planning_run_id: Mapped[str] = mapped_column(ID, ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id"), nullable=True)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id"), nullable=True)
    assignment_id: Mapped[str | None] = mapped_column(ID, ForeignKey("planning_assignments.id"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_reference: Mapped[str] = mapped_column(String(512), nullable=False)
    gitlab_issue_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="PENDING_TRIAGE", nullable=False)
    proposed_priority: Mapped[str | None] = mapped_column(String(8), nullable=True)
    requested_hours: Mapped[float | None] = mapped_column(Numeric(4, 2), nullable=True)
    target_slot: Mapped[str | None] = mapped_column(String(16), nullable=True)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PlanningWarning(Base):
    __tablename__ = "planning_warnings"
    __table_args__ = (Index("ix_planning_warning_run_severity", "planning_run_id", "severity"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    planning_run_id: Mapped[str] = mapped_column(ID, ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False)
    assignment_id: Mapped[str | None] = mapped_column(ID, ForeignKey("planning_assignments.id", ondelete="CASCADE"), nullable=True)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id"), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id"), nullable=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    source_values: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    acknowledged_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PlanningApprovalSnapshot(Base):
    __tablename__ = "planning_approval_snapshots"
    __table_args__ = (
        UniqueConstraint("planning_run_id", "run_version", name="uq_planning_snapshot_run_version"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    planning_run_id: Mapped[str] = mapped_column(ID, ForeignKey("planning_runs.id"), nullable=False)
    run_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approved_by: Mapped[str] = mapped_column(ID, ForeignKey("users.id"), nullable=False)
    approved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON_DOCUMENT, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    warning_acknowledgements: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PlanningSyncJob(Base):
    __tablename__ = "planning_sync_jobs"
    __table_args__ = (
        UniqueConstraint(
            "planning_snapshot_id", "project_id", "gitlab_issue_external_id",
            name="uq_planning_sync_snapshot_issue",
        ),
        CheckConstraint("attempt >= 0 AND max_attempts > 0", name="ck_planning_sync_attempts"),
        Index(
            "ix_planning_sync_dispatch",
            "status", "next_attempt_at", "created_at",
            postgresql_where=text("status IN ('PENDING', 'RETRY')"),
        ),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    planning_snapshot_id: Mapped[str] = mapped_column(ID, ForeignKey("planning_approval_snapshots.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    gitlab_issue_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    request_payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    before_state: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    after_state: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_detail_redacted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_project_created", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(32), default="USER", nullable=False)
    actor_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PostDraft(Base):
    """A post written by AI from one idea, for a person to edit, copy and schedule elsewhere (ADR-0031)."""

    __tablename__ = "post_drafts"
    __table_args__ = (
        CheckConstraint("channel IN ('FACEBOOK', 'LINKEDIN', 'THREADS', 'FACEBOOK_GROUP', 'BLOG', 'VIDEO_SCRIPT')", name="ck_post_drafts_channel"),
        CheckConstraint("kind IN ('POST', 'OUTLINE')", name="ck_post_drafts_kind"),
        CheckConstraint("status IN ('PENDING', 'DONE', 'FAILED')", name="ck_post_drafts_status"),
        Index("ix_post_drafts_intake", "intake_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    # An outline is cheap to throw away; a long piece is then written from the one the author kept (ADR-0036).
    kind: Mapped[str] = mapped_column(String(16), default="POST", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    text_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    hooks: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    gaps: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    # What the person asked the draft to stress.
    angle_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Set when this draft adapts another one to a different channel.
    source_draft_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    # Whether the AI may read the original text: only when the person who asked may read it too.
    uses_raw: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Which voice wrote it, and what the post is for (ADR-0035).
    track: Mapped[str | None] = mapped_column(String(32), nullable=True)
    goal: Mapped[str | None] = mapped_column(String(16), nullable=True)
    audience: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pillar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Set when the post was rewritten for a Facebook group of one industry.
    group_context: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # What the idea is (REAL, EXAMPLE, SOURCE) and whether money is behind the piece (SPONSORED, AFFILIATE) (ADR-0042).
    context: Mapped[str | None] = mapped_column(String(16), nullable=True)
    commercial: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Approved means the text is final and locked; it can then be picked up for posting (ADR-0037).
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    posted_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Who said it was posted: the person on the screen, or the posting flow outside calling back.
    posted_via: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # What the posting flow said when it could not post.
    publish_error: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IdeaTrack(Base):
    """Which of the owner's two lines of content an idea belongs to (ADR-0035)."""

    __tablename__ = "idea_tracks"

    intake_id: Mapped[str] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="CASCADE"), primary_key=True)
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PlanSlot(Base):
    """One post a track means to publish in one week: a day, a channel, then the idea and the draft that fill it (ADR-0037)."""

    __tablename__ = "plan_slots"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 1 AND 7", name="ck_plan_slots_weekday"),
        Index("ix_plan_slots_week", "project_id", "week_start", "track"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    weekday: Mapped[int] = mapped_column(Integer, nullable=False)
    time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False)
    pillar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="SET NULL"), nullable=True)
    # The approved draft that fills the slot.
    draft_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    skipped: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # What the AI proposed for this slot, until the person takes it or waves it away.
    suggestion_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PlanRequest(Base):
    """One request for the AI to propose ideas for the open slots of a week."""

    __tablename__ = "plan_requests"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'DONE', 'FAILED')", name="ck_plan_requests_status"),
        Index("ix_plan_requests_week", "project_id", "week_start", "track", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    keywords_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Short keys given to the AI, and the slots and ideas they stand for.
    mapping: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WatchSource(Base):
    """An address the owner wants watched. Intake never opens it: a flow outside reads the list (ADR-0039)."""

    __tablename__ = "watch_sources"
    __table_args__ = (Index("ix_watch_sources_project", "project_id", "created_at"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    # One track, or "both".
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WatchRequest(Base):
    """One request for the AI to suggest keywords for the pillars of a track."""

    __tablename__ = "watch_requests"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'DONE', 'FAILED')", name="ck_watch_requests_status"),
        Index("ix_watch_requests_track", "project_id", "track", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    result: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WatchContact(Base):
    """When the scanning flow outside last read its config, and when it last delivered a signal."""

    __tablename__ = "watch_contacts"

    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), primary_key=True)
    last_config_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_signal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WatchCheck(Base):
    """What one 12-hour check found for a track that asked for signals (ADR-0040)."""

    __tablename__ = "watch_checks"
    __table_args__ = (
        CheckConstraint("status IN ('OK', 'WARNING')", name="ck_watch_checks_status"),
        Index("ix_watch_checks_track", "project_id", "track", "checked_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remaining: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WatchSignal(Base):
    """Something the scanning flow found: public text from the internet, short, untrusted, kept for a month."""

    __tablename__ = "watch_signals"
    __table_args__ = (
        CheckConstraint("state IN ('NEW', 'USED', 'DISMISSED')", name="ck_watch_signals_state"),
        CheckConstraint("via IN ('api', 'scrape', 'agent')", name="ck_watch_signals_via"),
        CheckConstraint("priority IN ('high', 'normal')", name="ck_watch_signals_priority"),
        UniqueConstraint("project_id", "track", "url_hash", name="uq_watch_signals_url"),
        Index("ix_watch_signals_track", "project_id", "track", "state", "received_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(ID, ForeignKey("watch_sources.id", ondelete="SET NULL"), nullable=True)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    url_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    excerpt: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    author: Mapped[str | None] = mapped_column(String(120), nullable=True)
    pillar: Mapped[str | None] = mapped_column(String(120), nullable=True)
    keyword: Mapped[str | None] = mapped_column(String(120), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    state: Mapped[str] = mapped_column(String(16), default="NEW", nullable=False)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="SET NULL"), nullable=True)
    # How it was found (an official API, a scraping service, or the owner's own agent) and whether its keyword was a priority one (FR-MKT-09).
    via: Mapped[str] = mapped_column(String(8), default="api", nullable=False)
    priority: Mapped[str] = mapped_column(String(8), default="normal", nullable=False)


class WatchPlatform(Base):
    """A network the scanning flow may read, as the CTO opened it for the whole system (FR-MKT-08): on or off, and
    whether it is read through an official API or a scraping service the CTO runs outside Intake."""

    __tablename__ = "watch_platforms"
    __table_args__ = (CheckConstraint("via IN ('api', 'scrape', 'none')", name="ck_watch_platforms_via"),)

    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    via: Mapped[str] = mapped_column(String(8), default="none", nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WatchConnector(Base):
    """One door through which an outside service pushes findings into a marketing project (FR-MKT-13): its own
    secret, how its payload maps to signals, and how it has been doing. Intake never calls the service back."""

    __tablename__ = "watch_connectors"
    __table_args__ = (
        CheckConstraint("kind IN ('GENERIC', 'N8N', 'MAKE', 'APIFY', 'MENTION')", name="ck_watch_connectors_kind"),
        CheckConstraint("via IN ('api', 'scrape')", name="ck_watch_connectors_via"),
        Index("ix_watch_connectors_project", "project_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), default="GENERIC", nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(12), nullable=False)
    via: Mapped[str] = mapped_column(String(8), default="api", nullable=False)
    default_pillar: Mapped[str | None] = mapped_column(String(60), nullable=True)
    mapping: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    received_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WatchDelivery(Base):
    """One call to a connector's door: what came of it, for the CTO's log. The payload itself is not kept."""

    __tablename__ = "watch_deliveries"
    __table_args__ = (
        CheckConstraint("status IN ('ACCEPTED', 'EMPTY', 'INVALID', 'UNAUTHORIZED')", name="ck_watch_deliveries_status"),
        Index("ix_watch_deliveries_connector", "connector_id", "at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    connector_id: Mapped[str] = mapped_column(ID, ForeignKey("watch_connectors.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    accepted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)


class AppSetting(Base):
    """One system-wide setting the CTO edits on a screen, by key (FR-MKT-10): the first is the daily cap on AI runs
    per marketing project."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | int | str | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class GithubToken(Base):
    """A GitHub token added on a screen, stored encrypted; it never comes back out (FR-INTG-21, ADR-0076)."""

    __tablename__ = "github_tokens"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    updated_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class GitlabConnection(Base):
    """The company GitLab connected on a screen: one row, token encrypted, never read back (FR-INTG-22, ADR-0080)."""

    __tablename__ = "gitlab_connection"
    __table_args__ = (CheckConstraint("id = 'default'", name="ck_gitlab_connection_single"),)

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="default")
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    token_enc: Mapped[str] = mapped_column(Text, nullable=False)
    key_hint: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    updated_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ShowcaseEnabled(Base):
    """A showcase catalogue item the CTO switched on (FR-SETUP-15): which project it created. Switching off only
    archives that project, so this row is kept and switching on again restores the same project."""

    __tablename__ = "showcase_enabled"

    item_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    catalog_version: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    enabled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AiProvider(Base):
    """One OpenAI-compatible LLM endpoint the CTO added on the AI settings tab (FR-AI-15, ADR-0070). The key is
    Fernet-encrypted and never leaves the API; `name` is what extractions record as their provider."""

    __tablename__ = "ai_providers"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    name: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(String(300), nullable=False)
    api_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_body: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)


class AiRoute(Base):
    """Which provider and model serve one task, or `default` for the tasks without a row (FR-AI-17)."""

    __tablename__ = "ai_routes"
    __table_args__ = (
        CheckConstraint("task IN ('default', 'normalize', 'report', 'meeting', 'vision', 'content', 'stt')", name="ck_ai_routes_task"),
    )

    task: Mapped[str] = mapped_column(String(16), primary_key=True)
    provider_id: Mapped[str] = mapped_column(ID, ForeignKey("ai_providers.id"), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)


class AiModelCheck(Base):
    """The last sample-picture or sample-sound check of one provider's model (FR-AI-21, ADR-0077)."""

    __tablename__ = "ai_model_checks"
    __table_args__ = (CheckConstraint("kind IN ('vision', 'stt')", name="ck_ai_model_checks_kind"),)

    provider_id: Mapped[str] = mapped_column(ID, ForeignKey("ai_providers.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    ok: Mapped[bool] = mapped_column(Boolean, nullable=False)
    error: Mapped[str | None] = mapped_column(String(32), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WatchTopic(Base):
    """A subject several signals point at this week, scored by rule and summed up by AI, waiting for the owner to
    make a post of it or drop it (FR-MKT-09). The same subject built twice in a week lands on the same row."""

    __tablename__ = "watch_topics"
    __table_args__ = (
        CheckConstraint("state IN ('NEW', 'USED', 'DISMISSED')", name="ck_watch_topics_state"),
        UniqueConstraint("project_id", "week_start", "key", name="uq_watch_topics_key"),
        Index("ix_watch_topics_project", "project_id", "state", "score"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    why: Mapped[str | None] = mapped_column(String(400), nullable=True)
    angles: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    channels: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    caution: Mapped[str | None] = mapped_column(String(300), nullable=True)
    pillar: Mapped[str | None] = mapped_column(String(60), nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    signal_ids: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    state: Mapped[str] = mapped_column(String(16), default="NEW", nullable=False)
    work_id: Mapped[str | None] = mapped_column(ID, ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    ai_written: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TrackNote(Base):
    """One line of the author's notebook for a track: something the AI may rely on when it writes (ADR-0036)."""

    __tablename__ = "track_notes"
    __table_args__ = (
        CheckConstraint("kind IN ('FACT', 'PROOF', 'DECISION', 'RESULT')", name="ck_track_notes_kind"),
        Index("ix_track_notes_track", "project_id", "track", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    track: Mapped[str] = mapped_column(String(32), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    text_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Meeting(Base):
    __tablename__ = "meetings"
    __table_args__ = (
        CheckConstraint("status IN ('RECORDING', 'FINISHED', 'FAILED')", name="ck_meetings_status"),
        CheckConstraint("source IN ('TAB_AND_MIC', 'MIC', 'FILE')", name="ck_meetings_source"),
        Index("ix_meetings_started", "started_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="RECORDING", nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    language: Mapped[str] = mapped_column(String(16), default="vi", nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audio_chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    audio_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    audio_content_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    transcript_status: Mapped[str] = mapped_column(String(16), default="NONE", nullable=False)
    transcript_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transcript_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    transcript_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_transcription_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    provider_deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note_status: Mapped[str] = mapped_column(String(16), default="NONE", nullable=False)
    note_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    note_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    note_summary_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    # MEETING: several people, separated by speaker afterwards and summarised into a note.
    # DICTATION: one person speaking a request; kept as the source of an Intake, with neither of those steps.
    kind: Mapped[str] = mapped_column(String(16), default="MEETING", server_default="MEETING", nullable=False)
    # A live recording past the limit goes on as the next part of the same meeting (FR-REC-17).
    series_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    part_number: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    # The spoken words rewritten as a short request, made only when asked for.
    rewrite_status: Mapped[str] = mapped_column(String(16), default="NONE", server_default="NONE", nullable=False)
    rewrite_text_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    rewrite_error: Mapped[str | None] = mapped_column(String(128), nullable=True)
    speaker_names: Mapped[dict] = mapped_column(JSON_DOCUMENT, default=dict, nullable=False)
    purge_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MeetingNoteItem(Base):
    __tablename__ = "meeting_note_items"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('DECISION', 'REQUIREMENT', 'BUG', 'SCOPE_CHANGE', 'ACTION', 'QUESTION', 'RISK')",
            name="ck_meeting_note_items_kind",
        ),
        Index("ix_meeting_note_items_meeting", "meeting_id", "position"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ID, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    detail_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    due_text: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # The subject of the meeting this item belongs to; None for notes written before subjects existed.
    topic: Mapped[str | None] = mapped_column(String(120), nullable=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id"), nullable=True)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id"), nullable=True)
    edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class MeetingSegment(Base):
    __tablename__ = "meeting_segments"
    __table_args__ = (
        UniqueConstraint("meeting_id", "source", "sequence", name="uq_meeting_segments_order"),
        CheckConstraint("source IN ('REALTIME', 'BATCH')", name="ck_meeting_segments_source"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    meeting_id: Mapped[str] = mapped_column(ID, ForeignKey("meetings.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    start_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    term: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class BoardDailySnapshot(Base):
    """The morning board of one project as it stood at the end of a day (FR-PLAN-30, ADR-0053).

    The board counts things that are true now; this keeps what was true each evening so the week page can say how
    long work waited and how often the day had enough data to review."""

    __tablename__ = "board_daily_snapshots"
    __table_args__ = (
        UniqueConstraint("snapshot_date", "project_id", name="uq_board_daily_snapshot"),
        Index("ix_board_daily_snapshot_date", "snapshot_date"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    readiness_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reports_expected: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reports_received: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    reports_late: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approvals_pending: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approvals_cto: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    approvals_overdue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waiting: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    waiting_overdue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unsynced: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stuck: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    work_log_pending: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    work_log_overdue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    p0_open: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    p0_open_overdue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    plan_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    assigned_hours: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    available_hours: Mapped[float] = mapped_column(Numeric(6, 2), default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class Holiday(Base):
    """A day the reminders stay silent, besides weekends (FR-NTF-04)."""

    __tablename__ = "holidays"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TelegramMessage(Base):
    """One reminder sent (or not) to one chat for one day and slot; the row is what keeps a slot from going twice (FR-NTF-05)."""

    __tablename__ = "telegram_messages"
    __table_args__ = (
        UniqueConstraint("kind", "chat_id", "thread_id", "for_date", "slot", name="uq_telegram_message_slot"),
        Index("ix_telegram_messages_date", "for_date", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    project_id: Mapped[str | None] = mapped_column(ID, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="SET NULL"), nullable=True)
    for_date: Mapped[date] = mapped_column(Date, nullable=False)
    slot: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class TelegramState(Base):
    """The bot's own bookkeeping: the update offset, its username, when it was last seen."""

    __tablename__ = "telegram_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PersonalTask(Base):
    """A person's own task for a day, outside any project (FR-PER-01). Only its owner reads it; its hours come off
    the person's free hours; a reminder may go to their Telegram."""

    __tablename__ = "personal_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('PLANNED', 'DONE', 'SKIPPED', 'DELEGATED')", name="ck_personal_tasks_status"),
        Index("ix_personal_tasks_user_date", "user_id", "task_date"),
        Index("ix_personal_tasks_member_date", "member_id", "task_date"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="SET NULL"), nullable=True)
    # No date yet: the task waits in the matrix to be scheduled (FR-PER-05).
    task_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    hours: Mapped[float] = mapped_column(Numeric(4, 2), default=0, nullable=False)
    # How many nights the task rolled to the next working day unfinished; archived when the drop quadrant kept it 7 days.
    rollover_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Handed to a staff member: the work sits in their day plan (FR-PER-06).
    delegated_member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="SET NULL"), nullable=True)
    delegated_assignment_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    # WEEKLY:<0-6> (Monday 0) or MONTHLY:<1-31>; the next occurrence is made when this one is finished.
    repeat_rule: Mapped[str | None] = mapped_column(String(16), nullable=True)
    repeat_parent_id: Mapped[str | None] = mapped_column(ID, nullable=True)
    # The quadrant the task was in when it was finished, for the week's numbers.
    done_quadrant: Mapped[int | None] = mapped_column(Integer, nullable=True)
    start_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    remind_at: Mapped[str | None] = mapped_column(String(5), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="PLANNED", nullable=False)
    # Eisenhower (FR-PER-04): important is the person's call; urgent None means the date decides.
    important: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    urgent: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class ProjectContextSnapshot(Base):
    """The project context pack as last read from the main repository, split and scored (ADR-0063)."""

    __tablename__ = "project_context_snapshots"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), unique=True, nullable=False)
    source: Mapped[str] = mapped_column(Text, default="REPO", nullable=False)
    path: Mapped[str] = mapped_column(Text, default="docs/agent/CONTEXT.md", nullable=False)
    sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    meta: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    sections: Mapped[dict | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    band: Mapped[str] = mapped_column(Text, default="MISSING", nullable=False)
    missing: Mapped[list | None] = mapped_column(JSON_DOCUMENT, nullable=True)
    stale_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_sha: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    def content_hash(self) -> str:
        import hashlib

        return hashlib.sha256((self.content or "").encode("utf-8")).hexdigest()


class ProjectContextSuggestion(Base):
    """One thing an agent or a person found missing or wrong in the context pack while working (FR-CTX-04)."""

    __tablename__ = "project_context_suggestions"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="SET NULL"), nullable=True)
    work_log_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_work_log.id", ondelete="SET NULL"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    suggested_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    agent_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(Text, default="PENDING", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class FeedbackItem(Base):
    """A suggestion from a member who is not the Project Owner: words and pictures waiting for the owner's yes or no
    before anything becomes a request (FR-FBK-01..03, ADR-0064)."""

    __tablename__ = "feedback_items"
    __table_args__ = (
        CheckConstraint("status IN ('PENDING', 'ACCEPTED', 'REJECTED')", name="ck_feedback_items_status"),
        CheckConstraint("transport IN ('WEB', 'TELEGRAM', 'AGENT')", name="ck_feedback_items_transport"),
        Index("ix_feedback_items_project_status", "project_id", "status", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id"), nullable=True)
    user_id: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    transport: Mapped[str] = mapped_column(String(16), default="WEB", nullable=False)
    text_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="PENDING", nullable=False)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="SET NULL"), nullable=True)
    decided_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    idempotency_key_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class FeedbackFile(Base):
    """A picture or PDF on a suggestion; the bytes live in object storage, copied to the request when accepted."""

    __tablename__ = "feedback_files"

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    feedback_id: Mapped[str] = mapped_column(ID, ForeignKey("feedback_items.id", ondelete="CASCADE"), nullable=False)
    object_key: Mapped[str] = mapped_column(String(512), unique=True, nullable=False)
    name_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class IssueEvidenceLink(Base):
    """One piece of evidence a person or an agent attached to an Issue: a commit, a merge request, or a link to a
    document, video or picture (FR-PLAN-36, ADR-0065). The read model's own traces live on the Issue snapshot."""

    __tablename__ = "issue_evidence_links"
    __table_args__ = (
        CheckConstraint("kind IN ('COMMIT', 'MR', 'LINK')", name="ck_issue_evidence_links_kind"),
        CheckConstraint("source IN ('WORKER', 'ACCEPTOR', 'AGENT', 'WORK_LOG', 'REPORT')", name="ck_issue_evidence_links_source"),
        Index("ix_issue_evidence_links_issue", "project_id", "issue_external_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    issue_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    added_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkItem(Base):
    """A piece of work the team tracks inside Intake instead of an external board (FR-WRK-01..06, ADR-0066):
    non-code work, or a feature that must be discussed before it becomes an Issue. It moves across six columns;
    once it has become an Issue it stays closed."""

    __tablename__ = "work_items"
    __table_args__ = (
        UniqueConstraint("project_id", "seq", name="uq_work_items_project_seq"),
        CheckConstraint(
            "status IN ('DISCUSS', 'READY', 'IN_PROGRESS', 'ACCEPTANCE', 'APPROVED', 'DONE', 'CANCELLED')", name="ck_work_items_status",
        ),
        CheckConstraint("priority IN ('P0', 'P1', 'P2', 'P3')", name="ck_work_items_priority"),
        CheckConstraint("outcome IS NULL OR outcome IN ('ISSUE_PENDING', 'ISSUE')", name="ck_work_items_outcome"),
        Index("ix_work_items_project_status", "project_id", "status", "updated_at"),
        Index("ix_work_items_intake", "intake_id"),
        Index("ix_work_items_parent", "parent_id", "step_order"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    project_id: Mapped[str] = mapped_column(ID, ForeignKey("projects.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="DISCUSS", nullable=False)
    priority: Mapped[str] = mapped_column(String(2), default="P3", nullable=False)
    member_id: Mapped[str | None] = mapped_column(ID, ForeignKey("workforce_members.id", ondelete="SET NULL"), nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    intake_id: Mapped[str | None] = mapped_column(ID, ForeignKey("intake_items.id", ondelete="SET NULL"), nullable=True)
    issue_system: Mapped[str | None] = mapped_column(String(16), nullable=True)
    issue_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(16), nullable=True)
    closed_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    # A pipeline (FR-WRK-08): the parent carries the template, each step is a child with its place in the order.
    parent_id: Mapped[str | None] = mapped_column(ID, ForeignKey("work_items.id", ondelete="SET NULL"), nullable=True)
    template: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    step_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # A post for a marketing project (FR-MKT-01): its main channel, format, campaign label and the Gấp flag.
    channel: Mapped[str | None] = mapped_column(String(24), nullable=True)
    format: Mapped[str | None] = mapped_column(String(16), nullable=True)
    campaign: Mapped[str | None] = mapped_column(String(80), nullable=True)
    urgent: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkChannel(Base):
    """One rendering of a post for one channel (FR-MKT-01): its own publish date, state and, once out, the link."""

    __tablename__ = "work_channels"
    __table_args__ = (
        UniqueConstraint("work_id", "channel", name="uq_work_channels_work_channel"),
        CheckConstraint("status IN ('DRAFT', 'READY', 'PUBLISHED')", name="ck_work_channels_status"),
        Index("ix_work_channels_channel_time", "channel", "publish_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    work_id: Mapped[str] = mapped_column(ID, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    channel: Mapped[str] = mapped_column(String(24), nullable=False)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="DRAFT", nullable=False)
    published_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)
    # The words of this version, counted against the channel's rule before the post goes for review (FR-MKT-11).
    text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PostLink(Base):
    """The short link of one channel version (FR-MKT-12): Intake redirects it to the page the post points at, with UTM
    tags, and counts the clicks itself, so every channel is measured with one ruler."""

    __tablename__ = "post_links"
    __table_args__ = (UniqueConstraint("work_channel_id", name="uq_post_links_version"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    work_channel_id: Mapped[str] = mapped_column(ID, ForeignKey("work_channels.id", ondelete="CASCADE"), nullable=False)
    code: Mapped[str] = mapped_column(String(12), unique=True, nullable=False)
    target_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class PostClick(Base):
    """One click on a short link: when, from which site, and whether a crawler made it. No address of the visitor."""

    __tablename__ = "post_clicks"
    __table_args__ = (Index("ix_post_clicks_link_time", "link_id", "at"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    link_id: Mapped[str] = mapped_column(ID, ForeignKey("post_links.id", ondelete="CASCADE"), nullable=False)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    referrer_host: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_bot: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ChannelRule(Base):
    """What a channel allows (FR-MKT-02): lengths, images, hashtags, links, language, good hours. Edited by the CTO
    in settings, read by counters and, later, by the AI that writes channel versions."""

    __tablename__ = "channel_rules"

    code: Mapped[str] = mapped_column(String(24), primary_key=True)
    label: Mapped[str] = mapped_column(String(60), nullable=False)
    language: Mapped[str] = mapped_column(String(8), default="vi", nullable=False)
    max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    recommended_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    long_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_images: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_ratio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    video_ratio: Mapped[str | None] = mapped_column(String(40), nullable=True)
    hashtag_max: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    link_counts_chars: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    link_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    best_hours: Mapped[list] = mapped_column(JSON_DOCUMENT, default=list, nullable=False)
    tone: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Whether approved, ready versions of this channel go to the posting flow's queue (FR-MKT-14).
    auto_publish: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkComment(Base):
    """A line of discussion on a work item between the owner, the CTO and the people doing it (FR-WRK-04)."""

    __tablename__ = "work_comments"
    __table_args__ = (Index("ix_work_comments_work", "work_id", "created_at"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    work_id: Mapped[str] = mapped_column(ID, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    body_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class WorkLink(Base):
    """A link attached to a work item: the Drive folder, the Canva design, the cut, the published post (FR-WRK-07).
    Intake keeps the address and a note, never the file."""

    __tablename__ = "work_links"
    __table_args__ = (
        CheckConstraint("source IN ('USER', 'AGENT')", name="ck_work_links_source"),
        Index("ix_work_links_work", "work_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    work_id: Mapped[str] = mapped_column(ID, ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="USER", nullable=False)
    added_by: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    # A file from the computer instead of an address (FR-WRK-10): the bytes sit in object storage, `url` is the download path.
    object_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)


class UserHintDismissal(Base):
    """"Đã hiểu" on a page introduction: the person saw it and does not need it again on any device (FR-UI-17)."""

    __tablename__ = "user_hint_dismissals"

    user_id: Mapped[str] = mapped_column(ID, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    dismissed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class HintOpen(Base):
    """One line each time a person opens a hint (FR-UI-17): the week shows which hints are reached for."""

    __tablename__ = "hint_opens"
    __table_args__ = (Index("ix_hint_opens_key_time", "key", "opened_at"),)

    id: Mapped[str] = mapped_column(ID, primary_key=True)
    user_id: Mapped[str | None] = mapped_column(ID, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
