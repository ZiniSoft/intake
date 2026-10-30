export type IntakeStatus =
  | 'NEW'
  | 'PROCESSING'
  | 'PENDING_APPROVAL'
  | 'NEEDS_INFORMATION'
  | 'PROCESSING_FAILED'
  | 'DEFERRED'
  | 'APPROVED'
  | 'REJECTED'
  | 'SYNC_PENDING'
  | 'SYNCED'
  | 'CLOSED'

export type IntakeLifecycleStage =
  | 'RECEIVED'
  | 'NEEDS_INFORMATION'
  | 'PENDING_APPROVAL'
  | 'WAITING_PLANNING'
  | 'IN_PROGRESS'
  | 'PENDING_ACCEPTANCE'
  | 'ACCEPTED'
  | 'STOPPED'

export type Priority = 'P0' | 'P1' | 'P2' | 'P3'
// PLANE only on requests decided before ADR-0066; new decisions use WORK, the board inside Intake.
export type RouteTarget = 'RESPONSE' | 'WORK' | 'PLANE' | 'GITLAB' | 'GITHUB' | 'NEEDS_INFO'
export type Channel = 'ZALO' | 'WHATSAPP' | 'EMAIL' | 'MEETING' | 'MANUAL' | 'AGENT' | 'TELEGRAM' | 'FEEDBACK'

export interface User {
  subject: string
  email: string
  display_name?: string
  role: string
  can_view_raw: boolean
  can_approve: boolean
  mfa_enabled: boolean
  // null means every project (the CTO); a list means exactly those projects.
  project_ids: string[] | null
  must_change_password: boolean
  // The member this account is, when it is one: "Việc của tôi" and the Góp ý page come from it.
  member_id?: string | null
  // The person's projects with their kind, and the side of the app they should see (FR-MKT-03).
  projects?: { id: string; code: string; name: string; kind: string }[]
  mode?: 'MARKETING' | 'FULL'
  // False hides the Beta areas (marketing posts, watch sources) from the menu and routes.
  beta_features_enabled?: boolean
}

export interface Account {
  id: string
  subject: string
  email: string
  display_name: string
  role: string
  is_active: boolean
  mfa_enabled: boolean
  must_change_password: boolean
  member_id: string | null
  member_name: string | null
  agent_last_used_at: string | null
  projects: { id: string; code: string; name: string }[]
}

export interface AgentCommand {
  name: string
  slash: string
  mcp_slash: string | null
  description: string
  when: string
  codex: string
}

export interface AgentCommandSheet {
  commands: AgentCommand[]
  install: { bash: string; powershell: string; repo: string }
  // For a marketing project: which commands matter there, and one sentence per tool to paste (FR-MCP-09).
  marketing?: { commands: string[]; tools: { tool: string; sentence: string; when: string; owner_only: boolean }[] }
}

export interface ProjectTeam {
  project_id: string
  project_code: string
  owner_member_id: string | null
  members: { member_id: string; display_name: string; email: string | null; is_owner: boolean; delivery_user_id: string | null; account_subject: string | null; account_active: boolean }[]
  issued: { subject: string; display_name: string; temporary_password: string } | null
}

export interface ProjectMemberCandidate {
  member_id: string
  display_name: string
  email: string | null
}

export interface ProjectMemberAdded {
  added: boolean
  team: ProjectTeam
}

export interface ProjectMemberRemoved {
  removed: boolean
  team: ProjectTeam
}

export interface IntakeDetails {
  where: string | null
  steps: string[]
  expected: string | null
  subtasks: string[]
  acceptance: string[]
  open_questions: string[]
  related: { id: string; title: string | null; url: string | null }[]
  split_suggested: boolean
  clarifications: { question: string; answer: string | null; skipped: boolean }[]
}

export interface Intake {
  id: string
  public_id: string
  project_id: string
  channel: Channel
  item_type: string
  status: IntakeStatus
  lifecycle_stage: IntakeLifecycleStage
  normalized_title: string | null
  normalized_summary: string | null
  details: IntakeDetails | null
  duplicate_of_id: string | null
  duplicate_of: { id: string; public_id: string; title: string | null } | null
  // Closed as a repeat of an Issue that already exists at GitLab (FR-APR-12).
  duplicate_issue: { system: string; external_id: string; title: string | null; url: string | null } | null
  suggested_priority: Priority | null
  proposed_route: RouteTarget | null
  approved_priority: Priority | null
  approved_route: RouteTarget | null
  sync_targets: IntakeSyncSummary[]
  // The work item this request became when approved for WORK (FR-WRK-06).
  work_item: WorkRef | null
  // What the CTO tells whoever fixes it (FR-MCP-03).
  fix_hints: string | null
  // Set only by the CTO: acceptance always comes back to the CTO (FR-PLAN-39).
  needs_cto_acceptance: boolean
  // Whether an agent could take this as it stands (FR-MCP-04).
  agent_readiness: AgentReadiness | null
  // Who should decide it while it waits for approval, and whether it has waited over a day (FR-APR-14).
  approval_owner: 'CTO' | 'PO' | null
  approval_overdue: boolean
  version: number
  created_at: string
  updated_at: string
}

export interface IntakePage {
  items: Intake[]
  next_cursor: string | null
  limit: number
  summary: {
    total_items: number
    p0_attention: number
    p1_attention: number
    pending_approval: number
    sync_failed: number
  }
}

export interface IntakeSyncSummary {
  system: 'PLANE' | 'GITLAB' | 'GITHUB'
  status: 'PENDING' | 'RUNNING' | 'RETRY' | 'SUCCEEDED' | 'FAILED'
  external_id: string | null
  sequence_id: string | null
  external_url: string | null
  error_code: string | null
  updated_at: string
  // The decision this sync belonged to was taken back; the item is still out there (FR-APR-10).
  superseded: boolean
}

export interface Project {
  id: string
  code: string
  intake_key: string
  name: string
  status: string
  kind: ProjectKind
  gitlab_project_id: string | null
  gitlab_project_url: string | null
  gitlab_enabled: boolean
  github_repository: string | null
  github_project_url: string | null
  github_enabled: boolean
  telegram_chat_title: string | null
  telegram_linked: boolean
  github_token_ref: string | null
  delivery_system: 'GITLAB' | 'GITHUB' | null
  owner_member_id: string | null
  owner_name: string | null
  done_evidence: 'COMMIT' | 'MR'
  agent_ready: boolean
}

