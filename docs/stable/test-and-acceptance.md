English | [Tiếng Việt](test-and-acceptance.vi.md)

# Test and acceptance plan 1.2

_Updated 2026-10-01 | The test catalog is the target; for evidence already run see `PRODUCTION-READINESS.md` and the Gate reports_

## 1. Test layers

| Layer | Scope |
|---|---|
| Unit | Validator, state machine, redaction, key generation, provider classification |
| Database contract | PostgreSQL types, constraints, JSONB, TIMESTAMPTZ, indexes, locking |
| Component | API + PostgreSQL/Redis/SeaweedFS test services |
| Adapter contract | UModelVerse, OpenRouter, GitLab, GitHub, IMAPS with stubs and real sandboxes |
| E2E | End-to-end browser/API on the pilot topology |
| Security | Auth/MFA/session, project isolation, file safety, secret/log checks |
| Performance | Keyset list, detail, dashboard, queue claim with the standard dataset |
| Operations | Restart, backup/restore, rollback and incident drills |

### Latest automated evidence

- SQLite isolation: `80 passed, 2 skipped, 1 warning`.
- PostgreSQL 16 production-like: `82 passed, 1 warning`.
- Frontend Vitest: `4 passed`.
- TypeScript and Docker production build: pass.
- Planning Chrome desktop/mobile mocked E2E: pass, including per-Issue failed -> retry -> pending.
- Planning live internal mutation: created a run + real Quick Add Intake/candidate, stopped before approval and cleaned up all test data.

These numbers are a working tree snapshot from 2026-10-01 and do not replace the Gate report/release commit.

Addendum 2026-10-05 (commit `0064c33` on branch `feature/ui-shell-email-reports`):

- SQLite isolation: `111 passed, 2 skipped`. PostgreSQL production-like has not been rerun after migrations 004 to 006.
- `frontend/e2e/intake-composer.mjs`: 10 Chrome desktop/mobile scenarios pass on the dev server, with the Intake write request mocked.
- `meeting-capture.mjs` (fake microphone), `meeting-upload.mjs` (WAV file), `meeting-notes.mjs` (Meetings ("Cuộc họp") page): pass on the pilot stack with real ElevenLabs and UModelVerse, using a synthesized two-voice conversation of about 32 seconds.
- Not yet done: testing with real Zoom/Meet/Teams, a 60-minute session, multi-person meetings, a gate report for meeting recording, and Vitest has not been rerun.

## 2. Mandatory tests

