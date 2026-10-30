from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# AGENT: written by Codex, Claude or another agent through MCP, as the person whose token it carries.
Channel = Literal["ZALO", "WHATSAPP", "EMAIL", "MEETING", "MANUAL", "AGENT", "TELEGRAM", "FEEDBACK"]
IntakeType = Literal[
    "QUESTION",
    "BUG",
    "TASK",
    "FEATURE",
    "SCOPE_CHANGE",
    "FEEDBACK",
    "UNCLEAR",
]
IntakeStatus = Literal[
    "NEW",
    "PROCESSING",
    "PENDING_APPROVAL",
    "NEEDS_INFORMATION",
    "PROCESSING_FAILED",
    "DEFERRED",
    "APPROVED",
    "REJECTED",
    "SYNC_PENDING",
    "SYNCED",
    "CLOSED",
]
IntakeLifecycleStage = Literal[
    "RECEIVED",
    "NEEDS_INFORMATION",
    "PENDING_APPROVAL",
    "WAITING_PLANNING",
    "IN_PROGRESS",
    "PENDING_ACCEPTANCE",
    "ACCEPTED",
    "STOPPED",
]
Priority = Literal["P0", "P1", "P2", "P3"]
# PLANE stays readable for requests decided before ADR-0066; new decisions use WORK instead.
Route = Literal["RESPONSE", "WORK", "PLANE", "GITLAB", "GITHUB", "NEEDS_INFO"]


class IntakeCreate(BaseModel):
    project_id: str = Field(..., description="UUID or project code")
    channel: Channel
    raw_text: str | None = None
    sender_reference: str | None = None
    received_at: datetime | None = None
    # Only the CTO's value counts: acceptance of this work always comes back to the CTO (FR-PLAN-39).
    needs_cto_acceptance: bool = False


class FeedbackCreate(BaseModel):
    """A suggestion from a member: which project, what should be done (FR-FBK-01)."""

    project: str = Field(..., min_length=1, max_length=64, description="Project code or id")
    text: str = Field(..., min_length=5, max_length=20000)


class FeedbackDecision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class FeedbackFileOut(BaseModel):
    id: str
    name: str | None = None
    mime_type: str
    size_bytes: int


class FeedbackOut(BaseModel):
    """A suggestion as the owner and the person see it (FR-FBK-02)."""

    id: str
    project_id: str
    project_code: str | None = None
    project_name: str | None = None
    member_id: str | None = None
    member_name: str | None = None
    user_id: str | None = None
    transport: str
    text: str
    status: str
    intake_id: str | None = None
    intake_public_id: str | None = None
    decided_by: str | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None
    files: list[FeedbackFileOut] = Field(default_factory=list)
    created_at: datetime


class IntakeDecision(BaseModel):
    approved_route: Route
    approved_priority: Priority
    reason: str | None = None
    expected_version: int
    # None keeps the flag as it is; only the CTO can change it (FR-PLAN-39).
    needs_cto_acceptance: bool | None = None


class IntakeReopenRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=2000)
    expected_version: int = Field(..., ge=1)


class ApprovalSourceWeek(BaseModel):
    week_start: date
    from_queue: int
    from_planning: int


class IntakeReview(BaseModel):
    normalized_title: str = Field(..., min_length=1, max_length=255)
    normalized_summary: str = Field(..., min_length=1, max_length=20_000)
    suggested_priority: Priority
    proposed_route: Route
    expected_version: int = Field(..., ge=1)
    details: IntakeDetailsEdit | None = None


class IntakeAction(BaseModel):
    reason: str | None = None
    defer_until: datetime | None = None
    expected_version: int


class ApprovalDecisionOut(BaseModel):
    """One decision taken on a request (FR-APR-15): who, when, what, why; and what the request is now."""

    id: str
    at: datetime
    action: str
    source: str = "QUEUE"
    actor_id: str | None = None
    actor_name: str | None = None
    reason: str | None = None
    intake_id: str
    public_id: str
    title: str
    status: str
    project_id: str
    project_code: str
    project_name: str
    approved_route: str | None = None
    approved_priority: str | None = None


class ApprovalDecisionPage(BaseModel):
    items: list[ApprovalDecisionOut] = Field(default_factory=list)
    # Pass as `before` to read older decisions; absent when the page was not full.
    next_before: datetime | None = None
    # The start of the window the page covers; absent when `before` was used.
    since: datetime | None = None


class IntakeSyncSummary(BaseModel):
    system: Literal["PLANE", "GITLAB", "GITHUB"]
    status: Literal["PENDING", "RUNNING", "RETRY", "SUCCEEDED", "FAILED"]
    external_id: str | None = None
    sequence_id: str | None = None
    external_url: str | None = None
    error_code: str | None = None
    updated_at: datetime
    # The decision this sync belonged to was taken back; the item is still out there (FR-APR-10).
    superseded: bool = False


class IntakeRelatedIssue(BaseModel):
    id: str
    title: str | None = None
    url: str | None = None


class IntakeClarification(BaseModel):
    """One question AI raised, settled by the team: answered, or marked as not needed."""

    question: str = Field(..., min_length=1, max_length=300)
    answer: str | None = Field(default=None, max_length=1000)
    skipped: bool = False


class IntakeClarify(BaseModel):
    expected_version: int = Field(..., ge=1)
    answers: list[IntakeClarification] = Field(default_factory=list, max_length=12)
    # Ask AI to read the request again with the answers.
    reanalyse: bool = False


class IntakeReady(BaseModel):
    expected_version: int = Field(..., ge=1)


class IntakeDetails(BaseModel):
    """What a developer needs to start, beyond the summary (FR-AI-12)."""

    where: str | None = None
    steps: list[str] = Field(default_factory=list)
    expected: str | None = None
    subtasks: list[str] = Field(default_factory=list)
    acceptance: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    related: list[IntakeRelatedIssue] = Field(default_factory=list)
    split_suggested: bool = False
    clarifications: list["IntakeClarification"] = Field(default_factory=list)


class IntakeDetailsEdit(BaseModel):
    """The parts a reviewer may change. Steps, expected result, questions and related issues stay as proposed."""

    where: str | None = Field(default=None, max_length=600)
    subtasks: list[str] = Field(default_factory=list, max_length=12)
    acceptance: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("where")
    @classmethod
    def _blank_is_none(cls, value: str | None) -> str | None:
        return (value or "").strip() or None

    @field_validator("subtasks", "acceptance")
    @classmethod
    def _clean_lines(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(item.split()) for item in value if item and item.strip()]
        if any(len(item) > 300 for item in cleaned):
            raise ValueError("A line is at most 300 characters")
        return cleaned


class IntakeDuplicate(BaseModel):
    expected_version: int = Field(..., ge=1)
    # The request that is kept: its code (SAV-26W41-003) or its ID.
    of: str = Field(..., min_length=3, max_length=64)


class IntakeDuplicateIssue(BaseModel):
    expected_version: int = Field(..., ge=1)
    # The Issue that already covers this request, as its number at the delivery system ("22" or "#22").
    issue: str = Field(..., min_length=1, max_length=64)


class IntakeDeleted(BaseModel):
    deleted: bool
    public_id: str
    attachments_left: int = 0


class IntakeSplit(BaseModel):
    """Turn one request with several unrelated asks into one request per ask (FR-APR-09)."""

    expected_version: int = Field(..., ge=1)
    items: list[str] = Field(..., min_length=2, max_length=8)

    @field_validator("items")
    @classmethod
    def _clean_items(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(item.split()) for item in value if item and item.strip()]
        if len(cleaned) < 2:
            raise ValueError("Splitting needs at least two items")
        if any(len(item) > 300 for item in cleaned):
            raise ValueError("An item is at most 300 characters")
        return cleaned


class IntakeSplitOut(BaseModel):
    original: "IntakeOut"
    children: list["IntakeOut"]


class ProjectContextSection(BaseModel):
    number: int
    title: str
    required: bool
    to_ai: bool
    present: bool
    lines: int


class ProjectContextOut(BaseModel):
    """The project's context pack as last read: where from, what it has, the score (FR-CTX-03)."""

    project_id: str
    source: str
    path: str
    sha: str | None = None
    fetched_at: datetime | None = None
    meta: dict = Field(default_factory=dict)
    sections: dict[str, ProjectContextSection] = Field(default_factory=dict)
    score: int
    band: str
    missing: list[str] = Field(default_factory=list)
    stale_days: int | None = None
    error: str | None = None
    has_content: bool = False
    approved: bool = False
    approved_sha: str | None = None
    approved_at: datetime | None = None
    content: str | None = None
    pending_suggestions: int = 0


class ProjectContextSuggestionOut(BaseModel):
    """One thing found missing in the pack while working; PENDING until the CTO marks it APPLIED or DISMISSED (FR-CTX-04)."""

    id: str
    project_id: str
    intake_id: str | None = None
    intake_public_id: str | None = None
    work_log_id: str | None = None
    text: str
    suggested_by: str | None = None
    suggested_by_name: str | None = None
    agent_name: str | None = None
    status: str
    decided_by: str | None = None
    decided_by_name: str | None = None
    decided_at: datetime | None = None
    created_at: datetime


class ProjectContextPaste(BaseModel):
    content: str = Field(..., min_length=1, max_length=60 * 1024)


class ProjectReportCodes(BaseModel):
    """The other codes staff write for a project in daily reports (FR-EML-12)."""

    codes: list[str] = Field(default_factory=list, max_length=20)


class ProjectBrief(BaseModel):
    """What the product is, in the team's own words: reference for AI when it reads a request (FR-AI-12)."""

    brief: str = Field(default="", max_length=4000)


class ProjectBriefOut(ProjectBrief):
    """The brief plus which source AI actually reads (FR-CTX-05): PACK when the approved context pack supplies
    sections 1 and 2, otherwise BRIEF (this field, possibly empty)."""

    ai_source: str = "BRIEF"
    pack_approved_at: datetime | None = None
    pack_sections: list[str] = Field(default_factory=list)


class AgentReadiness(BaseModel):
    score: int = Field(..., ge=0, le=100)
    band: Literal["READY", "NEEDS_WORK", "HUMAN"]
    reasons: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)


class WorkRef(BaseModel):
    """The work item a request became when approved for the WORK route (FR-WRK-06)."""

    id: str
    code: str
    status: str
    project_id: str


class IntakeOut(BaseModel):
    id: str
    public_id: str
    project_id: str
    channel: Channel
    item_type: IntakeType = "UNCLEAR"
    status: IntakeStatus = "NEW"
    # A management-facing stage derived from Intake, planning, work and acceptance state.
    lifecycle_stage: IntakeLifecycleStage = "RECEIVED"
    normalized_title: str | None = None
    normalized_summary: str | None = None
    details: IntakeDetails | None = None
    # Set when this request was closed as a repeat of another one.
    duplicate_of_id: str | None = None
    duplicate_of: dict | None = None
    # Set when the request was closed as a repeat of an Issue that already exists at the delivery system (FR-APR-12):
    # system, external_id, title, url.
    duplicate_issue: dict | None = None
    suggested_priority: Priority | None = None
    proposed_route: Route | None = None
    approved_priority: Priority | None = None
    approved_route: Route | None = None
    sync_targets: list[IntakeSyncSummary] = Field(default_factory=list)
    work_item: WorkRef | None = None
    fix_hints: str | None = None
    needs_cto_acceptance: bool = False
    # Whether an agent could take this as it stands (FR-MCP-04).
    agent_readiness: AgentReadiness | None = None
    # Who should decide it while it waits for approval, and whether it has waited too long (FR-APR-14).
    approval_owner: Literal["CTO", "PO"] | None = None
    approval_overdue: bool = False
    version: int = 1
    created_at: datetime
    updated_at: datetime