export interface AgentReadiness {
  score: number
  band: 'READY' | 'NEEDS_WORK' | 'HUMAN'
  reasons: string[]
  missing: string[]
}

export type ProjectKind = 'IDEA' | 'NON_CODE' | 'SOFTWARE'

export interface RemoteProject {
  id: string
  name: string
  url: string | null
  identifier?: string | null
}

// The tracker's users beside the team, for the planning dialog (FR-PLAN-32).
export interface TrackerUsers {
  status: 'PENDING' | 'DONE' | 'FAILED' | string
  error_code: string | null
  users: { id: string; name: string; username: string | null; mapped_member_id: string | null; suggested_member_id: string | null }[]
  unmapped: { member_id: string; display_name: string; suggested_user_id: string | null }[]
  issue_assignees: string[]
}

export interface GitLabUser {
  id: string
  name: string
  username: string | null
}

export interface IntegrationProbe {
  id: string
  system: 'GITLAB' | 'GITHUB'
  action: 'LIST' | 'CHECK' | 'MEMBERS' | 'TOKENS'
  reference: string | null
  status: 'PENDING' | 'DONE' | 'FAILED'
  result: RemoteProject | RemoteProject[] | null
  error_code: string | null
}

export interface ProcessingRun {
  id: string
  run_type: string
  status: string
  attempt: number
  model_name?: string
  started_at: string | null
  finished_at: string | null
  error_code: string | null
}

export interface PipelineStage {
  run_id: string
  stage: string
  run_type: string
  status: string
  attempt: number
  worker_id: string | null
  retryable: boolean
  queued_at: string | null
  started_at: string | null
  finished_at: string | null
  error_code: string | null
}

export interface PipelineStatus {
  intake_id: string
  public_id: string
  intake_status: IntakeStatus
  overall_state: 'NOT_STARTED' | 'QUEUED' | 'RUNNING' | 'SUCCEEDED' | 'FAILED'
  stages: PipelineStage[]
}

export interface SyncJob {
  id: string
  approval_snapshot_id: string
    target_system: 'PLANE' | 'GITLAB' | 'GITHUB'
  status: 'PENDING' | 'RUNNING' | 'RETRY' | 'SUCCEEDED' | 'FAILED'
  attempt: number
  max_attempts: number
  error_code: string | null
  external_id: string | null
  external_url: string | null
  created_at: string
  updated_at: string
}

export type VoiceChannel = 'FACEBOOK' | 'LINKEDIN' | 'THREADS'
export type DraftChannel = VoiceChannel | 'FACEBOOK_GROUP' | 'BLOG' | 'VIDEO_SCRIPT'
export type DraftTrack = 'business' | 'technical'
export type DraftContext = 'REAL' | 'EXAMPLE' | 'SOURCE'
export type DraftCommercial = 'NONE' | 'SPONSORED' | 'AFFILIATE'

export interface VoiceReference {
  title: string
  text: string
}

export interface VoiceTrial {
  text: string
  prompt_version: string
  model: string
  message_chars: number
}

export interface PrivateVoice {
  name: string
  direction_note: string
  positioning: string
  audience: string
  pillars: string[]
  tone: string
  avoid: string
  default_channel: DraftChannel
  samples: { text: string; channel: VoiceChannel }[]
  references: VoiceReference[]
}

export interface PrivateSpace {
  project: { id: string; code: string; name: string } | null
  voice: PrivateVoice | null
  voices: Record<string, PrivateVoice>
  master_dna: string
  counts: { ideas: number; no_draft: number; drafted: number; posted: number; dropped: number; unposted_drafts: number }
}

export interface PrivateIdea {
  id: string
  public_id: string
  title: string | null
  note: string | null
  analysed: boolean
  status: string
  state: 'NO_DRAFT' | 'DRAFTED' | 'POSTED' | 'DROPPED'
  channels: string[]
  track: DraftTrack | null
  posted_at: string | null
  created_at: string
  version: number
}

export interface RhythmSlot {
  weekday: number
  time: string | null
  channel: DraftChannel
  pillar: string | null
}

export interface PlanSlot {
  id: string
  track: DraftTrack
  week_start: string
  day: string
  weekday: number
  time: string | null
  planned_for: string
  channel: DraftChannel
  pillar: string | null
  state: 'EMPTY' | 'PROPOSED' | 'IDEA' | 'DRAFTED' | 'APPROVED' | 'POSTED' | 'SKIPPED'
  idea: { id: string; public_id: string; title: string | null } | null
  draft: { id: string; channel: string; approved_at: string | null; scheduled_for: string | null; posted_at: string | null; posted_url: string | null; posted_via: string | null } | null
  suggestion: { title: string; reason: string; pillar: string | null; from_store: boolean } | null
}

export interface PlanTrack {
  name: string
  slots: PlanSlot[]
  stats: {
    slots: number; posted: number; approved: number; open: number; drafted_ideas: number; posted_total: number; off_plan: number
    pillars: { pillar: string; posted: number }[]; missing_pillars: string[]
  }
  request: { status: 'PENDING' | 'DONE' | 'FAILED'; error: string | null } | null
}

export interface PlanWeek {
  week_start: string
  this_week: string
  editable: boolean
  tracks: Record<string, PlanTrack>
  rhythm: Record<string, RhythmSlot[]>
}

export interface WatchSource {
  id: string
  kind: 'WEB' | 'FACEBOOK' | 'X' | 'YOUTUBE' | 'LINKEDIN' | 'OTHER'
  url: string
  label: string
  track: DraftTrack | 'both'
  active: boolean
  note: string | null
  created_at: string
}

export interface PillarKeywords {
  track: string
  pillars: { pillar: string; keywords: string[] }[]
  request: { status: 'PENDING' | 'DONE' | 'FAILED'; error: string | null } | null
  suggested: Record<string, string[]>
}

export interface WatchDemand {
  wanted_per_week: number
  weekday: number
  time: string
  lookback_days: number
  timezone: string
  window_start: string | null
  deadline: string | null
  received: number
  remaining: number
  accept_up_to: number | null
}

