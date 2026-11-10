English | [Tiếng Việt](BRD.vi.md)

# BRD - Private Feedback Intake

_Version 2.0 | Open source edition | Owner: CTO/Tech Lead_

This document describes the business goals. The actual implementation level is published separately in `PRODUCTION-READINESS.md` and reconciled against the code in `IMPLEMENTATION-INVENTORY.md`.

## 1. Context

A small software company both builds products and delivers projects for customers. Customer requests arrive through chat apps, email, and in-person meetings; the CTO spends most of each day reading, classifying, and tracking them.

Requests are usually discussed over chat/email before they become a specification. GitLab Issues are often created only after a bug has appeared. As a result, it is hard to trace where a request came from, requests are easily missed or duplicated, members have no unified queue, and progress reporting depends on the CTO compiling it by hand.

## 2. Business goals

### BR-BIZ-01 - Private intake portal

Centralize text, images, PDFs, and email reports in one self-hosted system, accessible only to the CTO in the initial phase.

### BR-BIZ-02 - Request normalization

The AI extracts the request type, summary, acceptance criteria, suggested priority, route, and missing information. The AI has no authority to make the final decision.

### BR-BIZ-03 - Separate internal work and delivery

- Intake manages ideas, features, discovery, BRDs, scope changes, and Internal tasks.
- GitLab/GitHub manage Issues, assignees, branches, Merge Requests/Pull Requests, CI, tests, and releases.
- Intake keeps the origin, approval, snapshot, sync status, and audit.

### BR-BIZ-04 - Reduce CTO workload

- Reduce the time spent manually classifying and tracking feedback.
- All work that starts development must have a GitLab Issue. P0 is prioritized through the emergency flow but must still create a minimal Issue before Planning approval.
- Daily/weekly reports must show completed volume, blockers, and pending decisions per project.

### BR-BIZ-05 - Prepare for AI Agent orchestration

Create structured, well-traced data so that a later phase can assign work to multiple AI Agents in the same GitLab repository. Multi-agent orchestration is outside the current implementation scope.

### BR-BIZ-06 - Daily Report into a delivery plan

Automatically read Daily Reports, reconcile with GitLab/GitHub, and create a morning/afternoon plan at 07:00 every day. The system still plans when reports are missing, late, or malformed; the CTO approves priority, assignee, milestone, and due date before Intake updates the delivery target.

## 3. Pilot scope

### In scope

- Multiple projects in parallel; the GitLab/GitHub delivery target is configured per project.
- Local account + MFA; only the CTO logs in to Intake.
- Manual intake from Zalo, WhatsApp, and meetings.
- Recording online meetings or uploading recording files, speech-to-text with speaker separation, AI-generated meeting notes, and turning items into Intakes (ADR-0018, ADR-0019).
- The CTO reviews and confirms Daily Reports before use; unfinished tasks in a report become candidates for the next day plan (ADR-0019).
- Read-only IMAPS for the report mailbox configured by the installer.
- End-of-day summary at 23:30, source refresh at 06:45, and Planning Run creation at 07:00 in `Asia/Ho_Chi_Minh`, including Saturday/Sunday.
- Weekday capacity defaults to 8 hours; weekends default to 0 hours, with OT only when the CTO enters an override. Available capacity excludes meetings, reviews, support, and other fixed activities.
- The Planning Run splits the plan into morning/afternoon, with a default limit of one main development task in `Doing` per person.
- Unified Quick Add from an existing item, a quick-entry form, or pasted source; delivery requests must have a GitLab Issue before the plan is approved. For P0, `Emergency Add` lets Intake immediately create a minimal Issue, with a reason and audit (ADR-0012).
- The CTO approves the Planning Run; approval creates an immutable snapshot and automatically enqueues updates to the GitLab Issue's assignee, milestone, and due date.
- Text, PDF, and images; at most 5 MB per file.
- Raw data retained for 90 days.
- Async queue, transactional outbox, pipeline status, and controlled retry.
- One primary AI provider through an adapter (OpenRouter or a compatible provider); changing providers only requires a configuration change.
- Intake runs on a dedicated Linux server, HTTPS with a valid TLS certificate, preferably behind a VPN.
- The CTO edits, approves, and syncs in two steps: `Approve` then `Sync`.
- Idempotent GitLab/GitHub adapter that stores the external link after successful creation.
- Daily backup; target RPO 24 hours, RTO 4 hours.