| ID | Test | Expected result |
|---|---|---|
| T-001 | Create text intake | DB + outbox in the same commit; response does not echo raw |
| T-002 | Redis down after DB commit | Intake still exists; republished when Redis recovers |
| T-003 | Two dispatchers claim the same event | Only one dispatch takes effect |
| T-004 | UModelVerse success | Valid JSON persisted as JSONB, provider/model trace correct |
| T-005 | UModelVerse 429/5xx | Pilot: bounded retry then run `FAILED`, no call to another provider (ADR-0011). Fallback is tested only when enabled after the pilot |
| T-006 | UModelVerse 401/403 | Permanent fail, no retry and no call to another provider |
| T-007 | Invalid model ID | Blocked before the network call |
| T-008 | Approve stale version | 409, no snapshot |
| T-009 | Successful approve | Immutable snapshot; no external write |
| T-010 | Edit item after approve | Snapshot invalidated; Sync blocked |
| T-011 | Double/concurrent Sync | One external item |
| T-012 | Mapping project disabled | Fail closed, no routing to another project |
| T-013 | Two projects in parallel | No cross-project data/job/token/target |
| T-014 | File >5 MB/wrong magic bytes | 413/422; no orphan object |
| T-015 | File fails the safety check (ADR-0015): wrong magic bytes, too many pages, encrypted PDF or with embedded files | Reject + audit; no OCR/vision/cloud call |
| T-015a | OCR exceeds timeout/resource limits or tries to call the network | Container stopped/blocked; failed run has a trace; other files unaffected |
| T-015c | Processing a valid image/PDF | Request to UModelVerse contains only the OCR'd text; no original file, base64 or vision model call |
| T-015d | Calling the OCR machine with missing/wrong authentication or the wrong address | Rejected; the OCR machine keeps no file/result after processing |
| T-015b | Download/view attachment | Requires authorization and the correct project; direct download response with `no-store`, `nosniff`; the UI fetches an authenticated blob to show images in a modal, never embeds the file URL directly |
| T-016 | One PDF page broken | PARTIAL + warning/evidence still usable |
| T-017 | IMAPS duplicate | One email record |
| T-018 | SMTP attempt from a worker | Blocked by network policy |
| T-019 | Raw older than 90 days | Ciphertext/object purge + audit |
| T-020 | Restore drill | RPO <=24h, RTO <=4h |
| T-021 | Scheduler 07:00 on a weekday | One idempotent Planning Run, correct Vietnam timezone |
| T-022 | Scheduler 07:00 on a weekend without OT | Run is still created; default capacity 0; no missing-report warning for people without OT |
| T-023 | CTO enters weekend OT | Override has a reason; capacity correct and report expectation enabled |
| T-024 | Subtract meeting/review/support/fixed | Available capacity correct; never negative |
| T-025 | Report missing/late/wrong format | Planning Run is still created from GitLab with warnings at the right level |
| T-026 | Email DONE, GitLab Doing | GitLab state is used; task still carries over; `STATUS_MISMATCH` shown |
| T-027 | Email has a blocker, GitLab Doing | Blocker warning is not ignored |
| T-028 | Two primary development tasks | Approval blocked if CTO override reason is missing |
| T-029 | Morning/afternoon over-capacity or overlap | Blocked/warned per rule; override is audited |
| T-030 | Quick Add from three sources | Existing/form/paste all trace the source; new items go through normalize/dedupe |
| T-031 | Assignment without a GitLab Issue | Planning approval fails closed; P0 uses Emergency Add so Intake immediately creates a minimal Issue (see T-043) |
| T-032 | Planning approve stale version | 409; no snapshot/job |
| T-033 | Successful Planning approve | Immutable snapshot and exactly one job per Issue |
| T-034 | GitLab update partial failure | Run `PARTIAL`; successful jobs not rolled back; retry only failed jobs |
| T-035 | Double/concurrent Planning approval/retry | No repeated assignee/milestone/due-date side effects |
| T-036 | User mapping missing or milestone does not exist | Fail closed before the external update |
| T-037 | Project Owner tries to approve in the current phase | 403; CTO approval still works |
| T-038 | Quick Add form/paste committed but enqueue temporarily fails | Intake + candidate still exist; normalize/dedupe is retried, no duplicate records |
| T-039 | CTO edits assignment before approval | Six fields priority/assignee/milestone/due date/slot/planned hours saved with the correct expected version; mapping/capacity/WIP still fail closed |
| T-040 | Planning sync in the pilot | GitLab only changes assignee/milestone/due date; priority label is not changed |
| T-041 | Amendment of an approved run | Creates a new revision + immutable snapshot, linked as supersede; only Issues with a delta generate jobs and retry stays idempotent |
| T-042 | Pilot activation IMAPS | Read-only TLS probe, real report ingest, revision/warning and UID dedupe pass; SMTP egress still blocked |
| T-043 | Emergency Add P0 (ADR-0012) | Exactly one minimal GitLab Issue with `priority:p0`, with a reason and audit; non-CTO, priority other than P0, missing reason or duplicate retry all create no Issue |
| T-044 | Planner priority (ADR-0013) | An Issue with an approved snapshot uses the priority from the latest snapshot; an Issue without one uses the GitLab label; differing values are shown |
| T-045 | Missing milestone/due date (ADR-0013) | Approve is rejected while the warning is not acknowledged, succeeds once acknowledged; the job does not send or clear the missing fields |
| T-046 | Access `intake.example.com` (ADR-0014) | HTTPS with a valid certificate over VPN; not reachable from outside the VPN; cookie has `Secure` |
| T-047 | Intake approval does not write outbox (OD-017) | Approve creates snapshot and audit, no outbox event `intake.approved` |
| T-048 | CTO-confirmed work log and the status screens (INT-26W43-004) | `CONFIRMED` in the same transaction accepts the Issue, enqueues tracker close; Daily Planning, Intake detail and My work ("Việc của tôi") all have `accepted_at`/"Accepted" ("Đã nghiệm thu"); collector backfills old `CONFIRMED` rows; Planning URL uses `date`, `project`, the public Intake ID and focuses the right card |
| T-049 | Management lifecycle in All Intakes ("Tất cả Intake") | Every row always has one of eight `lifecycle_stage` values; filter `stage` uses the same source of truth; Work goes through Awaiting scheduling ("Chờ xếp việc")/In progress ("Đang thực hiện")/Awaiting acceptance ("Chờ nghiệm thu")/Accepted, direct responses and Issues accepted by the CTO or confirmed done by the Project Owner go into Accepted, terminal outcomes are grouped into Stopped ("Đã dừng") but keep the detailed reason |
| T-050 | CTO acceptance directly on the Intake journey | Journey returns `work.latest_id`; when the latest log is `PENDING`, the CTO sees and can use the two CTAs right at the Acceptance ("Nghiệm thu") step; confirming creates acceptance/schedules Issue close, returning requires a reason; the PO has no CTA; after the decision, Journey and Work log refresh together; `CONFIRMED` without `accepted_at` no longer shows "awaiting CTO check" ("chờ CTO kiểm") |
| T-051 | An Issue appears only once in Daily Planning (INT-26W43-005) | The planner does not split work over 4 hours into two morning/afternoon cards; the manual add API and candidate promote reject an Issue already present with `ISSUE_ALREADY_PLANNED`; a unique index blocks races; migration 056 keeps the row with the highest progress, reattaches candidates/warnings, merges hours up to 4 and deletes extra rows; `get_my_day.items[].issue_url` and the My work card open the Issue detail to work on |