export interface WatchHealth {
  check_hours: number
  last_config_at: string | null
  last_signal_at: string | null
  tracks: {
    track: DraftTrack; name: string; wanted_per_week: number; received: number; remaining: number; deadline: string | null
    checked_at: string | null; warning: boolean; reason: 'ROUTES_CLOSED' | 'NO_SOURCES' | 'NO_KEYWORDS' | 'FLOW_SILENT' | 'NOTHING_SENT' | null
    received_in_check: number | null
  }[]
}

export interface WatchSignal {
  id: string
  track: DraftTrack
  url: string
  title: string
  excerpt: string | null
  author: string | null
  pillar: string | null
  keyword: string | null
  source_label: string | null
  published_at: string | null
  received_at: string
  state: 'NEW' | 'USED' | 'DISMISSED'
  intake_id: string | null
}

export interface PromptPreview {
  prompt_version: string
  model: string
  system_prompt: string
  system_chars: number
  blocks: { key: string; trust: 'CHOICE' | 'AUTHOR' | 'DATA' | 'UNTRUSTED'; text: string; chars: number; cuts: { what: string; kept: number; total: number }[] }[]
  message_chars: number
  placeholder: boolean
}

export interface TrackNote {
  id: string
  track: string
  kind: 'FACT' | 'PROOF' | 'DECISION' | 'RESULT'
  text: string
  created_at: string
}

export interface PostDraft {
  id: string
  intake_id: string
  channel: DraftChannel
  kind: 'POST' | 'OUTLINE'
  status: 'PENDING' | 'DONE' | 'FAILED'
  text: string | null
  hooks: string[]
  gaps: string[]
  angle: string | null
  source_draft_id: string | null
  track: DraftTrack | null
  goal: string | null
  audience: string | null
  pillar: string | null
  group_context: string | null
  context: DraftContext | null
  commercial: DraftCommercial | null
  approved_at: string | null
  scheduled_for: string | null
  posted_url: string | null
  posted_via: string | null
  publish_error: string | null
  slot_id: string | null
  error: string | null
  edited_at: string | null
  posted_at: string | null
  created_at: string
  updated_at: string
}

export interface PlanningDay {
  plan_date: string
  run_id: string | null
  status: string | null
  assigned: number
  waiting: number
}

// The morning picture: one row per project with whether the day can be reviewed on complete data (FR-PLAN-23).
export interface PlanningOverviewProject {
  id: string
  code: string
  name: string
  p0: boolean
  readiness: { state: 'READY' | 'MISSING' | 'NO_WORK'; reasons: string[] }
  // The project's context pack as scored (FR-CTX-04).
  context: { band: 'FULL' | 'PARTIAL' | 'MISSING' | string; score: number; missing: string[]; approved: boolean }
  reports: { report_date: string | null; expected: number; received: number; missing: string[]; late: number; malformed: number; unreviewed: number; items_without_issue: number }
  approvals: { pending: number; urgent: number; cto: number; po: number; overdue: number; has_owner: boolean }
  unsynced: number
  stuck: number
  meetings: { yesterday: number; notes_pending: number; items_unconverted: number }
  plan: { run_id: string | null; status: string | null; scope: 'PROJECT' | 'ALL' | null; assigned_people: number; assigned_hours: number; waiting: number; warnings: number; available_hours: number; people_today: number; made_by: string | null; updated_at: string | null }
  acceptance: { verifications_pending: number; work_log_pending: number }
  gitlab: { snapshot_at: string | null; fresh: boolean; open_p0: number }
  people_off: string[]
  unassigned: string[]
  carry_over: number
  // Waiting that went on longer than the thresholds in ADR-0052 (FR-PLAN-27).
  overdue: { approvals: number; waiting: number; work_log: number; p0_open: number }
  attention: number
}

// Minutes the CTO spent acting in the app, from the audit trail; only the CTO gets it (FR-UI-15).
export interface CtoTime {
  today_minutes: number
  actions_today: number
  avg7_minutes: number
  days: { date: string; minutes: number }[]
}

export interface PlanningOverview {
  plan_date: string
  generated_at: string
  gitlab_snapshot_at: string | null
  missing_projects: number
  overdue_total: number
  projects: PlanningOverviewProject[]
  cto_time: CtoTime | null
}

// One row per person for a day: hours planned across every project against the hours they have (FR-PLAN-28).
export interface PeopleDayPerson {
  member_id: string
  display_name: string
  available_hours: number
  planned_hours: number
  free_hours: number
  state: 'OVER' | 'FREE' | 'OK' | 'OFF'
  projects: { id: string; name: string; hours: number; run_status: string | null }[]
}

export interface PeopleDay {
  plan_date: string
  over: number
  free: number
  people: PeopleDayPerson[]
}

export interface SyncStatus {
  intake_id: string
  snapshot_id: string | null
  target_system: 'PLANE' | 'GITLAB' | 'GITHUB' | null
  sync_available: boolean
  reason: string | null
  job: SyncJob | null
}

export interface OperationsStatus {
  status: string
  web: string
  worker_ai: string
  worker_integration: string
  backup: string
  backup_detail: BackupDetail
  storage: string
  ai_provider_primary: string
  ai_primary_configured: boolean
  ai_provider_fallback: string
  ai_fallback_configured: boolean
  ai_configured: boolean
  ai_source: string
}

export interface AiProvider {
  id: string
  name: string
  base_url: string
  enabled: boolean
  key_hint: string
  key_ok: boolean
  extra_body: Record<string, unknown> | null
  last_test_at: string | null
  last_test_ok: boolean | null
  last_test_error: string | null
}

export interface AiProviderTest {
  ok: boolean
  error: string | null
  models: string[]
}

export interface AiRoute {
  task: string
  provider_id: string | null
  provider_name: string | null
  model: string | null
  source: string
  effective_provider: string | null
  effective_model: string | null
}

export type PlanningSlot = 'MORNING' | 'AFTERNOON'
export type PlanningWorkType = 'DEVELOPMENT' | 'REVIEW' | 'QA' | 'SUPPORT' | 'MEETING' | 'FIXED'
export type PlanningCandidateStatus = 'PENDING_TRIAGE' | 'READY' | 'ASSIGNED' | 'REJECTED' | 'DONE_ELSEWHERE'

export interface WorkforceProjectMapping {
  project_id: string
  gitlab_user_external_id: string | null
  role: string | null
  active: boolean
}

