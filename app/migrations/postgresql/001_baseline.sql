-- Baseline of the schema as of the first public release.
-- Generated 2026-10-28 from 61 migrations; later migrations apply on top.

-- from 001_gate_a_baseline.sql
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_subject VARCHAR(255) NOT NULL UNIQUE,
    email CITEXT NOT NULL UNIQUE,
    display_name VARCHAR(255) NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'PROJECT_OWNER' CHECK (role IN ('CTO', 'PROJECT_OWNER')),
    password_hash TEXT NOT NULL,
    mfa_secret_ciphertext TEXT,
    mfa_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE mfa_recovery_codes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    code_hash TEXT NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_mfa_recovery_user_hash UNIQUE (user_id, code_hash)
);

CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(128) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    ip_hash VARCHAR(128),
    user_agent_hash VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_user_sessions_active ON user_sessions(user_id, expires_at) WHERE revoked_at IS NULL;

CREATE TABLE customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code CITEXT NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES customers(id),
    code CITEXT NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    settings JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE project_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    system VARCHAR(32) NOT NULL CHECK (system IN ('PLANE', 'GITLAB')),
    base_url TEXT NOT NULL,
    workspace_external_id VARCHAR(255),
    project_external_id VARCHAR(255),
    credential_ref VARCHAR(255),
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    config JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_project_integrations_project_system UNIQUE (project_id, system)
);

CREATE TABLE gitlab_issue_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    issue_external_id VARCHAR(255) NOT NULL,
    global_external_id VARCHAR(255),
    title VARCHAR(512) NOT NULL,
    state VARCHAR(32) NOT NULL,
    labels JSONB NOT NULL,
    assignee_external_ids JSONB NOT NULL,
    milestone_external_id VARCHAR(255),
    milestone_title VARCHAR(255),
    due_date DATE,
    web_url TEXT,
    external_updated_at TIMESTAMPTZ,
    payload_hash VARCHAR(64) NOT NULL,
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    fetched_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_gitlab_issue_snapshot_hash UNIQUE (project_id, issue_external_id, payload_hash)
);
CREATE INDEX ix_gitlab_issue_current ON gitlab_issue_snapshots(project_id, state, is_current);

CREATE TABLE intake_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    public_id VARCHAR(64) NOT NULL UNIQUE,
    project_id UUID NOT NULL REFERENCES projects(id),
    customer_id UUID REFERENCES customers(id),
    channel VARCHAR(32) NOT NULL,
    item_type VARCHAR(32) NOT NULL DEFAULT 'UNCLEAR',
    status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    normalized_title VARCHAR(255),
    normalized_summary TEXT,
    suggested_priority VARCHAR(8),
    approved_priority VARCHAR(8),
    proposed_route VARCHAR(32),
    approved_route VARCHAR(32),
    current_extraction_id UUID,
    duplicate_of_id UUID REFERENCES intake_items(id),
    defer_until TIMESTAMPTZ,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    closed_at TIMESTAMPTZ
);
CREATE INDEX ix_intake_project_status_updated ON intake_items(project_id, status, updated_at DESC, id DESC);
CREATE INDEX ix_intake_project_created ON intake_items(project_id, created_at DESC, id DESC);

CREATE TABLE source_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    channel VARCHAR(32) NOT NULL,
    external_message_id VARCHAR(255),
    sender_reference_ciphertext TEXT,
    raw_content_ciphertext TEXT,
    content_hash VARCHAR(64),
    raw_payload JSONB,
    received_at TIMESTAMPTZ NOT NULL,
    purge_after TIMESTAMPTZ NOT NULL,
    purged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_source_messages_intake_created ON source_messages(intake_id, created_at);
CREATE INDEX ix_source_messages_content_hash ON source_messages(content_hash);
CREATE INDEX ix_source_messages_purge ON source_messages(purge_after) WHERE purged_at IS NULL;

CREATE TABLE attachments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    source_message_id UUID REFERENCES source_messages(id),
    object_key VARCHAR(512) NOT NULL UNIQUE,
    original_name_ciphertext TEXT,
    declared_mime_type VARCHAR(128),
    detected_mime_type VARCHAR(128),
    size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    storage_state VARCHAR(32) NOT NULL DEFAULT 'QUARANTINE',
    scan_status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    ocr_status VARCHAR(32) NOT NULL DEFAULT 'NONE',
    purge_after TIMESTAMPTZ NOT NULL,
    purged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_attachments_intake_created ON attachments(intake_id, created_at);
CREATE INDEX ix_attachments_sha256 ON attachments(sha256);
CREATE INDEX ix_attachments_purge ON attachments(purge_after) WHERE purged_at IS NULL;

CREATE TABLE processing_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    run_type VARCHAR(32) NOT NULL,
    stage VARCHAR(32) NOT NULL,
    parent_run_id UUID REFERENCES processing_runs(id),
    job_key VARCHAR(255) NOT NULL UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'QUEUED',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    input_hash VARCHAR(64),
    output_hash VARCHAR(64),
    retryable BOOLEAN NOT NULL DEFAULT TRUE,
    next_attempt_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    run_metadata JSONB,
    worker_id VARCHAR(128),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    error_code VARCHAR(128),
    error_detail_redacted TEXT,
    CONSTRAINT ck_processing_runs_attempts CHECK (attempt >= 0 AND max_attempts > 0)
);
CREATE INDEX ix_processing_runs_intake_created ON processing_runs(intake_id, created_at);
CREATE INDEX ix_processing_runs_dispatch ON processing_runs(status, next_attempt_at, created_at) WHERE status IN ('QUEUED', 'RETRY');

CREATE TABLE evidence_fragments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processing_run_id UUID NOT NULL REFERENCES processing_runs(id) ON DELETE CASCADE,
    attachment_id UUID REFERENCES attachments(id),
    source_message_id UUID REFERENCES source_messages(id),
    page_number INTEGER,
    fragment_order INTEGER NOT NULL,
    content_ciphertext TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    bounding_box JSONB,
    extractor VARCHAR(128) NOT NULL,
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_evidence_run_order UNIQUE (processing_run_id, fragment_order)
);

CREATE TABLE ai_extractions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    processing_run_id UUID NOT NULL REFERENCES processing_runs(id),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    schema_version VARCHAR(64) NOT NULL,
    prompt_version VARCHAR(64) NOT NULL,
    model_provider VARCHAR(32) NOT NULL,
    model_name VARCHAR(128) NOT NULL,
    input_policy VARCHAR(64) NOT NULL,
    result JSONB NOT NULL,
    confidence DOUBLE PRECISION CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    token_usage JSONB,
    fallback_reason VARCHAR(128),
    latency_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_ai_extractions_intake_created ON ai_extractions(intake_id, created_at);
ALTER TABLE intake_items ADD CONSTRAINT fk_intake_current_extraction FOREIGN KEY (current_extraction_id) REFERENCES ai_extractions(id);

CREATE TABLE duplicate_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    candidate_type VARCHAR(32) NOT NULL,
    candidate_reference VARCHAR(255) NOT NULL,
    match_method VARCHAR(32) NOT NULL,
    score DOUBLE PRECISION CHECK (score IS NULL OR (score >= 0 AND score <= 1)),
    decision VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    decided_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_duplicate_candidate UNIQUE (intake_id, candidate_type, candidate_reference)
);
CREATE INDEX ix_duplicate_candidates_intake_decision ON duplicate_candidates(intake_id, decision);

CREATE TABLE approval_actions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    actor_id UUID REFERENCES users(id),
    action VARCHAR(32) NOT NULL,
    reason TEXT,
    item_version INTEGER NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_approval_actions_intake_created ON approval_actions(intake_id, created_at);

CREATE TABLE approval_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_action_id UUID NOT NULL UNIQUE REFERENCES approval_actions(id),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    item_version INTEGER NOT NULL,
    approved_route VARCHAR(32) NOT NULL,
    payload JSONB NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    invalidated_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_approval_snapshots_intake_created ON approval_snapshots(intake_id, created_at);

CREATE TABLE sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    approval_snapshot_id UUID NOT NULL REFERENCES approval_snapshots(id),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    target_system VARCHAR(32) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    request_payload_hash VARCHAR(64) NOT NULL,
    response_metadata JSONB,
    error_code VARCHAR(128),
    error_detail_redacted TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_sync_jobs_attempts CHECK (attempt >= 0 AND max_attempts > 0)
);
CREATE INDEX ix_sync_jobs_dispatch ON sync_jobs(status, next_attempt_at, created_at) WHERE status IN ('PENDING', 'RETRY');

CREATE TABLE external_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sync_job_id UUID NOT NULL UNIQUE REFERENCES sync_jobs(id),
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    target_system VARCHAR(32) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    url VARCHAR(1024),
    payload_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_external_link_target UNIQUE (project_id, target_system, external_id)
);

CREATE TABLE outbox_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id UUID NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id),
    event_type VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    dedupe_key VARCHAR(255) NOT NULL UNIQUE,
    attempt INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    published_at TIMESTAMPTZ,
    error_detail_redacted TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_outbox_events_dispatch ON outbox_events(status, next_attempt_at, created_at) WHERE status IN ('NEW', 'RETRY', 'FAILED');