### Out of pilot scope

- Directly reading private Zalo/WhatsApp chats.
- Automatically sending email or replying to customers.
- Project Owner logging in to Intake.
- Project Owner approving Planning Runs; this permission opens only in a later phase and must be limited per project.
- Full two-way GitLab/GitHub sync.
- AI self-approving or creating work outside the system on its own.
- Multi-agent coding, review, and bug fixing.
- High availability or zero downtime.

## 4. Business principles

1. Raw source belongs to Intake.
2. Discovery and non-code work belong to Intake; delivery belongs to GitLab/GitHub.
3. AI only proposes; the CTO is responsible for decisions.
4. `Approve` locks the snapshot but does not create external data.
5. `Sync` only uses the approved snapshot; editing the payload invalidates the previous approval.
6. All business data must carry a `project_id`; no system-wide default project.
7. Do not put raw chat, phone numbers, personal email, or secrets into GitLab/GitHub.
8. Retry must not create duplicate external items.
9. Email is a source of reports/exceptions, not the sole source of progress percentage.
10. GitLab is the source of truth for delivery status.
11. When email and GitLab conflict, GitLab decides task, status, assignee, milestone, and due date; email adds time, next steps, blockers, risks, and support requests. Priority comes from the latest approved Planning snapshot, with the GitLab label as fallback (ADR-0013). Conflicts are always shown, never silently overwritten.
12. Missing, late, or malformed reports do not block the Planning Run.
13. Planning approval differs from intake approval: the CTO approving a Planning Run locks the snapshot and enqueues GitLab update jobs; retry must be idempotent, and a failure on one Issue does not roll back Issues already updated successfully.
14. Morning/afternoon details belong to Intake; GitLab only receives assignee, milestone, and due date as far as the API allows.

## 5. Roles

| Role | Responsibility in the pilot |
|---|---|
| CTO | Enter/check raw data, edit AI results, decide P0-P3, approve, sync, and resolve conflicts |
| Project member | Choose and update GitLab Issues; report blockers; no access to Intake |
| Project Owner | Coordinate scope and manage projects in Intake per granted permissions |
| AI worker | Normalize, propose, and record evidence; has no GitLab/GitHub write credentials |
| Integration worker | Only processes sync jobs from approved snapshots |

In the current phase, only the CTO approves Planning Runs and finalizes priority, assignee, milestone, and due date. The data model and authorization must be ready so that a later phase can grant Project Owner permissions per project; the CTO keeps override rights.

## 6. Success metrics

| ID | Pilot metric | Initial target |
|---|---|---|
| KPI-01 | Intakes not lost after API/Redis restart | 100% |
| KPI-02 | Sync retry does not create duplicate GitLab/GitHub Issues | 100% |
| KPI-03 | Dev work starts with a GitLab Issue | 100%, including P0 via the audited emergency flow |
| KPI-04 | AI results have a provider/model/prompt/schema trace | 100% |
| KPI-05 | Expired raw data is purged | Within 24 hours after the 90-day mark |
| KPI-06 | Restore from backup | RPO <= 24 hours, RTO <= 4 hours in a restore drill |
| KPI-07 | Data separation between projects | No cross-project leak in tests |
| KPI-08 | Planning Run on schedule | Created at 07:00 daily; report errors do not block the run |
| KPI-09 | Planning GitLab sync | Retry does not update twice; each Issue's status is traceable |
| KPI-10 | Capacity/WIP | No allocation over capacity or more than one main development task without a CTO override with a reason |

## 7. Completion criteria

The deployment is considered passing only when the mandatory requirements in the SRS are `VERIFIED`, no P0/P1 remain open, the restore drill meets its targets, and the CTO completes UAT for both the success path and controlled failure paths.