class IntakeWorkLogDetails(BaseModel):
    cause: str | None = Field(default=None, max_length=500)
    changes: list[str] = Field(default_factory=list, max_length=20)
    tests: str | None = Field(default=None, max_length=500)
    branch: str | None = Field(default=None, max_length=200)
    commit: str | None = Field(default=None, max_length=200)
    verify_steps: list[str] = Field(default_factory=list, max_length=20)
    deploy_steps: list[str] = Field(default_factory=list, max_length=20)
    # Actual work is deliberately separate from Daily Planning: it describes what happened, not planned capacity.
    worked_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    actual_minutes: int | None = Field(default=None, ge=0, le=1440)
    deployed: bool | None = None
    # What the project's context pack lacked while doing this (FR-CTX-04); the CTO decides on the project page.
    context_suggestions: list[str] = Field(default_factory=list, max_length=10)


class IntakeWorkLogCreate(BaseModel):
    summary: str = Field(..., min_length=5, max_length=1000)
    details: IntakeWorkLogDetails = Field(default_factory=IntakeWorkLogDetails)
    agent_name: str | None = Field(default=None, max_length=80)


class IntakeWorkLogReview(BaseModel):
    decision: Literal["CONFIRMED", "RETURNED"]
    note: str | None = Field(default=None, max_length=1000)


class IntakeWorkLogOut(BaseModel):
    id: str
    intake_id: str
    project_id: str
    actor_id: str | None = None
    actor_name: str | None = None
    agent_name: str | None = None
    summary: str
    details: IntakeWorkLogDetails = Field(default_factory=IntakeWorkLogDetails)
    review_decision: Literal["PENDING", "CONFIRMED", "RETURNED"]
    review_note: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    created_at: datetime


class IntakeFixHints(BaseModel):
    fix_hints: str | None = Field(default=None, max_length=2000)


class IntakeHardFlag(BaseModel):
    needs_cto_acceptance: bool


class IntakeListSummary(BaseModel):
    total_items: int = 0
    p0_attention: int = 0
    p1_attention: int = 0
    pending_approval: int = 0
    sync_failed: int = 0


class IntakePage(BaseModel):
    items: list[IntakeOut]
    next_cursor: str | None = None
    limit: int
    summary: IntakeListSummary = Field(default_factory=IntakeListSummary)


class PipelineStageOut(BaseModel):
    run_id: str
    stage: str
    run_type: str
    status: str
    attempt: int
    worker_id: str | None = None
    retryable: bool
    queued_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_code: str | None = None


class PipelineStatusOut(BaseModel):
    intake_id: str
    public_id: str
    intake_status: IntakeStatus
    overall_state: str
    stages: list[PipelineStageOut]


class SyncJobOut(BaseModel):
    id: str
    approval_snapshot_id: str
    target_system: Literal["PLANE", "GITLAB", "GITHUB"]
    status: Literal["PENDING", "RUNNING", "RETRY", "SUCCEEDED", "FAILED"]
    attempt: int
    max_attempts: int
    error_code: str | None = None
    external_id: str | None = None
    external_url: str | None = None
    created_at: datetime
    updated_at: datetime


class SyncStatusOut(BaseModel):
    intake_id: str
    snapshot_id: str | None = None
    target_system: Literal["PLANE", "GITLAB", "GITHUB"] | None = None
    sync_available: bool
    reason: str | None = None
    job: SyncJobOut | None = None


class HealthResponse(BaseModel):
    status: str
    app_name: str
    project_name: str
    environment: str


class ApiTokenCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="Where the token is used, e.g. 'Codex máy làm việc'")


class ChangelogBuild(BaseModel):
    sha: str
    built_at: str | None = None


class ChangelogEntry(BaseModel):
    date: date
    title: str
    commits: list[str] = Field(default_factory=list)
    refs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    cto_only: bool = False


class ChangelogOut(BaseModel):
    build: ChangelogBuild
    latest: date | None = None
    entries: list[ChangelogEntry] = Field(default_factory=list)
    # Entries newer than the running build; None when unknown or not the CTO (FR-UI-15).
    behind: int | None = None


class ApiTokenOut(BaseModel):
    id: str
    name: str
    prefix: str
    created_at: datetime
    last_used_at: datetime | None = None
    expires_at: datetime | None = None


class ApiTokenIssued(ApiTokenOut):
    # Shown once; only its hash is kept.
    token: str


class LoginRequest(BaseModel):
    subject: str
    password: str
    otp: str | None = Field(default=None, min_length=6, max_length=6)
    recovery_code: str | None = Field(default=None, min_length=17, max_length=17)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class MfaCodeRequest(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class MfaStepUpRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    otp: str | None = Field(default=None, min_length=6, max_length=6)


class MfaSetupResponse(BaseModel):
    secret: str
    issuer: str
    subject: str


class RecoveryCodesResponse(BaseModel):
    recovery_codes: list[str]


PlanningSlot = Literal["MORNING", "AFTERNOON"]
PlanningWorkType = Literal["DEVELOPMENT", "REVIEW", "QA", "SUPPORT", "MEETING", "FIXED"]
PlanningQuickAddMode = Literal["EXISTING", "FORM", "PASTE"]
PlanningQuickAddSource = Literal["GITLAB", "INTAKE"]


class WorkforceProjectMappingIn(BaseModel):
    project_id: str
    gitlab_user_external_id: str = Field(..., min_length=1, max_length=255)
    role: str | None = Field(default=None, max_length=64)


class WorkforceMemberCreate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    email_reference: str | None = Field(default=None, max_length=320)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", max_length=64)
    default_weekday_hours: float = Field(default=8, ge=0, le=24)
    project_mappings: list[WorkforceProjectMappingIn] = Field(default_factory=list, max_length=100)


class WorkforceMembershipIn(BaseModel):
    project_id: str
    # Only software projects need a GitLab user; other kinds just record who works on the project.
    gitlab_user_external_id: str | None = Field(default=None, max_length=255)
    role: str | None = Field(default=None, max_length=64)


class WorkforceMemberUpdate(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=255)
    email_reference: str | None = Field(default=None, max_length=320)
    default_weekday_hours: float = Field(default=8, ge=0, le=24)
    status: str = Field(default="ACTIVE", pattern="^(ACTIVE|INACTIVE)$")
    project_mappings: list[WorkforceMembershipIn] = Field(default_factory=list, max_length=100)


class WorkforceProjectMappingOut(BaseModel):
    project_id: str
    gitlab_user_external_id: str | None = None
    role: str | None = None
    active: bool = True


class WorkforceMemberOut(BaseModel):
    id: str
    display_name: str
    email_reference: str | None = None
    status: str
    timezone: str
    default_weekday_hours: float
    project_mappings: list[WorkforceProjectMappingOut] = Field(default_factory=list)
    # Telegram (FR-NTF-03): linked, with which username, or an invite still open.
    telegram_linked: bool = False
    telegram_username: str | None = None
    telegram_invite_pending: bool = False
    # The CTO's own staff record (FR-PLAN-37): no hours unless set for a day, no Daily Report expected.
    is_cto: bool = False


class HolidayIn(BaseModel):
    day: date
    note: str | None = Field(default=None, max_length=200)


class HolidaysUpdate(BaseModel):
    days: list[HolidayIn] = Field(default_factory=list, max_length=60)


class TelegramProjectStatus(BaseModel):
    id: str
    code: str
    name: str
    chat_title: str | None = None
    linked: bool = False
    linked_at: datetime | None = None


class TelegramMemberStatus(BaseModel):
    id: str
    display_name: str
    username: str | None = None
    linked: bool = False
    linked_at: datetime | None = None
    invite_pending: bool = False


class TelegramHolidayOut(BaseModel):
    day: date
    note: str | None = None


class TelegramStatusOut(BaseModel):
    bot_username: str | None = None
    bot_seen_at: str | None = None
    projects: list[TelegramProjectStatus] = Field(default_factory=list)
    members: list[TelegramMemberStatus] = Field(default_factory=list)
    holidays: list[TelegramHolidayOut] = Field(default_factory=list)


class TelegramInviteOut(BaseModel):
    member_id: str
    code: str
    link: str | None = None
    linked: bool = False


class TelegramMessageOut(BaseModel):
    id: str
    kind: str
    for_date: date
    slot: str
    status: str
    error: str | None = None
    sent_at: datetime | None = None
    project_name: str | None = None
    member_name: str | None = None


class CapacityUpdate(BaseModel):
    expected_version: int = Field(default=0, ge=0)
    override_hours: float | None = Field(default=None, ge=0, le=24)
    meeting_hours: float = Field(default=0, ge=0, le=24)
    review_hours: float = Field(default=0, ge=0, le=24)
    support_hours: float = Field(default=0, ge=0, le=24)
    fixed_hours: float = Field(default=0, ge=0, le=24)
    reason: str | None = Field(default=None, max_length=2000)


class PlannedElsewhere(BaseModel):
    """Hours a person already has that day in another project's plan: the project's name and the hours, no more."""

    project_id: str
    project_name: str
    hours: float


class CapacityOut(BaseModel):
    member_id: str
    display_name: str
    work_date: date
    base_hours: float
    override_hours: float | None = None
    meeting_hours: float
    review_hours: float
    support_hours: float
    fixed_hours: float
    personal_hours: float = 0.0
    available_hours: float
    override_reason: str | None = None
    version: int
    # Set when the list is asked for a planning scope.
    is_owner: bool = False
    # The CTO's own record (FR-PLAN-37): no hours unless set for the day.
    is_cto: bool = False
    planned_elsewhere_hours: float = 0
    planned_elsewhere: list[PlannedElsewhere] = Field(default_factory=list)
    remaining_hours: float | None = None


class PlanningRunCreate(BaseModel):
    plan_date: date
    project_ids: list[str] = Field(default_factory=list, max_length=100)
    timezone: str = Field(default="Asia/Ho_Chi_Minh", max_length=64)


class CandidateDoneRequest(BaseModel):
    note: str = Field(..., min_length=3, max_length=500)


class WorkProposalRequest(BaseModel):
    """A member proposes work for a day (FR-PLAN-35): an Issue ("#12"), an Intake code, or just words."""

    project: str = Field(..., max_length=64)
    plan_date: date
    text: str | None = Field(default=None, max_length=2000)
    issue: str | None = Field(default=None, max_length=32)
    intake: str | None = Field(default=None, max_length=64)
    hours: float | None = Field(default=None, gt=0, le=24)
    slot: PlanningSlot | None = None


class EvidenceLinkIn(BaseModel):
    """A piece of evidence behind "done": a commit or merge request (code), or a link to a document, video or picture (FR-PLAN-36)."""

    kind: Literal["COMMIT", "MR", "LINK"] | None = None
    url: str | None = Field(default=None, max_length=1000)
    ref: str | None = Field(default=None, max_length=200, description="A commit sha or a short name when there is no address")
    note: str | None = Field(default=None, max_length=300)


class EvidenceLinkOut(BaseModel):
    id: str
    kind: str
    url: str | None = None
    ref: str | None = None
    note: str | None = None
    source: str
    added_by_name: str | None = None
    created_at: datetime


class EvidenceCheckOut(BaseModel):
    """Whether what stands behind "done" is enough, by the fixed rule (FR-PLAN-36)."""

    work: str
    status: str
    why: str


class EvidenceLinksRequest(BaseModel):
    links: list[EvidenceLinkIn] = Field(..., min_length=1, max_length=10)


class WorkStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(PLANNED|IN_PROGRESS|DONE|BLOCKED)$")
    note: str | None = Field(default=None, max_length=500)
    # What stands behind "done": attached to the Issue when the status is DONE (FR-PLAN-36).
    evidence: list[EvidenceLinkIn] = Field(default_factory=list, max_length=10)


class PlanningAssignmentCreate(BaseModel):
    expected_run_version: int = Field(..., ge=1)
    project_id: str
    member_id: str
    slot: PlanningSlot
    work_type: PlanningWorkType
    is_primary: bool = False
    planned_hours: float = Field(..., gt=0, le=24)
    source_type: str = Field(..., min_length=1, max_length=32)
    source_reference: str = Field(..., min_length=1, max_length=512)
    gitlab_issue_external_id: str | None = Field(default=None, max_length=255)
    approved_priority: Priority | None = None
    approved_assignee_external_id: str | None = Field(default=None, max_length=255)
    approved_milestone_external_id: str | None = Field(default=None, max_length=255)
    approved_due_date: date | None = None
    dependency_state: str | None = Field(default=None, max_length=32)
    source_state: str | None = Field(default=None, max_length=32)
    override_reason: str | None = Field(default=None, max_length=2000)


class PlanningAssignmentOut(BaseModel):
    id: str
    project_id: str
    member_id: str
    slot: PlanningSlot
    work_type: PlanningWorkType
    is_primary: bool
    planned_hours: float
    source_type: str
    source_reference: str
    gitlab_issue_external_id: str | None = None
    proposed_priority: Priority | None = None
    approved_priority: Priority | None = None
    proposed_assignee_external_id: str | None = None
    approved_assignee_external_id: str | None = None
    proposed_milestone_external_id: str | None = None
    approved_milestone_external_id: str | None = None
    proposed_due_date: date | None = None
    approved_due_date: date | None = None
    dependency_state: str | None = None
    work_status: str = "PLANNED"
    work_status_at: str | None = None
    work_status_note: str | None = None
    # When the CTO accepted the Issue behind this item: drawn as accepted, no longer as work to do (FR-PLAN-34).
    accepted_at: datetime | None = None
    source_state: str | None = None
    override_reason: str | None = None
    version: int
    # The Intake this Issue was created from, when there is one; the Issue's page on the tracker.
    intake_id: str | None = None
    intake_public_id: str | None = None
    title: str | None = None
    issue_url: str | None = None


class PlanningQuickAddRequest(BaseModel):
    expected_run_version: int = Field(..., ge=1)
    mode: PlanningQuickAddMode
    project_id: str
    source_system: PlanningQuickAddSource | None = None
    reference: str | None = Field(default=None, max_length=512)
    title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, max_length=20_000)
    channel: Channel = "MANUAL"
    requested_hours: float | None = Field(default=None, gt=0, le=24)
    target_slot: PlanningSlot | None = None


