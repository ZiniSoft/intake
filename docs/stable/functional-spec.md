English | [Tiếng Việt](functional-spec.vi.md)

# Functional specification

_Target behavior 1.2 | Updated 2026-10-01 | For implementation status see PRODUCTION-READINESS and IMPLEMENTATION-INVENTORY_

## 0. Target/runtime boundary

The use cases in this document describe target behavior. The runtime currently closes the loop for text Intake, approval/sync, the Daily Report parser and most of Daily Planning; parts without code or live evidence stay in the use cases but are listed in `IMPLEMENTATION-INVENTORY.md`. Notably: Project Owner, Emergency Add with automatic Issue creation, the Planning assignment editor/amendment, auto-normalize for Quick Add and live IMAPS are not working yet. The target policy for the Planning gaps was settled by the CTO on 2026-10-01 in ADR-0010 and extended on 2026-10-03 in ADR-0011 through ADR-0014.

## 1. Personas

### CTO

The only user in the pilot. Has the right to view the raw source, create/edit intakes, run/retry the pipeline, decide priority/route, approve, sync and view audit/operations.

### Project members

Do not log in to Intake. Receive approved work through GitLab and update the delivery state in GitLab.

### Project Owner

Does not log in to Intake during the pilot yet. May take part in discovery through Plane and in delivery planning through GitLab.

From 2026-10-05 (ADR-0022) the CTO grants permissions per project: within a granted project the Project Owner can view the original content, create, approve and sync Intakes, and work with meetings; they see nothing from other projects. Daily reports and per-project Daily Planning are phase 2. Before that the documentation said: a later phase may grant the right to view and approve Planning Runs in the projects they are authorized for. The CTO always keeps override rights; Project Owner permissions are never opened system-wide.

## 2. Navigation

| Screen | Purpose |
|---|---|
| Login/MFA | Local account and TOTP authentication |
| Dashboard | Items the CTO must decide and the approval queue; system status has moved to Settings ("Cài đặt") |
| New Intake | Choose project/channel, enter text, upload files |
| All Intakes | List with project/stage/priority/sync target/search filters and a shareable page/cursor pair in the URL, keyset pagination that returns to the first page when the cursor is invalid, P0/P1 summary per project, a copy-link button and work item links |
| Intake Detail | Raw source, attachments, pipeline, AI result, evidence, audit |
| Approval Queue | Items that need a CTO decision |
| Sync Queue | Pending/running/failed jobs and controlled retry |
| Projects | Project list by type and links; a four-step project creation wizard and a project edit screen (ADR-0020) |
| Reports | Daily reports: the original email next to the extracted tasks, confirm or discard. Daily/weekly summaries per project are not available yet |
| Meetings | Meeting list; transcript by speaker, playback, download, meeting note and turning items into Intakes |
| Meeting recorder | Right sidebar on the Intake creation page: choose project, audio source, glossary, realtime transcript |
| Daily Planning | Overview of all projects, priority order or a per-account custom order; Planning Run per day, capacity, two morning/afternoon lanes, conflicts/warnings and GitLab sync status |
| Capacity | Default/override per person/day; meetings, review, support and OT |
| Settings | One tabbed page that groups rarely used configuration: Projects ("Dự án"), Members ("Nhân sự", assign projects and GitLab users), Glossary ("Thuật ngữ"), System ("Hệ thống"), Account and security ("Tài khoản và bảo mật": MFA, recovery codes) |

## 3. Use cases

### UC-01 - Create an intake

1. The CTO selects a project (required).
2. Selects a channel and enters text or a file.
3. The server validates, encrypts the raw text, stores the file in quarantine and commits the outbox in the same transaction.
4. The UI receives `201` with the public ID and pipeline status.

An intake must not be accepted if the project is inactive, the payload exceeds the limits or object persistence fails.

### UC-02 - AI processing

1. The CTO or a policy enqueues processing.
2. The dispatcher publishes the run ID.
3. The worker processes the source, calls the provider chain, validates the output and materializes the review fields.
4. The UI shows the provider/model, warnings, evidence and terminal state.

A retry with the same input/prompt/schema does not create a duplicate current extraction outside the versioning policy.

### UC-03 - Review

The CTO compares the raw source with the AI proposal, edits type/title/summary/priority/route/acceptance criteria, handles duplicates and notes missing information. Every change increments the item version.

### UC-04 - Approve