export interface TelegramStatus {
  bot_username: string | null
  bot_seen_at: string | null
  projects: { id: string; code: string; name: string; chat_title: string | null; linked: boolean; linked_at: string | null }[]
  members: { id: string; display_name: string; username: string | null; linked: boolean; linked_at: string | null; invite_pending: boolean }[]
  holidays: { day: string; note: string | null }[]
}

export interface TelegramMessageRow {
  id: string
  kind: string
  for_date: string
  slot: string
  status: string
  error: string | null
  sent_at: string | null
  project_name: string | null
  member_name: string | null
}

export interface WorkforceMember {
  id: string
  display_name: string
  email_reference: string | null
  status: string
  timezone: string
  default_weekday_hours: number
  project_mappings: WorkforceProjectMapping[]
  telegram_linked: boolean
  telegram_username: string | null
  telegram_invite_pending: boolean
  // The CTO's own staff record (FR-PLAN-37): no hours unless set for a day, no Daily Report expected.
  is_cto?: boolean
}

export interface DailyCapacity {
  member_id: string
  display_name: string
  work_date: string
  base_hours: number
  override_hours: number | null
  meeting_hours: number
  review_hours: number
  support_hours: number
  fixed_hours: number
  personal_hours: number
  available_hours: number
  override_reason: string | null
  version: number
  is_owner: boolean
  is_cto?: boolean
  planned_elsewhere_hours: number
  planned_elsewhere: { project_id: string; project_name: string; hours: number }[]
  remaining_hours: number | null
}

export interface PlanningAssignment {
  id: string
  intake_id: string | null
  intake_public_id: string | null
  title: string | null
  issue_url: string | null
  project_id: string
  member_id: string
  slot: PlanningSlot
  work_type: PlanningWorkType
  is_primary: boolean
  planned_hours: number
  source_type: string
  source_reference: string
  gitlab_issue_external_id: string | null
  work_status: WorkStatus
  work_status_at: string | null
  work_status_note: string | null
  // When the CTO accepted the Issue behind this item: drawn as accepted, not as work to do (FR-PLAN-34).
  accepted_at?: string | null
  proposed_priority: Priority | null
  approved_priority: Priority | null
  proposed_assignee_external_id: string | null
  approved_assignee_external_id: string | null
  proposed_milestone_external_id: string | null
  approved_milestone_external_id: string | null
  proposed_due_date: string | null
  approved_due_date: string | null
  dependency_state: string | null
  source_state: string | null
  override_reason: string | null
  version: number
}

// One decision taken on a request, for the history under the approval queue (FR-APR-15).
export interface ApprovalDecision {
  id: string
  at: string
  action: 'APPROVED' | 'REJECTED' | 'DEFERRED' | 'NEEDS_INFORMATION' | 'REOPENED'
  source: string
  actor_id: string | null
  actor_name: string | null
  reason: string | null
  intake_id: string
  public_id: string
  title: string
  status: IntakeStatus
  project_id: string
  project_code: string
  project_name: string
  approved_route: string | null
  approved_priority: Priority | null
}

export interface ApprovalDecisionPage {
  items: ApprovalDecision[]
  next_before: string | null
  since: string | null
}

export interface PlanningCandidate {
  id: string
  planning_run_id: string
  project_id: string
  member_id: string | null
  intake_id: string | null
  assignment_id: string | null
  source_type: string
  source_reference: string
  gitlab_issue_external_id: string | null
  title: string
  summary: string | null
  intake_public_id: string | null
  issue_url: string | null
  status: PlanningCandidateStatus
  proposed_priority: Priority | null
  requested_hours: number | null
  // When the CTO accepted the Issue behind this line; a "done outside the plan" line then leaves the screen (FR-PLAN-34).
  accepted_at?: string | null
  target_slot: PlanningSlot | null
  created_at: string
  origin_at: string | null
}

export interface PlanningWarning {
  id: string
  code: string
  severity: string
  message: string
  member_id: string | null
  project_id: string | null
  assignment_id: string | null
  acknowledged_at: string | null
}

export interface PlanningRun {
  id: string
  plan_date: string
  timezone: string
  project_ids: string[]
  status: string
  version: number
  revision: number
  supersedes_run_id: string | null
  source_snapshot_at: string
  assignments: PlanningAssignment[]
  candidates: PlanningCandidate[]
  warnings: PlanningWarning[]
  verifications: IssueVerification[]
}

// A closed Issue the CTO is asked to look at today, with what stands behind it (FR-PLAN-22).
// One piece of work waiting to be, or already, accepted (FR-PLAN-31).
export interface AcceptanceItem {
  id: string
  source: 'REPORT' | 'CLOSED' | string
  project_id: string
  project_name: string | null
  issue_external_id: string
  title: string
  web_url: string | null
  state: string | null
  closed_at: string | null
  assignee_member_id: string | null
  assignee_name: string | null
  reporter_member_id: string | null
  reporter_name: string | null
  reported_on: string | null
  reported_hours: number | null
  report_item_title: string | null
  priority: string
  level: number
  level_name: string
  done_evidence: string
  evidence: { commits: number; merge_requests: number; merged: number; pipeline: string | null; links: string[] }
  evidence_fetched_at: string | null
  intake_id: string | null
  intake_public_id: string | null
  acceptance: string[]
  picked_on: string | null
  decision: 'PENDING' | 'ACCEPTED' | 'REJECTED'
  reason: string | null
  decided_at: string | null
  decided_by_name: string | null
  po_decision: 'ACCEPTED' | 'REJECTED' | null
  po_reason: string | null
  po_decided_at: string | null
  po_decided_by_name: string | null
  sync_status: string | null
  sync_error: string | null
  synced_at: string | null
  created_at: string
  source_note: string | null
  // What stands behind "done" beside the read model's traces, and whether it is enough (FR-PLAN-36).
  evidence_links: EvidenceLink[]
  evidence_check: { work: 'CODE' | 'OTHER' | 'UNKNOWN' | string; status: 'OK' | 'WEAK' | 'MISSING' | string; why: string } | null
  evidence_missing_reason: string | null
}

export interface EvidenceLink {
  id: string
  kind: 'COMMIT' | 'MR' | 'LINK' | string
  url: string | null
  ref: string | null
  note: string | null
  source: 'WORKER' | 'ACCEPTOR' | 'AGENT' | 'WORK_LOG' | 'REPORT' | string
  added_by_name: string | null
  created_at: string
}