class PlanningCandidatePromoteRequest(BaseModel):
    expected_run_version: int = Field(..., ge=1)
    member_id: str
    gitlab_issue_external_id: str | None = Field(default=None, max_length=255)
    slot: PlanningSlot
    work_type: PlanningWorkType = "DEVELOPMENT"
    is_primary: bool = True
    planned_hours: float = Field(..., gt=0, le=24)
    override_reason: str | None = Field(default=None, max_length=2000)


class PlanningCandidateOut(BaseModel):
    id: str
    planning_run_id: str
    project_id: str
    member_id: str | None = None
    intake_id: str | None = None
    intake_public_id: str | None = None
    issue_url: str | None = None
    assignment_id: str | None = None
    source_type: str
    source_reference: str
    gitlab_issue_external_id: str | None = None
    title: str
    summary: str | None = None
    status: str
    proposed_priority: Priority | None = None
    requested_hours: float | None = None
    target_slot: PlanningSlot | None = None
    created_at: datetime
    # When the work behind the line began: the Intake's creation for an Intake entry, else when the entry was listed.
    origin_at: datetime | None = None
    # When the CTO accepted the Issue behind the line; a "done outside the plan" line then leaves the screen (FR-PLAN-34).
    accepted_at: datetime | None = None


class PlanningWarningOut(BaseModel):
    id: str
    code: str
    severity: str
    message: str
    member_id: str | None = None
    project_id: str | None = None
    assignment_id: str | None = None
    acknowledged_at: datetime | None = None


class IssueEvidenceOut(BaseModel):
    commits: int = 0
    merge_requests: int = 0
    merged: int = 0
    pipeline: str | None = None
    links: list[str] = Field(default_factory=list)


class IssueVerificationOut(BaseModel):
    """A closed Issue picked for the CTO to look at (FR-PLAN-22)."""
    id: str
    planning_run_id: str | None = None
    project_id: str
    issue_external_id: str
    title: str
    web_url: str | None = None
    closed_at: datetime | None = None
    closed_by_member_id: str | None = None
    assignee_member_id: str | None = None
    level: int
    level_name: str
    done_evidence: str
    evidence: IssueEvidenceOut
    evidence_fetched_at: datetime | None = None
    intake_id: str | None = None
    intake_public_id: str | None = None
    acceptance: list[str] = Field(default_factory=list)
    decision: str
    reason: str | None = None
    decided_at: datetime | None = None


class AcceptanceItemOut(BaseModel):
    """One piece of work waiting to be, or already, accepted (FR-PLAN-31)."""
    id: str
    source: str
    project_id: str
    project_name: str | None = None
    issue_external_id: str
    title: str
    web_url: str | None = None
    state: str | None = None
    closed_at: datetime | None = None
    assignee_member_id: str | None = None
    assignee_name: str | None = None
    reporter_member_id: str | None = None
    reporter_name: str | None = None
    reported_on: date | None = None
    reported_hours: float | None = None
    report_item_title: str | None = None
    priority: str
    level: int
    level_name: str
    done_evidence: str
    evidence: IssueEvidenceOut
    evidence_fetched_at: datetime | None = None
    intake_id: str | None = None
    intake_public_id: str | None = None
    acceptance: list[str] = Field(default_factory=list)
    picked_on: date | None = None
    decision: str
    reason: str | None = None
    decided_at: datetime | None = None
    decided_by_name: str | None = None
    po_decision: str | None = None
    po_reason: str | None = None
    po_decided_at: datetime | None = None
    po_decided_by_name: str | None = None
    sync_status: str | None = None
    # What was written when the work was set aside as done already (FR-PLAN-34).
    source_note: str | None = None
    sync_error: str | None = None
    synced_at: datetime | None = None
    sync_queued: bool | None = None
    created_at: datetime
    evidence_links: list[EvidenceLinkOut] = Field(default_factory=list)
    evidence_check: EvidenceCheckOut | None = None
    evidence_missing_reason: str | None = None


class AcceptanceWorkLogOut(BaseModel):
    """Off-plan work waiting for the CTO's review (FR-PLAN-38, FR-MCP-03)."""
    id: str
    intake_id: str
    intake_public_id: str
    project_id: str
    project_name: str | None = None
    title: str
    summary: str
    issue_external_id: str | None = None
    web_url: str | None = None
    executor: str
    details: IntakeWorkLogDetails = Field(default_factory=IntakeWorkLogDetails)
    review_decision: Literal["PENDING", "CONFIRMED", "RETURNED"]
    review_note: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: datetime | None = None
    accepted_at: datetime | None = None
    created_at: datetime


class AcceptanceQueueOut(BaseModel):
    plan_date: date
    sample_size: int = 5
    pending_total: int = 0
    today: list[AcceptanceItemOut] = Field(default_factory=list)
    more: list[AcceptanceItemOut] = Field(default_factory=list)
    decided: list[AcceptanceItemOut] = Field(default_factory=list)
    work_log_pending_total: int = 0
    work_logs_pending: list[AcceptanceWorkLogOut] = Field(default_factory=list)
    work_logs_decided: list[AcceptanceWorkLogOut] = Field(default_factory=list)


class AcceptanceDecisionRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1000)
    # Accepting with nothing behind it needs a line that says why (FR-PLAN-36).
    evidence_missing_reason: str | None = Field(default=None, max_length=500)


class TrackerUserOut(BaseModel):
    id: str
    name: str
    username: str | None = None
    mapped_member_id: str | None = None
    suggested_member_id: str | None = None


class TrackerUnmappedOut(BaseModel):
    member_id: str
    display_name: str
    suggested_user_id: str | None = None


class TrackerUsersOut(BaseModel):
    """The tracker's users beside the team, for the planning dialog (FR-PLAN-32). `status` is the probe's: PENDING, DONE, FAILED."""
    status: str = "DONE"
    error_code: str | None = None
    users: list[TrackerUserOut] = Field(default_factory=list)
    unmapped: list[TrackerUnmappedOut] = Field(default_factory=list)
    issue_assignees: list[str] = Field(default_factory=list)


class TrackerUserMappingRequest(BaseModel):
    gitlab_user_external_id: str | None = Field(default=None, max_length=255)


class VerificationDecisionRequest(BaseModel):
    expected_version: int = Field(..., ge=1)
    reason: str | None = Field(default=None, max_length=1000)


class ProjectDoneEvidenceUpdate(BaseModel):
    done_evidence: Literal["COMMIT", "MR"]


class ProjectAgentReadyUpdate(BaseModel):
    # The repo has CLAUDE.md, a test command and seed data an agent can use.
    agent_ready: bool


class PlanningRunOut(BaseModel):
    id: str
    plan_date: date
    timezone: str
    project_ids: list[str]
    status: str
    version: int
    revision: int
    supersedes_run_id: str | None = None
    source_snapshot_at: datetime
    assignments: list[PlanningAssignmentOut] = Field(default_factory=list)
    candidates: list[PlanningCandidateOut] = Field(default_factory=list)
    warnings: list[PlanningWarningOut] = Field(default_factory=list)
    verifications: list[IssueVerificationOut] = Field(default_factory=list)


class PlanningApprovalRequest(BaseModel):
    expected_version: int = Field(..., ge=1)
    acknowledged_warning_ids: list[str] = Field(default_factory=list, max_length=100)
    override_reason: str | None = Field(default=None, max_length=2000)


class PlanningReopenRequest(BaseModel):
    expected_version: int = Field(..., ge=1)


class PlanningProposalAcceptRequest(BaseModel):
    expected_version: int = Field(..., ge=1)


class PlanningSyncJobOut(BaseModel):
    id: str
    project_id: str
    gitlab_issue_external_id: str
    status: str
    attempt: int
    max_attempts: int
    error_code: str | None = None
    next_attempt_at: datetime | None = None
    updated_at: datetime | None = None


class PlanningRunSyncStatusOut(BaseModel):
    planning_run_id: str
    snapshot_id: str | None = None
    status: str
    jobs: list[PlanningSyncJobOut] = Field(default_factory=list)


class PlanningApprovalOut(BaseModel):
    planning_run_id: str
    snapshot_id: str
    status: str
    jobs: list[PlanningSyncJobOut]


class DailyReportIngestRequest(BaseModel):
    mailbox: str = Field(..., min_length=3, max_length=320)
    uid_validity: str = Field(..., min_length=1, max_length=64)
    uid: str = Field(..., min_length=1, max_length=64)
    message_id: str | None = Field(default=None, max_length=512)
    sender_address: str = Field(..., min_length=3, max_length=320)
    sender_name: str | None = Field(default=None, max_length=255)
    subject: str = Field(..., min_length=1, max_length=2000)
    body: str = Field(..., min_length=1, max_length=200_000)
    received_at: datetime


class DailyReportIssueOut(BaseModel):
    code: str
    severity: str
    message: str


class DailyReportOut(BaseModel):
    id: str
    member_id: str | None = None
    report_date: date | None = None
    status: str
    revision: int
    is_current: bool
    is_late: bool
    received_at: datetime
    item_count: int
    unlinked_items: int = 0
    # For a Project Owner: items of other projects left out of this view, and whether the whole email is theirs to confirm.
    hidden_items: int = 0
    can_review: bool = True
    issues: list[DailyReportIssueOut] = Field(default_factory=list)
    duplicate: bool = False
    member_name: str | None = None
    sender_address: str | None = None
    parsed_by: str = "RULES"
    review_decision: str | None = None
    usable_for_planning: bool = True