The CTO must save the normalized review first. The CTO sends `expected_version`; the server only allows approval when the item is in `PENDING_APPROVAL` and has a normalized title/summary, then validates route prerequisites, redaction and the project mapping requirement and creates an immutable snapshot. The result is `APPROVED`; there is no external write yet. Approving directly from `NEW` returns `REVIEW_REQUIRED`.

### UC-05 - Sync

The CTO selects a valid snapshot and clicks Sync. The API creates an idempotent sync job/outbox and returns `202`. The integration worker creates/updates the GitLab or GitHub Issue and stores the external link or a terminal error. Retry does not create duplicates.

### UC-06 - Reject, defer, request information

- Reject: a reason is required; terminal unless reopened with permission.
- Defer: a future time is required.
- Request information: at least one specific question.

### UC-07 - Email report

The worker reads new email over IMAPS, dedupes, encrypts/stores it, maps the project and creates a source for the report. Email does not change the GitLab Issue percentage by itself and does not create outbound mail.

### UC-08 - Multi-project

The CTO can work on several projects in parallel. The project filter is always clearly visible; P0/P1, pending approval, sync errors, total results and pagination all follow the selected project. Workers route by the project ID in the record. A missing/disabled mapping makes sync fail closed.

### UC-09 - Re-sync an Intake