## 3. Performance baseline

Minimum standard dataset: 2 projects, 100,000 intakes, 300,000 source messages, 100,000 processing runs and representative audit volume.

- List p95 <= 500 ms with indexed project/status/cursor query.
- Detail p95 <= 800 ms, no binary/raw history loaded by default.
- Worker claim without full-table scan; `EXPLAIN ANALYZE` stored in evidence.
- Concurrent create/process/sync without duplicates and without deadlocks outside the retry policy.

## 4. Security acceptance

- No secrets in the repository/image/log.
- A simulated Project Owner cannot read raw/approve/sync.
- Cross-project ID returns 404 or a policy-safe response.
- Session/recovery code rotation works.
- Attachment download authorization and signed URL expiry.
- AI worker has no GitLab/GitHub token; IMAPS worker has no SMTP credential.

## 5. UAT

The CTO performs at minimum, on at least two projects:

1. Create a text intake and an attachment.
2. View the pipeline/provenance.
3. Edit the result, approve and confirm there is no external item yet.
4. Sync to the correct project and check the link.
5. Try stale snapshot, duplicate click, provider failure and missing project mapping.
6. View report/blocker and audit.
7. Create a weekday and a weekend Planning Run, enter an OT override and check morning/afternoon capacity.
8. Try missing/wrong/late reports, email/GitLab conflicts and confirm the run is still created with warnings.
9. Quick Add from an existing item, form and paste; confirm every delivery assignment has a GitLab Issue.
10. Approve the Planning Run and check assignee/milestone/due date on the correct GitLab project.
11. Fault-inject a failing Issue update, confirm `PARTIAL`, separate retry and no rollback of Issues that succeeded.

## 6. Go/no-go

### Go

All MUSTs within the controlled pilot scope are `VERIFIED`, no P0/P1, backup/restore passes and the CTO signs Gate G.

### Conditional go

Applies only to SHOULD/P2 with a workaround, owner/deadline and written risk acceptance.

### No-go

Any possibility of leak/cross-project, loss of an accepted intake, duplicate external side effects, unscanned files going to the cloud, failed restore, or a requirement status reported higher than its evidence.