class DailyReportItemOut(BaseModel):
    id: str
    project_name: str | None = None
    reported_project_code: str | None = None
    work_status: str
    title: str
    worked_hours: float | None = None
    planned_hours: float | None = None
    progress_percent: int | None = None
    gitlab_issue: str | None = None
    next_step: str | None = None
    blocker_detail: str | None = None
    parsed_by: str
    edited: bool = False
    # Where the Issue came from and what the machine suggested (FR-RPT-07).
    issue_suggestions: list[dict] = Field(default_factory=list)
    issue_link_source: str | None = None
    no_issue_reason: str | None = None


class DailyReportItemIssueRequest(BaseModel):
    """Link the item to an Issue, say it needs none, or clear both."""
    gitlab_issue: str | None = Field(default=None, pattern="^[0-9]{1,12}$")
    no_issue_reason: Literal["MEETING", "SUPPORT", "REVIEW", "LEARNING", "OTHER"] | None = None


class IssueSuggestionOutcome(BaseModel):
    items: int = 0
    linked: int = 0
    suggested: int = 0
    for_ai: list[str] = Field(default_factory=list)
    ai_queued: bool | None = None
    reports: int | None = None


class DailyReportItemUpdate(BaseModel):
    work_status: str | None = Field(default=None, pattern="^(PLANNED|IN_PROGRESS|PENDING_REVIEW|DONE|BLOCKED|CANCELLED)$")
    title: str | None = Field(default=None, min_length=1, max_length=512)
    worked_hours: float | None = Field(default=None, ge=0, le=24)
    planned_hours: float | None = Field(default=None, ge=0, le=24)
    progress_percent: int | None = Field(default=None, ge=0, le=100)
    gitlab_issue: str | None = Field(default=None, pattern="^[0-9]{1,12}$")
    blocker_detail: str | None = Field(default=None, max_length=2000)
    next_step: str | None = Field(default=None, max_length=2000)
    project_code: str | None = Field(default=None, max_length=64)


class DailyReportDetailOut(DailyReportOut):
    items: list[DailyReportItemOut] = Field(default_factory=list)


class DailyReportSourceOut(BaseModel):
    id: str
    purged: bool
    subject: str | None = None
    body: str | None = None
    signature: str | None = None


class MailboxScanOut(BaseModel):
    id: str
    trigger: str
    status: str
    ingested: int
    duplicates: int
    failed: int
    error_code: str | None = None
    created_at: datetime
    completed_at: datetime | None = None


class MailboxStatusOut(BaseModel):
    enabled: bool
    mailbox: str
    poll_minutes: int
    current: MailboxScanOut | None = None
    last: MailboxScanOut | None = None


class DailyReportReviewRequest(BaseModel):
    decision: str = Field(..., pattern="^(CONFIRMED|REJECTED)$")


class MeetingCreate(BaseModel):
    project_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    source: str = Field(default="TAB_AND_MIC", pattern="^(TAB_AND_MIC|MIC|FILE)$")
    kind: str = Field(default="MEETING", pattern="^(MEETING|DICTATION)$")
    # The meeting this one continues (the browser hit the time limit): same project, next part number.
    continues_meeting_id: str | None = Field(default=None, max_length=64)


class MeetingOut(BaseModel):
    id: str
    title: str
    status: str
    source: str
    kind: str = "MEETING"
    language: str
    project_code: str | None = None
    project_name: str | None = None
    started_at: datetime
    ended_at: datetime | None = None
    duration_seconds: int | None = None
    audio_chunk_count: int
    audio_bytes: int
    max_minutes: int
    series_id: str | None = None
    part_number: int = 1
    transcript_error: str | None = None
    note_error: str | None = None
    transcript_status: str = "NONE"
    note_status: str = "NONE"
    provider_data_deleted: bool = True
    audio_available: bool = False


class MeetingSegmentOut(BaseModel):
    id: str
    source: str
    sequence: int
    speaker_label: str | None = None
    speaker_name: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None
    text: str | None = None


class MeetingSpeakerOut(BaseModel):
    label: str
    name: str | None = None


class MeetingNoteItemOut(BaseModel):
    id: str
    kind: str
    topic: str | None = None
    title: str | None = None
    detail: str | None = None
    owner: str | None = None
    due_text: str | None = None
    project_code: str | None = None
    project_name: str | None = None
    intake_id: str | None = None
    edited: bool = False
    can_become_intake: bool = False
    # Straight to the board (FR-REC-19): the work it became, or whether it still can.
    work_id: str | None = None
    work_code: str | None = None
    can_become_work: bool = False


class MeetingPartOut(BaseModel):
    id: str
    part_number: int
    title: str
    status: str
    transcript_status: str
    note_status: str


class MeetingNoteBulkIntake(BaseModel):
    item_ids: list[str] = Field(..., min_length=1, max_length=50)
    full_transcript: bool = False


class MeetingNoteWorkItem(BaseModel):
    """One note item to put on the board, with what the person settled on the line (FR-REC-19)."""

    item_id: str = Field(..., min_length=1, max_length=64)
    member_id: str | None = None
    due_date: date | None = None
    status: Literal["DISCUSS", "READY"] | None = None
    channel: ChannelCode | None = None
    publish_at: datetime | None = None


class MeetingNoteWorkCreate(BaseModel):
    items: list[MeetingNoteWorkItem] = Field(..., min_length=1, max_length=50)


class MeetingNoteWorkResult(BaseModel):
    item_id: str
    work_id: str | None = None
    code: str | None = None
    intake_id: str | None = None
    error: str | None = None


class MeetingNoteWorkOut(BaseModel):
    results: list[MeetingNoteWorkResult]
    meeting: "MeetingDetailOut"


class MeetingNoteBulkResult(BaseModel):
    item_id: str
    intake_id: str | None = None
    error: str | None = None


class MeetingDetailOut(MeetingOut):
    parts: list[MeetingPartOut] = Field(default_factory=list)
    transcript_source: str | None = None
    speakers: list[MeetingSpeakerOut] = Field(default_factory=list)
    segments: list[MeetingSegmentOut] = Field(default_factory=list)
    note_summary: str | None = None
    note_items: list[MeetingNoteItemOut] = Field(default_factory=list)
    rewrite_status: str = "NONE"
    rewrite_text: str | None = None
    rewrite_error: str | None = None


class MeetingNoteBulkIntakeOut(BaseModel):
    results: list[MeetingNoteBulkResult]
    meeting: MeetingDetailOut


class MeetingProjectUpdate(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=64)


class MeetingSpeakersUpdate(BaseModel):
    names: dict[str, str] = Field(..., min_length=1, max_length=32)


DraftChannel = Literal["FACEBOOK", "LINKEDIN", "THREADS", "FACEBOOK_GROUP", "BLOG", "VIDEO_SCRIPT"]
VoiceChannel = Literal["FACEBOOK", "LINKEDIN", "THREADS"]
DraftTrack = Literal["business", "technical"]
DraftContext = Literal["REAL", "EXAMPLE", "SOURCE"]
DraftCommercial = Literal["NONE", "SPONSORED", "AFFILIATE"]
DraftGoal = Literal["AUTHORITY", "DISCUSSION", "REACH", "CONVERSATION", "FOLLOW"]
DraftAudience = Literal["SME", "AGENCY", "CONSULTANT", "DEVELOPER", "AI_USER"]
NoteKind = Literal["FACT", "PROOF", "DECISION", "RESULT"]
DraftGroup = Literal["FNB", "EDUCATION", "RETAIL", "SERVICE", "AGENCY", "CONSULTING"]


class VoiceSample(BaseModel):
    text: str = Field(..., min_length=20, max_length=4000)
    channel: VoiceChannel = "FACEBOOK"


class VoiceReference(BaseModel):
    title: str = Field(default="", max_length=120)
    text: str = Field(..., min_length=1, max_length=20000)


class MasterDna(BaseModel):
    # The one brand document every track reads: a shared core and its directions (FR-CNT-15).
    text: str = Field(default="", max_length=40000)


class PrivateVoice(BaseModel):
    """How the owner of a project writes: what the AI follows when it drafts a post (FR-CNT-02)."""

    name: str = Field(default="", max_length=60)
    # Which direction of the master brand document this track is (ADR-0042).
    direction_note: str = Field(default="", max_length=300)
    positioning: str = Field(default="", max_length=300)
    audience: str = Field(default="", max_length=300)
    pillars: list[str] = Field(default_factory=list, max_length=5)
    tone: str = Field(default="", max_length=300)
    avoid: str = Field(default="", max_length=300)
    default_channel: DraftChannel = "FACEBOOK"
    samples: list[VoiceSample] = Field(default_factory=list, max_length=8)
    # Documents about an organisation or a product the author may mention: facts to check against, not a voice.
    references: list[VoiceReference] = Field(default_factory=list, max_length=2)

    @field_validator("pillars")
    @classmethod
    def _short_pillars(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(item.split()) for item in value if item and item.strip()]
        if any(len(item) > 80 for item in cleaned):
            raise ValueError("A pillar is at most 80 characters")
        return cleaned


class PrivateSpaceProject(BaseModel):
    id: str
    code: str
    name: str


class PrivateSpaceCounts(BaseModel):
    ideas: int = 0
    no_draft: int = 0
    drafted: int = 0
    posted: int = 0
    dropped: int = 0
    unposted_drafts: int = 0


class PrivateSpaceOut(BaseModel):
    project: PrivateSpaceProject | None = None
    voice: PrivateVoice | None = None
    voices: dict[str, PrivateVoice] = Field(default_factory=dict)
    master_dna: str = ""
    counts: PrivateSpaceCounts = Field(default_factory=PrivateSpaceCounts)


class PrivateIdeaOut(BaseModel):
    id: str
    public_id: str
    title: str | None = None
    note: str | None = None
    analysed: bool = False
    status: str
    state: Literal["NO_DRAFT", "DRAFTED", "POSTED", "DROPPED"]
    channels: list[str] = Field(default_factory=list)
    track: str | None = None
    posted_at: datetime | None = None
    created_at: datetime
    version: int


class PrivateIdeaTrack(BaseModel):
    track: DraftTrack | None = None


class TrackNoteCreate(BaseModel):
    track: DraftTrack
    kind: NoteKind
    text: str = Field(..., min_length=3, max_length=1000)


class TrackNoteOut(BaseModel):
    id: str
    track: str
    kind: NoteKind
    text: str
    created_at: datetime


class PostDraftCreate(BaseModel):
    channel: DraftChannel = "FACEBOOK"
    angle: str | None = Field(default=None, max_length=500)
    source_draft_id: str | None = None
    track: DraftTrack | None = None
    goal: DraftGoal | None = None
    audience: DraftAudience | None = None
    pillar: str | None = Field(default=None, max_length=120)
    group_context: DraftGroup | None = None
    # An outline first: only before a blog post or a video script.
    outline: bool = False
    context: DraftContext | None = None
    commercial: DraftCommercial | None = None


class PromptPreviewRequest(BaseModel):
    track: DraftTrack = "business"
    # The voice and the master document as they stand on the screen, saved or not; left out, the saved ones are used.
    voice: PrivateVoice | None = None
    master_dna: str | None = Field(default=None, max_length=40000)
    context: DraftContext | None = None
    commercial: DraftCommercial | None = None
    intake_id: str | None = None
    channel: DraftChannel = "FACEBOOK"
    outline: bool = False
    goal: DraftGoal | None = None
    audience: DraftAudience | None = None
    pillar: str | None = Field(default=None, max_length=120)
    group_context: DraftGroup | None = None
    angle: str | None = Field(default=None, max_length=500)
    source_draft_id: str | None = None


class VoiceTrialRequest(BaseModel):
    track: DraftTrack = "business"
    voice: PrivateVoice | None = None
    master_dna: str | None = Field(default=None, max_length=40000)
    channel: DraftChannel = "FACEBOOK"
    # One made-up line to write about; the owner's own ideas are not read here.
    idea: str = Field(default="", max_length=500)


class VoiceTrialOut(BaseModel):
    text: str
    prompt_version: str
    model: str
    message_chars: int


class PromptCut(BaseModel):
    what: str
    kept: int
    total: int