CREATE TABLE email_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    member_id UUID,
    supersedes_email_id UUID REFERENCES email_messages(id),
    mailbox VARCHAR(320) NOT NULL,
    uid_validity VARCHAR(64) NOT NULL,
    uid VARCHAR(64) NOT NULL,
    message_id VARCHAR(512),
    sender_address CITEXT NOT NULL,
    sender_name VARCHAR(255),
    report_date DATE,
    subject_ciphertext TEXT,
    body_ciphertext TEXT,
    content_hash VARCHAR(64) NOT NULL,
    parsed_summary TEXT,
    parse_version VARCHAR(32) NOT NULL DEFAULT 'daily-report-v1',
    parse_errors JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'NEW',
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    is_late BOOLEAN NOT NULL DEFAULT FALSE,
    received_at TIMESTAMPTZ NOT NULL,
    purge_after TIMESTAMPTZ NOT NULL,
    purged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_email_mailbox_uid UNIQUE (mailbox, uid_validity, uid)
);
CREATE INDEX ix_email_messages_message_id ON email_messages(message_id);
CREATE INDEX ix_email_report_member_date ON email_messages(member_id, report_date, is_current);

CREATE TABLE report_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    kind VARCHAR(32) NOT NULL,
    period_start TIMESTAMPTZ NOT NULL,
    period_end TIMESTAMPTZ NOT NULL,
    snapshot_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE report_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_run_id UUID REFERENCES report_runs(id) ON DELETE CASCADE,
    email_message_id UUID REFERENCES email_messages(id) ON DELETE CASCADE,
    intake_id UUID REFERENCES intake_items(id),
    project_id UUID REFERENCES projects(id),
    member_id UUID,
    source_type VARCHAR(32) NOT NULL,
    source_reference VARCHAR(512) NOT NULL,
    category VARCHAR(64) NOT NULL,
    work_status VARCHAR(32) NOT NULL,
    title VARCHAR(512) NOT NULL,
    summary TEXT NOT NULL,
    worked_hours NUMERIC(5,2) CHECK (worked_hours IS NULL OR worked_hours >= 0),
    remaining_hours NUMERIC(5,2),
    planned_hours NUMERIC(5,2),
    progress_percent INTEGER CHECK (progress_percent IS NULL OR (progress_percent >= 0 AND progress_percent <= 100)),
    next_step TEXT,
    gitlab_issue_external_id VARCHAR(255),
    plane_reference VARCHAR(255),
    intake_reference VARCHAR(255),
    deadline_text VARCHAR(255),
    dependency TEXT,
    progress_evidence JSONB,
    blocker BOOLEAN NOT NULL DEFAULT FALSE,
    blocker_detail TEXT,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    is_current BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE audit_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id),
    actor_type VARCHAR(32) NOT NULL DEFAULT 'USER',
    actor_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(128) NOT NULL,
    entity_type VARCHAR(64),
    entity_id UUID,
    request_id VARCHAR(128),
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_audit_project_created ON audit_events(project_id, created_at);

CREATE TABLE workforce_members (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    display_name VARCHAR(255) NOT NULL,
    email_reference CITEXT UNIQUE,
    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'INACTIVE')),
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    default_weekday_hours NUMERIC(4,2) NOT NULL DEFAULT 8
        CHECK (default_weekday_hours >= 0 AND default_weekday_hours <= 24),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
ALTER TABLE email_messages
    ADD CONSTRAINT fk_email_messages_member FOREIGN KEY (member_id) REFERENCES workforce_members(id);
ALTER TABLE report_items
    ADD CONSTRAINT fk_report_items_member FOREIGN KEY (member_id) REFERENCES workforce_members(id);

CREATE TABLE workforce_project_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES workforce_members(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    gitlab_user_external_id VARCHAR(255),
    role VARCHAR(64),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_workforce_membership_member_project UNIQUE (member_id, project_id)
);

CREATE TABLE daily_capacities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    member_id UUID NOT NULL REFERENCES workforce_members(id) ON DELETE CASCADE,
    work_date DATE NOT NULL,
    base_hours NUMERIC(4,2) NOT NULL,
    override_hours NUMERIC(4,2),
    meeting_hours NUMERIC(4,2) NOT NULL DEFAULT 0,
    review_hours NUMERIC(4,2) NOT NULL DEFAULT 0,
    support_hours NUMERIC(4,2) NOT NULL DEFAULT 0,
    fixed_hours NUMERIC(4,2) NOT NULL DEFAULT 0,
    available_hours NUMERIC(4,2) NOT NULL,
    override_reason TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    updated_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_daily_capacity_member_date UNIQUE (member_id, work_date),
    CONSTRAINT ck_daily_capacity_hours CHECK (
        base_hours >= 0 AND base_hours <= 24 AND
        (override_hours IS NULL OR (override_hours >= 0 AND override_hours <= 24)) AND
        meeting_hours >= 0 AND review_hours >= 0 AND support_hours >= 0 AND fixed_hours >= 0 AND
        available_hours >= 0 AND available_hours <= 24
    )
);

CREATE TABLE planning_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plan_date DATE NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Asia/Ho_Chi_Minh',
    project_scope JSONB NOT NULL,
    scope_hash VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT' CHECK (
        status IN ('DRAFT', 'REVIEW_REQUIRED', 'APPROVED', 'SYNCING', 'SYNCED', 'PARTIAL', 'SYNC_FAILED', 'SUPERSEDED')
    ),
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
    source_snapshot_at TIMESTAMPTZ NOT NULL,
    report_cutoff_at TIMESTAMPTZ,
    gitlab_snapshot_at TIMESTAMPTZ,
    supersedes_run_id UUID REFERENCES planning_runs(id),
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_planning_run_date_scope_revision UNIQUE (plan_date, scope_hash, revision)
);
CREATE INDEX ix_planning_run_date_status ON planning_runs(plan_date DESC, status, id DESC);

CREATE TABLE planning_assignments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planning_run_id UUID NOT NULL REFERENCES planning_runs(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    member_id UUID NOT NULL REFERENCES workforce_members(id),
    slot VARCHAR(16) NOT NULL CHECK (slot IN ('MORNING', 'AFTERNOON')),
    work_type VARCHAR(32) NOT NULL CHECK (work_type IN ('DEVELOPMENT', 'REVIEW', 'QA', 'SUPPORT', 'MEETING', 'FIXED')),
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    planned_hours NUMERIC(4,2) NOT NULL CHECK (planned_hours > 0 AND planned_hours <= 24),
    source_type VARCHAR(32) NOT NULL,
    source_reference VARCHAR(512) NOT NULL,
    gitlab_issue_external_id VARCHAR(255),
    proposed_priority VARCHAR(8),
    approved_priority VARCHAR(8),
    proposed_assignee_external_id VARCHAR(255),
    approved_assignee_external_id VARCHAR(255),
    proposed_milestone_external_id VARCHAR(255),
    approved_milestone_external_id VARCHAR(255),
    proposed_due_date DATE,
    approved_due_date DATE,
    dependency_state VARCHAR(32),
    source_state VARCHAR(32),
    override_reason TEXT,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_planning_assignment_member_slot
    ON planning_assignments(planning_run_id, member_id, slot);

CREATE TABLE planning_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planning_run_id UUID NOT NULL REFERENCES planning_runs(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    member_id UUID REFERENCES workforce_members(id),
    intake_id UUID REFERENCES intake_items(id),
    assignment_id UUID REFERENCES planning_assignments(id),
    source_type VARCHAR(32) NOT NULL CHECK (source_type IN ('GITLAB', 'INTAKE', 'PLANE', 'FORM', 'PASTE')),
    source_reference VARCHAR(512) NOT NULL,
    gitlab_issue_external_id VARCHAR(255),
    plane_reference VARCHAR(255),
    title VARCHAR(255) NOT NULL,
    summary TEXT,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING_TRIAGE' CHECK (
        status IN ('PENDING_TRIAGE', 'READY', 'ASSIGNED', 'REJECTED')
    ),
    proposed_priority VARCHAR(8),
    requested_hours NUMERIC(4,2) CHECK (requested_hours IS NULL OR (requested_hours > 0 AND requested_hours <= 24)),
    target_slot VARCHAR(16) CHECK (target_slot IS NULL OR target_slot IN ('MORNING', 'AFTERNOON')),
    idempotency_key_hash VARCHAR(64) UNIQUE,
    request_hash VARCHAR(64),
    created_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_planning_candidate_run_status
    ON planning_candidates(planning_run_id, status, created_at);

CREATE TABLE planning_warnings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planning_run_id UUID NOT NULL REFERENCES planning_runs(id) ON DELETE CASCADE,
    assignment_id UUID REFERENCES planning_assignments(id) ON DELETE CASCADE,
    member_id UUID REFERENCES workforce_members(id),
    project_id UUID REFERENCES projects(id),
    code VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL,
    source_values JSONB,
    message TEXT NOT NULL,
    acknowledged_by UUID REFERENCES users(id),
    acknowledged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_planning_warning_run_severity ON planning_warnings(planning_run_id, severity);

CREATE TABLE planning_approval_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planning_run_id UUID NOT NULL REFERENCES planning_runs(id),
    run_version INTEGER NOT NULL,
    approved_by UUID NOT NULL REFERENCES users(id),
    approved_at TIMESTAMPTZ NOT NULL,
    payload JSONB NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    warning_acknowledgements JSONB,
    override_reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_planning_snapshot_run_version UNIQUE (planning_run_id, run_version)
);