export interface AcceptanceQueue {
  plan_date: string
  sample_size: number
  pending_total: number
  today: AcceptanceItem[]
  more: AcceptanceItem[]
  decided: AcceptanceItem[]
  work_log_pending_total: number
  work_logs_pending: AcceptanceWorkLog[]
  work_logs_decided: AcceptanceWorkLog[]
}

export interface AcceptanceWorkLog {
  id: string
  intake_id: string
  intake_public_id: string
  project_id: string
  project_name: string | null
  title: string
  summary: string
  issue_external_id: string | null
  web_url: string | null
  executor: string
  details: IntakeWorkLogDetails
  review_decision: 'PENDING' | 'CONFIRMED' | 'RETURNED'
  review_note: string | null
  reviewed_by_name: string | null
  reviewed_at: string | null
  accepted_at: string | null
  created_at: string
}

export interface IssueVerification {
  id: string
  planning_run_id: string | null
  project_id: string
  issue_external_id: string
  title: string
  web_url: string | null
  closed_at: string | null
  closed_by_member_id: string | null
  assignee_member_id: string | null
  level: number
  level_name: 'SELF_REPORTED' | 'CLOSED' | 'TRACED' | 'ACCEPTED' | string
  done_evidence: 'COMMIT' | 'MR'
  evidence: { commits: number; merge_requests: number; merged: number; pipeline: string | null; links: string[] }
  evidence_fetched_at: string | null
  intake_id: string | null
  intake_public_id: string | null
  acceptance: string[]
  decision: 'PENDING' | 'ACCEPTED' | 'REJECTED'
  reason: string | null
  decided_at: string | null
}

export interface PlanningSyncJob {
  id: string
  project_id: string
  gitlab_issue_external_id: string
  status: string
  attempt: number
  max_attempts: number
  error_code: string | null
  next_attempt_at: string | null
  updated_at: string | null
}

export interface PlanningRunSyncStatus {
  planning_run_id: string
  snapshot_id: string | null
  status: string
  jobs: PlanningSyncJob[]
}

export interface DailyReportIssue {
  code: string
  severity: string
  message: string
}

export interface DailyReport {
  id: string
  member_id: string | null
  member_name: string | null
  sender_address: string | null
  report_date: string | null
  status: string
  revision: number
  is_late: boolean
  received_at: string
  item_count: number
  // Delivery items still without an Issue and without a reason (FR-RPT-07).
  unlinked_items: number
  // For a Project Owner: items of other projects left out, and whether the whole email is theirs to confirm (FR-ID-08).
  hidden_items: number
  can_review: boolean
  parsed_by: 'AI' | 'RULES'
  review_decision: 'CONFIRMED' | 'REJECTED' | null
  usable_for_planning: boolean
  issues: DailyReportIssue[]
}

export interface DailyReportItem {
  id: string
  project_name: string | null
  reported_project_code: string | null
  work_status: string
  title: string
  worked_hours: number | null
  planned_hours: number | null
  progress_percent: number | null
  gitlab_issue: string | null
  next_step: string | null
  blocker_detail: string | null
  parsed_by: 'AI' | 'RULES'
  edited: boolean
  // What the machine found for an item without an Issue, and where a linked number came from (FR-RPT-07).
  issue_suggestions: IssueSuggestion[]
  issue_link_source: string | null
  no_issue_reason: NoIssueReason | null
}

export interface IssueSuggestion { issue: string; title: string; source: string; confidence: number; reason?: string }
export type NoIssueReason = 'MEETING' | 'SUPPORT' | 'REVIEW' | 'LEARNING' | 'OTHER'

export interface DailyReportDetail extends DailyReport {
  items: DailyReportItem[]
}

export interface DailyReportSource {
  id: string
  purged: boolean
  subject: string | null
  body: string | null
  signature: string | null
}

export interface Meeting {
  id: string
  title: string
  status: 'RECORDING' | 'FINISHED' | 'FAILED'
  source: 'TAB_AND_MIC' | 'MIC' | 'FILE'
  kind: 'MEETING' | 'DICTATION'
  project_code: string | null
  project_name: string | null
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  audio_chunk_count: number
  audio_bytes: number
  max_minutes: number
  // A recording past the limit goes on as the next part of the same meeting (FR-REC-17).
  series_id: string | null
  part_number: number
  transcript_status: string
  note_status: string
  transcript_error: string | null
  note_error: string | null
  provider_data_deleted: boolean
  audio_available: boolean
}

export interface MeetingPart {
  id: string
  part_number: number
  title: string
  status: string
  transcript_status: string
  note_status: string
}

export interface MeetingNoteBulkIntakeOut {
  results: { item_id: string; intake_id: string | null; error: string | null }[]
  meeting: MeetingDetail
}

export interface MeetingSegment {
  id: string
  source: 'REALTIME' | 'BATCH'
  sequence: number
  speaker_label: string | null
  speaker_name: string | null
  start_ms: number | null
  text: string | null
}

export interface MeetingNoteItem {
  id: string
  kind: string
  topic: string | null
  title: string | null
  detail: string | null
  owner: string | null
  due_text: string | null
  project_code: string | null
  project_name: string | null
  intake_id: string | null
  edited: boolean
  can_become_intake: boolean
  // Straight to the board (FR-REC-19): the work it became, or whether it still can.
  work_id: string | null
  work_code: string | null
  can_become_work: boolean
}

export interface MeetingNoteWorkOut {
  results: { item_id: string; work_id: string | null; code: string | null; intake_id: string | null; error: string | null }[]
  meeting: MeetingDetail
}

export interface MeetingDetail extends Meeting {
  parts: MeetingPart[]
  transcript_source: 'BATCH' | 'REALTIME' | null
  speakers: { label: string; name: string | null }[]
  segments: MeetingSegment[]
  note_summary: string | null
  note_items: MeetingNoteItem[]
  rewrite_status: 'NONE' | 'PENDING' | 'DONE' | 'FAILED'
  rewrite_text: string | null
  rewrite_error: string | null
}

export interface GlossaryTerm {
  id: string
  term: string
  project_code: string | null
  usable_in_realtime: boolean
}

export interface PlanningWorkItem {
  kind: 'ISSUE' | 'INTAKE'
  project_id: string
  project_name: string | null
  issue_external_id: string | null
  intake_id: string | null
  public_id: string | null
  title: string
  priority: string | null
  already_planned: boolean
  needs_issue: boolean
  url: string | null
  assignee_names: string[]
  unknown_assignees: number
  milestone: string | null
  due_date: string | null
  suggested: 'PERSON' | 'TITLE' | null
  assigned_to_other: boolean
}