An Intake has at most one current Issue on the approved delivery route. If the route that already has an Issue is selected again, the next Sync updates that Issue (found by the request's marker, reopened if closed) instead of creating a second item (ADR-0048). Plane links created before ADR-0066 are kept and shown read-only.

### UC-10 - Collect and reconcile Daily Reports

1. The IMAPS worker continuously reads the `report@example.com` mailbox, dedupes and stores encrypted email.
2. The parser checks the subject/body against the Daily Report format, links replies/updates in the same thread and stores errors per field.
3. The report builder aggregates at 23:30 and refreshes at 06:45 in `Asia/Ho_Chi_Minh`.
4. GitLab provides the Issue, state, assignee, priority label, milestone, due date, MR/CI/test; email provides hours worked, next steps, blockers, risks and support needs.
5. Conflicts are stored as warnings. An email `DONE` does not turn the GitLab Issue into Done; a blocker from email is still flagged even if GitLab is still Doing.
6. A missing, late or malformed report does not stop the flow. On weekends, reports are only expected from people with OT capacity or work evidence.

### UC-10A - The CTO reviews a Daily Report before it is used for planning

1. The CTO opens the Daily reports ("Báo cáo ngày") page, selects a date and a report; sees a label showing whether the report was read by the rule set or by AI, and the warnings.
2. The CTO opens the original email (audited). The signature after the `--` line is in a collapsed section.
3. The CTO edits or deletes each task if it was extracted incorrectly.
4. The CTO clicks "Confirm correct" ("Xác nhận đúng"): the button locks, the screen says the tasks will go to Daily Planning and leads to the next unreviewed report.
5. The CTO clicks "Discard report" ("Loại báo cáo"): the system asks again because discarding removes the tasks from Planning and cannot be undone in the UI.
6. A report read by AI is not used for Planning until it is confirmed.

### UC-11 - Create the Planning Run at 07:00

1. The scheduler creates one run for the plan date, including Saturday/Sunday.
2. Load capacity: weekdays default to 8 hours, weekends to 0 hours, then apply CTO overrides.
3. Subtract meetings, review, support and fixed activities to get the available capacity.
4. Generate candidates in the order: approved P0/P1, `Doing` carry-over, review/QA, near milestones, `Ready` Issues, then P2/P3 if capacity remains. Priority comes from the most recent approved Planning snapshot that contains the Issue; if there is none, the GitLab priority label is used (ADR-0013). Runtime 1.2 only reads the GitLab label.
5. Split assignments into `MORNING`/`AFTERNOON`; a task may appear in both slots but is still one primary development task.
6. Warn about over-capacity, overlap, blocked dependencies, source conflicts and more than one primary development task.

### UC-11A - Tasks in a report become Planning candidates

1. When the run is created or reopened while still editable, unfinished tasks (`PLANNED`, `IN_PROGRESS`, `PENDING_REVIEW`, `BLOCKED`) from usable reports appear in the "Requests to triage" ("Yêu cầu cần phân loại") section with the "Daily report" label, the member's name, the next step and the hours if any.
2. Tasks without a GitLab Issue still appear, in pending triage state; the CTO enters the Issue number on the card and then promotes.
3. Tasks whose Issue the planner already proposed for the same member are not shown twice.

### UC-11A.1 - Order projects in the Daily Planning overview

1. The CTO or Project Owner opens the "All projects" ("Tất cả dự án") scope; this is a read-only overview and only includes active software projects within the current permission scope.
2. The default "Priority" ("Ưu tiên xử lý") mode puts projects without a Project Owner first for the CTO, then in turn prioritizes projects with work waiting for assignment, unread warnings and unfinalized plans; projects at the same level are sorted by name.
3. The user selects "Custom" ("Tùy chỉnh") to drag and drop or use the up/down buttons. The server stores the ID list per account, not per browser, and it is not shared between the CTO and a Project Owner.
4. New or newly granted projects that are not in the saved list are appended after the ordered projects, following the default priority rule. Projects the user lost access to are filtered out of the response.
5. "Restore priority" ("Khôi phục ưu tiên") switches back to `PRIORITY` and deletes the custom list; it does not change any plan or project data.

### UC-11B - Add work to the plan during the day (ADR-0024)

1. The CTO clicks "Add work to plan" ("Thêm việc vào kế hoạch"); a panel opens in the right sidebar.
2. Existing work: type a few characters, pick an open Issue or an Intake pending approval. New work: enter title, description, type, priority.
3. Choose the assignee, session and hours. If the work has no Issue yet, enter a reason; the system records it as an approval decision, creates the Issue in the project's delivery target, then adds the work to the plan once the Issue exists.
4. Work from daily reports is in the "Work awaiting assignment" ("Việc chờ phân công") list below the two plan columns. Each row has "Schedule" ("Xếp việc": attach an existing Issue or create a new one, then assign) and "Skip" ("Bỏ qua": hide from today's plan, can be restored).
5. While the plan is still open, drag a card to another person's morning or afternoon cell to change the assignee and optionally the session in one action. The recipient must still belong to the project and have a tracker mapping for delivery work. If it exceeds the daily capacity, 4 hours/session, or the person already has another primary development task, the UI asks the CTO/Project Owner to confirm the exception and then sends the reason to be stored in the audit.

The flow below (UC-12) is the design from before ADR-0024; its API still exists but the UI no longer uses it.

### UC-12 - Unified Quick Add

The CTO has three entry points on the same Planning screen:

1. Pick an existing GitLab Issue or Intake item.
2. Fill in a quick form to create an Intake with source `MANUAL`/`MEETING`.
3. Paste a chat, customer email or meeting note to create an Intake; after the transaction that creates Intake + candidate commits, the target enqueues normalize/dedupe asynchronously. Enqueue errors are retried/shown as status but do not roll back the Quick Add action. Runtime 1.2 only creates Intake + candidate and does not enqueue the AI pipeline automatically yet.

Items without a GitLab Issue must complete triage/promote before planning approval. For P0, the CTO uses `Emergency Add`: enter the minimum content and a reason, and Intake immediately creates the GitLab Issue without going through the two steps `Approve` then `Sync`, records an audit entry and makes the Issue a candidate (ADR-0012). `Emergency Add` is still a target with no endpoint/UI in runtime 1.2.

### UC-13 - Approve and update GitLab

1. The CTO reviews and may directly edit priority, assignee, milestone, due date, slot and planned hours before approval.
2. The API checks the expected version, capacity/WIP, GitLab user mapping, Issue reference and existing milestone. A missing milestone or due date is a warning: the CTO acknowledges it and can still approve, and the job only sends fields that have values (ADR-0013). Runtime 1.2 still blocks approval when they are missing.
3. Approval creates an immutable planning snapshot and enqueues one update job per Issue.
4. The integration worker updates assignee, milestone and due date. The approved priority and the morning/afternoon details are only stored in Intake during the pilot; the worker does not change the GitLab priority label.
5. Success is recorded per Issue. A failure on one Issue makes the run `PARTIAL` without rolling back Issues that succeeded; retry only processes failed jobs with the original idempotency key.
6. Target: editing an approved plan creates a new revision of the whole run, linked by `supersedes_run_id`, creates a new snapshot and only syncs the per-Issue delta approved by the CTO. Runtime 1.2 locks approved runs and has no amendment/supersede API yet.

### UC-13A - Projects that deliver on the customer's GitHub

1. The CTO pastes the customer's token in Settings > Projects, GitHub Token ("Token GitHub") section (stored encrypted, FR-INTG-21; tokens placed in `.env.github` still work), then in the wizard chooses the Software ("Phần mềm") type, the delivery target "Customer's GitHub" ("GitHub của khách hàng"), the token by name and the repository; it can only be saved after the connection check passes.
2. When an Intake of the project is approved, the delivery route is GitHub; Sync creates an Issue containing only the approved title and description.
3. Every morning the repository's Issues are refreshed at the same time as GitLab; the planner proposes work from open Issues assigned to members who have been mapped to a GitHub user.
4. The CTO approves the plan; the plan is stored and viewed in Intake, and nothing is written to the customer's repository.

### UC-14 - Meeting recording and meeting note

1. The CTO opens "Record meeting" ("Ghi âm họp"), chooses the meeting's project (required) and the audio source: meeting tab + microphone, microphone only, or upload an existing file.
2. During the meeting, the transcript appears progressively; the shared and project glossaries are loaded so proper names are recognized correctly.
3. After it ends, the system transcribes again with speaker separation ("Member 1, 2…" ("Thành viên 1, 2…")), deletes the copy on the ElevenLabs side, and AI creates a meeting note with a summary and four groups: decisions; requests, bugs, scope changes; action items; open questions and risks.
4. On the Meetings ("Cuộc họp") page, the CTO sets real names for speakers, plays back or downloads the recording, edits the summary and each item, regenerates the note, and changes the meeting's project.
5. The CTO clicks "Create Intake" ("Tạo Intake") on a request, bug, scope change or action item; the `MEETING` channel Intake goes through the pipeline and waits for approval like any Intake.
6. Audio, transcripts and notes are purged under the 90-day retention.

## 4. State machines

### Intake

```text
NEW -> QUEUED -> PROCESSING -> REVIEW_REQUIRED
PROCESSING -> NEEDS_INFORMATION | FAILED
REVIEW_REQUIRED -> APPROVED | REJECTED | DEFERRED | NEEDS_INFORMATION
APPROVED -> SYNC_PENDING -> SYNCED
SYNC_PENDING -> APPROVED   (sync failed nhưng snapshot còn hợp lệ)
APPROVED -> REVIEW_REQUIRED (payload thay đổi, snapshot invalidated)
```

### Processing run

```text
QUEUED -> RUNNING -> SUCCEEDED | PARTIAL | FAILED
RUNNING -> RETRY -> RUNNING
```

### Sync job

```text
PENDING -> RUNNING -> SUCCEEDED | RETRY | FAILED
RETRY -> RUNNING
```

### Planning Run

```text
DRAFT -> REVIEW_REQUIRED -> APPROVED -> SYNCING -> SYNCED
SYNCING -> PARTIAL | SYNC_FAILED
PARTIAL -> SYNCING
DRAFT | REVIEW_REQUIRED -> SUPERSEDED
APPROVED | SYNCED | PARTIAL -> SUPERSEDED (khi CTO duyệt version mới)
```

An approved Planning Run is not edited in place. Every amendment creates a new revision of the whole run, linked by `supersedes_run_id`; the old snapshot is immutable and only the per-Issue delta of the new revision is enqueued.

Every other transition must return `409 INVALID_STATE_TRANSITION`.

## 5. Classification and route

| Type | Description | Default route |
|---|---|---|
| BUG | Actual differs from expected | GitLab if there is evidence/AC |
| TASK | Work already within scope | GitLab if there is enough data |
| FEATURE | New need that requires discovery | Internal tasks |
| SCOPE_CHANGE | Change to a commitment/scope | Internal tasks |
| FEEDBACK | Opinion not yet enough to be a requirement | Response or needs info |
| QUESTION | Needs a response/information | Response draft |
| UNCLEAR | Not enough to classify | Needs information |

## 6. Priority

AI only proposes. The CTO decides P0-P3 during the pilot.

| Priority | Criteria |
|---|---|
| P0 | Outage, data loss, critical security issue or severe business stoppage |
| P1 | Affects a near-term commitment/many users, no reasonable workaround |
| P2 | Normal planned work or a bug with a workaround |
| P3 | Improvement, optimization, nice-to-have or research backlog |

## 7. UX rules

- Always show the project and public ID on detail/review/sync.
- Distinguish AI suggestions from CTO-approved values.
- Make it clear that `Approve` does not mean `Synced`.
- `PARTIAL` warnings, stale snapshots and provider errors must not be hidden; the pilot has no provider fallback (ADR-0011).
- Dangerous actions have a confirmation and an idempotent result.
- Do not render raw HTML from chat/email unless it has been sanitized.
- Planning always shows the source of truth next to the self-reported value and never hides conflicts automatically.
- Morning/afternoon lanes show planned hours, work type, primary/secondary and remaining capacity.
- `Approve & Sync` must state clearly that it will update assignee, milestone and due date on GitLab.
- Per-Issue sync failures have their own retry; never present `PARTIAL` as a completed sync.