CREATE TABLE planning_sync_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    planning_snapshot_id UUID NOT NULL REFERENCES planning_approval_snapshots(id),
    project_id UUID NOT NULL REFERENCES projects(id),
    gitlab_issue_external_id VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    idempotency_key VARCHAR(128) NOT NULL UNIQUE,
    request_payload_hash VARCHAR(64) NOT NULL,
    before_state JSONB,
    after_state JSONB,
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_attempt_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    error_code VARCHAR(128),
    error_detail_redacted TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_planning_sync_attempts CHECK (attempt >= 0 AND max_attempts > 0),
    CONSTRAINT uq_planning_sync_snapshot_issue UNIQUE (
        planning_snapshot_id, project_id, gitlab_issue_external_id
    )
);
CREATE INDEX ix_planning_sync_dispatch
    ON planning_sync_jobs(status, next_attempt_at, created_at)
    WHERE status IN ('PENDING', 'RETRY');

-- from 002_gate_b_api_contract.sql
ALTER TABLE intake_items
    ADD COLUMN create_idempotency_key_hash VARCHAR(64),
    ADD COLUMN create_request_hash VARCHAR(64);

CREATE UNIQUE INDEX uq_intake_create_idempotency_key
    ON intake_items(create_idempotency_key_hash)
    WHERE create_idempotency_key_hash IS NOT NULL;

-- from 002_gate_e_plane_sync.sql
CREATE UNIQUE INDEX IF NOT EXISTS uq_sync_jobs_snapshot_target
    ON sync_jobs(approval_snapshot_id, target_system);

-- from 003_intake_codes_and_list_ux.sql
ALTER TABLE projects ADD COLUMN intake_key VARCHAR(8);
ALTER TABLE projects ALTER COLUMN intake_key SET NOT NULL;
ALTER TABLE projects ADD CONSTRAINT uq_projects_intake_key UNIQUE (intake_key);

CREATE TABLE intake_counters (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    iso_year INTEGER NOT NULL,
    iso_week INTEGER NOT NULL CHECK (iso_week BETWEEN 1 AND 53),
    last_value INTEGER NOT NULL CHECK (last_value BETWEEN 1 AND 999),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (project_id, iso_year, iso_week)
);

CREATE INDEX ix_sync_jobs_intake_created ON sync_jobs(intake_id, created_at DESC);
CREATE INDEX ix_external_links_intake_target ON external_links(intake_id, target_system, created_at DESC);

-- from 004_meeting_capture.sql
-- Additive migration (ADR-0018, OD-032): the pilot database holds real data and must not be reset.
CREATE TABLE meetings (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id),
    title VARCHAR(255) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'RECORDING' CHECK (status IN ('RECORDING', 'FINISHED', 'FAILED')),
    source VARCHAR(16) NOT NULL CHECK (source IN ('TAB_AND_MIC', 'MIC', 'FILE')),
    language VARCHAR(16) NOT NULL DEFAULT 'vi',
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    duration_seconds INTEGER CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    audio_chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (audio_chunk_count >= 0),
    audio_bytes BIGINT NOT NULL DEFAULT 0 CHECK (audio_bytes >= 0),
    audio_content_type VARCHAR(64),
    created_by VARCHAR(255) NOT NULL,
    purge_after TIMESTAMPTZ NOT NULL,
    purged_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_meetings_started ON meetings(started_at DESC);
CREATE INDEX ix_meetings_purge ON meetings(purge_after) WHERE purged_at IS NULL;

CREATE TABLE meeting_segments (
    id UUID PRIMARY KEY,
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    source VARCHAR(16) NOT NULL CHECK (source IN ('REALTIME', 'BATCH')),
    sequence INTEGER NOT NULL CHECK (sequence >= 0),
    speaker_label VARCHAR(64),
    start_ms INTEGER,
    end_ms INTEGER,
    text_ciphertext TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_meeting_segments_order UNIQUE (meeting_id, source, sequence)
);

CREATE TABLE glossary_terms (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    term VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX uq_glossary_terms_scope ON glossary_terms (COALESCE(project_id, '00000000-0000-0000-0000-000000000000'::uuid), LOWER(term));

-- from 005_meeting_transcript_and_notes.sql
-- Additive migration (ADR-0018 steps 2 and 3): speaker-separated transcript, provider cleanup and meeting notes.
ALTER TABLE meetings ADD COLUMN transcript_status VARCHAR(16) NOT NULL DEFAULT 'NONE' CHECK (transcript_status IN ('NONE', 'PENDING', 'RUNNING', 'DONE', 'FAILED', 'SKIPPED'));
ALTER TABLE meetings ADD COLUMN transcript_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE meetings ADD COLUMN transcript_claimed_at TIMESTAMPTZ;
ALTER TABLE meetings ADD COLUMN transcript_error VARCHAR(128);
ALTER TABLE meetings ADD COLUMN provider_transcription_id VARCHAR(128);
ALTER TABLE meetings ADD COLUMN provider_deleted_at TIMESTAMPTZ;
ALTER TABLE meetings ADD COLUMN note_status VARCHAR(16) NOT NULL DEFAULT 'NONE' CHECK (note_status IN ('NONE', 'PENDING', 'DONE', 'FAILED', 'SKIPPED'));
ALTER TABLE meetings ADD COLUMN note_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE meetings ADD COLUMN note_error VARCHAR(128);
ALTER TABLE meetings ADD COLUMN note_model VARCHAR(128);
ALTER TABLE meetings ADD COLUMN note_summary_ciphertext TEXT;
ALTER TABLE meetings ADD COLUMN speaker_names JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE meetings SET transcript_status = 'PENDING' WHERE status = 'FINISHED' AND audio_chunk_count > 0;

CREATE TABLE meeting_note_items (
    id UUID PRIMARY KEY,
    meeting_id UUID NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    kind VARCHAR(16) NOT NULL CHECK (kind IN ('DECISION', 'REQUIREMENT', 'BUG', 'SCOPE_CHANGE', 'ACTION', 'QUESTION', 'RISK')),
    position INTEGER NOT NULL CHECK (position >= 0),
    title_ciphertext TEXT NOT NULL,
    detail_ciphertext TEXT,
    owner VARCHAR(255),
    due_text VARCHAR(255),
    project_id UUID REFERENCES projects(id),
    intake_id UUID REFERENCES intake_items(id),
    edited BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_meeting_note_items_meeting ON meeting_note_items(meeting_id, position);
CREATE INDEX ix_meetings_work ON meetings(transcript_status, note_status) WHERE status = 'FINISHED';

-- from 006_report_planning_candidates.sql
-- Additive migration: unfinished Daily Report items become Planning candidates (source type REPORT).
ALTER TABLE planning_candidates DROP CONSTRAINT planning_candidates_source_type_check;
ALTER TABLE planning_candidates ADD CONSTRAINT planning_candidates_source_type_check CHECK (source_type IN ('GITLAB', 'INTAKE', 'PLANE', 'FORM', 'PASTE', 'REPORT'));

-- from 007_project_kinds_and_integration_probes.sql
-- Additive migration (ADR-0020): project kinds and connection checks run by the integration worker.
ALTER TABLE projects ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'SOFTWARE' CHECK (kind IN ('IDEA', 'NON_CODE', 'SOFTWARE'));
UPDATE projects SET kind = 'IDEA' WHERE code = 'other';

CREATE TABLE integration_probes (
    id UUID PRIMARY KEY,
    system VARCHAR(16) NOT NULL CHECK (system IN ('PLANE', 'GITLAB')),
    action VARCHAR(16) NOT NULL CHECK (action IN ('LIST', 'CHECK')),
    reference VARCHAR(512),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DONE', 'FAILED')),
    result JSONB,
    error_code VARCHAR(64),
    requested_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX ix_integration_probes_created ON integration_probes (created_at);

-- from 008_probe_gitlab_members.sql
-- Additive migration: the settings page lists the GitLab users of a project through a probe.
ALTER TABLE integration_probes DROP CONSTRAINT integration_probes_action_check;
ALTER TABLE integration_probes ADD CONSTRAINT integration_probes_action_check CHECK (action IN ('LIST', 'CHECK', 'MEMBERS'));

-- from 009_github_delivery.sql
-- Additive migration (ADR-0021): a customer's GitHub repository as the delivery system of a project.
ALTER TABLE project_integrations DROP CONSTRAINT project_integrations_system_check;
ALTER TABLE project_integrations ADD CONSTRAINT project_integrations_system_check CHECK (system IN ('PLANE', 'GITLAB', 'GITHUB'));
ALTER TABLE integration_probes DROP CONSTRAINT integration_probes_system_check;
ALTER TABLE integration_probes ADD CONSTRAINT integration_probes_system_check CHECK (system IN ('PLANE', 'GITLAB', 'GITHUB'));
ALTER TABLE integration_probes DROP CONSTRAINT integration_probes_action_check;
ALTER TABLE integration_probes ADD CONSTRAINT integration_probes_action_check CHECK (action IN ('LIST', 'CHECK', 'MEMBERS', 'TOKENS'));

-- from 010_project_owner_access.sql
-- Additive migration (ADR-0022): Project Owner accounts limited to the projects the CTO grants.
ALTER TABLE users ADD COLUMN must_change_password BOOLEAN NOT NULL DEFAULT FALSE;
CREATE TABLE user_project_access (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    granted_by UUID NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, project_id)
);
CREATE INDEX ix_user_project_access_project ON user_project_access (project_id);

-- from 011_project_team.sql
-- Additive migration (ADR-0023): one Project Owner per project, chosen from the staff list.
ALTER TABLE projects ADD COLUMN owner_member_id UUID REFERENCES workforce_members(id);
ALTER TABLE users ADD COLUMN member_id UUID REFERENCES workforce_members(id);
CREATE UNIQUE INDEX uq_users_member ON users (member_id) WHERE member_id IS NOT NULL;

-- from 012_mailbox_scans.sql
-- Additive migration (FR-EML-14): scans of the Daily Report mailbox, scheduled or asked for by the CTO.
CREATE TABLE mailbox_scans (
    id UUID PRIMARY KEY,
    trigger VARCHAR(16) NOT NULL CHECK (trigger IN ('SCHEDULED', 'MANUAL')),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'RUNNING', 'DONE', 'FAILED')),
    ingested INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    requested_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ
);