export interface PlanningAddWorkResult {
  state: 'PLANNED' | 'WAITING_ASSIGNMENT' | 'CREATING_ISSUE'
  candidate: PlanningCandidate
  assignment_error: string | null
  added_as_secondary: boolean
}

export interface IntakeJourney {
  intake_id: string
  intake_public_id: string
  project_id: string
  status: string
  received_at: string
  channel: string
  decision: { action: string; at: string; by: string | null; route: string | null; priority: string | null } | null
  issue: { system: 'GITLAB' | 'GITHUB'; external_id: string; url: string | null } | null
  other_target: string | null
  work_item: WorkRef | null
  previous_targets: { system: string; external_id: string; url: string | null }[]
  sync_status: string | null
  accepted_at: string | null
  verification: { id: string; decision: 'PENDING' | 'ACCEPTED' | 'REJECTED'; source: string; created_at: string; reason: string | null } | null
  work: { entries: number; latest_id?: string; latest_decision: 'PENDING' | 'CONFIRMED' | 'RETURNED'; latest_at: string; latest_by: string | null; off_plan: boolean; worked_on: string | null; actual_minutes: number | null; deployed: boolean | null } | null
  unlogged_evidence: { commits: number; merge_requests: number; links: number } | null
  plans: { plan_date: string; run_id: string; assignment_id: string; member_name: string; slot: string; planned_hours: number; settled: boolean; work_status: WorkStatus; work_status_at: string | null; accepted_at: string | null }[]
  waiting_in_plan: { plan_date: string; run_id: string; plan_closed: boolean } | null
}

export interface MailboxScan {
  id: string
  trigger: 'SCHEDULED' | 'MANUAL'
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'
  ingested: number
  duplicates: number
  failed: number
  error_code: string | null
  created_at: string
  completed_at: string | null
}

export interface MailboxStatus {
  enabled: boolean
  mailbox: string
  poll_minutes: number
  current: MailboxScan | null
  last: MailboxScan | null
}

export interface ApprovalSourceWeek {
  week_start: string
  from_queue: number
  from_planning: number
}

export interface BackupDetail {
  state: 'healthy' | 'never' | 'overdue'
  last_ok_at: string | null
  last_ok_file: string | null
  last_ok_size_bytes: number | null
  last_ok_objects: number | null
  last_error_code: string | null
  last_error_at: string | null
}

// A personal token an agent (Codex, Claude Code, Claude Desktop) uses to call Intake as this person (FR-MCP-01).
export interface ApiToken {
  id: string
  name: string
  prefix: string
  created_at: string
  last_used_at: string | null
  expires_at: string | null
  token?: string
}

// One piece of work done about a request, by a person or an agent, and the CTO's call on it (FR-MCP-03).
export interface IntakeWorkLogDetails {
  cause?: string | null
  changes?: string[]
  tests?: string | null
  branch?: string | null
  commit?: string | null
  verify_steps?: string[]
  deploy_steps?: string[]
  worked_on?: string | null
  actual_minutes?: number | null
  deployed?: boolean | null
  // What the project's context pack lacked while doing this (FR-CTX-04).
  context_suggestions?: string[]
}

export interface IntakeWorkLog {
  id: string
  intake_id: string
  project_id: string
  actor_id: string | null
  actor_name: string | null
  agent_name: string | null
  summary: string
  details: IntakeWorkLogDetails
  review_decision: 'PENDING' | 'CONFIRMED' | 'RETURNED'
  review_note: string | null
  reviewed_by_name: string | null
  reviewed_at: string | null
  created_at: string
}

// What changed, for the people using the app, and the build that is running (FR-UI-14).
// The week in counts (FR-PLAN-29): planned, reported, really done, and where the process waited.
export interface WeekHours { available: number; planned: number; reported: number }
export interface WeekReports { expected: number; received: number; missing: number; late: number }
export interface WeekItems { reported: number; without_issue: number; no_issue_needed: number }
export interface WeekProject {
  id: string
  code: string
  name: string
  people: number
  hours: WeekHours
  plans: { total: number; closed: number }
  done: { reported: number; issues_closed: number; accepted: number; rejected: number; po_accepted: number; work_logs_confirmed: number; accepted_without_evidence?: number }
  items: WeekItems
  reports: WeekReports
  requests: { new: number; approved: number; approved_within_24h: number; from_planning: number; avg_wait_hours: number | null; avg_to_issue_hours: number | null }
  board: { days: number; ready_days: number; no_work_days: number; overdue_days: number; max_approvals_overdue: number; max_stuck: number; escalated_days: number }
}
export interface WeekPerson {
  member_id: string
  display_name: string
  hours: WeekHours
  done_reported: number
  items: WeekItems
  reports: WeekReports
  projects: { id: string; name: string; planned: number; reported: number }[]
}
export interface WeekSummary {
  week_start: string
  week_end: string
  days_passed: number
  generated_at: string
  projects: WeekProject[]
  people: WeekPerson[]
  process: {
    requests_new: number; approved: number; approved_within_24h: number; avg_wait_hours: number | null
    from_queue: number; from_planning: number; issues_created: number; avg_to_issue_hours: number | null
    board_days: number; ready_days: number; overdue_project_days: number; escalated_project_days: number; max_stuck: number
  }
  cto_days: { date: string; minutes: number }[] | null
  personal: PersonalWeekBlock | null
  text: string
}

export interface ChangelogEntry {
  date: string
  title: string
  commits: string[]
  refs: string[]
  bullets: string[]
  cto_only: boolean
}

export interface Changelog {
  build: { sha: string; built_at: string | null }
  latest: string | null
  entries: ChangelogEntry[]
  // Entries newer than the running build; null when unknown or not asked by the CTO (FR-UI-15).
  behind: number | null
}

export interface PersonalTask {
  id: string
  task_date: string | null
  title: string
  note: string | null
  hours: number
  start_time: string | null
  remind_at: string | null
  status: 'PLANNED' | 'DONE' | 'SKIPPED' | 'DELEGATED'
  done_at: string | null
  important: boolean
  urgent: boolean | null
  urgent_effective: boolean
  quadrant: 1 | 2 | 3 | 4
  quadrant_label: string
  rollover_count: number
  archived_at: string | null
  delegated_member_id: string | null
  delegated_member_name: string | null
  delegated_assignment_id: string | null
  repeat_rule: string | null
  repeat_label: string | null
  done_quadrant: number | null
  plan?: { run_id: string; project_id: string; plan_date: string } | null
  created_at: string
  updated_at: string
}