class PromptBlock(BaseModel):
    key: str
    trust: Literal["CHOICE", "AUTHOR", "DATA", "UNTRUSTED"]
    text: str
    chars: int
    cuts: list[PromptCut] = Field(default_factory=list)


class PromptPreviewOut(BaseModel):
    prompt_version: str
    model: str
    system_prompt: str
    system_chars: int
    blocks: list[PromptBlock] = Field(default_factory=list)
    message_chars: int
    # True when no idea was chosen: the idea's places hold marked placeholders.
    placeholder: bool


class PostDraftUpdate(BaseModel):
    # A blog post or a video script runs several times longer than a social post.
    text: str | None = Field(default=None, max_length=30000)
    posted: bool | None = None
    # When and where it really went out; the hour defaults to now.
    posted_at: datetime | None = None
    posted_url: str | None = Field(default=None, max_length=500)

    @field_validator("posted_url")
    @classmethod
    def _web_address(cls, value: str | None) -> str | None:
        if value and value.strip() and not value.strip().lower().startswith(("http://", "https://")):
            raise ValueError("posted_url must start with http:// or https://")
        return value


class PlanRequestState(BaseModel):
    status: Literal["PENDING", "DONE", "FAILED"]
    error: str | None = None


WatchKind = Literal["WEB", "FACEBOOK", "X", "YOUTUBE", "LINKEDIN", "OTHER"]
WatchTrack = Literal["business", "technical", "content", "both"]


class WatchSourceCreate(BaseModel):
    url: str = Field(..., min_length=8, max_length=500)
    track: WatchTrack
    label: str | None = Field(default=None, max_length=120)
    kind: WatchKind | None = None
    note: str | None = Field(default=None, max_length=300)


class WatchSourceChange(BaseModel):
    track: WatchTrack | None = None
    active: bool | None = None
    label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=300)


class WatchSourceOut(BaseModel):
    id: str
    kind: str
    url: str
    label: str
    track: str
    active: bool
    note: str | None = None
    created_at: datetime


class PillarKeywords(BaseModel):
    pillar: str
    keywords: list[str] = Field(default_factory=list)