CREATE INDEX ix_mailbox_scans_created ON mailbox_scans (created_at);

-- from 013_approval_source.sql
-- Additive migration (FR-APR-07): where an approval was given, the approval queue or Daily Planning.
ALTER TABLE approval_actions ADD COLUMN source VARCHAR(16) NOT NULL DEFAULT 'QUEUE' CHECK (source IN ('QUEUE', 'PLANNING'));
-- Approvals given from Daily Planning before this column existed carry this reason prefix (ADR-0024).
UPDATE approval_actions SET source = 'PLANNING' WHERE action = 'APPROVE' AND reason LIKE 'Thêm vào kế hoạch trong ngày:%';

-- from 014_backup_runs.sql
-- Additive migration (NFR-REL-02): outcome of each backup, written by the backup container.
CREATE TABLE backup_runs (
    id UUID PRIMARY KEY,
    status VARCHAR(16) NOT NULL CHECK (status IN ('DONE', 'FAILED')),
    file_name VARCHAR(255),
    size_bytes BIGINT NOT NULL DEFAULT 0,
    table_count INTEGER NOT NULL DEFAULT 0,
    object_count INTEGER NOT NULL DEFAULT 0,
    error_code VARCHAR(64),
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_backup_runs_completed ON backup_runs (completed_at);

-- from 015_meeting_note_topics.sql
-- Additive migration (FR-REC-09): meeting note items are grouped by the subject they were discussed under.
ALTER TABLE meeting_note_items ADD COLUMN topic VARCHAR(120);

-- from 016_dictation_and_rewrite.sql
-- Additive migration (FR-REC-11): a short recording spoken to fill an Intake, and its text rewritten by AI on request.
ALTER TABLE meetings ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'MEETING' CHECK (kind IN ('MEETING', 'DICTATION'));
ALTER TABLE meetings ADD COLUMN rewrite_status VARCHAR(16) NOT NULL DEFAULT 'NONE' CHECK (rewrite_status IN ('NONE', 'PENDING', 'DONE', 'FAILED'));
ALTER TABLE meetings ADD COLUMN rewrite_text_ciphertext TEXT;
ALTER TABLE meetings ADD COLUMN rewrite_error VARCHAR(128);

-- from 017_post_drafts.sql
-- Additive migration (FR-CNT-01): post drafts written by AI from one idea. Never posted anywhere by the system.
CREATE TABLE post_drafts (
    id UUID PRIMARY KEY,
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    channel VARCHAR(16) NOT NULL CHECK (channel IN ('FACEBOOK', 'LINKEDIN', 'THREADS')),
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'DONE', 'FAILED')),
    text_ciphertext TEXT,
    hooks JSONB,
    gaps JSONB,
    angle_ciphertext TEXT,
    source_draft_id UUID,
    uses_raw BOOLEAN NOT NULL DEFAULT FALSE,
    error VARCHAR(128),
    prompt_version VARCHAR(32),
    model VARCHAR(128),
    edited_at TIMESTAMPTZ,
    posted_at TIMESTAMPTZ,
    created_by VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX ix_post_drafts_intake ON post_drafts (intake_id, created_at);

-- from 018_intake_details.sql
-- Additive migration (FR-AI-12): what a developer needs to start, proposed by AI and edited by the reviewer.
ALTER TABLE intake_items ADD COLUMN normalized_details JSONB;

-- from 019_draft_tracks_and_choices.sql
-- Additive migration (FR-CNT-04): two voices side by side, what a draft is for, and posts rewritten for an industry group.
ALTER TABLE post_drafts DROP CONSTRAINT IF EXISTS post_drafts_channel_check;
ALTER TABLE post_drafts DROP CONSTRAINT IF EXISTS ck_post_drafts_channel;
ALTER TABLE post_drafts ADD CONSTRAINT ck_post_drafts_channel CHECK (channel IN ('FACEBOOK', 'LINKEDIN', 'THREADS', 'FACEBOOK_GROUP'));
ALTER TABLE post_drafts ADD COLUMN track VARCHAR(32);
ALTER TABLE post_drafts ADD COLUMN goal VARCHAR(16);
ALTER TABLE post_drafts ADD COLUMN audience VARCHAR(16);
ALTER TABLE post_drafts ADD COLUMN pillar VARCHAR(120);
ALTER TABLE post_drafts ADD COLUMN group_context VARCHAR(16);