export interface PersonalWeekBlock {
  done: { quadrant: 1 | 2 | 3 | 4; label: string; count: number; hours: number }[]
  open: { quadrant: 1 | 2 | 3 | 4; label: string; count: number; hours: number }[]
  done_total: number
  done_hours: number
  delegated: number
  rollovers: number
  schedule_share: number | null
}

export interface PersonalMatrix {
  week_start: string
  week_end: string
  today: string
  tasks: PersonalTask[]
  summary: {
    today_open: number
    today_hours: number
    quadrants: { quadrant: 1 | 2 | 3 | 4; label: string; open: number; hours: number }[]
    rolled_over: number
    undated: number
    overdue: number
  }
}

export interface DayPlanAssignment {
  id: string
  slot: PlanningSlot
  hours: number
  issue: string | null
  issue_url: string | null
  title: string
  intake_id: string | null
  intake_public_id: string | null
  priority: Priority | null
  work_status: string
  accepted: boolean
  accepted_at?: string | null
}

export interface DayPlanProject {
  id: string
  code: string
  name: string
  owner_name: string | null
  run: { id: string; status: string; version: number; revision: number; open: boolean; assigned_hours: number; assignments: number; warnings: number; unseen_warnings: number } | null
  people: { member_id: string; name: string; hours: number; planned: number; elsewhere: { project_id: string; project_name: string; hours: number }[]; assignments: DayPlanAssignment[] }[]
  free: { member_id: string; name: string; hours: number; elsewhere: { project_id: string; project_name: string; hours: number }[] }[]
  off: string[]
  waiting: { id: string; title: string; summary: string | null; source_type: string; issue: string | null; issue_url: string | null; intake_id: string | null; intake_public_id: string | null; priority: Priority | null; member_name: string | null; origin_at: string | null }[]
  off_plan: { id: string; intake_id: string; intake_public_id: string; title: string; issue: string; issue_url: string | null; executor: string; review_decision: 'PENDING' | 'CONFIRMED' | 'RETURNED'; worked_on: string; actual_minutes: number | null; deployed: boolean | null; accepted_at: string | null }[]
}

export interface DayPlans {
  plan_date: string
  projects: DayPlanProject[]
  project_order: { mode: 'PRIORITY' | 'CUSTOM'; project_ids: string[] }
  totals: { projects: number; unclosed: number; free_hours: number; free_people: number; waiting: number; off_plan: number; off_plan_actual_minutes: number }
}

export type WorkStatus = 'PLANNED' | 'IN_PROGRESS' | 'DONE' | 'BLOCKED'

export interface WorkStatusResult {
  assignment_id: string
  issue: string | null
  work_status: WorkStatus
  previous: WorkStatus
  at: string
  work_status_note: string | null
  acceptance_queued: boolean
  evidence_added?: number
}

export interface MyDayItem {
  assignment_id: string
  run_id: string
  project: string
  project_name: string
  issue: string | null
  issue_url: string | null
  title: string
  intake: string | null
  priority: Priority | null
  slot: PlanningSlot
  hours: number
  work_type: string
  primary: boolean
  work_status: WorkStatus
  work_status_note: string | null
  accepted_at?: string | null
  plan_closed: boolean
}

export interface MyDay {
  date: string
  member: string
  projects: { id: string; code: string; name: string }[]
  items: MyDayItem[]
  personal: { task_id: string; title: string; hours: number; start_time: string | null; remind_at: string | null; status: string; quadrant: number; quadrant_label: string }[]
  note?: string | null
  hint?: string | null
}

// A file on a request and whether the vision model has read it (FR-AI-14).
export interface IntakeAttachment {
  id: string
  index: number
  name: string | null
  mime_type: string | null
  size_bytes: number
  ocr_status: 'NONE' | 'RUNNING' | 'RETRY' | 'DONE' | 'FAILED' | 'REJECTED' | 'SKIPPED' | string
  ocr_error: string | null
  ocr_at: string | null
  page_count: number | null
  pages_read: number
}

export interface IntakeRaw {
  id: string
  raw_text: string | null
  attachments: (IntakeAttachment & { text: string | null })[]
}

// The project's context pack as Intake last read it (FR-CTX-03).
export interface ProjectContextSection {
  number: number
  title: string
  required: boolean
  to_ai: boolean
  present: boolean
  lines: number
}

export interface ProjectContext {
  project_id: string
  source: 'REPO' | 'PASTED' | string
  path: string
  sha: string | null
  fetched_at: string | null
  meta: Record<string, string>
  sections: Record<string, ProjectContextSection>
  score: number
  band: 'FULL' | 'PARTIAL' | 'MISSING' | string
  missing: string[]
  stale_days: number | null
  error: string | null
  has_content: boolean
  approved: boolean
  approved_sha: string | null
  approved_at: string | null
  content: string | null
  pending_suggestions: number
}

// One thing an agent or a person found missing in the pack while working; the CTO decides (FR-CTX-04).
export interface ProjectContextSuggestion {
  id: string
  project_id: string
  intake_id: string | null
  intake_public_id: string | null
  work_log_id: string | null
  text: string
  suggested_by: string | null
  suggested_by_name: string | null
  agent_name: string | null
  status: 'PENDING' | 'APPLIED' | 'DISMISSED' | string
  decided_by: string | null
  decided_by_name: string | null
  decided_at: string | null
  created_at: string
}

// A suggestion from a member who is not the Project Owner, waiting for the owner's yes or no (FR-FBK-01..03).
export interface FeedbackFile {
  id: string
  name: string | null
  mime_type: string
  size_bytes: number
}

export interface FeedbackItem {
  id: string
  project_id: string
  project_code: string | null
  project_name: string | null
  member_id: string | null
  member_name: string | null
  user_id: string | null
  transport: 'WEB' | 'TELEGRAM' | 'AGENT' | string
  text: string
  status: 'PENDING' | 'ACCEPTED' | 'REJECTED' | string
  intake_id: string | null
  intake_public_id: string | null
  decided_by: string | null
  decided_by_name: string | null
  decided_at: string | null
  decision_note: string | null
  files: FeedbackFile[]
  created_at: string
}