class PillarKeywordsUpdate(BaseModel):
    pillars: dict[str, list[str]] = Field(default_factory=dict)

    @field_validator("pillars")
    @classmethod
    def _bounded(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if len(value) > 5 or any(len(words) > 40 or any(len(word) > 200 for word in words) for words in value.values()):
            raise ValueError("too many pillars or keywords")
        return value


class PillarKeywordsOut(BaseModel):
    track: str
    pillars: list[PillarKeywords] = Field(default_factory=list)
    request: PlanRequestState | None = None
    suggested: dict[str, list[str]] = Field(default_factory=dict)


class WatchRequestOut(BaseModel):
    id: str
    status: Literal["PENDING", "DONE", "FAILED"]


class WatchSignalOut(BaseModel):
    id: str
    track: str
    url: str
    title: str
    excerpt: str | None = None
    author: str | None = None
    pillar: str | None = None
    keyword: str | None = None
    source_id: str | None = None
    source_label: str | None = None
    published_at: datetime | None = None
    received_at: datetime
    state: Literal["NEW", "USED", "DISMISSED"]
    intake_id: str | None = None
    via: Literal["api", "scrape", "agent"] = "api"
    priority: Literal["high", "normal"] = "normal"


class WatchSignalKept(BaseModel):
    signal: WatchSignalOut
    idea_id: str


class WatchDemandUpdate(BaseModel):
    wanted_per_week: int = Field(..., ge=0, le=50)
    weekday: int = Field(..., ge=1, le=7)
    time: str = Field(..., pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    lookback_days: int = Field(default=7, ge=1, le=30)


class WatchDemandOut(BaseModel):
    wanted_per_week: int
    weekday: int
    time: str
    lookback_days: int
    timezone: str
    window_start: datetime | None = None
    deadline: datetime | None = None
    received: int
    remaining: int
    accept_up_to: int | None = None


class WatchHealthTrack(BaseModel):
    track: str
    name: str
    wanted_per_week: int
    received: int
    remaining: int
    deadline: datetime | None = None
    checked_at: datetime | None = None
    warning: bool = False
    reason: Literal["ROUTES_CLOSED", "NO_SOURCES", "NO_KEYWORDS", "FLOW_SILENT", "NOTHING_SENT"] | None = None
    received_in_check: int | None = None


class WatchHealthOut(BaseModel):
    check_hours: int
    last_config_at: datetime | None = None
    last_signal_at: datetime | None = None
    tracks: list[WatchHealthTrack] = Field(default_factory=list)


class WatchConfigSource(BaseModel):
    id: str
    kind: str
    url: str
    label: str


class WatchTerm(BaseModel):
    """One keyword or hashtag of a pillar, and whether the scanner should look for it first (FR-MKT-08)."""

    text: str = Field(..., min_length=1, max_length=60)
    kind: Literal["keyword", "hashtag"] = "keyword"
    priority: Literal["high", "normal"] = "normal"


class WatchConfigPillar(PillarKeywords):
    terms: list[WatchTerm] = Field(default_factory=list)


class WatchConfigTrack(BaseModel):
    track: str
    name: str
    pillars: list[WatchConfigPillar] = Field(default_factory=list)
    sources: list[WatchConfigSource] = Field(default_factory=list)
    demand: WatchDemandOut | None = None


class WatchConfigProject(BaseModel):
    project: str
    name: str
    kind: str
    networks: list[str] = Field(default_factory=list)
    scan_every_hours: int = 2
    next_scan_at: datetime | None = None
    tracks: list[WatchConfigTrack] = Field(default_factory=list)


class WatchConfigOut(BaseModel):
    tracks: list[WatchConfigTrack] = Field(default_factory=list)
    projects: list[WatchConfigProject] = Field(default_factory=list)


class WatchItem(BaseModel):
    # Everything here is text found on the internet. It is trimmed on arrival and never treated as an instruction.
    url: str = Field(..., max_length=1000)
    title: str = Field(..., max_length=2000)
    excerpt: str | None = Field(default=None, max_length=20000)
    author: str | None = Field(default=None, max_length=500)
    source_id: str | None = Field(default=None, max_length=64)
    track: str | None = Field(default=None, max_length=32)
    project: str | None = Field(default=None, max_length=16)
    pillar: str | None = Field(default=None, max_length=500)
    keyword: str | None = Field(default=None, max_length=500)
    published_at: datetime | None = None
    via: Literal["api", "scrape"] | None = None
    priority: Literal["high", "normal"] | None = None


class WatchBatch(BaseModel):
    items: list[WatchItem] = Field(default_factory=list, max_length=200)


class WatchRejected(BaseModel):
    index: int
    reason: str


class WatchBatchOut(BaseModel):
    accepted: int
    duplicates: int
    rejected: list[WatchRejected] = Field(default_factory=list)


class WatchSample(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    url: str = Field(..., min_length=8, max_length=1000)


class PillarIn(BaseModel):
    """A marketing pillar as the owner writes it (FR-MKT-08)."""

    name: str = Field(..., min_length=1, max_length=60)
    description: str | None = Field(default=None, max_length=200)
    audience: str | None = Field(default=None, max_length=120)
    channels: list[str] = Field(default_factory=list, max_length=12)
    share_pct: int = Field(default=0, ge=0, le=100)
    keywords: list[WatchTerm | str] = Field(default_factory=list, max_length=12)
    samples: list[WatchSample] = Field(default_factory=list, max_length=2)
    avoid: str | None = Field(default=None, max_length=300)


class PillarsUpdate(BaseModel):
    pillars: list[PillarIn] = Field(default_factory=list, max_length=6)


class PillarOut(BaseModel):
    name: str
    description: str = ""
    audience: str = ""
    channels: list[str] = Field(default_factory=list)
    share_pct: int = 0
    keywords: list[WatchTerm] = Field(default_factory=list)
    samples: list[WatchSample] = Field(default_factory=list)
    avoid: str = ""


class WatchScheduleOut(BaseModel):
    times: list[str] = Field(default_factory=list)
    weekdays: list[int] = Field(default_factory=list)


class WatchSettingsOut(BaseModel):
    networks: list[str] = Field(default_factory=list)
    open_networks: list[str] = Field(default_factory=list)
    schedule: WatchScheduleOut
    scan_every_hours: int
    scan_hours: list[int] = Field(default_factory=list)
    max_ai_runs_per_day: int
    ai_runs_per_week: int


class WatchSettingsUpdate(BaseModel):
    networks: list[str] | None = Field(default=None, max_length=12)
    times: list[str] | None = Field(default=None, max_length=8)
    weekdays: list[int] | None = Field(default=None, max_length=7)
    scan_every_hours: int | None = None


class WatchPlatformOut(BaseModel):
    code: str
    label: str
    enabled: bool
    via: Literal["api", "scrape", "none"]
    note: str | None = None
    sort_order: int
    updated_at: datetime


class WatchPlatformUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    enabled: bool | None = None
    via: Literal["api", "scrape", "none"] | None = None
    note: str | None = Field(default=None, max_length=300)


class WatchLimitsOut(BaseModel):
    max_ai_runs_per_day: int


class WatchLimitsUpdate(BaseModel):
    max_ai_runs_per_day: int = Field(..., ge=0, le=8)


class WatchTopicSignal(BaseModel):
    id: str
    title: str
    url: str
    host: str
    keyword: str | None = None
    published_at: datetime | None = None
    via: str = "api"


class WatchTopicOut(BaseModel):
    id: str
    week_start: date
    title: str
    why: str | None = None
    angles: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    caution: str | None = None
    pillar: str | None = None
    score: int
    state: Literal["NEW", "USED", "DISMISSED"]
    ai_written: bool = False
    work_id: str | None = None
    sources: int = 0
    signals: list[WatchTopicSignal] = Field(default_factory=list)
    updated_at: datetime


class WatchTopicsOut(BaseModel):
    week_start: date
    has_sources: bool
    kept_this_week: int
    refresh_left: int
    built_at: datetime | None = None
    schedule: WatchScheduleOut
    topics: list[WatchTopicOut] = Field(default_factory=list)


class WatchTopicsRequested(BaseModel):
    status: Literal["PENDING"]
    refresh_left: int


class WatchTopicPost(BaseModel):
    mode: Literal["post", "series"] = "post"
    angle: int | None = Field(default=None, ge=0, le=2)
    member_id: str | None = None
    week: date | None = None


class ConnectorMapping(BaseModel):
    items: str = Field(default="", max_length=120)
    fields: dict[str, str] = Field(default_factory=dict)


class ConnectorCreate(BaseModel):
    """A door for an outside service into a marketing project (FR-MKT-13)."""

    project: str = Field(..., min_length=1, max_length=64)
    name: str = Field(..., min_length=1, max_length=80)
    kind: Literal["GENERIC", "N8N", "MAKE", "APIFY", "MENTION"] = "GENERIC"
    via: Literal["api", "scrape"] = "api"
    default_pillar: str | None = Field(default=None, max_length=60)
    mapping: ConnectorMapping | None = None


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None
    via: Literal["api", "scrape"] | None = None
    default_pillar: str | None = Field(default=None, max_length=60)
    mapping: ConnectorMapping | None = None


class ConnectorOut(BaseModel):
    id: str
    project_id: str
    project_code: str | None = None
    name: str
    kind: str
    token_prefix: str
    via: str
    default_pillar: str | None = None
    mapping: ConnectorMapping
    enabled: bool
    received_count: int = 0
    rejected_count: int = 0
    last_received_at: datetime | None = None
    last_status: str | None = None
    path: str
    created_at: datetime
    # Only in the answer that made or rotated the door.
    token: str | None = None


class ConnectorSummary(BaseModel):
    id: str
    name: str
    kind: str
    enabled: bool
    last_received_at: datetime | None = None
    received_count: int = 0
    last_status: str | None = None


class ConnectorTryItem(BaseModel):
    url: str
    title: str
    excerpt: str | None = None
    author: str | None = None
    keyword: str | None = None
    pillar: str | None = None
    published_at: datetime | None = None
    would_reject: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ConnectorTryOut(BaseModel):
    items: list[ConnectorTryItem] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)
    would_accept: int = 0


class ConnectorDelivery(BaseModel):
    at: datetime
    status: Literal["ACCEPTED", "EMPTY", "INVALID", "UNAUTHORIZED"]
    accepted: int = 0
    duplicates: int = 0
    rejected: int = 0
    note: str | None = None


class ConnectorBatchOut(WatchBatchOut):
    problems: list[str] = Field(default_factory=list)


class PublishPauseOut(BaseModel):
    paused: bool


class PublishPauseUpdate(BaseModel):
    paused: bool


class PostLinkCreate(BaseModel):
    target_url: str = Field(..., min_length=8, max_length=900)


class PostLinkOut(BaseModel):
    code: str
    url: str
    target_url: str
    clicks: int = 0
    created_at: datetime


class PublishQueueItem(BaseModel):
    draft_id: str
    # "draft" for the private space (ADR-0038); "post_version" for a marketing post's channel version (FR-MKT-14).
    kind: Literal["draft", "post_version"] = "draft"
    track: str | None = None
    channel: str
    group_context: str | None = None
    pillar: str | None = None
    title: str | None = None
    text: str
    scheduled_for: datetime | None = None
    approved_at: datetime
    project: str | None = None
    work: str | None = None
    language: str | None = None
    short_link: str | None = None


class PublishEvent(BaseModel):
    draft_id: str = Field(..., min_length=8, max_length=64)
    status: Literal["POSTED", "FAILED"]
    posted_at: datetime | None = None
    url: str | None = Field(default=None, max_length=500)
    platform: str | None = Field(default=None, max_length=40)
    error: str | None = Field(default=None, max_length=200)

    @field_validator("url")
    @classmethod
    def _web_address(cls, value: str | None) -> str | None:
        if value and value.strip() and not value.strip().lower().startswith(("http://", "https://")):
            raise ValueError("url must start with http:// or https://")
        return value


class PublishEventOut(BaseModel):
    draft_id: str
    posted_at: datetime | None = None
    posted_url: str | None = None
    posted_via: str | None = None
    publish_error: str | None = None


class PostDraftApprove(BaseModel):
    slot_id: str | None = None
    scheduled_for: datetime | None = None


class RhythmSlot(BaseModel):
    weekday: int = Field(..., ge=1, le=7)
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    channel: DraftChannel
    pillar: str | None = Field(default=None, max_length=120)


class RhythmUpdate(BaseModel):
    slots: list[RhythmSlot] = Field(default_factory=list, max_length=7)


class PlanSlotIdea(BaseModel):
    id: str
    public_id: str
    title: str | None = None


class PlanSlotDraft(BaseModel):
    id: str
    channel: str
    approved_at: datetime | None = None
    scheduled_for: datetime | None = None
    posted_at: datetime | None = None
    posted_url: str | None = None
    posted_via: str | None = None


class PlanSuggestion(BaseModel):
    title: str
    reason: str = ""
    pillar: str | None = None
    from_store: bool = False


class PlanSlotOut(BaseModel):
    id: str
    track: str
    week_start: date
    day: date
    weekday: int
    time: str | None = None
    planned_for: datetime
    channel: str
    pillar: str | None = None
    state: Literal["EMPTY", "PROPOSED", "IDEA", "DRAFTED", "APPROVED", "POSTED", "SKIPPED"]
    idea: PlanSlotIdea | None = None
    draft: PlanSlotDraft | None = None
    suggestion: PlanSuggestion | None = None


class PlanSlotChange(BaseModel):
    intake_id: str | None = None
    skipped: bool | None = None
    dismiss: bool | None = None


class PlanSlotAccepted(BaseModel):
    slot: PlanSlotOut
    created_idea_id: str | None = None


class PlanPillarCount(BaseModel):
    pillar: str
    posted: int


class PlanStats(BaseModel):
    slots: int
    posted: int
    approved: int
    open: int
    drafted_ideas: int
    posted_total: int
    off_plan: int
    pillars: list[PlanPillarCount] = Field(default_factory=list)
    missing_pillars: list[str] = Field(default_factory=list)


class PlanTrackOut(BaseModel):
    name: str
    slots: list[PlanSlotOut] = Field(default_factory=list)
    stats: PlanStats
    request: PlanRequestState | None = None


class PlanWeekOut(BaseModel):
    week_start: date
    this_week: date
    editable: bool
    tracks: dict[str, PlanTrackOut] = Field(default_factory=dict)
    rhythm: dict[str, list[RhythmSlot]] = Field(default_factory=dict)


class PlanProposalCreate(BaseModel):
    track: DraftTrack
    week_start: date
    # Words or news of the week the person pasted: untrusted text, read by AI.
    keywords: str | None = Field(default=None, max_length=2000)


class PlanProposalOut(BaseModel):
    id: str
    status: Literal["PENDING", "DONE", "FAILED"]


class PostDraftOut(BaseModel):
    id: str
    intake_id: str
    channel: DraftChannel
    kind: Literal["POST", "OUTLINE"] = "POST"
    status: Literal["PENDING", "DONE", "FAILED"]
    text: str | None = None
    hooks: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    angle: str | None = None
    source_draft_id: str | None = None
    track: str | None = None
    goal: str | None = None
    audience: str | None = None
    pillar: str | None = None
    group_context: str | None = None
    context: str | None = None
    commercial: str | None = None
    approved_at: datetime | None = None
    scheduled_for: datetime | None = None
    posted_url: str | None = None
    posted_via: str | None = None
    publish_error: str | None = None
    slot_id: str | None = None
    error: str | None = None
    edited_at: datetime | None = None
    posted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class MeetingFinish(BaseModel):
    # Measured by the browser while recording; the server's clock would count the time the sound spent waiting
    # on the computer for a line that was down.
    duration_seconds: int | None = Field(default=None, ge=0, le=24 * 3600)


class MeetingRename(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)


class MeetingDeleted(BaseModel):
    deleted: bool
    intakes_kept: int = 0


class MeetingSummaryUpdate(BaseModel):
    summary: str = Field(..., min_length=1, max_length=8000)


class MeetingNoteItemUpdate(BaseModel):
    kind: str | None = Field(default=None, pattern="^(DECISION|REQUIREMENT|BUG|SCOPE_CHANGE|ACTION|QUESTION|RISK)$")
    title: str | None = Field(default=None, max_length=500)
    detail: str | None = Field(default=None, max_length=8000)
    owner: str | None = Field(default=None, max_length=255)
    due_text: str | None = Field(default=None, max_length=255)
    project_code: str | None = Field(default=None, max_length=64)


class GlossaryTermCreate(BaseModel):
    term: str = Field(..., min_length=1, max_length=50)
    project_id: str | None = Field(default=None, max_length=64)


class GlossaryTermOut(BaseModel):
    id: str
    term: str
    project_code: str | None = None
    usable_in_realtime: bool


class ProjectOut(BaseModel):
    id: str
    code: str
    intake_key: str
    name: str
    status: str
    kind: str
    gitlab_project_id: str | None = None
    gitlab_project_url: str | None = None
    gitlab_enabled: bool = False
    github_repository: str | None = None
    github_project_url: str | None = None
    github_enabled: bool = False
    # The Telegram group of the project (FR-NTF-02).
    telegram_chat_title: str | None = None
    telegram_linked: bool = False
    github_token_ref: str | None = None
    # Where delivery work lives for this project: GITLAB, GITHUB or nothing.
    delivery_system: str | None = None
    owner_member_id: str | None = None
    owner_name: str | None = None
    done_evidence: str = "COMMIT"
    agent_ready: bool = False


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255)
    code: str = Field(..., min_length=2, max_length=32)
    intake_key: str = Field(..., min_length=2, max_length=8)
    kind: str = Field(..., pattern="^(IDEA|NON_CODE|SOFTWARE)$")
    gitlab_project_path: str | None = Field(default=None, max_length=512)
    gitlab_probe_id: str | None = Field(default=None, max_length=36)
    github_repository: str | None = Field(default=None, max_length=512)
    github_token_ref: str | None = Field(default=None, max_length=64)
    github_probe_id: str | None = Field(default=None, max_length=36)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    kind: str | None = Field(default=None, pattern="^(IDEA|NON_CODE|SOFTWARE)$")
    status: str | None = Field(default=None, pattern="^(ACTIVE|INACTIVE)$")
    gitlab_project_path: str | None = Field(default=None, max_length=512)
    gitlab_probe_id: str | None = Field(default=None, max_length=36)
    github_repository: str | None = Field(default=None, max_length=512)
    github_token_ref: str | None = Field(default=None, max_length=64)
    github_probe_id: str | None = Field(default=None, max_length=36)


class IntegrationProbeCreate(BaseModel):
    system: str = Field(..., pattern="^(GITLAB|GITHUB)$")
    action: str = Field(..., pattern="^(LIST|CHECK|MEMBERS|TOKENS)$")
    # GitHub only: the name of the environment variable that holds this project's token.
    token_ref: str | None = Field(default=None, max_length=64)
    reference: str | None = Field(default=None, max_length=512)


class IntegrationProbeOut(BaseModel):
    id: str
    system: str
    action: str
    reference: str | None = None
    status: str
    result: dict | list | None = None
    error_code: str | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


class PasswordResetRequestIn(BaseModel):
    identifier: str = Field(..., min_length=3, max_length=320)


class PasswordResetConfirm(BaseModel):
    token: str = Field(..., min_length=32, max_length=256)
    new_password: str = Field(..., min_length=1, max_length=256)


class PasswordResetAccepted(BaseModel):
    accepted: bool = True
    message: str


class AccountProjectOut(BaseModel):
    id: str
    code: str
    name: str


class AccountOut(BaseModel):
    id: str
    subject: str
    email: str
    display_name: str
    role: str
    is_active: bool
    mfa_enabled: bool
    must_change_password: bool
    member_id: str | None = None
    member_name: str | None = None
    # When a personal token of this account last called Intake; None means no agent has been connected.
    agent_last_used_at: datetime | None = None
    projects: list[AccountProjectOut] = Field(default_factory=list)


class AccountCreate(BaseModel):
    subject: str = Field(..., min_length=3, max_length=64)
    # A Developer takes email and name from the staff member; a Project Owner gives them here.
    email: str | None = Field(default=None, min_length=3, max_length=320, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    project_ids: list[str] = Field(default_factory=list, max_length=100)
    role: Literal["PROJECT_OWNER", "DEVELOPER"] = "PROJECT_OWNER"
    member_id: str | None = Field(default=None, max_length=64)


class AccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None
    project_ids: list[str] | None = Field(default=None, max_length=100)
    # The staff member this login is; "" clears the link. The CTO links their own login so hours and Telegram find them.
    member_id: str | None = Field(default=None, max_length=64)


class AccountWithPassword(BaseModel):
    account: AccountOut
    # Shown once, right after creating the account or resetting its password.
    temporary_password: str


class ProjectTeamMemberOut(BaseModel):
    member_id: str
    display_name: str
    email: str | None = None
    is_owner: bool = False
    delivery_user_id: str | None = None
    account_subject: str | None = None
    account_active: bool = False


class ProjectTeamIssued(BaseModel):
    subject: str
    display_name: str
    # Shown once, when choosing the owner created or unlocked their account.
    temporary_password: str


class ProjectTeamOut(BaseModel):
    project_id: str
    project_code: str
    owner_member_id: str | None = None
    members: list[ProjectTeamMemberOut] = Field(default_factory=list)
    issued: ProjectTeamIssued | None = None


class ProjectTeamUpdate(BaseModel):
    owner_member_id: str | None = Field(default=None, max_length=36)
    member_ids: list[str] = Field(default_factory=list, max_length=200)


class ProjectMemberAdd(BaseModel):
    member_id: str = Field(..., min_length=36, max_length=36)


class ProjectMemberCandidateOut(BaseModel):
    member_id: str
    display_name: str
    email: str | None = None


class ProjectMemberAddedOut(BaseModel):
    added: bool
    team: ProjectTeamOut


class ProjectMemberRemovedOut(BaseModel):
    removed: bool
    team: ProjectTeamOut


class PlanningAddWorkRequest(BaseModel):
    expected_run_version: int = Field(..., ge=1)
    project_id: str
    source: Literal["ISSUE", "INTAKE", "NEW"]
    issue_external_id: str | None = Field(default=None, max_length=255)
    intake_id: str | None = Field(default=None, max_length=64)
    title: str | None = Field(default=None, max_length=255)
    content: str | None = Field(default=None, max_length=20_000)
    channel: Channel = "MANUAL"
    item_type: Literal["BUG", "TASK", "FEATURE"] = "TASK"
    priority: Priority = "P1"
    # Required when an Issue has to be created: it replaces the usual review of the Intake.
    reason: str | None = Field(default=None, max_length=2000)
    member_id: str | None = Field(default=None, max_length=36)
    slot: PlanningSlot | None = None
    planned_hours: float | None = Field(default=None, gt=0, le=24)
    override_reason: str | None = Field(default=None, max_length=2000)


class PlanningProjectOrderUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["PRIORITY", "CUSTOM"]
    project_ids: list[str] = Field(default_factory=list, max_length=200)


class PlanningProjectOrderOut(BaseModel):
    mode: Literal["PRIORITY", "CUSTOM"]
    project_ids: list[str] = Field(default_factory=list)


class PlanningWorkItemOut(BaseModel):
    kind: Literal["ISSUE", "INTAKE"]
    project_id: str
    project_name: str | None = None
    issue_external_id: str | None = None
    intake_id: str | None = None
    public_id: str | None = None
    title: str
    priority: str | None = None
    already_planned: bool = False
    needs_issue: bool = False
    # For Issues: where to open it, who has it, and why it is offered first when scheduling a waiting entry.
    url: str | None = None
    assignee_names: list[str] = Field(default_factory=list)
    unknown_assignees: int = 0
    milestone: str | None = None
    due_date: date | None = None
    suggested: Literal["PERSON", "TITLE"] | None = None
    assigned_to_other: bool = False


class PlanningAddWorkOut(BaseModel):
    # PLANNED: assigned in the run. WAITING_ASSIGNMENT: in the run, not assigned. CREATING_ISSUE: the Issue is being created.
    state: Literal["PLANNED", "WAITING_ASSIGNMENT", "CREATING_ISSUE"]
    candidate: PlanningCandidateOut
    assignment_error: str | None = None
    # The person already has a main Issue that day, so this was added as secondary work.
    added_as_secondary: bool = False


class PlanningDayStatus(BaseModel):
    plan_date: date
    run_id: str | None = None
    status: str | None = None
    assigned: int = 0
    waiting: int = 0


class OverviewReadiness(BaseModel):
    state: Literal["READY", "MISSING", "NO_WORK"]
    reasons: list[str] = Field(default_factory=list)


class OverviewReports(BaseModel):
    report_date: date | None = None
    expected: int = 0
    received: int = 0
    missing: list[str] = Field(default_factory=list)
    late: int = 0
    malformed: int = 0
    unreviewed: int = 0
    items_without_issue: int = 0


class OverviewApprovals(BaseModel):
    pending: int = 0
    urgent: int = 0
    cto: int = 0
    po: int = 0
    overdue: int = 0
    has_owner: bool = False


class OverviewOverdue(BaseModel):
    approvals: int = 0
    waiting: int = 0
    work_log: int = 0
    p0_open: int = 0


class OverviewCtoDay(BaseModel):
    date: date
    minutes: int = 0


class OverviewCtoTime(BaseModel):
    today_minutes: int = 0
    actions_today: int = 0
    avg7_minutes: int = 0
    days: list[OverviewCtoDay] = Field(default_factory=list)


class OverviewMeetings(BaseModel):
    yesterday: int = 0
    notes_pending: int = 0
    items_unconverted: int = 0


class OverviewPlan(BaseModel):
    run_id: str | None = None
    status: str | None = None
    scope: Literal["PROJECT", "ALL"] | None = None
    assigned_people: int = 0
    assigned_hours: float = 0
    waiting: int = 0
    warnings: int = 0
    available_hours: float = 0
    people_today: int = 0
    made_by: str | None = None
    updated_at: datetime | None = None


class OverviewAcceptance(BaseModel):
    verifications_pending: int = 0
    work_log_pending: int = 0


class OverviewGitLab(BaseModel):
    snapshot_at: datetime | None = None
    fresh: bool = False
    open_p0: int = 0


class OverviewContext(BaseModel):
    """The project's context pack as scored (FR-CTX-04)."""

    band: str = "MISSING"
    score: int = 0
    missing: list[str] = Field(default_factory=list)
    approved: bool = False


class PlanningOverviewProject(BaseModel):
    id: str
    code: str
    name: str
    p0: bool = False
    readiness: OverviewReadiness
    context: OverviewContext = Field(default_factory=OverviewContext)
    reports: OverviewReports
    approvals: OverviewApprovals
    unsynced: int = 0
    stuck: int = 0
    meetings: OverviewMeetings
    plan: OverviewPlan
    acceptance: OverviewAcceptance
    gitlab: OverviewGitLab
    people_off: list[str] = Field(default_factory=list)
    unassigned: list[str] = Field(default_factory=list)
    carry_over: int = 0
    overdue: OverviewOverdue = Field(default_factory=OverviewOverdue)
    attention: int = 0


class PlanningOverviewOut(BaseModel):
    plan_date: date
    generated_at: datetime
    gitlab_snapshot_at: datetime | None = None
    missing_projects: int = 0
    overdue_total: int = 0
    projects: list[PlanningOverviewProject] = Field(default_factory=list)
    cto_time: OverviewCtoTime | None = None


class WeekHours(BaseModel):
    available: float = 0
    planned: float = 0
    reported: float = 0


class WeekReports(BaseModel):
    expected: int = 0
    received: int = 0
    missing: int = 0
    late: int = 0


class WeekItems(BaseModel):
    reported: int = 0
    without_issue: int = 0
    no_issue_needed: int = 0


class WeekDone(BaseModel):
    reported: int = 0
    issues_closed: int = 0
    accepted: int = 0
    po_accepted: int = 0
    rejected: int = 0
    work_logs_confirmed: int = 0
    accepted_without_evidence: int = 0


class WeekRequests(BaseModel):
    new: int = 0
    approved: int = 0
    approved_within_24h: int = 0
    from_planning: int = 0
    avg_wait_hours: float | None = None
    avg_to_issue_hours: float | None = None


class WeekBoard(BaseModel):
    days: int = 0
    ready_days: int = 0
    no_work_days: int = 0
    overdue_days: int = 0
    max_approvals_overdue: int = 0
    max_stuck: int = 0
    escalated_days: int = 0


class WeekPlans(BaseModel):
    total: int = 0
    closed: int = 0


class WeekProject(BaseModel):
    id: str
    code: str
    name: str
    people: int = 0
    hours: WeekHours
    plans: WeekPlans
    done: WeekDone
    items: WeekItems
    reports: WeekReports
    requests: WeekRequests
    board: WeekBoard


class WeekPersonProject(BaseModel):
    id: str
    name: str
    planned: float = 0
    reported: float = 0


class WeekPerson(BaseModel):
    member_id: str
    display_name: str
    hours: WeekHours
    done_reported: int = 0
    items: WeekItems
    reports: WeekReports
    projects: list[WeekPersonProject] = Field(default_factory=list)


class WeekProcess(BaseModel):
    requests_new: int = 0
    approved: int = 0
    approved_within_24h: int = 0
    avg_wait_hours: float | None = None
    from_queue: int = 0
    from_planning: int = 0
    issues_created: int = 0
    avg_to_issue_hours: float | None = None
    board_days: int = 0
    ready_days: int = 0
    overdue_project_days: int = 0
    escalated_project_days: int = 0
    max_stuck: int = 0


class WeekSummaryOut(BaseModel):
    week_start: date
    week_end: date
    days_passed: int = 0
    generated_at: datetime
    projects: list[WeekProject] = Field(default_factory=list)
    people: list[WeekPerson] = Field(default_factory=list)
    process: WeekProcess
    cto_days: list[OverviewCtoDay] | None = None
    personal: dict[str, object] | None = None
    text: str = ""


class PeopleDayProject(BaseModel):
    id: str
    name: str
    hours: float = 0
    run_status: str | None = None


class PeopleDayPerson(BaseModel):
    member_id: str
    display_name: str
    available_hours: float = 0
    planned_hours: float = 0
    free_hours: float = 0
    state: Literal["OVER", "FREE", "OK", "OFF"]
    projects: list[PeopleDayProject] = Field(default_factory=list)


class PeopleDayOut(BaseModel):
    plan_date: date
    over: int = 0
    free: int = 0
    people: list[PeopleDayPerson] = Field(default_factory=list)


class PlanningAssignmentUnassign(BaseModel):
    expected_run_version: int = Field(..., ge=1)


class PlanningAssignmentMove(BaseModel):
    expected_run_version: int = Field(..., ge=1)
    slot: PlanningSlot
    member_id: str | None = Field(default=None, max_length=36)
    override_reason: str | None = Field(default=None, max_length=2000)


class PlanningAssignWaitingRequest(BaseModel):
    expected_run_version: int = Field(..., ge=1)
    member_id: str = Field(..., max_length=36)
    slot: PlanningSlot
    planned_hours: float = Field(..., gt=0, le=24)
    # EXISTING links an Issue that already exists; CREATE has one created (needs a reason).
    issue_mode: Literal["EXISTING", "CREATE"] = "EXISTING"
    issue_external_id: str | None = Field(default=None, max_length=255)
    item_type: Literal["BUG", "TASK", "FEATURE"] = "TASK"
    priority: Priority = "P2"
    reason: str | None = Field(default=None, max_length=2000)
    override_reason: str | None = Field(default=None, max_length=2000)


class IntakeJourneyDecision(BaseModel):
    action: str
    at: datetime
    by: str | None = None
    route: str | None = None
    priority: str | None = None


class IntakeJourneyIssue(BaseModel):
    system: str
    external_id: str
    url: str | None = None


class IntakeJourneyPlan(BaseModel):
    plan_date: date
    run_id: str
    assignment_id: str
    member_name: str
    slot: str
    planned_hours: float
    settled: bool
    work_status: str = "PLANNED"
    work_status_at: datetime | None = None
    accepted_at: datetime | None = None


class IntakeJourneyWaiting(BaseModel):
    plan_date: date
    run_id: str
    # The plan was closed with this request still waiting: it comes back on the next day's plan.
    plan_closed: bool = False


class IntakeJourneyVerification(BaseModel):
    id: str
    decision: str
    source: str
    created_at: datetime
    reason: str | None = None


class IntakeJourneyOut(BaseModel):
    intake_id: str
    intake_public_id: str
    project_id: str
    status: str
    received_at: datetime
    channel: str
    decision: IntakeJourneyDecision | None = None
    issue: IntakeJourneyIssue | None = None
    other_target: str | None = None
    work_item: WorkRef | None = None
    # Work items created under a decision that was later reopened: still out there, no longer in use.
    previous_targets: list[IntakeJourneyIssue] = Field(default_factory=list)
    sync_status: str | None = None
    accepted_at: datetime | None = None
    # The human/agent completion claim for the current Issue, including a pending item the CTO can decide here.
    verification: IntakeJourneyVerification | None = None
    plans: list[IntakeJourneyPlan] = Field(default_factory=list)
    waiting_in_plan: IntakeJourneyWaiting | None = None
    # The latest piece of work logged about the request, and whether the CTO has checked it.
    work: IntakeJourneyWork | None = None
    # Tracker evidence without a work log is a reconciliation warning, never an automatic acceptance.
    unlogged_evidence: IntakeJourneyEvidenceGap | None = None


class IntakeJourneyWork(BaseModel):
    entries: int
    latest_id: str
    latest_decision: str
    latest_at: datetime
    latest_by: str | None = None
    off_plan: bool = False
    worked_on: date | None = None
    actual_minutes: int | None = None
    deployed: bool | None = None


class IntakeJourneyEvidenceGap(BaseModel):
    commits: int = 0
    merge_requests: int = 0
    links: int = 0


IntakeSplitOut.model_rebuild()
IntakeDetails.model_rebuild()
IntakeJourneyOut.model_rebuild()
MeetingNoteWorkOut.model_rebuild()


class PersonalTaskIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    # None: no date yet, the task waits in the matrix.
    task_date: date | None = None
    hours: float = Field(default=0, ge=0, le=24)
    start_time: str | None = Field(default=None, max_length=5)
    remind_at: str | None = Field(default=None, max_length=5)
    note: str | None = Field(default=None, max_length=2000)
    important: bool = False
    # None: the date decides (today, tomorrow or a reminder set).
    urgent: bool | None = None
    repeat_rule: str | None = Field(default=None, max_length=16)


class PersonalTaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    task_date: date | None = None
    hours: float | None = Field(default=None, ge=0, le=24)
    start_time: str | None = Field(default=None, max_length=5)
    remind_at: str | None = Field(default=None, max_length=5)
    note: str | None = Field(default=None, max_length=2000)
    status: Literal["PLANNED", "DONE", "SKIPPED"] | None = None
    important: bool | None = None
    urgent: bool | None = None
    archived: bool | None = None
    repeat_rule: str | None = Field(default=None, max_length=16)


class PersonalDelegateIn(BaseModel):
    member_id: str = Field(..., max_length=64)
    project_id: str = Field(..., max_length=64)
    task_date: date
    hours: float | None = Field(default=None, gt=0, le=24)


class PersonalTaskOut(BaseModel):
    id: str
    task_date: date | None = None
    title: str
    note: str | None = None
    hours: float
    start_time: str | None = None
    remind_at: str | None = None
    status: str
    done_at: datetime | None = None
    important: bool = False
    urgent: bool | None = None
    urgent_effective: bool = False
    quadrant: int = 4
    quadrant_label: str = ""
    rollover_count: int = 0
    archived_at: datetime | None = None
    delegated_member_id: str | None = None
    delegated_member_name: str | None = None
    delegated_assignment_id: str | None = None
    repeat_rule: str | None = None
    repeat_label: str | None = None
    done_quadrant: int | None = None
    plan: dict[str, object] | None = None
    created_at: datetime
    updated_at: datetime


class PersonalQuadrantSummary(BaseModel):
    quadrant: int
    label: str
    open: int
    hours: float


class PersonalMatrixSummary(BaseModel):
    today_open: int
    today_hours: float
    quadrants: list[PersonalQuadrantSummary]
    rolled_over: int
    undated: int
    overdue: int


class PersonalMatrixOut(BaseModel):
    week_start: date
    week_end: date
    today: date
    tasks: list[PersonalTaskOut]
    summary: PersonalMatrixSummary


# --- Work tracked inside Intake (FR-WRK-01..06, ADR-0066) ---------------------------------------------

WorkStatus = Literal["DISCUSS", "READY", "IN_PROGRESS", "ACCEPTANCE", "APPROVED", "DONE", "CANCELLED"]
ChannelCode = Literal["FACEBOOK_PAGE", "FACEBOOK_PERSONAL", "THREADS", "X", "LINKEDIN", "INSTAGRAM", "TIKTOK", "YOUTUBE", "REELS", "EMAIL", "WEBSITE", "BLOG"]
PostFormat = Literal["POST", "IMAGE", "VIDEO", "LONGFORM", "EMAIL"]


class WorkChannelIn(BaseModel):
    """A channel a post goes out on, with its own date (FR-MKT-01)."""

    channel: ChannelCode
    publish_at: datetime | None = None
    language: str | None = Field(default=None, max_length=8)


class WorkChannelOut(BaseModel):
    id: str
    channel: str
    publish_at: datetime | None = None
    status: Literal["DRAFT", "READY", "PUBLISHED"] = "DRAFT"
    published_url: str | None = None
    language: str | None = None
    text: str | None = None
    short_link: PostLinkOut | None = None


class WorkChannelUpdate(BaseModel):
    publish_at: datetime | None = None
    clear_publish: bool = False
    status: Literal["DRAFT", "READY", "PUBLISHED"] | None = None
    published_url: str | None = Field(default=None, max_length=1000)
    text: str | None = Field(default=None, max_length=60000)
    clear_text: bool = False


class WorkBulkRow(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    channel: ChannelCode | None = None
    publish_at: datetime | None = None
    member_id: str | None = None
    campaign: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=20000)


class WorkBulkCreate(BaseModel):
    project: str = Field(..., min_length=1, max_length=64)
    rows: list[WorkBulkRow] = Field(..., min_length=1, max_length=50)


class WorkBulkUpdate(BaseModel):
    ids: list[str] = Field(..., min_length=1, max_length=100)
    member_id: str | None = None
    clear_member: bool = False
    publish_at: datetime | None = None
    status: WorkStatus | None = None


class ChannelRuleOut(BaseModel):
    code: str
    label: str
    language: str
    max_chars: int
    recommended_chars: int | None = None
    long_max_chars: int | None = None
    max_images: int
    image_ratio: str | None = None
    video_ratio: str | None = None
    hashtag_max: int
    link_counts_chars: bool
    link_chars: int
    best_hours: list[str] = Field(default_factory=list)
    tone: str | None = None
    enabled: bool
    auto_publish: bool = False
    sort_order: int
    updated_at: datetime


class ChannelRuleUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=60)
    language: Literal["vi", "en"] | None = None
    max_chars: int | None = Field(default=None, ge=1, le=1_000_000)
    recommended_chars: int | None = Field(default=None, ge=0, le=1_000_000)
    long_max_chars: int | None = Field(default=None, ge=0, le=1_000_000)
    max_images: int | None = Field(default=None, ge=0, le=100)
    image_ratio: str | None = Field(default=None, max_length=40)
    video_ratio: str | None = Field(default=None, max_length=40)
    hashtag_max: int | None = Field(default=None, ge=0, le=100)
    link_counts_chars: bool | None = None
    link_chars: int | None = Field(default=None, ge=0, le=200)
    best_hours: list[str] | None = None
    tone: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    auto_publish: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)