CREATE TABLE idea_tracks (
    intake_id UUID PRIMARY KEY REFERENCES intake_items(id) ON DELETE CASCADE,
    track VARCHAR(32) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- from 020_long_drafts_and_track_notes.sql
-- Additive migration (FR-CNT-05, FR-CNT-06): long pieces written from an outline, and a notebook the AI reads for each track.
ALTER TABLE post_drafts DROP CONSTRAINT IF EXISTS ck_post_drafts_channel;
ALTER TABLE post_drafts ADD CONSTRAINT ck_post_drafts_channel CHECK (channel IN ('FACEBOOK', 'LINKEDIN', 'THREADS', 'FACEBOOK_GROUP', 'BLOG', 'VIDEO_SCRIPT'));
ALTER TABLE post_drafts ADD COLUMN kind VARCHAR(16) NOT NULL DEFAULT 'POST';
ALTER TABLE post_drafts ADD CONSTRAINT ck_post_drafts_kind CHECK (kind IN ('POST', 'OUTLINE'));

CREATE TABLE track_notes (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    track VARCHAR(32) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    text_ciphertext TEXT NOT NULL,
    created_by VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_track_notes_kind CHECK (kind IN ('FACT', 'PROOF', 'DECISION', 'RESULT'))
);
CREATE INDEX ix_track_notes_track ON track_notes (project_id, track, created_at);

-- from 021_week_plan_and_draft_approval.sql
-- Additive migration (FR-CNT-07..09): the week plan of the private space, and a draft that is approved, then posted.
ALTER TABLE post_drafts ADD COLUMN approved_at TIMESTAMPTZ;
ALTER TABLE post_drafts ADD COLUMN approved_by VARCHAR(64);
ALTER TABLE post_drafts ADD COLUMN scheduled_for TIMESTAMPTZ;
ALTER TABLE post_drafts ADD COLUMN posted_url VARCHAR(500);
ALTER TABLE post_drafts ADD COLUMN posted_via VARCHAR(16);

CREATE TABLE plan_slots (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    track VARCHAR(32) NOT NULL,
    week_start DATE NOT NULL,
    weekday INTEGER NOT NULL,
    time VARCHAR(5),
    channel VARCHAR(16) NOT NULL,
    pillar VARCHAR(120),
    intake_id UUID REFERENCES intake_items(id) ON DELETE SET NULL,
    draft_id UUID,
    skipped BOOLEAN NOT NULL DEFAULT FALSE,
    suggestion_ciphertext TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_plan_slots_weekday CHECK (weekday BETWEEN 1 AND 7)
);
CREATE INDEX ix_plan_slots_week ON plan_slots (project_id, week_start, track);

CREATE TABLE plan_requests (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    track VARCHAR(32) NOT NULL,
    week_start DATE NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    keywords_ciphertext TEXT,
    mapping JSONB,
    error VARCHAR(128),
    created_by VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_plan_requests_status CHECK (status IN ('PENDING', 'DONE', 'FAILED'))
);
CREATE INDEX ix_plan_requests_week ON plan_requests (project_id, week_start, track, created_at);

-- from 022_draft_publish_error.sql
-- Additive migration (FR-CNT-10): what the posting flow outside Intake said when a post could not go out.
ALTER TABLE post_drafts ADD COLUMN publish_error VARCHAR(200);

-- from 023_watch_sources_and_signals.sql
-- Additive migration (FR-CNT-11, FR-CNT-12): sources the owner watches, and signals a scanning flow outside Intake found.
CREATE TABLE watch_sources (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    kind VARCHAR(16) NOT NULL,
    url VARCHAR(500) NOT NULL,
    label VARCHAR(120) NOT NULL,
    track VARCHAR(32) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    note VARCHAR(300),
    created_by VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX ix_watch_sources_project ON watch_sources (project_id, created_at);

CREATE TABLE watch_requests (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    track VARCHAR(32) NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    result JSONB,
    error VARCHAR(128),
    created_by VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_watch_requests_status CHECK (status IN ('PENDING', 'DONE', 'FAILED'))
);
CREATE INDEX ix_watch_requests_track ON watch_requests (project_id, track, created_at);

CREATE TABLE watch_signals (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    track VARCHAR(32) NOT NULL,
    source_id UUID REFERENCES watch_sources(id) ON DELETE SET NULL,
    url VARCHAR(1000) NOT NULL,
    url_hash VARCHAR(64) NOT NULL,
    title VARCHAR(300) NOT NULL,
    excerpt VARCHAR(1000),
    author VARCHAR(120),
    pillar VARCHAR(120),
    keyword VARCHAR(120),
    published_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    state VARCHAR(16) NOT NULL DEFAULT 'NEW',
    intake_id UUID REFERENCES intake_items(id) ON DELETE SET NULL,
    CONSTRAINT ck_watch_signals_state CHECK (state IN ('NEW', 'USED', 'DISMISSED')),
    CONSTRAINT uq_watch_signals_url UNIQUE (project_id, track, url_hash)
);
CREATE INDEX ix_watch_signals_track ON watch_signals (project_id, track, state, received_at);

-- from 024_watch_health.sql
-- Additive migration (FR-CNT-13): when the scanning flow last called, and what each 12-hour check found.
CREATE TABLE watch_contacts (
    project_id UUID PRIMARY KEY REFERENCES projects(id),
    last_config_at TIMESTAMPTZ,
    last_signal_at TIMESTAMPTZ
);

CREATE TABLE watch_checks (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    track VARCHAR(32) NOT NULL,
    checked_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(16) NOT NULL,
    reason VARCHAR(32),
    received INTEGER NOT NULL DEFAULT 0,
    remaining INTEGER NOT NULL DEFAULT 0,
    deadline TIMESTAMPTZ,
    CONSTRAINT ck_watch_checks_status CHECK (status IN ('OK', 'WARNING'))
);
CREATE INDEX ix_watch_checks_track ON watch_checks (project_id, track, checked_at);

-- from 025_directions_context_commercial.sql
-- Additive migration (FR-CNT-15, ADR-0042): tracks renamed to the two directions of the author's content, and what a
-- draft's idea is and whether money is behind it. Settings keyed by the old names are read by the application.
ALTER TABLE post_drafts ADD COLUMN context VARCHAR(16);
ALTER TABLE post_drafts ADD COLUMN commercial VARCHAR(16);


-- from 026_issue_done_evidence.sql
-- Additive migration (FR-PLAN-22): when and by whom an Issue was closed, the traces of code behind it, and the
-- CTO's spot checks of closed Issues.
ALTER TABLE gitlab_issue_snapshots ADD COLUMN IF NOT EXISTS closed_at TIMESTAMPTZ;
ALTER TABLE gitlab_issue_snapshots ADD COLUMN IF NOT EXISTS closed_by_external_id VARCHAR(255);
ALTER TABLE gitlab_issue_snapshots ADD COLUMN IF NOT EXISTS evidence JSONB;
ALTER TABLE gitlab_issue_snapshots ADD COLUMN IF NOT EXISTS evidence_fetched_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS issue_verifications (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    issue_external_id VARCHAR(255) NOT NULL,
    planning_run_id UUID REFERENCES planning_runs(id) ON DELETE SET NULL,
    evidence_level INTEGER NOT NULL DEFAULT 0,
    decision VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    reason TEXT,
    decided_by UUID REFERENCES users(id),
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_issue_verifications_decision CHECK (decision IN ('PENDING', 'ACCEPTED', 'REJECTED'))
);
CREATE INDEX IF NOT EXISTS ix_issue_verifications_issue ON issue_verifications (project_id, issue_external_id);
CREATE INDEX IF NOT EXISTS ix_issue_verifications_run ON issue_verifications (planning_run_id);

-- Rework found at a spot check is a candidate of its own kind.
ALTER TABLE planning_candidates DROP CONSTRAINT IF EXISTS planning_candidates_source_type_check;
ALTER TABLE planning_candidates ADD CONSTRAINT planning_candidates_source_type_check CHECK (source_type IN ('GITLAB', 'INTAKE', 'PLANE', 'FORM', 'PASTE', 'REPORT', 'VERIFICATION'));

-- from 027_api_tokens.sql
-- Additive migration (FR-MCP-01): personal tokens with which Codex, Claude Code and other agents call Intake.
CREATE TABLE IF NOT EXISTS api_tokens (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name VARCHAR(80) NOT NULL,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    prefix VARCHAR(16) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS ix_api_tokens_user ON api_tokens (user_id);

-- from 028_intake_work_log.sql
-- Additive migration (FR-MCP-03): what was done about a request, by a person or an agent, and the CTO's call on it;
-- and the hints the CTO leaves for whoever fixes it.
ALTER TABLE intake_items ADD COLUMN IF NOT EXISTS fix_hints TEXT;

CREATE TABLE IF NOT EXISTS intake_work_log (
    id UUID PRIMARY KEY,
    intake_id UUID NOT NULL REFERENCES intake_items(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id),
    actor_id UUID REFERENCES users(id),
    agent_name VARCHAR(80),
    summary TEXT NOT NULL,
    details JSONB,
    review_decision VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    review_note TEXT,
    reviewed_by UUID REFERENCES users(id),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_intake_work_log_decision CHECK (review_decision IN ('PENDING', 'CONFIRMED', 'RETURNED'))
);
CREATE INDEX IF NOT EXISTS ix_intake_work_log_intake ON intake_work_log (intake_id, created_at);

-- from 029_meeting_parts.sql
-- Additive migration (FR-REC-17): a live recording past the time limit goes on as the next part of the same meeting.
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS series_id UUID;
ALTER TABLE meetings ADD COLUMN IF NOT EXISTS part_number INTEGER NOT NULL DEFAULT 1;
CREATE INDEX IF NOT EXISTS ix_meetings_series ON meetings (series_id, part_number);

-- from 030_board_daily_snapshots.sql
-- Additive migration (FR-PLAN-30): one row per project per day with the morning board's counts as they stood at
-- 23:55, so the week page can say how long things waited and how often the day had enough data to review.
CREATE TABLE IF NOT EXISTS board_daily_snapshots (
    id UUID PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    readiness_state TEXT NOT NULL,
    reports_expected INTEGER NOT NULL DEFAULT 0,
    reports_received INTEGER NOT NULL DEFAULT 0,
    reports_late INTEGER NOT NULL DEFAULT 0,
    approvals_pending INTEGER NOT NULL DEFAULT 0,
    approvals_cto INTEGER NOT NULL DEFAULT 0,
    approvals_overdue INTEGER NOT NULL DEFAULT 0,
    waiting INTEGER NOT NULL DEFAULT 0,
    waiting_overdue INTEGER NOT NULL DEFAULT 0,
    unsynced INTEGER NOT NULL DEFAULT 0,
    stuck INTEGER NOT NULL DEFAULT 0,
    work_log_pending INTEGER NOT NULL DEFAULT 0,
    work_log_overdue INTEGER NOT NULL DEFAULT 0,
    p0_open INTEGER NOT NULL DEFAULT 0,
    p0_open_overdue INTEGER NOT NULL DEFAULT 0,
    plan_status TEXT,
    assigned_hours NUMERIC(6, 2) NOT NULL DEFAULT 0,
    available_hours NUMERIC(6, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_board_daily_snapshot UNIQUE (snapshot_date, project_id)
);
CREATE INDEX IF NOT EXISTS ix_board_daily_snapshot_date ON board_daily_snapshots (snapshot_date);

-- from 031_report_item_issue_links.sql
-- Additive migration (FR-RPT-07): a report item remembers where its Issue number came from, the Issues the machine
-- suggested for it, and the reason when it needs no Issue at all (a meeting, support, a review, learning).
ALTER TABLE report_items ADD COLUMN IF NOT EXISTS issue_suggestions JSONB;
ALTER TABLE report_items ADD COLUMN IF NOT EXISTS issue_link_source TEXT;
ALTER TABLE report_items ADD COLUMN IF NOT EXISTS no_issue_reason TEXT;

-- from 032_acceptance_queue.sql
-- Additive migration (FR-PLAN-31): acceptance is its own queue. A verification remembers where it came from (a report
-- saying done, or a closed Issue), who reported it, the day it entered the CTO's sample, what the Project Owner
-- said, and what happened on the tracker after the CTO accepted it.
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'CLOSED';
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS report_item_id UUID REFERENCES report_items(id) ON DELETE SET NULL;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS member_id UUID REFERENCES workforce_members(id) ON DELETE SET NULL;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS reported_on DATE;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS picked_on DATE;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS po_decision TEXT;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS po_reason TEXT;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS po_decided_by UUID REFERENCES users(id);
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS po_decided_at TIMESTAMPTZ;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS sync_status TEXT;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS sync_error TEXT;
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS synced_at TIMESTAMPTZ;
CREATE INDEX IF NOT EXISTS ix_issue_verifications_pending ON issue_verifications (decision, picked_on);

-- from 033_telegram_reminders.sql
-- Additive migration (FR-NTF-01..05, ADR-0057): reminders over Telegram. A project knows its group, a member knows
-- their private chat (joined through a one-time invite code), holidays switch reminders off, and every message sent
-- is remembered so a slot is never sent twice.
ALTER TABLE workforce_members ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT;
ALTER TABLE workforce_members ADD COLUMN IF NOT EXISTS telegram_username TEXT;
ALTER TABLE workforce_members ADD COLUMN IF NOT EXISTS telegram_invite_code TEXT;
ALTER TABLE workforce_members ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ;
CREATE UNIQUE INDEX IF NOT EXISTS uq_workforce_members_telegram_invite ON workforce_members (telegram_invite_code) WHERE telegram_invite_code IS NOT NULL;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS telegram_chat_id TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS telegram_chat_title TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS telegram_linked_at TIMESTAMPTZ;
CREATE TABLE IF NOT EXISTS holidays (
    day DATE PRIMARY KEY,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS telegram_messages (
    id UUID PRIMARY KEY,
    kind TEXT NOT NULL,
    chat_id TEXT NOT NULL,
    project_id UUID REFERENCES projects(id) ON DELETE SET NULL,
    member_id UUID REFERENCES workforce_members(id) ON DELETE SET NULL,
    for_date DATE NOT NULL,
    slot TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    sent_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_telegram_message_slot UNIQUE (kind, chat_id, for_date, slot)
);
CREATE INDEX IF NOT EXISTS ix_telegram_messages_date ON telegram_messages (for_date, created_at);
CREATE TABLE IF NOT EXISTS telegram_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- from 034_telegram_topics.sql
-- Additive migration (FR-NTF-02, ADR-0057 ops note): one Telegram group with a topic per project. A project remembers
-- the topic it was linked from, and the once-only key of a message includes the topic, since several projects now
-- share one chat id. The old unique constraint is replaced by a wider one and no data is dropped.
ALTER TABLE projects ADD COLUMN IF NOT EXISTS telegram_thread_id INTEGER;
ALTER TABLE telegram_messages ADD COLUMN IF NOT EXISTS thread_id INTEGER NOT NULL DEFAULT 0;
ALTER TABLE telegram_messages DROP CONSTRAINT IF EXISTS uq_telegram_message_slot;
ALTER TABLE telegram_messages ADD CONSTRAINT uq_telegram_message_slot UNIQUE (kind, chat_id, thread_id, for_date, slot);

-- from 035_developer_accounts_and_work_status.sql
-- Additive migration (FR-MCP-05, FR-MCP-06, ADR-0058): a Developer login that only carries a personal token for an
-- agent, and the state of a piece of planned work as the person doing it reports it from the terminal.
-- The first migration named the check users_role_check, the ORM names it ck_users_role: both go, one comes back.
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users DROP CONSTRAINT IF EXISTS ck_users_role;
ALTER TABLE users ADD CONSTRAINT ck_users_role CHECK (role IN ('CTO', 'PROJECT_OWNER', 'DEVELOPER'));
ALTER TABLE planning_assignments ADD COLUMN IF NOT EXISTS work_status TEXT NOT NULL DEFAULT 'PLANNED';
ALTER TABLE planning_assignments ADD COLUMN IF NOT EXISTS work_status_at TIMESTAMPTZ;
ALTER TABLE planning_assignments ADD COLUMN IF NOT EXISTS work_status_note TEXT;

-- from 036_personal_tasks.sql
-- Additive migration (FR-PER-01..03, ADR-0060): a person's own tasks for a day, outside any project. Only the owner
-- reads them. Their hours come off the person's free hours in planning and a reminder may go to their Telegram.
CREATE TABLE IF NOT EXISTS personal_tasks (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    member_id UUID REFERENCES workforce_members(id) ON DELETE SET NULL,
    task_date DATE NOT NULL,
    title TEXT NOT NULL,
    note TEXT,
    hours NUMERIC(4, 2) NOT NULL DEFAULT 0,
    start_time TEXT,
    remind_at TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNED',
    done_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_personal_tasks_user_date ON personal_tasks (user_id, task_date);
CREATE INDEX IF NOT EXISTS ix_personal_tasks_member_date ON personal_tasks (member_id, task_date);

-- from 037_personal_tasks_eisenhower.sql
-- Additive migration (FR-PER-04, ADR-0060 ops note): the Eisenhower matrix on a person's own tasks. important is the
-- person's call. urgent is NULL when the date decides (today, tomorrow or a reminder set) and true/false when the
-- person overrode it.
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS important BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS urgent BOOLEAN;

-- from 038_personal_tasks_week.sql
-- Additive migration (FR-PER-05, ADR-0060 ops note): a task may have no date yet (it waits in the matrix to be
-- scheduled), unfinished work rolls to the next working day with a count, and the drop quadrant archives itself.
ALTER TABLE personal_tasks ALTER COLUMN task_date DROP NOT NULL;
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS rollover_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;

-- from 039_personal_tasks_delegate_repeat.sql
-- Additive migration (FR-PER-06, ADR-0060 ops note): a personal task handed to a staff member becomes work in that
-- person's day plan, a task may repeat weekly or monthly, and the quadrant a task was in when it was finished is
-- kept for the week's numbers.
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS delegated_member_id UUID REFERENCES workforce_members(id) ON DELETE SET NULL;
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS delegated_assignment_id UUID;
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS repeat_rule TEXT;
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS repeat_parent_id UUID;
ALTER TABLE personal_tasks ADD COLUMN IF NOT EXISTS done_quadrant INTEGER;

-- from 040_attachment_vision.sql
-- Attachments read by the vision model (ADR-0061, FR-AI-14): the transcript, encrypted, with model, time, error and page count
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS ocr_text_ciphertext TEXT;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS ocr_model TEXT;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS ocr_at TIMESTAMPTZ;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS ocr_error TEXT;
ALTER TABLE attachments ADD COLUMN IF NOT EXISTS page_count INTEGER;

-- from 041_verification_source_note.sql
-- The note written when waiting work is set aside as done already (FR-PLAN-34): kept on the acceptance row and copied to the Issue when the CTO closes it
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS source_note TEXT;

-- from 042_project_context_snapshots.sql
-- The project context pack as last read from the main repository, split and scored (ADR-0063, FR-CTX-03)
CREATE TABLE IF NOT EXISTS project_context_snapshots (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT 'REPO',
    path TEXT NOT NULL DEFAULT 'docs/agent/CONTEXT.md',
    sha TEXT,
    content TEXT,
    meta JSONB,
    sections JSONB,
    score INTEGER NOT NULL DEFAULT 0,
    band TEXT NOT NULL DEFAULT 'MISSING',
    missing JSONB,
    stale_days INTEGER,
    error TEXT,
    fetched_at TIMESTAMPTZ,
    approved_sha TEXT,
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- from 043_project_context_suggestions.sql
-- What agents and people found missing or wrong in a project's context pack while working (ADR-0063, FR-CTX-04)
-- Intake never edits the pack: the CTO reads these, changes the file in the repository, then marks APPLIED or DISMISSED
CREATE TABLE IF NOT EXISTS project_context_suggestions (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    intake_id UUID REFERENCES intake_items(id) ON DELETE SET NULL,
    work_log_id UUID REFERENCES intake_work_log(id) ON DELETE SET NULL,
    text TEXT NOT NULL,
    suggested_by UUID REFERENCES users(id),
    agent_name TEXT,
    status TEXT NOT NULL DEFAULT 'PENDING',
    decided_by UUID REFERENCES users(id),
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_project_context_suggestions_project ON project_context_suggestions(project_id, status);

-- from 044_feedback_items.sql
-- Suggestions from members who are not Project Owners, waiting for the owner's word before becoming a request (ADR-0064, FR-FBK-01..03)
CREATE TABLE IF NOT EXISTS feedback_items (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    member_id UUID REFERENCES workforce_members(id),
    user_id UUID REFERENCES users(id),
    transport VARCHAR(16) NOT NULL DEFAULT 'WEB',
    text_ciphertext TEXT NOT NULL,
    status VARCHAR(16) NOT NULL DEFAULT 'PENDING',
    intake_id UUID REFERENCES intake_items(id) ON DELETE SET NULL,
    decided_by UUID REFERENCES users(id),
    decided_at TIMESTAMPTZ,
    decision_note TEXT,
    idempotency_key_hash VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_feedback_items_project_status ON feedback_items(project_id, status, created_at);
CREATE INDEX IF NOT EXISTS ix_feedback_items_decided ON feedback_items(status, decided_at);
CREATE TABLE IF NOT EXISTS feedback_files (
    id UUID PRIMARY KEY,
    feedback_id UUID NOT NULL REFERENCES feedback_items(id) ON DELETE CASCADE,
    object_key VARCHAR(512) NOT NULL UNIQUE,
    name_ciphertext TEXT,
    mime_type VARCHAR(128) NOT NULL,
    size_bytes BIGINT NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- from 045_issue_evidence_links.sql
-- Evidence people attach behind "done": commit, merge request or a link to a document, video or picture (ADR-0065, FR-PLAN-36)
CREATE TABLE IF NOT EXISTS issue_evidence_links (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    issue_external_id VARCHAR(255) NOT NULL,
    kind VARCHAR(16) NOT NULL,
    url VARCHAR(1000),
    ref VARCHAR(200),
    note VARCHAR(300),
    source VARCHAR(16) NOT NULL,
    added_by UUID REFERENCES users(id),
    member_id UUID REFERENCES workforce_members(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_issue_evidence_links_issue ON issue_evidence_links(project_id, issue_external_id, created_at);
-- Accepted although nothing stood behind it: the acceptor's reason, shown on the card and counted in the week
ALTER TABLE issue_verifications ADD COLUMN IF NOT EXISTS evidence_missing_reason TEXT;

-- from 046_work_items.sql
-- Work tracked inside Intake instead of Plane (ADR-0066, FR-WRK-01..06): items, their discussion, and the
-- approval source WORK used when an item is turned into a delivery Issue.
CREATE TABLE IF NOT EXISTS work_items (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    seq INTEGER NOT NULL,
    code VARCHAR(32) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    description_ciphertext TEXT,
    status VARCHAR(16) NOT NULL DEFAULT 'DISCUSS' CHECK (status IN ('DISCUSS', 'READY', 'IN_PROGRESS', 'ACCEPTANCE', 'DONE', 'CANCELLED')),
    priority VARCHAR(2) NOT NULL DEFAULT 'P3' CHECK (priority IN ('P0', 'P1', 'P2', 'P3')),
    member_id UUID REFERENCES workforce_members(id) ON DELETE SET NULL,
    due_date DATE,
    intake_id UUID REFERENCES intake_items(id) ON DELETE SET NULL,
    issue_system VARCHAR(16),
    issue_external_id VARCHAR(255),
    issue_url VARCHAR(1000),
    outcome VARCHAR(16) CHECK (outcome IS NULL OR outcome IN ('ISSUE_PENDING', 'ISSUE')),
    closed_note TEXT,
    created_by UUID REFERENCES users(id),
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    CONSTRAINT uq_work_items_project_seq UNIQUE (project_id, seq)
);
CREATE INDEX IF NOT EXISTS ix_work_items_project_status ON work_items(project_id, status, updated_at);
CREATE INDEX IF NOT EXISTS ix_work_items_intake ON work_items(intake_id);
CREATE TABLE IF NOT EXISTS work_comments (
    id UUID PRIMARY KEY,
    work_id UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    user_id UUID REFERENCES users(id),
    body_ciphertext TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_work_comments_work ON work_comments(work_id, created_at);
-- Migration 013 wrote the source CHECK inline, so PostgreSQL named it itself.
ALTER TABLE approval_actions DROP CONSTRAINT IF EXISTS approval_actions_source_check;
ALTER TABLE approval_actions ADD CONSTRAINT approval_actions_source_check CHECK (source IN ('QUEUE', 'PLANNING', 'WORK'));

-- from 047_work_links.sql
-- Links on work items: where the asset, the design or the published post lives (ADR-0066, FR-WRK-07).
CREATE TABLE IF NOT EXISTS work_links (
    id UUID PRIMARY KEY,
    work_id UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    url VARCHAR(1000) NOT NULL,
    note VARCHAR(300),
    source VARCHAR(16) NOT NULL DEFAULT 'USER' CHECK (source IN ('USER', 'AGENT')),
    added_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_work_links_work ON work_links(work_id, created_at);

-- from 048_work_templates.sql
-- Pipelines on the board (ADR-0066, FR-WRK-08..09): a parent with a template and its steps as children.
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS parent_id UUID REFERENCES work_items(id) ON DELETE SET NULL;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS template VARCHAR(32);
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS step VARCHAR(32);
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS step_order INTEGER;
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS evidence_required BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX IF NOT EXISTS ix_work_items_parent ON work_items(parent_id, step_order);

-- from 049_user_hint_dismissals.sql
-- Page introductions a person has read, and each hint open (FR-UI-17).
CREATE TABLE IF NOT EXISTS user_hint_dismissals (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key VARCHAR(64) NOT NULL,
    dismissed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS hint_opens (
    id UUID PRIMARY KEY,
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    key VARCHAR(64) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_hint_opens_key_time ON hint_opens(key, opened_at);

-- from 050_approval_source_meeting.sql
-- A note item that goes straight to the board is approved from the meeting (FR-REC-19).
ALTER TABLE approval_actions DROP CONSTRAINT IF EXISTS approval_actions_source_check;
ALTER TABLE approval_actions ADD CONSTRAINT approval_actions_source_check CHECK (source IN ('QUEUE', 'PLANNING', 'WORK', 'MEETING'));

-- from 051_marketing_posts.sql
-- Posts for marketing projects (ADR-0067, FR-MKT-01..02): channel, format, campaign and Gấp on a work item, one
-- rendering per channel with its own publish date, the APPROVED state, and the channel rules the CTO edits.
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS channel VARCHAR(24);
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS format VARCHAR(16);
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS campaign VARCHAR(80);
ALTER TABLE work_items ADD COLUMN IF NOT EXISTS urgent BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE work_items DROP CONSTRAINT IF EXISTS work_items_status_check;
ALTER TABLE work_items ADD CONSTRAINT work_items_status_check CHECK (status IN ('DISCUSS', 'READY', 'IN_PROGRESS', 'ACCEPTANCE', 'APPROVED', 'DONE', 'CANCELLED'));
CREATE TABLE IF NOT EXISTS work_channels (
    id UUID PRIMARY KEY,
    work_id UUID NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    channel VARCHAR(24) NOT NULL,
    publish_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL DEFAULT 'DRAFT' CHECK (status IN ('DRAFT', 'READY', 'PUBLISHED')),
    published_url VARCHAR(1000),
    language VARCHAR(8),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_work_channels_work_channel UNIQUE (work_id, channel)
);
CREATE INDEX IF NOT EXISTS ix_work_channels_channel_time ON work_channels(channel, publish_at);
CREATE TABLE IF NOT EXISTS channel_rules (
    code VARCHAR(24) PRIMARY KEY,
    label VARCHAR(60) NOT NULL,
    language VARCHAR(8) NOT NULL DEFAULT 'vi',
    max_chars INTEGER NOT NULL,
    recommended_chars INTEGER,
    long_max_chars INTEGER,
    max_images INTEGER NOT NULL DEFAULT 0,
    image_ratio VARCHAR(40),
    video_ratio VARCHAR(40),
    hashtag_max INTEGER NOT NULL DEFAULT 0,
    link_counts_chars BOOLEAN NOT NULL DEFAULT TRUE,
    link_chars INTEGER NOT NULL DEFAULT 0,
    best_hours JSONB NOT NULL DEFAULT '[]'::jsonb,
    tone TEXT,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- from 052_watch_topics_and_links.sql
-- Listening for marketing projects (ADR-0068, FR-MKT-08..12): signals carry how they were found and whether their
-- keyword was a priority one, the networks the CTO opened, system settings by key, hot topics built from signals,
-- the words of a channel version, short links and their clicks. (No semicolons in comments: the runner splits on them.)
ALTER TABLE watch_signals ADD COLUMN IF NOT EXISTS via VARCHAR(8) NOT NULL DEFAULT 'api';
ALTER TABLE watch_signals ADD COLUMN IF NOT EXISTS priority VARCHAR(8) NOT NULL DEFAULT 'normal';
ALTER TABLE watch_signals DROP CONSTRAINT IF EXISTS ck_watch_signals_via;
ALTER TABLE watch_signals ADD CONSTRAINT ck_watch_signals_via CHECK (via IN ('api', 'scrape'));
ALTER TABLE watch_signals DROP CONSTRAINT IF EXISTS ck_watch_signals_priority;
ALTER TABLE watch_signals ADD CONSTRAINT ck_watch_signals_priority CHECK (priority IN ('high', 'normal'));
CREATE TABLE IF NOT EXISTS watch_platforms (
    code VARCHAR(16) PRIMARY KEY,
    label VARCHAR(60) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    via VARCHAR(8) NOT NULL DEFAULT 'none' CHECK (via IN ('api', 'scrape', 'none')),
    note VARCHAR(300),
    sort_order INTEGER NOT NULL DEFAULT 0,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS app_settings (
    key VARCHAR(64) PRIMARY KEY,
    value JSONB,
    updated_by UUID REFERENCES users(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS watch_topics (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    week_start DATE NOT NULL,
    key VARCHAR(64) NOT NULL,
    title VARCHAR(200) NOT NULL,
    why VARCHAR(400),
    angles JSONB,
    channels JSONB,
    caution VARCHAR(300),
    pillar VARCHAR(60),
    score INTEGER NOT NULL DEFAULT 0,
    signal_ids JSONB,
    state VARCHAR(16) NOT NULL DEFAULT 'NEW' CHECK (state IN ('NEW', 'USED', 'DISMISSED')),
    work_id UUID REFERENCES work_items(id) ON DELETE SET NULL,
    ai_written BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_watch_topics_key UNIQUE (project_id, week_start, key)
);
CREATE INDEX IF NOT EXISTS ix_watch_topics_project ON watch_topics(project_id, state, score);
ALTER TABLE work_channels ADD COLUMN IF NOT EXISTS text TEXT;
CREATE TABLE IF NOT EXISTS post_links (
    id UUID PRIMARY KEY,
    work_channel_id UUID NOT NULL REFERENCES work_channels(id) ON DELETE CASCADE,
    code VARCHAR(12) NOT NULL UNIQUE,
    target_url VARCHAR(1000) NOT NULL,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_post_links_version UNIQUE (work_channel_id)
);
CREATE TABLE IF NOT EXISTS post_clicks (
    id UUID PRIMARY KEY,
    link_id UUID NOT NULL REFERENCES post_links(id) ON DELETE CASCADE,
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    referrer_host VARCHAR(120),
    is_bot BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE INDEX IF NOT EXISTS ix_post_clicks_link_time ON post_clicks(link_id, at);

-- from 053_watch_signal_via_agent.sql
-- A signal may also come from the owner's own agent through MCP (FR-MCP-09, ADR-0068): one more value of via.
ALTER TABLE watch_signals DROP CONSTRAINT IF EXISTS ck_watch_signals_via;
ALTER TABLE watch_signals ADD CONSTRAINT ck_watch_signals_via CHECK (via IN ('api', 'scrape', 'agent'));

-- from 054_watch_connectors_and_auto_publish.sql
-- Doors for outside services to push findings into a marketing project (FR-MKT-13), their delivery log, and the
-- per-channel switch that sends approved versions to the posting flow (FR-MKT-14). No semicolons in comments.
CREATE TABLE IF NOT EXISTS watch_connectors (
    id UUID PRIMARY KEY,
    project_id UUID NOT NULL REFERENCES projects(id),
    name VARCHAR(80) NOT NULL,
    kind VARCHAR(16) NOT NULL DEFAULT 'GENERIC' CHECK (kind IN ('GENERIC', 'N8N', 'MAKE', 'APIFY', 'MENTION')),
    token_hash VARCHAR(64) NOT NULL,
    token_prefix VARCHAR(12) NOT NULL,
    via VARCHAR(8) NOT NULL DEFAULT 'api' CHECK (via IN ('api', 'scrape')),
    default_pillar VARCHAR(60),
    mapping JSONB,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    received_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    last_received_at TIMESTAMPTZ,
    last_status VARCHAR(16),
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_watch_connectors_project ON watch_connectors(project_id, created_at);
CREATE TABLE IF NOT EXISTS watch_deliveries (
    id UUID PRIMARY KEY,
    connector_id UUID NOT NULL REFERENCES watch_connectors(id) ON DELETE CASCADE,
    at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status VARCHAR(16) NOT NULL CHECK (status IN ('ACCEPTED', 'EMPTY', 'INVALID', 'UNAUTHORIZED')),
    accepted INTEGER NOT NULL DEFAULT 0,
    duplicates INTEGER NOT NULL DEFAULT 0,
    rejected INTEGER NOT NULL DEFAULT 0,
    note VARCHAR(300)
);
CREATE INDEX IF NOT EXISTS ix_watch_deliveries_connector ON watch_deliveries(connector_id, at);
ALTER TABLE channel_rules ADD COLUMN IF NOT EXISTS auto_publish BOOLEAN NOT NULL DEFAULT FALSE;

-- from 055_candidate_done_elsewhere.sql
-- A waiting entry recorded as done outside the plan has a state of its own (FR-PLAN-34): it is not "dismissed",
-- does not come back tomorrow and cannot be restored to the waiting list. Existing rows keep REJECTED. No semicolons in comments.
ALTER TABLE planning_candidates DROP CONSTRAINT IF EXISTS planning_candidates_status_check;
ALTER TABLE planning_candidates DROP CONSTRAINT IF EXISTS ck_planning_candidate_status;
ALTER TABLE planning_candidates ADD CONSTRAINT planning_candidates_status_check CHECK (status IN ('PENDING_TRIAGE', 'READY', 'ASSIGNED', 'REJECTED', 'DONE_ELSEWHERE'));
UPDATE planning_candidates SET status = 'DONE_ELSEWHERE' WHERE status = 'REJECTED' AND summary LIKE 'Đã làm xong ngoài kế hoạch: %';

-- from 056_one_issue_per_planning_run.sql
WITH ranked AS (
    SELECT
        id,
        FIRST_VALUE(id) OVER (
            PARTITION BY planning_run_id, project_id, gitlab_issue_external_id
            ORDER BY
                CASE work_status
                    WHEN 'DONE' THEN 0
                    WHEN 'IN_PROGRESS' THEN 1
                    WHEN 'BLOCKED' THEN 2
                    WHEN 'PLANNED' THEN 3
                    ELSE 4
                END,
                CASE slot WHEN 'MORNING' THEN 0 ELSE 1 END,
                created_at,
                id
        ) AS keep_id,
        SUM(planned_hours) OVER (
            PARTITION BY planning_run_id, project_id, gitlab_issue_external_id
        ) AS total_hours
    FROM planning_assignments
    WHERE gitlab_issue_external_id IS NOT NULL
), keepers AS (
    SELECT DISTINCT keep_id, LEAST(4.0, total_hours) AS planned_hours
    FROM ranked
)
UPDATE planning_assignments AS assignment
SET planned_hours = keepers.planned_hours
FROM keepers
WHERE assignment.id = keepers.keep_id;

WITH ranked AS (
    SELECT
        id,
        FIRST_VALUE(id) OVER (
            PARTITION BY planning_run_id, project_id, gitlab_issue_external_id
            ORDER BY
                CASE work_status WHEN 'DONE' THEN 0 WHEN 'IN_PROGRESS' THEN 1 WHEN 'BLOCKED' THEN 2 WHEN 'PLANNED' THEN 3 ELSE 4 END,
                CASE slot WHEN 'MORNING' THEN 0 ELSE 1 END,
                created_at,
                id
        ) AS keep_id
    FROM planning_assignments
    WHERE gitlab_issue_external_id IS NOT NULL
)
UPDATE planning_candidates AS candidate
SET assignment_id = ranked.keep_id
FROM ranked
WHERE candidate.assignment_id = ranked.id AND ranked.id <> ranked.keep_id;

WITH ranked AS (
    SELECT
        id,
        FIRST_VALUE(id) OVER (
            PARTITION BY planning_run_id, project_id, gitlab_issue_external_id
            ORDER BY
                CASE work_status WHEN 'DONE' THEN 0 WHEN 'IN_PROGRESS' THEN 1 WHEN 'BLOCKED' THEN 2 WHEN 'PLANNED' THEN 3 ELSE 4 END,
                CASE slot WHEN 'MORNING' THEN 0 ELSE 1 END,
                created_at,
                id
        ) AS keep_id
    FROM planning_assignments
    WHERE gitlab_issue_external_id IS NOT NULL
)
UPDATE planning_warnings AS warning
SET assignment_id = ranked.keep_id
FROM ranked
WHERE warning.assignment_id = ranked.id AND ranked.id <> ranked.keep_id;

WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY planning_run_id, project_id, gitlab_issue_external_id
            ORDER BY
                CASE work_status WHEN 'DONE' THEN 0 WHEN 'IN_PROGRESS' THEN 1 WHEN 'BLOCKED' THEN 2 WHEN 'PLANNED' THEN 3 ELSE 4 END,
                CASE slot WHEN 'MORNING' THEN 0 ELSE 1 END,
                created_at,
                id
        ) AS position
    FROM planning_assignments
    WHERE gitlab_issue_external_id IS NOT NULL
)
DELETE FROM planning_assignments AS assignment
USING ranked
WHERE assignment.id = ranked.id AND ranked.position > 1;

CREATE UNIQUE INDEX IF NOT EXISTS uq_planning_assignment_run_project_issue
    ON planning_assignments(planning_run_id, project_id, gitlab_issue_external_id)
    WHERE gitlab_issue_external_id IS NOT NULL;

-- from 057_retire_plane_runtime.sql
-- Plane stopped being an operational integration (ADR-0066).
-- Keep decisions, snapshots, sync jobs, queued audit events, candidate data and external links as history.

UPDATE sync_jobs
SET status = 'FAILED',
    error_code = 'ROUTE_RETIRED',
    error_detail_redacted = 'Plane integration retired, historical record kept',
    next_attempt_at = NULL,
    lease_expires_at = NULL,
    updated_at = CURRENT_TIMESTAMP
WHERE target_system = 'PLANE'
  AND status IN ('PENDING', 'RETRY', 'RUNNING');

UPDATE intake_items AS intake
SET status = 'APPROVED', updated_at = CURRENT_TIMESTAMP
WHERE status = 'SYNC_PENDING'
  AND EXISTS (
      SELECT 1 FROM sync_jobs AS job
      WHERE job.intake_id = intake.id
        AND job.target_system = 'PLANE'
        AND job.error_code = 'ROUTE_RETIRED'
  );

-- These two tables are runtime connection configuration, not historical work data.
DELETE FROM integration_probes WHERE system = 'PLANE';
DELETE FROM project_integrations WHERE system = 'PLANE';

ALTER TABLE project_integrations DROP CONSTRAINT IF EXISTS ck_project_integrations_system;
ALTER TABLE project_integrations DROP CONSTRAINT IF EXISTS project_integrations_system_check;
ALTER TABLE project_integrations
    ADD CONSTRAINT ck_project_integrations_system CHECK (system IN ('GITLAB', 'GITHUB'));

ALTER TABLE integration_probes DROP CONSTRAINT IF EXISTS ck_integration_probe_system;
ALTER TABLE integration_probes DROP CONSTRAINT IF EXISTS integration_probes_system_check;
ALTER TABLE integration_probes
    ADD CONSTRAINT ck_integration_probe_system CHECK (system IN ('GITLAB', 'GITHUB'));

-- from 058_password_reset_mailgun.sql
-- Self-service password recovery: opaque one-time links sent through Mailgun HTTP API.
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS password_reset_requests (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash VARCHAR(64) NOT NULL UNIQUE,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    sent_at TIMESTAMPTZ,
    send_error VARCHAR(80),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_password_reset_user_time
    ON password_reset_requests(user_id, created_at);
CREATE INDEX IF NOT EXISTS ix_password_reset_active
    ON password_reset_requests(expires_at)
    WHERE used_at IS NULL;

-- from 059_intake_hard_flag.sql
-- The CTO marks a request as hard: its acceptance always comes back to the CTO, whatever the Project Owner says.
ALTER TABLE intake_items ADD COLUMN IF NOT EXISTS needs_cto_acceptance BOOLEAN NOT NULL DEFAULT FALSE;

-- from 060_ai_providers.sql
-- LLM providers (OpenAI-compatible endpoints with an encrypted key) and which one serves each task (ADR-0070).
CREATE TABLE IF NOT EXISTS ai_providers (
    id UUID PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE,
    base_url VARCHAR(300) NOT NULL,
    api_key_enc TEXT,
    extra_body JSONB,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_test_at TIMESTAMPTZ,
    last_test_ok BOOLEAN,
    last_test_error VARCHAR(32),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS ai_routes (
    task VARCHAR(16) PRIMARY KEY,
    provider_id UUID NOT NULL REFERENCES ai_providers(id),
    model VARCHAR(128) NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by UUID REFERENCES users(id),
    CONSTRAINT ck_ai_routes_task CHECK (task IN ('default', 'normalize', 'report', 'meeting', 'vision', 'content'))
);