// --- Work tracked inside Intake (FR-WRK-01..06, ADR-0066) ---------------------------------------------

export type WorkItemStatus = 'DISCUSS' | 'READY' | 'IN_PROGRESS' | 'ACCEPTANCE' | 'APPROVED' | 'DONE' | 'CANCELLED'

export interface PostShortLink {
  code: string
  url: string
  target_url: string
  clicks: number
  created_at: string
}

export interface WorkChannel {
  id: string
  channel: string
  publish_at: string | null
  status: 'DRAFT' | 'READY' | 'PUBLISHED'
  published_url: string | null
  language: string | null
  // The words of this version (FR-MKT-11) and its short link (FR-MKT-12).
  text: string | null
  short_link: PostShortLink | null
}

// What a marketing project listens to (FR-MKT-08..10).
export interface WatchTerm { text: string; kind: 'keyword' | 'hashtag'; priority: 'high' | 'normal' }
export interface Pillar {
  name: string
  description: string
  audience: string
  channels: string[]
  share_pct: number
  keywords: WatchTerm[]
  samples: { title: string | null; url: string }[]
  avoid: string
}
export interface WatchSettings {
  networks: string[]
  open_networks: string[]
  schedule: { times: string[]; weekdays: number[] }
  scan_every_hours: number
  scan_hours: number[]
  max_ai_runs_per_day: number
  ai_runs_per_week: number
}
export interface WatchPlatform {
  code: string
  label: string
  enabled: boolean
  via: 'api' | 'scrape' | 'none'
  note: string | null
  sort_order: number
  updated_at: string
}
export interface WatchTopic {
  id: string
  week_start: string
  title: string
  why: string | null
  angles: string[]
  channels: string[]
  caution: string | null
  pillar: string | null
  score: number
  state: 'NEW' | 'USED' | 'DISMISSED'
  ai_written: boolean
  work_id: string | null
  sources: number
  signals: { id: string; title: string; url: string; host: string; keyword: string | null; published_at: string | null; via: string }[]
  updated_at: string
}
// A door for an outside service into a marketing project (FR-MKT-13).
export interface ConnectorMapping { items: string; fields: Record<string, string> }
export interface WatchConnector {
  id: string
  project_id: string
  project_code: string | null
  name: string
  kind: 'GENERIC' | 'N8N' | 'MAKE' | 'APIFY' | 'MENTION'
  token_prefix: string
  via: 'api' | 'scrape'
  default_pillar: string | null
  mapping: ConnectorMapping
  enabled: boolean
  received_count: number
  rejected_count: number
  last_received_at: string | null
  last_status: string | null
  path: string
  created_at: string
  token?: string | null
}
export interface ConnectorSummary { id: string; name: string; kind: string; enabled: boolean; last_received_at: string | null; received_count: number; last_status: string | null }
export interface ConnectorTry {
  items: { url: string; title: string; excerpt: string | null; keyword: string | null; pillar: string | null; published_at: string | null; would_reject: string[]; notes: string[] }[]
  problems: string[]
  would_accept: number
}
export interface ConnectorDelivery { at: string; status: 'ACCEPTED' | 'EMPTY' | 'INVALID' | 'UNAUTHORIZED'; accepted: number; duplicates: number; rejected: number; note: string | null }

export interface WatchTopics {
  week_start: string
  has_sources: boolean
  kept_this_week: number
  refresh_left: number
  built_at: string | null
  schedule: { times: string[]; weekdays: number[] }
  topics: WatchTopic[]
}

export interface ChannelRule {
  code: string
  label: string
  language: 'vi' | 'en'
  max_chars: number
  recommended_chars: number | null
  long_max_chars: number | null
  max_images: number
  image_ratio: string | null
  video_ratio: string | null
  hashtag_max: number
  link_counts_chars: boolean
  link_chars: number
  best_hours: string[]
  tone: string | null
  enabled: boolean
  auto_publish: boolean
  sort_order: number
  updated_at: string
}

export interface WorkRef {
  id: string
  code: string
  status: WorkItemStatus
  project_id: string
}

export interface WorkItem {
  id: string
  code: string
  project_id: string
  project_code: string | null
  project_name: string | null
  project_kind: string | null
  title: string
  description: string
  status: WorkItemStatus
  priority: Priority
  member_id: string | null
  member_name: string | null
  due_date: string | null
  intake_id: string | null
  intake_public_id: string | null
  intake_status: string | null
  issue_system: string | null
  issue_external_id: string | null
  issue_url: string | null
  outcome: 'ISSUE_PENDING' | 'ISSUE' | null
  issue_pending: boolean
  closed_note: string | null
  comment_count: number
  link_count: number
  version: number
  // A pipeline (FR-WRK-08): the parent carries the template, each step is a child in order.
  template: 'VIDEO' | null
  steps_total: number
  steps_done: number
  parent_id: string | null
  parent_code: string | null
  step: string | null
  step_label: string | null
  step_order: number | null
  evidence_required: boolean
  meeting_id: string | null
  meeting_title: string | null
  meeting_at: string | null
  // A post (FR-MKT-01): main channel, format, campaign, Gấp, and the channel versions with their dates.
  channel: string | null
  format: string | null
  campaign: string | null
  urgent: boolean
  channels: WorkChannel[]
  next_publish_at: string | null
  created_by: string | null
  created_by_name: string | null
  created_at: string
  updated_at: string
  closed_at: string | null
}

export interface WorkComment {
  id: string
  user_id: string | null
  user_name: string | null
  mine: boolean
  body: string
  created_at: string
}

export interface WorkHistory {
  at: string
  actor_name: string | null
  event_type: string
  details: Record<string, unknown>
}

export interface WorkLink {
  id: string
  url: string
  note: string | null
  source: 'USER' | 'AGENT'
  added_by: string | null
  added_by_name: string | null
  mine: boolean
  created_at: string
}

export interface WorkDetail extends WorkItem {
  comments: WorkComment[]
  links: WorkLink[]
  steps: WorkItem[]
  history: WorkHistory[]
}

export interface SetupState {
  completed: boolean
  has_project: boolean
  has_private_space: boolean
  sample_available: boolean
  wizard: boolean
  ai_ready: boolean
}