class WorkCreate(BaseModel):
    project: str = Field(..., min_length=1, max_length=64, description="Project code or id")
    title: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    priority: Priority = "P3"
    member_id: str | None = None
    due_date: date | None = None
    status: Literal["DISCUSS", "READY", "IN_PROGRESS", "ACCEPTANCE"] = "DISCUSS"
    # A pipeline: the item is the parent, its steps are made as children (FR-WRK-08).
    template: Literal["VIDEO"] | None = None
    # A post (FR-MKT-01): main channel, format, campaign label, Gấp, and the channel versions with their dates.
    channel: ChannelCode | None = None
    format: PostFormat | None = None
    campaign: str | None = Field(default=None, max_length=80)
    urgent: bool = False
    channels: list[WorkChannelIn] = Field(default_factory=list, max_length=12)


class WorkUpdate(BaseModel):
    expected_version: int = Field(..., ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    priority: Priority | None = None
    member_id: str | None = None
    clear_member: bool = False
    due_date: date | None = None
    clear_due: bool = False
    channel: ChannelCode | None = None
    format: PostFormat | None = None
    campaign: str | None = Field(default=None, max_length=80)
    clear_campaign: bool = False
    urgent: bool | None = None


class WorkMove(BaseModel):
    expected_version: int = Field(..., ge=1)
    status: WorkStatus
    note: str | None = Field(default=None, max_length=500)


class WorkCommentCreate(BaseModel):
    body: str = Field(..., min_length=2, max_length=5000)


class WorkCommentOut(BaseModel):
    id: str
    user_id: str | None = None
    user_name: str | None = None
    mine: bool = False
    body: str
    created_at: datetime


class WorkLinkCreate(BaseModel):
    url: str = Field(..., min_length=8, max_length=1000)
    note: str | None = Field(default=None, max_length=300)


class WorkLinkOut(BaseModel):
    id: str
    url: str
    note: str | None = None
    source: str = "USER"
    added_by: str | None = None
    added_by_name: str | None = None
    mine: bool = False
    created_at: datetime


class WorkHistoryOut(BaseModel):
    at: datetime
    actor_name: str | None = None
    event_type: str
    details: dict = Field(default_factory=dict)


class WorkOut(BaseModel):
    id: str
    code: str
    project_id: str
    project_code: str | None = None
    project_name: str | None = None
    project_kind: str | None = None
    title: str
    description: str = ""
    status: WorkStatus
    priority: Priority
    member_id: str | None = None
    member_name: str | None = None
    due_date: date | None = None
    intake_id: str | None = None
    intake_public_id: str | None = None
    intake_status: str | None = None
    issue_system: str | None = None
    issue_external_id: str | None = None
    issue_url: str | None = None
    outcome: str | None = None
    issue_pending: bool = False
    closed_note: str | None = None
    comment_count: int = 0
    link_count: int = 0
    version: int
    template: str | None = None
    steps_total: int = 0
    steps_done: int = 0
    parent_id: str | None = None
    parent_code: str | None = None
    step: str | None = None
    step_label: str | None = None
    step_order: int | None = None
    evidence_required: bool = False
    meeting_id: str | None = None
    meeting_title: str | None = None
    meeting_at: datetime | None = None
    channel: str | None = None
    format: str | None = None
    campaign: str | None = None
    urgent: bool = False
    channels: list[WorkChannelOut] = Field(default_factory=list)
    next_publish_at: datetime | None = None
    created_by: str | None = None
    created_by_name: str | None = None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None = None


class WorkDetail(WorkOut):
    comments: list[WorkCommentOut] = Field(default_factory=list)
    links: list[WorkLinkOut] = Field(default_factory=list)
    steps: list[WorkOut] = Field(default_factory=list)
    history: list[WorkHistoryOut] = Field(default_factory=list)


class SetupStateOut(BaseModel):
    completed: bool
    has_project: bool
    has_private_space: bool
    sample_available: bool
    # The first-run wizard (ADR-0071): `wizard` is the installer's flag, `ai_ready` says a route reaches an enabled provider.
    wizard: bool = False
    ai_ready: bool = False


class SetupStatusOut(BaseModel):
    needs_bootstrap: bool


class BootstrapAccountIn(BaseModel):
    email: str
    display_name: str
    password: str


class BootstrapIn(BaseModel):
    cto: BootstrapAccountIn
    owner: BootstrapAccountIn | None = None


class AiProviderIn(BaseModel):
    name: str
    base_url: str
    api_key: str
    enabled: bool = True
    extra_body: dict | None = None


class AiProviderPatch(BaseModel):
    name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    enabled: bool | None = None
    extra_body: dict | None = None


class AiProviderOut(BaseModel):
    id: str
    name: str
    base_url: str
    enabled: bool
    key_hint: str
    key_ok: bool
    extra_body: dict | None = None
    last_test_at: datetime | None = None
    last_test_ok: bool | None = None
    last_test_error: str | None = None


class AiProviderTestOut(BaseModel):
    ok: bool
    error: str | None = None
    models: list[str] = Field(default_factory=list)


class AiRouteIn(BaseModel):
    provider_id: str | None = None
    model: str | None = None


class AiRouteOut(BaseModel):
    task: str
    provider_id: str | None = None
    provider_name: str | None = None
    model: str | None = None
    source: str
    effective_provider: str | None = None
    effective_model: str | None = None
