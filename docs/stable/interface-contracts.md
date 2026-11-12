English | [Tiếng Việt](interface-contracts.vi.md)

# API and integration contracts

_Target + runtime contract 1.2 | Checked against OpenAPI on 2026-10-01_

Tables marked **runtime** list only endpoints that exist in OpenAPI. Target endpoints without code are in section 12; for verification status see `PRODUCTION-READINESS.md`.

## 1. Auth

| Method | Path | Access | Result |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Public; rate limit is a target, not yet implemented | Password and optional OTP/recovery; sets session + CSRF cookie, both valid for 7 days (`expires_in` = 604800; `ACCESS_TOKEN_TTL_MINUTES`, FR-ID-09) |
| POST | `/api/v1/auth/password-reset/request` | Public; rate limit per IP and cooldown per account | Accepts username or email; always returns 202 with a notice. If an active account exists, sends a one-time Mailgun link; no account enumeration leak |
| POST | `/api/v1/auth/password-reset/confirm` | Public + reset token | Accepts the token and a new password of ≥8 characters; the token is stored hashed, expires in 30 minutes, single use; increments `auth_version` to invalidate old cookies |
| POST | `/api/v1/auth/logout` | Authenticated | Clears session/CSRF cookie; persistent server-side revocation is a target |
| GET | `/api/v1/auth/me` | Authenticated | Role-safe identity |
| POST | `/api/v1/auth/mfa/setup` | Authenticated + step-up | Accepts the current password, and the current OTP when MFA is already on; creates a 10-minute pending secret without changing the active factor |
| POST | `/api/v1/auth/mfa/confirm` | Authenticated | Confirms the pending TOTP, swaps the factor atomically, increments `auth_version`, revokes old personal tokens and reissues cookies for the browser that just verified |
| POST | `/api/v1/auth/mfa/recovery-codes` | Authenticated + MFA on + step-up | Accepts the current password and OTP; rotates the hashed recovery codes |

### Per-project access (ADR-0022)

- `GET /auth/me` returns `role`, `project_ids` (`null` for the CTO, a list for a Project Owner) and `must_change_password`. When `must_change_password` is true, every business API returns 403 `PASSWORD_CHANGE_REQUIRED` until `POST /auth/password` is called.
- A Project Owner who calls a resource of a project they were not granted gets 404, as if it did not exist. Lists (`/intakes`, `/approvals`, `/meetings`, `/projects`) and the `summary` part count only within scope.
- CTO only: `/users`, `/reports/*`, `/planning/*`, `/operations/*`, `POST`/`PATCH /projects`, `/projects/integration-probes`, shared glossary.
- `PUT /projects/{code}/team` accepts `owner_member_id` (or null) and `member_ids`; the Owner is added to Member automatically. When choosing the Owner creates or reopens an account, the response has `issued` with the username and `temporary_password`, exactly once. Errors: `OWNER_EMAIL_REQUIRED`, `MEMBER_NOT_ACTIVE`. If the Owner is the CTO's member profile, `issued` is `null`, no account is created and no extra access is granted (FR-PLAN-37).
- `POST /users/{id}/reset-password` also returns `temporary_password` once. `POST /users` and `PATCH /users/{id}` refuse project assignment (`PROJECTS_ASSIGNED_ON_PROJECT`).

## 2. Project catalog

Runtime has only `GET /api/v1/projects` for the CTO. Projects and integration mappings are currently seeded/configured through the environment; the CRUD/test API is a target, not yet implemented.

From 2026-10-05 (ADR-0020), CTO only:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/projects` | List with `kind`, GitLab/GitHub link and sync enabled state; does not return Plane configuration |
| POST | `/api/v1/projects` | `name`, `code` (lowercase, digits, hyphens), `intake_key` (2-8 uppercase letters), `kind`; a software project accepts a probed GitLab or GitHub. Plane configuration fields are rejected with `422`. |
| PATCH | `/api/v1/projects/{code}` | Rename, change kind, status or add a link; the same per-kind rules apply. CTO only: `switch_delivery: "GITHUB"` with a verified `github_repository`, `github_token_ref`, `github_probe_id` moves a GitLab project to GitHub for new work; `422 DELIVERY_SWITCH_NOT_APPLICABLE` when the project is not a software project currently linked to GitLab or already has GitHub, `GITHUB_LINK_REQUIRED`, `GITHUB_LINK_NOT_VERIFIED`, `DELIVERY_SYSTEM_CONFLICT` when GitLab is sent too. `ProjectOut.previous_delivery { system, project_external_id, project_url, switched_at }` after the switch (FR-PRJ-13, ADR-0079) |
| GET | `/api/v1/projects/{code}/delivery-switch` | CTO only. `{ from_system: "GITLAB", to_system: "GITHUB", open_issues }` before the switch; `422 DELIVERY_SWITCH_NOT_APPLICABLE`, `404` when the project does not exist (FR-PRJ-13) |
| GET | `/api/v1/projects/{ref}/context` | CTO or the project's Project Owner. The context pack as of the latest read: `{ project_id, source (REPO|PASTED), path, sha, fetched_at, meta, sections{key: {number, title, required, to_ai, present, lines}}, score, band (FULL|PARTIAL|MISSING), missing[], stale_days, error, has_content, approved, approved_sha, approved_at, content, pending_suggestions }`; if none yet, `band MISSING` with 6 sections missing (FR-CTX-03, FR-CTX-04) |
| POST | `/api/v1/projects/{ref}/context/read` | `202 { project_id, queued }`; `422 NO_MAIN_REPO` when the project has no enabled GitLab/GitHub (FR-CTX-03) |
| PUT | `/api/v1/projects/{ref}/context` | `{ content }` up to 60 KB; saved as a `PASTED` version, scored, not approved (FR-CTX-03) |
| POST | `/api/v1/projects/{ref}/context/approve` | CTO only; `422 CONTEXT_EMPTY` when there is no pack yet (FR-CTX-03) |
| GET | `/api/v1/projects/{ref}/context/suggestions` | CTO or the project's Project Owner. Suggestions for the pack, newest first: `[{ id, project_id, intake_id, intake_public_id, work_log_id, text, suggested_by, suggested_by_name, agent_name, status (PENDING|APPLIED|DISMISSED), decided_by, decided_by_name, decided_at, created_at }]` (FR-CTX-04) |
| POST | `/api/v1/projects/{ref}/context/suggestions/{id}/{applied\|dismissed}` | CTO only; `409 ALREADY_DECIDED` when already decided, `422 DECISION_UNKNOWN` for any other word, 404 when the suggestion does not belong to the project (FR-CTX-04) |
| POST | `/api/v1/mcp-server` (added in ADR-0063) | Tool `get_project_context {project}` → `{project, band, score, missing[], approved, source, sha, fetched_at, sections{key: {number, title, required, present, lines}}, content, pending_suggestions, note}`; `list_projects` also returns `context_band`; `log_work` accepts `context_suggestions[]` and returns `context_suggestions` (the number of suggestions recorded) (FR-CTX-04) |
| GET | `/api/v1/agent-commands/files/context-template.md` | Public, the pack template (FR-CTX-01) |
| GET, PUT | `/api/v1/projects/{ref}/report-codes` | `{ codes: string[] }` (up to 20, stored uppercase, deduplicated). CTO or the project's Project Owner; `409 REPORT_CODE_TAKEN` when the code is already the main code or an alias of another project. Report emails with that code are assigned to this project (FR-EML-12) |
| POST | `/api/v1/projects/integration-probes` | `system=GITLAB|GITHUB`, `action`, `reference`; returns 202 with a `PENDING` probe. `PLANE` is rejected with `422`. `action=ACCESS` (FR-INTG-23) also accepts `token_ref` for GitHub, `reference` optional for GitLab; result `{system, ok, checks:[{key, status, detail}]}`, `status` is `OK|MISSING|WARN|UNKNOWN`. A GitHub `issues_write` `MISSING` may carry a `detail` cause code `public_read_only`, `read_only` or `org_policy`; a `metadata` `MISSING` carries `org_policy` or the repo name. |
| GET | `/api/v1/projects/integration-probes/{id}` | The client polls until `DONE` or `FAILED` |

`action=MEMBERS` (GitLab only, `reference` is the project path) returns the project's active users (`id`, `name`, `username`) to map to members. `PUT /api/v1/planning/members/{id}` replaces all of a member's information and project list; a project that is removed only switches to `active=false`; `gitlab_user_external_id` is valid only for a `SOFTWARE` project.

GitHub (ADR-0021): the probe accepts `system=GITHUB` with `token_ref` as the token variable name; `action=TOKENS` returns the names of the `GITHUB_TOKEN_*` variables the integration worker has (never the values); `MEMBERS` returns the people who can be assigned Issues. `POST`/`PATCH /projects` accept `github_repository`, `github_token_ref`, `github_probe_id`; sending both GitLab and GitHub returns `DELIVERY_SYSTEM_CONFLICT`. An Intake's `approved_route` also accepts `GITHUB`; on approval, `GITLAB` and `GITHUB` are switched to match the project's delivery system.

Probes are handled by the integration worker through the `intake.integration.probe` task, not through the outbox. A link is saved only together with the ID of a successful `CHECK` probe for the same reference within 30 minutes.

## 3. Intake

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/intakes` | Creates intake + source; supports `Idempotency-Key`. `channel` adds `FEEDBACK` (created only by "Accept" ("Nhận") on a feedback item, FR-FBK-03) |
| POST | `/api/v1/feedback` | All roles. `{ project, text }` → `201 FeedbackOut { id, project_id, project_code, project_name, member_id, member_name, user_id, transport (WEB\|TELEGRAM\|AGENT), text, status (PENDING\|ACCEPTED\|REJECTED), intake_id, intake_public_id, decided_by, decided_by_name, decided_at, decision_note, files[{id, name, mime_type, size_bytes}], created_at }`; the project must be one of the current account's member projects or a project they manage (otherwise 404); a Developer not mapped to a member gets `422 MEMBER_UNMAPPED`; `422 TEXT_REQUIRED` (FR-FBK-01, ADR-0064) |
| GET | `/api/v1/auth/me` | Adds `member_id` (the member linked to the account, or `null`) (FR-FBK-02) |
| POST | `/api/v1/feedback/{id}/files` | Multipart `file`, image or PDF 5 MB, up to 3 (`422 TOO_MANY_FILES`); only while still `PENDING` (`409 ALREADY_DECIDED`) (FR-FBK-01) |
| GET | `/api/v1/feedback` | `project_id?`, `status?`, `mine?`, `limit?`; `mine=true` returns your own feedback across all projects, otherwise feedback for the projects you manage; a Developer always sees only their own (FR-FBK-02) |
| GET | `/api/v1/feedback/{id}`, `/api/v1/feedback/{id}/files/{file_id}` | One feedback item; files return bytes `inline` (FR-FBK-02) |
| POST | `/api/v1/feedback/{id}/accept` | CTO or Project Owner (`403` for a Developer). `{ note? }` → an Intake in channel `FEEDBACK` is created, `intake_id`, `intake_public_id`; `409 ALREADY_DECIDED` (FR-FBK-03) |
| POST | `/api/v1/feedback/{id}/reject` | `{ note }` required (`422 NOTE_REQUIRED`); `409 ALREADY_DECIDED` (FR-FBK-03) |
| GET | `/api/v1/work` | `?project=<code or id>` required, `?include_closed=`; the project's internal tasks board (ADR-0066, FR-WRK-02) within the caller's project scope (CTO, Project Owner, project members; out of scope `404`). Each row `WorkOut { id, code, project_id, project_code, project_name, project_kind, title, description, status: DISCUSS\|READY\|IN_PROGRESS\|ACCEPTANCE\|DONE\|CANCELLED, priority, member_id, member_name, due_date, intake_id, intake_public_id, intake_status, issue_system, issue_external_id, issue_url, outcome: null\|ISSUE_PENDING\|ISSUE, issue_pending, closed_note, comment_count, version, created_by, created_by_name, created_at, updated_at, closed_at }` |
| POST | `/api/v1/work` | CTO or Project Owner. `{ project, title, description?, priority?=P3, member_id?, due_date?, status?=DISCUSS }` → `201 WorkOut`; `422 TITLE_REQUIRED\|MEMBER_NOT_IN_PROJECT\|STATUS_INVALID` (FR-WRK-01) |
| GET | `/api/v1/work/{id}` | `WorkDetail = WorkOut + comments[{ id, user_id, user_name, mine, body, created_at }] + history[{ at, actor_name, event_type, details }]` (FR-WRK-02) |
| PATCH | `/api/v1/work/{id}` | CTO or Project Owner. `{ expected_version, title?, description?, priority?, member_id?, clear_member?, due_date?, clear_due? }`; `409 STALE_VERSION\|WORK_CLOSED` (FR-WRK-01) |
| POST | `/api/v1/work/{id}/move` | `{ status, expected_version, note? }`; a Developer only on tasks assigned to them (`403 NOT_YOUR_WORK`) between DISCUSS/READY/IN_PROGRESS/ACCEPTANCE (`422 MOVE_NOT_ALLOWED`); `422 NOTE_REQUIRED` when moving to CANCELLED; `409 STALE_VERSION\|WORK_LOCKED_BY_ISSUE` (FR-WRK-03) |
| POST | `/api/v1/work/{id}/comments` | `{ body }` (2..5000) → `201 WorkDetail` (FR-WRK-04) |
| DELETE | `/api/v1/work/{id}/comments/{comment_id}` | Your own, or the CTO; `403 NOT_YOURS`; `204` (FR-WRK-04) |
| POST | `/api/v1/work` (added in FR-WRK-08) | `template?: VIDEO` also creates six steps as child tasks; `WorkOut` adds `template, steps_total, steps_done, parent_id, parent_code, step, step_label, step_order, evidence_required`; `WorkDetail.steps[]` on the parent task; `GET /work` returns the parent's steps on the board too |
| POST | `/api/v1/work/{id}/move` (added in FR-WRK-09) | `422 EVIDENCE_REQUIRED` (the step needs a link or a `note`), `422 NOTE_REQUIRED` when sending back from ACCEPTANCE, `409 STEPS_OPEN` when the parent task still has open steps |
| GET | `/api/v1/auth/me` (added in ADR-0067) | The caller's `projects[{ id, code, name, kind }]` and `mode: MARKETING\|FULL` (FR-MKT-03) |
| GET | `/api/v1/work` (added) | `?week=YYYY-MM-DD` (a Monday) also includes every post with a channel version publishing in that week (FR-MKT-04). `WorkOut` adds `channel, format, campaign, urgent, channels[{ id, channel, publish_at, status: DRAFT\|READY\|PUBLISHED, published_url, language }], next_publish_at`; `WorkStatus` adds `APPROVED` |
| POST | `/api/v1/work` (added) | `channel?, format?, campaign?, urgent?, channels[{ channel, publish_at?, language? }]` (FR-MKT-01); `PATCH /work/{id}` adds `channel, format, campaign, clear_campaign, urgent` |
| POST, PATCH, DELETE | `/api/v1/work/{id}/channels[/{channel_id}]` | Channel versions: add (`422 CHANNEL_UNKNOWN\|CHANNEL_EXISTS`), edit `{ publish_at?, clear_publish?, status?, published_url? }` (a Developer only on their own posts, cannot change the date; `422 URL_INVALID`), remove (`409 CHANNEL_PUBLISHED`) (FR-MKT-01) |
| GET | `/api/v1/work/review` | CTO, Project Owner: posts in `ACCEPTANCE` in the projects they manage (FR-MKT-05) |
| GET | `/api/v1/work/campaigns` | `?project=` → `[{ name, count }]` (FR-MKT-06) |
| POST | `/api/v1/work/bulk` | CTO, PO. `{ project, rows[{ title, channel?, publish_at?, member_id?, campaign?, description? }] }` (1..50) → `201 [{ title, id?, code?, error? }]` (FR-MKT-06) |
| POST | `/api/v1/work/bulk-update` | CTO, PO. `{ ids (1..100), member_id?, clear_member?, publish_at?, status? }` → `{ changed, errors[{ id, error }] }` (FR-MKT-06) |
| GET, PUT | `/api/v1/channel-rules[/{code}]` | Read: all roles; edit: CTO, `ChannelRuleUpdate` with the rule's fields, `422 RULE_VALUE_INVALID`, `404` (FR-MKT-02) |
| POST | `/api/v1/meetings/{id}/note/items/work` (added) | each item accepts `channel?`, `publish_at?`; a `NON_CODE` project creates the post in Idea ("Ý tưởng") with default channel versions (FR-MKT-07) |
| PATCH | `/api/v1/work/{id}/channels/{channel_id}` (added) | `text?` (up to 60,000), `clear_text?`; `WorkChannelOut` adds `text`, `short_link { code, url, target_url, clicks, created_at }`. Submitting for review (`/move` to `ACCEPTANCE`) returns `422 CHANNEL_TEXT_TOO_LONG` when a version exceeds the channel's length limit (FR-MKT-11) |
| POST | `/api/v1/work/{id}/channels/{channel_id}/link` | CTO, PO. `{ target_url }` → `PostLinkOut`; the code stays the same on repeated calls; `422 TARGET_INVALID` (FR-MKT-12) |
| GET | `/p/{code}` and `/api/v1/p/{code}` | No login, no envelope: `302` to the target page with UTM, records the click; `404` for an unknown code (FR-MKT-12) |
| GET, PUT | `/api/v1/projects/{code}/watch/pillars` | CTO, PO of a `NON_CODE` project (`409 WATCH_NOT_FOR_PROJECT` for other projects, `403` Developer). PUT `{ pillars[{ name, description?, audience?, channels[], share_pct, keywords[{text, kind, priority} \| string], samples[{title?, url}], avoid? }] }` (up to 6; `422 PILLARS_TOO_MANY`, `PILLAR_DUPLICATE`) (FR-MKT-08) |
| GET, PUT | `/api/v1/projects/{code}/watch/settings` | `{ networks?, times?, weekdays?, scan_every_hours? }` → `{ networks, open_networks, schedule{times, weekdays}, scan_every_hours, scan_hours, max_ai_runs_per_day, ai_runs_per_week }`; `422 NETWORK_NOT_OPEN`, `SCHEDULE_INVALID` (FR-MKT-08, FR-MKT-10) |
| GET, POST, PATCH, DELETE | `/api/v1/projects/{code}/watch/sources[/{id}]` | Like `/private-space/watch/sources`, stream always `content` (FR-MKT-08) |
| GET, PUT, POST | `/api/v1/projects/{code}/watch/keywords[/suggest]`, `GET, PUT …/demand`, `GET …/health`, `POST …/health/check` | Like the Private Space paths, for the project's `content` stream (FR-MKT-08) |
| GET | `/api/v1/watch-topics?project=` | All roles in the project. `{ week_start, has_sources, kept_this_week, refresh_left, built_at, schedule, topics[{ id, title, why, angles[], channels[], caution, pillar, score, state, ai_written, work_id, sources, signals[{ id, title, url, host, keyword, published_at, via }] }] }` (FR-MKT-09) |
| POST | `/api/v1/watch-topics/refresh?project=` | CTO, PO. `202 { status: PENDING, refresh_left }`; `429 TOPICS_LIMIT` after 3 times a day (FR-MKT-10) |
| POST | `/api/v1/watch-topics/{id}/post?project=` | CTO, PO. `{ mode: post \| series, angle?, member_id?, week? }` → `201 WorkDetail`; `409 TOPIC_CLOSED` (FR-MKT-09) |
| DELETE | `/api/v1/watch-topics/{id}?project=` | CTO, PO. Removes the topic and its signals (FR-MKT-09) |
| GET, PUT | `/api/v1/settings/watch-platforms[/{code}]` | Read: all roles; edit: CTO `{ label?, enabled?, via?, note? }`, `422 PLATFORM_VALUE_INVALID` (FR-MKT-08) |
| GET, PUT | `/api/v1/settings/watch-limits` | Read: all roles; edit: CTO `{ max_ai_runs_per_day 0..8 }` (FR-MKT-10) |
| POST | `/api/v1/watch/inbound/{connector_id}` | No login. `X-Intake-Token: <bí mật cổng>` (connector secret) or Bearer; JSON ≤ 512 KB, ≤ 50 items; `404` unknown or closed connector, `401` wrong secret, `413`, `422 BATCH_INVALID`; returns `{ accepted, duplicates, rejected[], problems[] }` (FR-MKT-13) |
| GET, POST | `/api/v1/settings/watch-connectors?project=` | CTO only. Create `{ project, name, kind?, via?, default_pillar?, mapping? }` → `201 ConnectorOut` with a one-time `token`; `409 CONNECTORS_FULL`, `422 PILLAR_UNKNOWN\|MAPPING_INVALID` (FR-MKT-13) |
| PATCH, DELETE, POST | `/api/v1/settings/watch-connectors/{id}[/rotate\|/try]`, `GET …/{id}/deliveries`, `GET …/presets` | CTO only. `try` accepts any JSON payload → `{ items[{…, would_reject[], notes[]}], problems[], would_accept }`, nothing saved (FR-MKT-13) |
| GET | `/api/v1/projects/{code}/watch/connectors` | CTO, PO: `[{ id, name, kind, enabled, last_received_at, received_count, last_status }]` (FR-MKT-13) |
| GET | `/api/v1/publish/queue` (added) | Items `kind: post_version` with `draft_id: work_channel:<id>`, `project`, `work`, `language`, `short_link` for Approved ("Đã duyệt") and Ready ("Sẵn sàng") versions on channels with `auto_publish` on (FR-MKT-14) |
| POST | `/api/v1/publish/events` (added) | `draft_id` of the form `work_channel:<id>`: `POSTED` with `url` → version `PUBLISHED`; `FAILED` writes an audit entry; `404 DRAFT_NOT_FOUND`, `409 DRAFT_NOT_APPROVED` (FR-MKT-14) |
| GET, PUT | `/api/v1/settings/publish-pause` | Read: all roles; edit: CTO `{ paused }` (FR-MKT-14) |
| PUT | `/api/v1/channel-rules/{code}` (added) | `auto_publish?` (FR-MKT-14) |
| POST | `/api/v1/meetings/{id}/note/items/work` | CTO or Project Owner of the meeting's project. `{ items[{ item_id, member_id?, due_date?, status?: DISCUSS\|READY }] }` (1..50) → `201 { results[{ item_id, work_id, code, intake_id, error }], meeting }`; for each item: an Intake in channel MEETING is created and approved on route WORK with source MEETING, and the task gets its assignee, due date and column (FR-REC-19). `MeetingNoteItemOut` adds `work_id`, `work_code`, `can_become_work`; `WorkOut` adds `meeting_id`, `meeting_title`, `meeting_at` |
| GET | `/api/v1/hints` | All roles. `{ dismissed: string[] }`: the page intros the caller has clicked "Got it" ("Đã hiểu") on (FR-UI-17) |
| POST, DELETE | `/api/v1/hints/{key}/dismiss` | Records or removes "Got it" for `key` (`page.work`, `page.my_day`, `page.feedback`, `page.account`); `422 HINT_KEY_INVALID` (FR-UI-17) |
| POST | `/api/v1/hints/{key}/opened` | One hint open, `204`; counted for statistics (FR-UI-17) |
| GET | `/api/v1/hints/stats` | CTO only. `?days=` (1..90, default 7) → `{ days, since, opened[{ key, opens, people }], dismissed[{ key, people }] }` (FR-UI-17) |
| (page) | `/huong-dan` | Not logged in: the public guide page; only the app's existing session check, no call to `/hints` or any data API. Logged in: the in-app version, calls the three `hints` endpoints above. A static copy with the same content is on the public repo's GitHub Pages; `?lang=en\|vi` (FR-UI-18, ADR-0078) |
| POST | `/api/v1/work/{id}/links` | Anyone who can see the task. `{ url, note? }` → `201 WorkDetail` with `links[{ id, url, note, source: USER\|AGENT, added_by, added_by_name, mine, created_at }]`; `422 URL_INVALID\|TOO_MANY_LINKS` (FR-WRK-07). `WorkOut` adds `link_count` |
| DELETE | `/api/v1/work/{id}/links/{link_id}` | Your own, or the CTO; `403 NOT_YOURS`; `204` (FR-WRK-07) |
| POST | `/api/v1/work/{id}/links/file` | Anyone who can see the task. `multipart/form-data`: `file` (JPG, PNG, WebP or PDF, ≤ 5 MB, magic bytes matching `content-type`) and `note?` ≤ 300 characters → `201 WorkDetail`; the link row also has `file_name`, `mime_type`, `size_bytes`, and `url` is the download path. `422 FILE_TYPE_UNSUPPORTED\|FILE_TYPE_MISMATCH\|FILE_TOO_LARGE\|FILE_EMPTY\|TOO_MANY_LINKS` (FR-WRK-10) |
| GET | `/api/v1/work/{id}/links/{link_id}/file` | Anyone who can see the task. Returns the file with `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`; `404` when the link has no file (FR-WRK-10) |
| POST | `/api/v1/mcp-server` (added in FR-MCP-08) | Tools `list_work`, `get_work`, `create_work` (not for Developers), `move_work`, `comment_work`, `attach_link`; prompt `content_day`; command file `/in-content-day` at `agent-commands/files/in-content-day.md` |
| POST | `/api/v1/mcp-server` (added in FR-MCP-09) | Marketing project tools: `hot_topics`, `trending`, `get_pillars`, `week_plan`, `review_queue`, `set_channel_text` (all roles in the project); `topic_to_post`, `dismiss_topic`, `refresh_topics`, `get_short_link`, `add_signals` (not for Developers); prompts `hot_topics`, `draft_post`; command files `in-hot-topics.md`, `in-draft-post.md` |
| POST | `/api/v1/work/{id}/issue` | CTO or Project Owner, SOFTWARE project with sync enabled. Re-decides the original request to GitLab/GitHub (or creates a new request) and queues the sync; returns `WorkDetail` with `issue_pending=true`; `422 PROJECT_NOT_SOFTWARE\|DELIVERY_SYNC_DISABLED\|INTAKE_NOT_READY`, `409 WORK_CLOSED` (FR-WRK-05) |
| GET | `/api/v1/intakes/{id}/github-issue-link` | A prefilled Issue creation link on GitHub, built only from normalized content (FR-INTG-20). Returns `url`, `repository`, `host`, `shortened`. 422 errors: `NOT_NORMALIZED`, `NO_REPOSITORY`; 404 when out of scope |
| GET/PUT | `/api/v1/integrations/github-tokens` | CTO only (FR-INTG-21). GET returns `[{name, key_hint, used_by_projects, updated_at}]`; PUT accepts `{label, token}`, `label` is converted to `GITHUB_TOKEN_<TÊN>`; the token value is never returned. 422 errors: `NAME_INVALID`, `TOKEN_INVALID`. |
| DELETE | `/api/v1/integrations/github-tokens/{name}` | CTO only. 204; 404 `NOT_FOUND`; 409 `TOKEN_IN_USE` when an enabled project still uses the token. |
| GET/PUT | `/api/v1/integrations/gitlab-connection` | CTO only (FR-INTG-22). Returns `{configured, source: APP|ENV|NONE, base_url, key_hint, updated_at, linked_projects}`; PUT accepts `{base_url, token?}` (leave `token` empty to keep the old token) and also returns `projects_enabled`. The token value is never returned. 422 errors: `GITLAB_BASE_URL_INVALID`, `TOKEN_INVALID`, `TOKEN_REQUIRED`. |
| DELETE | `/api/v1/integrations/gitlab-connection` | CTO only. 204, falls back to `GITLAB_TOKEN` in `.env` if present; 404 `NOT_FOUND` when nothing is saved. |
| POST | `/api/v1/intakes/{id}/approve` (added in ADR-0066) | `approved_route` accepts `WORK`; returns `IntakeOut.work_item { id, code, status, project_id }` when approved on this route. `PLANE` remains valid only for requests decided earlier. `GET /intakes/{id}/journey` adds `work_item` in the same shape; `GET /intakes/{id}/sync-status` returns `target_system=null` for non-syncing routes (FR-WRK-06) |
| POST | `/api/v1/acceptance/{id}/evidence` | CTO or the project's Project Owner. `{ links: [{ kind?: COMMIT\|MR\|LINK, url?, ref?, note? }] }` (1..10) → the acceptance card with `evidence_links[{id, kind, url, ref, note, source, added_by_name, created_at}]` and `evidence_check {work (CODE\|OTHER\|UNKNOWN), status (OK\|WEAK\|MISSING), why}`; `422 EVIDENCE_URL_INVALID`, `422 EVIDENCE_WRONG_REPO` (FR-PLAN-36) |
| POST | `/api/v1/acceptance/{id}/accept` | Adds `evidence_missing_reason?`: required when `evidence_check.status` is not `OK` (`422 EVIDENCE_REASON_REQUIRED`); the card returns `evidence_missing_reason` (FR-PLAN-36) |
| PATCH | `/api/v1/planning/runs/{run}/assignments/{id}/work-status` | Adds `evidence[]` in the same shape; written to the task's Issue with source `WORKER`; also returns `evidence_added` (FR-PLAN-36) |
| POST | `/api/v1/mcp-server` (added in ADR-0065) | `update_work_status` accepts `evidence[{kind, url, ref, note}]`; `log_work.commit` automatically becomes `WORK_LOG` evidence for the Issue linked to the request (FR-PLAN-36) |
| GET | `/api/v1/planning/week/{...}` | `projects[].done` adds `accepted_without_evidence` (FR-PLAN-36) |
| POST | `/api/v1/mcp-server` (added in ADR-0064) | Tool `suggest_intake {project, text, idempotency_key, attachments?}` → `{feedback_id, project, status, created, files, note}`; errors `MEMBER_UNMAPPED`, `PROJECT_NOT_FOUND`, `TEXT_REQUIRED`. `tools/list` does not list `create_intake` for a Developer token (FR-FBK-01) |
| GET | `/api/v1/intakes` | Keyset cursor; limit up to 100; project/stage/status/priority/target/channel/time/search filters. `stage` accepts `RECEIVED`, `NEEDS_INFORMATION`, `PENDING_APPROVAL`, `WAITING_PLANNING`, `IN_PROGRESS`, `PENDING_ACCEPTANCE`, `ACCEPTED`, `STOPPED`; raw `status` is still accepted for compatibility. |
| GET | `/api/v1/intakes/{id}` | Detail does not return raw ciphertext by itself. `IntakeOut.lifecycle_stage` uses the same derivation as list/filter from the Intake, Work, Planning and `IssueVerification` states; an approved direct reply, Work `DONE`, an Issue accepted by the CTO or confirmed done by the Project Owner are all `ACCEPTED`. The CTO's template decision and tracker close write remain independent. |
| GET | `/api/v1/intakes/{id}/raw` | CTO-only + audit. From FR-AI-14 also returns `attachments[{id, index, name, mime_type, size_bytes, ocr_status, ocr_error, ocr_at, page_count, pages_read, text}]` (`text` is the text read from the image) |
| POST | `/api/v1/intakes/{id}/attachments` | Multipart, 5 MB/file; `415 ATTACHMENT_TYPE_MISMATCH` when the magic bytes do not match the declared type. Also returns `ocr_status`. If the request is already normalized, the file is read in the worker and the request is then normalized again (FR-AI-14) |
| GET | `/api/v1/intakes/{id}/attachments` | CTO or the project's Project Owner. List of files and read status (`ocr_status` NONE, RUNNING, RETRY, DONE, FAILED, REJECTED, SKIPPED; `ocr_error` an error code or `PARTIAL`), without the text (FR-AI-14) |
| GET | `/api/v1/intakes/{id}/attachments/{aid}/file` | CTO or the project's Project Owner. Returns bytes with the verified MIME and `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`; the UI uses a fetch with cookies and an object URL to preview images in the app (FR-AI-14) |
| POST | `/api/v1/intakes/{id}/attachments/{aid}/read` | `202 { id, queued }`. Resets the file to unread and queues a re-read; `queued=false` when there is no broker (FR-AI-14) |
| POST | `/api/v1/intakes/{id}/process` | `202`, idempotent job |
| GET | `/api/v1/intakes/{id}/pipeline` | Redacted runs/stages/errors |
| PATCH | `/api/v1/intakes/{id}/review` | Edit normalized payload + expected version |
| POST | `/api/v1/intakes/{id}/approve` | Only after normalized review; creates a snapshot |
| POST | `/api/v1/intakes/{id}/reject` | Reason required |
| POST | `/api/v1/intakes/{id}/defer` | Future datetime |
| POST | `/api/v1/intakes/{id}/needs-information` | Question list |

## 4. Approval and sync

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/approvals` | Queue with pagination/project filter. Each row has `approval_owner` (`CTO`/`PO`) and `approval_overdue`; `?owner=CTO|PO` filters within the page already read (FR-APR-14) |
| GET | `/api/v1/approvals/decisions` | History of decisions on requests (FR-APR-15), newest first, within the caller's project scope: `?days=` (default 7, 1 to 365), `?before=<timestamp>` reads backward (ignores `days`), `?project_id=` (code or id), `?limit=` (default 50, max 200). Returns `{ items[], next_before, since }`; each row `{ id, at, action: APPROVED|REJECTED|DEFERRED|NEEDS_INFORMATION|REOPENED, source: QUEUE|PLANNING, actor_id, actor_name, reason, intake_id, public_id, title, status, project_id, project_code, project_name, approved_route, approved_priority }` |
| GET | `/api/v1/intakes/{id}/sync-status` | Current snapshot/job and target status |
| POST | `/api/v1/approval-snapshots/{id}/sync` | Target must match the approved route |

## 5. Create intake request

```json
{
  "project_id": "uuid",
  "channel": "ZALO",
  "raw_text": "Nội dung nguồn",
  "received_at": "2026-09-30T08:00:00Z"
}
```

The response does not echo the raw text. File upload is a separate request attached to the intake/source.

Every JSON success response under `/api/v1` is wrapped in `success`, `data`, `request_id`. Intake/Approval lists put `items`, `next_cursor`, `limit` inside `data`. The Intake list also returns `summary.total_items`, `p0_attention`, `p1_attention`, `pending_approval`, `sync_failed`; the attention counts are scoped by `project_id` if a project filter is sent. Each Intake returns `sync_targets[]` with the latest status, external ID and URL per target, plus `superseded` (a sync belonging to a decision that was withdrawn, FR-APR-10).

## 6. Approval request

Precondition: the item is in `PENDING_APPROVAL` after the normalized review has been saved. If not, the API returns `409 REVIEW_REQUIRED` and creates no snapshot/outbox.

```json
{
  "expected_version": 4,
  "approved_route": "GITLAB",
  "approved_priority": "P1",
  "reason": "Ready for delivery"
}
```

The normalized title/summary/priority proposal/route must be saved first with `PATCH /intakes/{id}/review`; the approval request does not accept an arbitrary payload. The server builds the snapshot from the current item and adds the Intake ID, project reference, actor and payload hash itself.

## 7. Plane · history

Plane no longer has an adapter, configuration, probe, worker or write operation. Old decisions, sync jobs and external links are still returned by the API in read-only mode with the label `Plane · lịch sử` (Plane · history); new sync requests return `ROUTE_RETIRED`.

## 8. GitLab adapter

| Intake | GitLab Issue |
|---|---|
| Approved title | Title |
| Sanitized summary/evidence | Description |
| Acceptance criteria | Checklist |
| Approved priority/type | Labels |
| Intake ID | Traceability section |
| Project mapping | GitLab project ID/path |

Minimum token scope. If the instance does not support an idempotency header, use a stable marker and look it up in the project before a create retry.

### GitLab label contract

Intake sends only three labels from a fixed allowlist:

- `source:intake`;
- exactly one `priority:p0|p1|p2|p3`, taken from the CTO's approved decision;
- exactly one `type:bug|feature|task|tech-debt`, mapped from the normalized `item_type`.

`FEATURE` and `SCOPE_CHANGE` map to `type:feature`; `TASK`, `FEEDBACK`, `QUESTION` and `UNCLEAR` map to `type:task`. Priority/type values outside the allowlist must fail closed before GitLab is called. Intake does not accept free-form label names from the AI because the GitLab Issues API can create labels that do not exist yet.

## 8A. GitHub adapter (ADR-0021)

- Base `https://api.github.com`, header `Authorization: Bearer <token của dự án>` (the project's token), `X-GitHub-Api-Version: 2022-11-28`.
- Create Issue: `POST /repos/{owner}/{repo}/issues` with only `title` and `body`; `body` is the approved description plus a hidden comment `<!-- {INTEGRATION_MARKER_PREFIX}:MÃ -->` (environment variable, default `intake`; where Issues already exist, keep the old prefix so they are recognized again). No labels, assignees or milestones are sent.
- Idempotency: before creating, look for the hidden comment in the 100 most recently created Issues (`GET /repos/{owner}/{repo}/issues?state=all&sort=created`).
- Reading for Planning: `GET /repos/{owner}/{repo}/issues?state=all` with pagination, skipping items that have `pull_request`.
- No other write calls: approving a Planning Run does not update the Issue on GitHub.
- Errors: 401/403 is `GITHUB_AUTH_FAILED`, 404 is `GITHUB_MAPPING_NOT_FOUND`, 429 or quota exhausted is a transient error and is retried.

## 9. IMAPS contract

- TLS, hostname verification and certificate validation are mandatory.
- The checkpoint consists of mailbox, UIDVALIDITY and last UID.
- A UIDVALIDITY change must be reconciled, not silently re-ingested.
- Parse limits for body/attachments; emails over the limit are recorded with a needs-handling status.
- No SMTP sending.

The Daily Report API serves backfill/internal verification, CTO only:

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/reports/daily/ingest` | Idempotent ingest by mailbox + UIDVALIDITY + UID; raw subject/body are encrypted |
| GET | `/api/v1/reports/daily` | Filter by `report_date` and `member_id`; by default returns only the current revision. Project Owner: only emails from team members who have at least one task they can see; `item_count`, `unlinked_items` count the part they see; adds `hidden_items`, `can_review` (FR-ID-08). Each row has `unlinked_items`; each task's detail has `issue_suggestions[{issue, title, source, confidence, reason?}]`, `issue_link_source`, `no_issue_reason` (FR-RPT-07) |
| GET | `/api/v1/reports/daily/{id}` | Detail and extracted tasks; does not return subject/body |
| GET | `/api/v1/reports/daily/{id}/raw` | Decrypted original email, writes audit `report.raw.read`. `body` is the report part, `signature` is the part after the `--` line (ADR-0019); the stored copy is not truncated |
| POST | `/api/v1/reports/daily/{id}/review` | `decision` is `CONFIRMED` or `REJECTED`; when rejected, the report's tasks are removed from Planning |
| PATCH, DELETE | `/api/v1/reports/daily/{id}/items/{item_id}` | CTO edits or deletes individual tasks |

The IMAP worker uses `BODY.PEEK[]` and does not mark emails as read. A reply/new email from the same member for the same report date creates a new revision; the old revision and old items change to `is_current=false` and are not deleted.

The standard format has the subject `DAILY REPORT | YYYY-MM-DD | HỌ TÊN | MÃ-DỰ-ÁN...` (full name, project code); the body uses the status allowlist `PLANNED|IN_PROGRESS|PENDING_REVIEW|DONE|BLOCKED|CANCELLED`, GitLab/Plane/Intake references (Issue numbers are recognized as `GitLab #19`, `Issue #19: …`, `[#8 KIN-26W41-007] …` or `#19 …` at the start of the title, or `Issue: https://…/issues/17` (`/work_items/17`); the `[#8 KIN-…]`/`Issue #19:` prefix is removed from the task title; an Intake ID in the title becomes `intake_reference`; the standard format is in `docs/stable/daily-report-format.md`), hours worked/remaining, next step, evidence and blocker. A parser error still persists the email/revision and returns a sanitized issue; an invalid report does not block the Planning Run.

## 10. Daily planning API

| Method | Path | Permission/Notes |
|---|---|---|
| GET | `/api/v1/planning/capacities/{date}` | CTO; capacity per person, deduction components and overrides; `is_cto` marks the CTO's own profile (FR-PLAN-37) |
| PUT | `/api/v1/planning/capacities/{date}/{member_id}` | CTO; optimistic version, override reason required for OT/exceptions |
| POST | `/api/v1/planning/members` | CTO; creates a workforce member and project mappings |
| GET | `/api/v1/planning/members` | CTO; workforce/mappings list; each row has `is_cto` (the CTO's own profile, FR-PLAN-37) |
| POST | `/api/v1/planning/members/me` | CTO only; creates the CTO's own member profile (the account's email, 0 hours by default) or links an existing profile with that email, writes `users.member_id`; clicking again returns the same `WorkforceMemberOut`; `422 MEMBER_HAS_ACCOUNT` when that profile already belongs to another account (FR-PLAN-37) |
| POST | `/api/v1/planning/runs` | CTO/scheduler; idempotent by plan date + scope |
| GET | `/api/v1/planning/days/{plan_date}` | Read only (FR-UI-12): whether the day's plan has been opened and how far it has gone. Returns `run_id`, `status`, `assigned`, `waiting`; with no plan yet, `run_id` is `null`. Never opens a plan. `?project_id=` for one project; a Project Owner must pass their own project, out of scope returns `404` |
| GET | `/api/v1/planning/runs/{id}` | Run, candidates, assignments, warnings and conflicts. Since 2026-10-15 each assignment has `issue_url` (the Issue page on the tracker, from the GitLab/GitHub read model) and each candidate has `intake_public_id`, `issue_url`, so the UI can link the Intake ID and the Issue number separately (FR-PLAN-33). Since 2026-10-19 a candidate has `accepted_at`: when the CTO accepted that row's Issue (null if not yet); a `DONE_ELSEWHERE` row with `accepted_at` is not shown on Daily Planning (FR-PLAN-34) Since 2026-10-20 each assignment also has `accepted_at` (the CTO has accepted the task's Issue; the UI draws the card as done, without changing hours). |
| POST | `/api/v1/planning/runs/{id}/assignments` | CTO; adds an assignment with the expected run version. A `(run, project, Issue)` has only one assignment; adding again returns `422 ISSUE_ALREADY_PLANNED` (FR-PLAN-04). |
| POST | `/api/v1/planning/runs/{id}/accept-proposals` | CTO; copies `proposed_*` to `approved_*` with the expected version, no GitLab sync yet |
| POST | `/api/v1/planning/runs/{id}/quick-add` | CTO; picks an existing reference or creates an Intake from form/paste; supports `Idempotency-Key` |
| POST | `/api/v1/planning/runs/{id}/quick-add/{candidate_id}/promote` | CTO; attaches the current GitLab Issue and turns the candidate into a proposal assignment; an Issue that already has an assignment in the run returns `422 ISSUE_ALREADY_PLANNED` (FR-PLAN-04). |
| POST | `/api/v1/planning/runs/{id}/approve` | CTO; creates an immutable snapshot and enqueues GitLab update jobs |
| GET | `/api/v1/planning/runs/{id}/sync-jobs` | Per-Issue status/error, redacted |
| POST | `/api/v1/planning/runs/{id}/sync-jobs/{job_id}/retry` | CTO; only failed jobs with retries left that belong to the right Planning Run |

Planning run create request:

```json
{
  "plan_date": "2026-10-03",
  "project_ids": ["uuid"],
  "timezone": "Asia/Ho_Chi_Minh"
}
```

Quick Add uses a single unified contract:

```json
{
  "expected_run_version": 3,
  "mode": "EXISTING",
  "project_id": "uuid",
  "source_system": "GITLAB",
  "reference": "#125",
  "requested_hours": 4,
  "target_slot": "MORNING"
}
```

`mode=FORM` requires `title`, with optional `content`; `mode=PASTE` requires `content` and accepts `channel` from `ZALO|WHATSAPP|EMAIL|MEETING|MANUAL`. These two modes create the Intake and a `PENDING_TRIAGE` candidate in the same transaction. The agreed target enqueues normalize/dedupe asynchronously after commit, without blocking the Quick Add response; runtime 1.2 does not enqueue this step yet. An existing open GitLab Issue creates a `READY` candidate; an existing Intake/Plane item is `READY` only when it already has a GitLab link matching the current read model.

Promotion requires `member_id`, `slot`, `planned_hours` and an open GitLab Issue. The result creates an assignment with only `proposed_*`; the CTO still has to call `accept-proposals`, then `approve`. Form/paste cannot go straight to a delivery assignment without a GitLab Issue.

At 06:45 the task `intake.planning.refresh-gitlab` is called on the integration queue. The task paginates `state=all`, stores an internal snapshot and does not write to GitLab. At 07:00 it only reads the current snapshot and ranks by email carry-over, priority and due date. Target per ADR-0013: priority comes from the most recent approved Planning snapshot containing the Issue, with the GitLab priority label as fallback; runtime 1.2 only reads the priority label. The planner creates at most one primary Issue per person, splitting at most 4 hours per lane. A proposal does not become a decision until the CTO calls `accept-proposals`, after which a separate `approve` is still needed.

Capacity override request:

```json
{
  "expected_version": 2,
  "override_hours": 4,
  "meeting_hours": 0,
  "review_hours": 0,
  "support_hours": 1,
  "fixed_hours": 0,
  "reason": "OT release Ember"
}
```

Planning approval request:

```json
{
  "expected_version": 7,
  "acknowledged_warning_ids": ["uuid"],
  "override_reason": null
}
```

Approval fails closed when an assignment lacks a GitLab Issue, lacks a GitLab user mapping or selects a milestone that does not exist. A missing milestone or due date does not block: the warning `GITLAB_MILESTONE_MISSING` / `GITLAB_DUE_DATE_MISSING` must be marked as seen (`acknowledged_warning_ids`), otherwise `422 WARNING_UNACKNOWLEDGED`; the GitLab update job only sends fields that have values (ADR-0013, implemented 2026-10-13).

### GitLab planning update contract

Each job updates only one Issue and the payload allowlist consists of:

```json
{
  "issue_external_id": "125",
  "assignee_external_id": "42",
  "milestone_external_id": "9",
  "due_date": "2026-10-03"
}
```

- No new milestones are created.
- `milestone_external_id` and `due_date` are optional; a missing field is not sent and is not cleared on GitLab (ADR-0013).
- The priority label is not updated in the pilot; the CTO-approved priority lives only in the Planning snapshot.
- No raw email/chat or morning/afternoon slot details are written to GitLab.
- The adapter re-reads the Issue before updating, stores the before/after allowlist and uses a stable idempotency key per planning snapshot + Issue.
- An error on one Issue does not roll back other Issues; a retry uses the same idempotency key and only the failed job.

`REPORT` source candidates (ADR-0019): `POST /api/v1/planning/runs` creates a run or returns the existing run for that day and scope. In both cases, if the run is still editable, unfinished tasks from usable Daily Reports are added as candidates and the run's `version` increases when there are new candidates. Promote uses the same endpoint as Quick Add and still requires an open GitLab Issue.

Project Owner daily permissions (FR-ID-08, ADR-0026). The following routes also accept a Project Owner, within their team and projects; out of scope returns 404:

- `GET /api/v1/reports/daily`, `GET /api/v1/reports/daily/{id}`, `GET .../raw`, `POST .../review`, `PATCH` and `DELETE .../items/{item_id}`.
- `GET /api/v1/planning/members` (their team only), `GET /api/v1/planning/capacities/{date}?project_id=` (project required), `PUT /api/v1/planning/capacities/{date}/{member_id}`.
- `POST /api/v1/planning/runs` (scope must be their projects), `GET /api/v1/planning/runs/{id}`, `POST .../assignments`, `GET .../work-items`, `POST .../work`, `POST .../candidates/{id}/assign`, `POST .../candidates/{id}/dismiss|restore`.
- `POST .../work` with a task that has no Issue yet and `POST .../candidates/{id}/assign` with `issue_mode=CREATE` return 403 `CTO_APPROVAL_REQUIRED` for a Project Owner.
- Each assignment in a Planning Run also has `title` (the Issue title in the read model, null if none yet).

Changing a decision (FR-APR-08, ADR-0028): `POST /api/v1/intakes/{id}/reopen` with `reason` (at least 5 characters) and `expected_version`; same scope as approval. Returns the Intake in `PENDING_APPROVAL`. 409 `SYNC_LOCKED`, `NOT_DECIDED`, `INTAKE_PLANNED`, or version mismatch. The Intake journey also has `previous_targets` (items created under the old decision). Since ADR-0028, `POST .../work` and `POST .../candidates/{id}/assign` no longer return `CTO_APPROVAL_REQUIRED` for a Project Owner.

Where approvals happen (FR-APR-07), CTO only: `GET /api/v1/approvals/sources?weeks=4` (1 to 12 weeks) returns a list of weeks, newest first, each with `week_start` (Monday, Vietnam time), `from_queue` and `from_planning`. Only `APPROVE` actions are counted.

Report mailbox scan (FR-EML-12, FR-EML-14), CTO only:

- `GET /api/v1/reports/mailbox` returns `enabled`, `mailbox`, `poll_minutes`, `current` (the scan pending or running) and `last` (the most recent finished scan). Each scan has `trigger` (`SCHEDULED`/`MANUAL`), `status` (`PENDING`/`RUNNING`/`DONE`/`FAILED`), `ingested`, `duplicates`, `failed`, `error_code`, `created_at`, `completed_at`.
- `POST /api/v1/reports/mailbox/scan` returns 202 with the same structure; if a scan is already open, it is reused. 409 `MAILBOX_DISABLED` when the mailbox scan is turned off. A request not picked up by the worker within 5 minutes is closed with `WORKER_UNAVAILABLE`.

Journey of a request (FR-UI-09): `GET /api/v1/intakes/{id}/journey`, same scope as viewing an Intake (CTO or the project's Project Owner, out of scope returns 404). Returns `intake_id`, `intake_public_id`, `project_id`, `received_at`, `channel`, `decision` (`action`, `at`, `by`, `route`, `priority`), `issue` (`system` GITLAB/GITHUB, `external_id`, `url`), `other_target`, `sync_status`, `accepted_at`, `plans` (up to the 6 most recent schedulings: `plan_date`, `run_id`, `member_name`, `slot`, `planned_hours`, `settled`, `work_status`, `accepted_at`) and `waiting_in_plan`. Each assignment in a Planning Run also has `intake_id` and `intake_public_id` (null if the Issue did not originate from an Intake). The UI builds the deep link `/planning?date=YYYY-MM-DD&project=<uuid>&intake=INT-...` from the most recent scheduling.

Adding work within the day (ADR-0024), CTO only:

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/planning/runs/{id}/work-items?search=` | Open Issues and Intakes awaiting approval for the projects in the run; each row says whether it is already in the plan and whether an Issue needs to be created |
| POST | `/api/v1/planning/runs/{id}/work` | `source` is `ISSUE`, `INTAKE` or `NEW`; `member_id`, `slot`, `planned_hours` are optional but must come together. `reason` is required when an Issue has to be created. Returns `state`: `PLANNED`, `WAITING_ASSIGNMENT` (with `assignment_error` if the assignment does not fit) or `CREATING_ISSUE` |
| POST | `/api/v1/planning/runs/{id}/candidates/{cid}/assign` | Schedules a waiting task: `issue_mode=EXISTING` attaches an existing Issue, `CREATE` creates a new Issue with `reason` |
| POST | `/api/v1/planning/runs/{id}/assignments/{aid}/unassign` | `{ expected_run_version }` (FR-PLAN-16). Removes a scheduled task from the day while the run is still editable; the task goes back to a `READY` candidate (the original candidate if it came from the waiting list, or a new candidate from the Issue) with its priority and hours; warnings tied to that task are deleted; `409 PLANNING_RUN_IMMUTABLE`, `409 PLANNING_VERSION_CONFLICT`, `422 PLANNING_ASSIGNMENT_NOT_FOUND`. Returns the whole run |
| POST | `/api/v1/planning/runs/{id}/assignments/{aid}/move` | `{ expected_run_version, slot, member_id?, override_reason? }` (FR-PLAN-04). Changes the slot; with `member_id` it also changes the assignee in the open run, updating the tracker assignee mapping, candidates/warnings and audit. Rejected if the person is inactive/not in the project, lacks a delivery mapping, exceeds the day's capacity, exceeds 4 hours in the slot or already has another primary development task (`MEMBER_NOT_ACTIVE`, `MEMBER_NOT_IN_PROJECT`, `GITLAB_ASSIGNEE_REQUIRED`, `OVER_CAPACITY`, `SLOT_OVER_CAPACITY`, `MULTIPLE_PRIMARY_DOING`). The CTO/Project Owner can send `override_reason` after a confirmation step to exceed the three limits capacity/4 hours/primary task; the reason is stored on the assignment and in audit, other roles get `PLANNING_OVERRIDE_FORBIDDEN`. Returns the whole run |
| POST | `/api/v1/planning/runs/{id}/candidates/{cid}/done` | `{ note }` (3..500 characters, `422 NOTE_REQUIRED`). CTO or the project's Project Owner. A waiting task already done outside the plan: `status REJECTED`, `summary` "Đã làm xong ngoài kế hoạch: <ghi chú>" (Done outside the plan: <note>), also returns `acceptance_queued`; a finalized plan still accepts it (FR-PLAN-34) |
| POST | `/api/v1/planning/runs/{id}/candidates/{cid}/dismiss` and `/restore` | Hides a waiting task from that day's run, or brings it back |
| POST | `/api/v1/planning/runs/{run_id}/reopen` | CTO or the project's Project Owner. `{ expected_version }`. A finalized plan (APPROVED, SYNCING, SYNCED, SYNC_FAILED, PARTIAL) becomes a new revision: `201` returns the new Planning Run (`revision + 1`, `supersedes_run_id`, status `REVIEW_REQUIRED`, with tasks, hours, priorities, reported task status and seen warnings copied over; the old revision becomes `SUPERSEDED` and is still readable). `422 PLANNING_RUN_OPEN` when it is open, `PLANNING_RUN_SUPERSEDED` when a newer revision exists, `PLANNING_SYNC_IN_PROGRESS` when the old revision's GitLab jobs have not finished, `409 PLANNING_VERSION_CONFLICT`. Finalizing again only creates jobs for Issues whose `after_state` differs from the most recent `SUCCEEDED` job in the chain of old revisions (FR-PLAN-18) |
| POST | `/api/v1/planning/runs/{run_id}/verifications/{verification_id}/{accept\|reject}` | CTO only (FR-PLAN-22). `{ expected_version, reason? }`; `reject` requires `reason`. Returns the whole Planning Run (`verifications[]` with `level` 0–5, `level_name`, `evidence {commits, merge_requests, merged, pipeline, links}`, `acceptance[]` from the Intake, `decision`). `409 PLANNING_VERSION_CONFLICT`, `409 VERIFICATION_DECIDED`, `422 REASON_REQUIRED`. Not done → candidate `source_type=VERIFICATION` "Làm lại" (Redo) and warning `ISSUE_NOT_DONE_AFTER_CLOSE`; nothing is written to GitLab |
| PUT | `/api/v1/planning/projects/{project_ref}/done-evidence` | CTO only. `{ done_evidence: COMMIT \| MR }` (FR-PLAN-22); `ProjectOut.done_evidence` reads it back |

When an Issue has to be created, the API records the approval action and the Intake snapshot, then queues a sync job like the normal flow; the integration worker creates the Issue, and when the sync succeeds the Issue is added to the read model together with the recorded assignment. Specific errors: `ADD_WORK_REASON_REQUIRED`, `DELIVERY_SYNC_DISABLED`, `ASSIGNMENT_INCOMPLETE`, `INTAKE_NOT_READY`.

## 10A. Meeting API (ADR-0018, ADR-0019)

CTO only. Every JSON response uses the common envelope.

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/meetings/speech` | Whether a speech provider is configured and whether live transcript is available (`{configured, live_text}`) |
| GET, POST, DELETE | `/api/v1/meetings/glossary` | Shared or per-project glossary terms |
| POST | `/api/v1/meetings` | `project_id` required (`MEETING_PROJECT_REQUIRED`), `source` is `TAB_AND_MIC`, `MIC` or `FILE`, `title` optional; returns 409 when `MEETING_CAPTURE_ENABLED=false` |
| GET | `/api/v1/meetings`, `/api/v1/meetings/{id}` | List; detail includes the transcript, speakers, summary and note items |
| POST | `/api/v1/meetings/{id}/audio?sequence=N` | Multipart, one audio chunk, max 5 MB, must be in order; total not more than `MEETING_MAX_AUDIO_MB` |
| GET | `/api/v1/meetings/{id}/audio` | Decrypted recording, writes audit; `?download=true` returns `Content-Disposition: attachment` |
| POST | `/api/v1/meetings/{id}/finish` | Ends and queues transcription with speaker separation. Optional body `{ duration_seconds }` (FR-REC-14): the duration measured by the browser; the server takes the smaller of it and its own clock; without a body the server clock is used. Calling again on a finished meeting changes nothing |
| POST | `/api/v1/meetings/{id}/audio?sequence=` | Accepts the next chunk in order; an existing chunk returns `200` unchanged; `409 AUDIO_CHUNK_OUT_OF_ORDER` with "Expected chunk N" so the browser drops the chunks the server already holds; `409 MEETING_NOT_RECORDING` when the meeting has ended (FR-REC-14) |
| PATCH | `/api/v1/meetings/{id}/project` | Changes the meeting's project; every item not yet turned into an Intake follows |
| POST | `/api/v1/meetings` with `continues_meeting_id` | The next part of a meeting that hit the minute limit: same project, `part_number` + 1, title "(phần n)" (part n); `MeetingOut` has `series_id`, `part_number`, `transcript_error`, `note_error`; the detail has `parts[]` (FR-REC-17, FR-REC-18) |
| POST | `/api/v1/meetings/{id}/note/items/{item_id}/intake?full_transcript=` | Intake from one item, with the transcript excerpt around the topic; `full_transcript=true` sends the whole transcript (FR-REC-15) |
| POST | `/api/v1/meetings/{id}/note/items/intakes` | `{ item_ids[], full_transcript }` → `{ results[{item_id, intake_id, error}], meeting }`; `201` even when some items fail (FR-REC-16) |
| POST | `/api/v1/meetings/{id}/transcript/retry` | Resends the file to the transcription service when `transcript_status` is FAILED or SKIPPED; `409 TRANSCRIPT_RETRY_NOT_ALLOWED` otherwise (FR-REC-18) |
| PATCH | `/api/v1/meetings/{id}` | Rename (FR-REC-12): `{ "title" }`, 1 to 200 characters, extra whitespace is collapsed |
| DELETE | `/api/v1/meetings/{id}` | Permanently deletes the recording, transcript and note (FR-REC-12). Returns `{ deleted, intakes_kept }`. `409 MEETING_BUSY` while recording, transcribing, or while the transcription service's copy has not finished deleting |
| PATCH | `/api/v1/meetings/{id}/speakers` | Sets real names for "Thành viên N" (Member N) |
| PATCH | `/api/v1/meetings/{id}/note` | Edits the summary |
| POST | `/api/v1/meetings/{id}/note/regenerate` | Regenerates the note; items already turned into Intakes are kept |
| POST, GET | `/api/v1/meetings` (addition) | `POST` also accepts `kind`: `MEETING` (default) or `DICTATION` (speak to enter text: ending means done, no speaker separation, no note). `GET` returns only `MEETING` by default; `?include_dictation=true` returns both. Each record has `kind` |
| POST | `/api/v1/meetings/{id}/rewrite` | `202`. Asks the AI to rewrite the transcript into a concise request (FR-REC-11); the worker carries it out. While one is running, a second is not created. `409 MEETING_HAS_NO_TRANSCRIPT` when not ended yet or there is no text |
| GET | `/api/v1/meetings/{id}/rewrite` | Reads the result: `rewrite_status` (`NONE`, `PENDING`, `DONE`, `FAILED`), `rewrite_text`, `rewrite_error`. Used for periodic polling, does not write a transcript-open audit |
| PATCH, DELETE | `/api/v1/meetings/{id}/note/items/{item_id}` | Edits or deletes one item |
| POST | `/api/v1/meetings/{id}/note/items/{item_id}/intake` | Creates a `MEETING` channel Intake from the item, idempotent per item, then enqueues normalize |

WebSocket `/api/v1/meetings/{id}/stream` is served by the `meeting-gateway` service, not the API: it authenticates with the session cookie and checks the origin, receives 16 kHz PCM from the browser, forwards it to ElevenLabs Scribe Realtime and returns finalized transcript lines. Only the gateway holds `ELEVENLABS_API_KEY`.

External provider: realtime `wss://api.elevenlabs.io/v1/speech-to-text/realtime`; batch `POST /v1/speech-to-text` with `diarize`; delete `DELETE /v1/speech-to-text/transcripts/{id}` (retried because it returns 404 for the first few seconds).
## 11. Internal events

| Event | Minimum payload |
|---|---|
| `intake.normalization.requested.v1` | `run_id`, `intake_id` |
| `integration.sync.requested.v1` | `sync_job_id` |
| `planning.gitlab-update.requested.v1` | `planning_sync_job_id` |

These are the three runtime outbox events the dispatcher currently routes to Celery. Post-meeting processing does not use the outbox: the gateway scans transcription jobs every 15 seconds and the AI worker scans note-creation jobs every minute; both claim work through the status on the `meetings` table with at most 3 attempts. Completion/approval/retention/planning lifecycle currently writes audit records or runs directly; they are not outbox events yet. Decision of 2026-10-03 (OD-017): Intake approval only writes audit, not an `intake.approved` outbox event; runtime 1.2 still writes this event without a dispatcher route, and it must be removed in code. The event version is part of the name; consumers must be idempotent.

## 12. Target contracts without an OpenAPI operation

The following endpoints are still target design; clients must not treat them as available:

- Deleting a project and unlinking it (create, edit and connection check already exist since ADR-0020).
- `GET /intakes/{id}/approval-snapshots`.
- Global `GET /sync-jobs` and `POST /sync-jobs/{id}/retry` for Intake sync.
- `POST /planning/runs/{id}/refresh`.
- `PATCH /planning/runs/{id}/assignments/{assignment_id}`.
- Planning amendment that creates a new revision of the whole run, a supersede link, and per-Issue delta sync.
- Emergency Add for P0 per ADR-0012: CTO only, reason required, idempotent; the integration worker immediately creates a minimal GitLab Issue with the label allowlist and `priority:p0`, without going through the Intake item's approval snapshot; the result is a Planning candidate.

When implemented, add the requirement ID, an OpenAPI contract test, and update inventory/readiness in the same change.

## Private Space and post drafts (FR-CNT-01..03, ADR-0031)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/private-space` | CTO only. Returns `project` (or `null` when not yet opened), `voice`, `counts` (`ideas`, `no_draft`, `drafted`, `posted`, `dropped`, `unposted_drafts`) |
| POST | `/api/v1/private-space` | CTO only. Opens the Private Space: creates an `IDEA` project marked private. Calling again returns the same space |
| GET | `/api/v1/private-space/ideas?state=&search=` | CTO only. `state`: `ALL` (default, excludes dropped ideas), `NO_DRAFT`, `DRAFTED`, `POSTED`, `DROPPED` |
| PUT | `/api/v1/private-space/voice` | CTO only. Saves voice and positioning; at most 5 pillars (80 characters each), 8 sample posts (20 to 4000 characters each) |
| GET | `/api/v1/intakes/{id}/drafts` | Anyone who can view the Intake. Newest draft first |
| POST | `/api/v1/intakes/{id}/drafts` | `202`. `{ channel, angle?, source_draft_id? }`; `source_draft_id` is the draft to adapt to another channel. `409 DRAFTS_NOT_FOR_KIND` for software projects; `409 SOURCE_DRAFT_NOT_READY` |
| PATCH | `/api/v1/intakes/{id}/drafts/{draft_id}` | `{ text?, posted? }`. `409 DRAFT_NOT_READY` when the draft is not finished |
| DELETE | `/api/v1/intakes/{id}/drafts/{draft_id}` | `204` |

The company list and count APIs (`/intakes`, `/approvals`, `/projects`, `/meetings`) never return data from private projects.

Content tracks and choices before drafting (FR-CNT-04, ADR-0035):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/private-space` | Adds `master_dna` (shared document, at most 40,000 characters) and `voices`: `{ business, technical }`, each voice has `name`, `direction_note`, `references` (at most 2, each with `title` and `text` ≤ 20,000 characters); `dna` is gone. `voice` is still the voice of the `business` track (ADR-0042) |
| GET/POST/DELETE | `/api/v1/auth/tokens[/{id}]` | Login session only (CTO, Project Owner), not via token (FR-MCP-01). `POST { name }` → `201` `{ id, name, prefix, token, created_at, expires_at }`, `token` is returned only once; `409` when there are already 10 tokens; `DELETE` → `204`, `404` if not your own. The token is used as `Authorization: Bearer itk_…` for every route with the creator's permissions |
| GET/POST | `/api/v1/intakes/{id}/work-log` | CTO or the project's PO (FR-MCP-03). `POST { summary (5–1.000), details { cause, changes[], tests, branch, commit, verify_steps[], deploy_steps[], worked_on? YYYY-MM-DD, actual_minutes? 0..1440, deployed? }, agent_name? }` → `201`. Date/minutes are actuals; they do not create or add to Daily Planning. Entries have `review_decision` `PENDING|CONFIRMED|RETURNED`, `review_note`, `reviewed_by_name`, `actor_name`, `agent_name`, `commit_url` (the commit page on GitLab/GitHub built from the request's Issue address; if `commit` is already a link it is kept as is; `null` when the repo is unknown) |
| POST | `/api/v1/intakes/{id}/work-log/{log_id}/review` | CTO only. `{ decision: CONFIRMED|RETURNED, note? }`; `RETURNED` requires `note` (`422 NOTE_REQUIRED`); `409 ALREADY_REVIEWED`. `CONFIRMED` on the current delivery Issue also creates/accepts an `IssueVerification` with source `WORK_LOG`, sets `sync_status=PENDING`, then enqueues the task that closes the Issue after commit. |
| GET | `/api/v1/changelog` | `{ build {sha, built_at}, latest, entries[{date, title, commits[], refs[], bullets[], cto_only}], behind }` read from `CHANGELOG.md`; `cto_only` entries are hidden from Project Owners (FR-UI-14). `behind`: number of entries newer than the running build, CTO only, `null` when unknown (FR-UI-15) |
| POST | `/api/v1/reports/daily/{id}/items/{item_id}/issue` | CTO or Project Owner (requester belongs to their team). `{ gitlab_issue? , no_issue_reason? MEETING|SUPPORT|REVIEW|LEARNING|OTHER }`: with `gitlab_issue` it links it (source taken from the suggestion if it matches, otherwise `MANUAL`), with only a reason it marks "no Issue needed", empty clears both. Returns the report detail (FR-RPT-07) |
| POST | `/api/v1/reports/daily/{id}/link-sure` | Links every item with a suggestion of 0.9 or higher in the message; returns the report detail (FR-RPT-07) |
| POST | `/api/v1/reports/daily/{id}/suggest-issues` | Recomputes suggestions by rules, sends the unclear part to AI via the `ai.normalize` queue; returns `{ items, linked, suggested, for_ai[], ai_queued }` (FR-RPT-07) |
| POST | `/api/v1/reports/issue-suggestions/backfill?days=14` | CTO only. Runs suggestions for every report that still has unlinked items within `days` days; returns totals with `reports` (FR-RPT-07) |
| GET | `/api/v1/planning/week/{day}` | CTO or Project Owner (own projects). The week containing `day`: `{ week_start, week_end, days_passed, projects[{id, code, name, people, hours{available, planned, reported}, plans{total, closed}, done{reported, issues_closed, accepted, rejected, work_logs_confirmed}, items{reported, without_issue}, reports{expected, received, missing, late}, requests{new, approved, approved_within_24h, from_planning, avg_wait_hours, avg_to_issue_hours}, board{days, ready_days, no_work_days, overdue_days, max_approvals_overdue, max_stuck, escalated_days}}], people[{member_id, display_name, hours, done_reported, items, reports, projects[{id, name, planned, reported}]}], process{...}, cto_days[{date, minutes}] (CTO only), text }` (FR-PLAN-29) |
| POST | `/api/v1/planning/board-snapshots/{day}` | CTO only. Writes (or replaces) the morning board snapshot for that day; returns `{ snapshot_date, projects }` (FR-PLAN-30) |
| GET | `/api/v1/acceptance` | CTO or Project Owner (own projects); `?project_id=`. `source` adds `PLAN` (reported done on the day plan, FR-PLAN-34); each item has `source_note` (the note written when cancelling a pending item, copied to the Issue when the CTO accepts). `{ plan_date, sample_size, pending_total, today[], more[], decided[] }`, each entry `{ id, source REPORT|CLOSED, project_id, project_name, issue_external_id, title, web_url, state, closed_at, assignee_*, reporter_*, reported_on, reported_hours, report_item_title, priority, level, level_name, done_evidence, evidence, evidence_fetched_at, intake_*, acceptance[], picked_on, decision, reason, decided_at, decided_by_name, po_decision, po_reason, po_decided_at, po_decided_by_name, sync_status, sync_error, synced_at }`. CTO: `today` is the day's sample (picked when requested), `more` is the rest, `decided` covers 7 days; Project Owner: `today` is every unconfirmed item of their own projects (FR-PLAN-31) |
| POST | `/api/v1/acceptance/{id}/accept` or `/reject` | `{ reason? }` (required for reject, `422 REASON_REQUIRED`). The CTO writes `decision`, the Project Owner writes `po_decision`; `409 VERIFICATION_DECIDED` when already decided. Reject: the item returns to the open plan as "Redo" ("Làm lại"). CTO accept: `sync_status = PENDING`, a task writes a note and closes the Issue; returns the entry with `sync_queued` (FR-PLAN-31) |
| POST | `/api/v1/acceptance/sample?extra=5` | CTO only. Adds `extra` items to today's sample; returns `{ added }` (FR-PLAN-31) |
| POST | `/api/v1/acceptance/collect` | CTO only. Collects items reported done and closed Issues; also reconciles old `CONFIRMED` work logs that have no formal acceptance, accepts them and enqueues closing the Issue. Returns `{ from_reports, from_closed, from_work_logs }` (FR-PLAN-31, FR-MCP-03) |
| PUT | `/api/v1/planning/projects/{project_ref}/acceptance-policy` | CTO only. `{ acceptance_policy: CTO_ALWAYS\|PO_FINAL_LOW_RISK }` (other values `422`) → `{ project_id, acceptance_policy }`; writes `planning.acceptance-policy.changed`. `GET /projects` also returns `acceptance_policy`. Acceptance cards (`GET /acceptance`, accept, reject) also return `final_by (CTO\|PO\|null)`, `acceptance_policy`, `needs_cto_acceptance`, `po_final_blockers[]` (`POLICY`, `HARD`, `P0`, `EVIDENCE`, `NOT_OWNER`, `SELF`, `REJECTED_BEFORE`). Project Owner accept with no blocker: `decision ACCEPTED`, `final_by PO`, `sync_status PENDING`, closes the Issue like the CTO. `GET /intakes/{id}/journey` `verification` adds `po_decision`, `po_decided_at`, `po_decided_by_name`, `final_by`, `accepted_by_name` (FR-PLAN-41) |
| POST | `/api/v1/planning/projects/{ref}/tracker-users/lookup` | CTO or Project Owner (own projects). `202 { probe_id, status, system }`: asks the integration-worker to read the tracker's user list (the API does not hold the token); `422 TRACKER_NOT_CONFIGURED` when the project has not enabled GitLab/GitHub (FR-PLAN-32) |
| GET | `/api/v1/notify/telegram` | CTO only. `{ bot_username, bot_seen_at, projects[{id, code, name, chat_title, linked, linked_at}], members[{id, display_name, username, linked, linked_at, invite_pending}], holidays[{day, note}] }` (FR-NTF-02, FR-NTF-03) |
| POST | `/api/v1/notify/telegram/members/{member_id}/invite` | CTO only. Creates (or recreates) a single-use invite code; `{ member_id, code, link, linked }`, `link` is null when `TELEGRAM_BOT_USERNAME` is not set; `404` when there is no such member (FR-NTF-03) |
| DELETE | `/api/v1/notify/telegram/members/{member_id}/link` | CTO only. Unlinks the member's Telegram and deletes any open invite code; `204` (FR-NTF-03) |
| DELETE | `/api/v1/notify/telegram/projects/{ref}/link` | CTO only. Unlinks the project's group (`ref` is the id or code); `204` (FR-NTF-02) |
| GET | `/api/v1/notify/holidays` | CTO only. `[{day, note}]` (FR-NTF-04) |
| PUT | `/api/v1/notify/holidays` | CTO only. `{ days: [{day, note?}] }` (at most 60) replaces the whole list; duplicate days keep the first row; returns the new list (FR-NTF-04) |
| GET | `/api/v1/notify/telegram/messages?days=7` | CTO only (`days` 1..60). `[{id, kind, for_date, slot, status SENT\|FAILED, error, sent_at, project_name, member_name}]`, newest first; `error` only contains a stable Telegram code and the exception type, never the raw transport error or the bot token (FR-NTF-01, FR-NTF-05) |
| POST | `/api/v1/planning/proposals` | `{ project (code or id), plan_date, issue?, intake?, text?, hours?, slot? }`. CTO, Project Owner (own projects), Developer (projects they are on, otherwise `404`); accounts not linked to a member get `422 MEMBER_UNMAPPED`. `201` returns the candidate with `created`, `run_id`, `project_name`, `project_code`, `plan_date`; `409 PLANNING_RUN_IMMUTABLE` when that day's plan is already closed; `422 GITLAB_ISSUE_NOT_FOUND`, `GITLAB_ISSUE_CLOSED`, `CANDIDATE_ALREADY_PLANNED`, `INTAKE_NOT_FOUND`, `PROPOSAL_TEXT_REQUIRED` (FR-PLAN-35) |
| GET | `/api/v1/planning/people/{plan_date}` (changed) | CTO: everyone; Project Owner: people on their project teams, each with `projects[{id, name, hours, run_status}]` for every project with hours, including projects of other Project Owners (FR-PLAN-28) |
| GET | `/api/v1/planning/capacities/{date}` (added) | Each row has `planned_elsewhere[{project_id, project_name, hours}]` next to `planned_elsewhere_hours` (FR-PLAN-28); `GET /planning/day-plans/{date}` gives `elsewhere[]` on `people[]` and `free[]` |
| PATCH | `/api/v1/planning/runs/{run_id}/assignments/{assignment_id}/work-status` | `{ status: PLANNED|IN_PROGRESS|DONE|BLOCKED, note? }`. CTO: every item; Project Owner: own projects; Developer: their own items (otherwise `404`). A closed plan still accepts it. Returns `{ assignment_id, issue, work_status, previous, at, work_status_note, acceptance_queued }`; `DONE` on an item with an Issue creates a pending Acceptance item with source `PLAN` if the Issue has no pending item yet (FR-PLAN-34) |
| GET | `/api/v1/planning/my-day/{plan_date}` | CTO, Project Owner, Developer (account linked to a member, otherwise `422 MEMBER_UNMAPPED`). Same data as the `get_my_day` tool: `{ date, member, items[{assignment_id, project, project_name, issue, issue_url, title, intake, priority, slot, hours, work_type, primary, work_status, work_status_note, plan_closed}], personal[], note?, hint? }` (FR-PLAN-34, FR-MCP-06). Since 2026-10-20 each item has `accepted_at`; since 2026-10-21 `issue_url` opens the Issue detail from the "My work" ("Việc của tôi") card. |
| GET | `/api/v1/planning/day-plans/{plan_date}` | CTO (all projects) or Project Owner (own projects). Read only, does not open a plan. `{ plan_date, projects[{id, code, name, owner_name, run{...}|null, people[...], free[...], off[], waiting[...], off_plan[{id, intake_id, intake_public_id, title, issue, issue_url, executor, review_decision, worked_on, actual_minutes, deployed, accepted_at}]}], project_order{mode: PRIORITY|CUSTOM, project_ids[]}, totals{projects, unclosed, free_hours, free_people, waiting, off_plan, off_plan_actual_minutes} }` (FR-PLAN-33). `project_order` is the current account's preference and is already filtered to the caller's project scope. `off_plan` is the day's work logs with no matching assignment; it only shows actual history and is not added to planned hours. Since 2026-10-20 each item card in `people[].assignments[]` has `accepted_at`. |
| PUT | `/api/v1/planning/project-order` | CTO or Project Owner. `{ mode: PRIORITY|CUSTOM, project_ids[] }`; stored per account. `PRIORITY` always clears the ID list. `CUSTOM` only accepts active software projects the caller can see; duplicate IDs return `422 PROJECT_ORDER_DUPLICATE`, out-of-scope projects return `422 PROJECT_ORDER_PROJECT_NOT_VISIBLE` (FR-PLAN-33, FR-ID-08). |
| GET | `/api/v1/planning/projects/{ref}/tracker-users?probe=&issue=` | `{ status PENDING|DONE|FAILED, error_code, users[{id, name, username, mapped_member_id, suggested_member_id}], unmapped[{member_id, display_name, suggested_user_id}], issue_assignees[] }`; a probe of another project returns `FAILED PROBE_NOT_FOUND` (FR-PLAN-32) |
| POST | `/api/v1/planning/projects/{ref}/tracker-users/auto-map?probe=` | Fills the mapping for people with a unique match from a finished probe; `409 PROBE_NOT_DONE` when it has not returned; returns `{ filled, names[], unmapped }` (FR-PLAN-32) |
| PUT | `/api/v1/planning/projects/{ref}/members/{member_id}/tracker-user` | CTO or Project Owner. `{ gitlab_user_external_id }` (null to clear); `404` when it is not your project or the person is not on the project (FR-PLAN-32) |
| GET | `/api/v1/planning/people/{plan_date}` | CTO only. `{ plan_date, over, free, people[{member_id, display_name, available_hours, planned_hours, free_hours, state OVER|FREE|OK|OFF, projects[{id, name, hours, run_status}]}] }`: hours scheduled across all non-superseded plans of the day (FR-PLAN-28) |
| GET | `/api/v1/planning/people` | Every logged-in role. People whose plan the caller may view by person: `{ me, members[{member_id, display_name, is_me}] }`, active members, the viewer first. CTO: everyone; others: themselves and people sharing a project (projects assigned to them and projects they are a member of) (FR-PLAN-40, ADR-0081) |
| GET | `/api/v1/planning/people/{member_id}/plan?from=&to=` | Every logged-in role, read only, at most 62 days (`422 RANGE_TOO_LONG`, `422 RANGE_INVALID`); people out of scope return `404 MEMBER_NOT_FOUND`. `{ member{member_id, display_name, is_me}, from, to, days[{date, capacity_hours, personal_hours, available_hours, planned_hours, off, items[], hidden_projects[{name, hours}]}], totals{planned_hours, available_hours, personal_hours, off_days, by_project[{name, hours, visible}], work_status{PLANNED, IN_PROGRESS, DONE, BLOCKED}, accepted, work_items{<status>: n}} }`. `items[]` by `kind`: `ASSIGNMENT {id, run_id, run_status, project_id, project, project_name, title, issue, issue_url, intake, priority, slot, hours, work_type, status, accepted_at}`, `WORK_ITEM {id, code, title, status, priority, project_id, project, project_name, channel, urgent, due_date, closed}` (closed items on their close date, open items on their due date), `PERSONAL {id, title, hours, status, start_time}` (only when viewing yourself). Projects the viewer is not on only appear in `hidden_projects` and as `by_project.visible=false` (FR-PLAN-40, ADR-0081) |
| GET | `/api/v1/planning/overview/{plan_date}` | Read only, does not open a plan. One row per software project: `readiness {state, reasons[]}`, `context {band, score, missing[], approved}` (FR-CTX-04), `reports`, `approvals`, `unsynced`, `stuck`, `meetings`, `plan` (the project's own plan or the combined plan that still contains it), `acceptance`, `gitlab`, `people_off[]`, `unassigned[]`, `carry_over`, `plan.made_by`, `approvals {pending, urgent, cto, po, overdue, has_owner}`, `overdue {approvals, waiting, work_log, p0_open}`, `attention`; at the top of the page `overdue_total` and `cto_time {today_minutes, actions_today, avg7_minutes, days[]}` (CTO only, `null` for Project Owners); Project Owners only see their own projects (FR-PLAN-23, FR-PLAN-26, FR-APR-14, FR-PLAN-27, FR-UI-15). `POST /runs/{id}/approve`, `/accept-proposals`, `GET /runs/{id}/sync-jobs`: CTO or the project's Project Owner (FR-PLAN-25) |
| PUT | `/api/v1/planning/projects/{project_ref}/agent-ready` | CTO only. `{ agent_ready: bool }` (FR-MCP-04); `ProjectOut.agent_ready`. `IntakeOut.agent_readiness { score, band: READY|NEEDS_WORK|HUMAN, reasons[], missing[] }` is present in detail and list |
| PATCH | `/api/v1/intakes/{id}/fix-hints` | CTO or PO. `{ fix_hints }` ≤ 2,000 characters, empty to clear; returns `IntakeOut` (with `fix_hints`). The journey (`/journey`) has `work { entries, latest_id, latest_decision, latest_at, latest_by, off_plan, worked_on, actual_minutes, deployed }` and `unlogged_evidence { commits, merge_requests, links }|null`; the UI uses `latest_id` so the CTO can decide a `PENDING` work log right at the Acceptance step. `unlogged_evidence` only opens the flow for recording results; it does not accept on its own. |
| PATCH | `/api/v1/intakes/{id}/hard-flag` | CTO only (403 for other roles). `{ needs_cto_acceptance: bool }`; returns `IntakeOut`. Changing the value writes `intake.hard_flag_changed`. `POST /intakes` and `approve` accept the same field, ignored if the caller is not the CTO; MCP `create_intake` accepts `needs_cto_acceptance` (CTO), `get_intake` returns it. FR-PLAN-39. |
| POST | `/api/v1/mcp-server` | MCP Streamable HTTP (FR-MCP-02): JSON-RPC 2.0 body (single or batch), returns JSON of the same shape, not wrapped in the envelope; notifications return `202`. Only accepts `Bearer itk_…` (`401` with cookie/session). Methods: `initialize`, `ping`, `tools/list`, `tools/call`; JSON-RPC errors `-32601/-32600/-32700`. Tool result: `content[0].text` (JSON) and `structuredContent`; business errors `isError: true` with `MÃ: lời` (CODE: message) |
| POST | `/api/v1/mcp-server` (added from ADR-0062) | Tool `propose_work` `{project, date?, issue?, intake?, text?, hours?, slot?}` for every role linked to a member; `get_my_day` also returns `projects[{id, code, name}]` (FR-PLAN-35) |
| POST | `/api/v1/mcp-server` (added from ADR-0061) | `create_intake` accepts `attachments[{name?, mime_type, data_base64}]`, at most 3 files, 5 MB each, types image/png, image/jpeg, image/webp, application/pdf; magic bytes are checked before the request is created (`ATTACHMENT_TYPE_MISMATCH`); also returns `attachments` (number of files received) (FR-AI-14) |
| POST | `/api/v1/mcp-server` (added from ADR-0058) | `tools/list` only lists tools the caller can use (`get_cto_board`, `list_work_log_pending` CTO only). New tools: `get_my_day {date?}` → `{date, member, items[{assignment_id, project, project_name, issue, issue_url, title, intake, priority, slot, hours, work_type, primary, work_status, work_status_note, plan_closed}], note, hint}`, error `MEMBER_UNMAPPED`; `update_work_status {assignment_id | issue + date?, status PLANNED\|IN_PROGRESS\|DONE\|BLOCKED, note?}` → `{assignment_id, issue, work_status, previous, at}`, error `ASSIGNMENT_NOT_FOUND` (including other people's items); `get_cto_board {date?}` → `{plan_date, overdue_total, missing_projects, projects[]}`; `get_week_summary {week_of?}` → `{week_start, week_end, days_passed, text, projects, people, process}`; `list_work_log_pending {limit?}` → `{pending, entries[{log_id, intake, title, project, summary, agent, branch, commit, verify_steps, deploy_steps, created_at}]}`. `prompts/list` → `today`, `end_day`, `week`, and `board` (CTO); `prompts/get {name, arguments{date? | week_of?}}` → one `user` message (FR-MCP-06, FR-MCP-07) |
| PATCH | `/api/v1/users/{id}` (added 2026-10-14) | `member_id` links the account to an active member that has no other account (`""` unlinks; a Developer cannot be unlinked): `MEMBER_REQUIRED`, `MEMBER_HAS_ACCOUNT`. `AccountOut` adds `member_name`. The CTO account can edit its own row (FR-NTF-06) |
| GET | `/api/v1/agent-commands/install.sh`, `/install.ps1`, `/files/{name}.md` | Public, text: the install line and the short command files (`in-today`, `in-end-day`, `in-week`, `in-board`, `fix-issue`); no data or secrets (FR-MCP-07) |
| GET | `/api/v1/auth/agent-commands` | Login session (every role). `{ commands[{name, slash (/in-...), mcp_slash, description, when, codex}], install{bash, powershell, repo} }`: the server's prompts by role as Claude Code commands, Codex prompts, and when to use them; plus the repo's `fix_issue`. `AccountOut` adds `agent_last_used_at` (FR-MCP-07) |
| POST | `/api/v1/users` (added from ADR-0058) | `{ subject, role PROJECT_OWNER\|DEVELOPER = PROJECT_OWNER, member_id? , email?, display_name? }`: `DEVELOPER` takes the email and name from member `member_id` (errors `MEMBER_REQUIRED`, `MEMBER_HAS_ACCOUNT`, `MEMBER_EMAIL_REQUIRED`); the `projects` of a Developer account are the member's projects. `GET /auth/tokens`, `POST /auth/tokens`, `DELETE /auth/tokens/{id}` are open to Developers (FR-MCP-05) |
| GET | `/api/v1/personal-tasks?from=&to=` | Every logged-in role (CTO, Project Owner, Developer). The caller's own personal tasks within the date range (default today and the next 7 days, at most 92 days): `[{id, task_date, title, note, hours, start_time, remind_at, status PLANNED\|DONE\|SKIPPED, done_at, created_at, updated_at}]` (FR-PER-01) |
| POST | `/api/v1/personal-tasks` | `{ title, task_date, hours?, start_time?, remind_at?, note?, important?, urgent? (null = computed) }`; `422 TIME_INVALID`, `HOURS_INVALID`, `TITLE_REQUIRED`. `201` returns the task with `important, urgent, urgent_effective, quadrant 1..4, quadrant_label` (FR-PER-01, FR-PER-04) |
| PATCH | `/api/v1/personal-tasks/{id}` | The fields above, `status`, `task_date: null` (removes the date, back to the matrix), `archived` (true archives, false restores); `404` when not your own (FR-PER-01, FR-PER-05) |
| GET | `/api/v1/personal-tasks/matrix?week_of=` | `{ week_start, week_end, today, tasks[], summary{today_open, today_hours, quadrants[{quadrant, label, open, hours}], rolled_over, undated, overdue} }`: tasks in the week, undated tasks and tasks left over from before, each with `rollover_count` (FR-PER-05) |
| POST | `/api/v1/personal-tasks/{id}/delegate` | `{ member_id, project_id, task_date, hours? }`. CTO: any member; Project Owner: `project_id` must be one of their projects (`404` otherwise); Developer `403`. Opens the project's plan for that day if there is none, adds a `SUPPORT` item without an Issue for the member; returns the personal task with `status DELEGATED`, `delegated_member_name`, `delegated_assignment_id`, `plan{run_id, project_id, plan_date}`. `422 TASK_NOT_OPEN`, `MEMBER_REQUIRED`, or a Planning code (`PLANNING_RUN_IMMUTABLE`, `OVER_CAPACITY`) (FR-PER-06) |
| GET/POST/PATCH | `/api/v1/personal-tasks` (added from FR-PER-06) | `repeat_rule` `WEEKLY:<0-6>` (Monday 0) or `MONTHLY:<1-31>`, `""` stops repeating; `422 REPEAT_INVALID`. Output adds `repeat_label`, `done_quadrant`, `delegated_*`. The CTO's `GET /planning/week/{monday}` returns `personal{done[], open[], done_total, done_hours, delegated, rollovers, schedule_share}` |
| GET | `/api/v1/personal-tasks/archived` | Your own archived tasks, newest first (FR-PER-05) |
| DELETE | `/api/v1/personal-tasks/{id}` | `204`; `404` when not your own (FR-PER-01) |
| GET | `/api/v1/planning/capacities/{date}` (added from ADR-0060) | Each row adds `personal_hours`; `available_hours` already subtracts personal task hours (FR-PER-02) |
| POST | `/api/v1/mcp-server` (added from ADR-0060) | `get_my_day` also returns `personal[{task_id, title, hours, start_time, remind_at, status, note}]`; tools `add_personal_task {title, date?, hours?, start_time?, remind_at?, note?}` and `update_personal_task {task_id, status?, title?, date?, hours?, start_time?, remind_at?, note?}` (FR-PER-03) |
| PUT | `/api/v1/private-space/master-dna` | `{ text }`. Saves the shared Master DNA |
| PUT | `/api/v1/private-space/voice?track=` | `track`: `business` (default) or `technical`; saves the voice of that track only. `default_channel` accepts long-form channels too |
| GET | `/api/v1/private-space/ideas?track=` | Adds a filter by track; each idea has `track` (or `null`) |
| GET, PUT | `/api/v1/private-space/ideas/{id}/track` | CTO only. `{ track }`, `null` means not yet assigned. `404 IDEA_NOT_FOUND` when it is not a Private Space idea |
| POST | `/api/v1/intakes/{id}/drafts` | Adds `context?` (`REAL`, `EXAMPLE`, `SOURCE`) and `commercial?` (`NONE`, `SPONSORED`, `AFFILIATE`; values other than `NONE` only on the `technical` track, otherwise `422 COMMERCIAL_NOT_FOR_TRACK`). `source_draft_id` with a `track` different from the source draft adapts it to the other direction; without `track` it keeps the source draft's direction. Adds `track?`, `goal?` (`AUTHORITY`, `DISCUSSION`, `REACH`, `CONVERSATION`), `audience?` (`SME`, `AGENCY`, `CONSULTANT`, `DEVELOPER`), `pillar?` (at most 120 characters), `group_context?` (`FNB`, `EDUCATION`, `RETAIL`, `SERVICE`, `AGENCY`, `CONSULTING`). With `group_context` the channel becomes `FACEBOOK_GROUP` and `audience` is dropped. Without `track` it follows the idea's track, then `business`. The returned draft carries these fields |

Long posts and the notebook (FR-CNT-05, FR-CNT-06, ADR-0036):

| Method | Path | Notes |
|---|---|---|
| POST | `/api/v1/intakes/{id}/drafts` | `channel` adds `BLOG`, `VIDEO_SCRIPT`; `goal` adds `FOLLOW`; `audience` adds `AI_USER`; `outline?` (only with the two long-form channels, otherwise `422 OUTLINE_NOT_FOR_CHANNEL`). If `source_draft_id` points to an outline, the post is written from that outline. The returned draft has `kind`: `POST` or `OUTLINE` |
| PATCH | `/api/v1/intakes/{id}/drafts/{draft_id}` | `text` at most 30,000 characters |
| GET | `/api/v1/private-space/notes?track=` | CTO only. Notes of one track, in the order `FACT`, `PROOF`, `DECISION`, `RESULT` |
| POST | `/api/v1/private-space/notes` | `201`. `{ track, kind, text }`, `text` 3 to 1,000 characters. `409 NOTES_FULL` when the track already has 60 notes |
| DELETE | `/api/v1/private-space/notes/{note_id}` | `204`; `404 NOTE_NOT_FOUND` |

Week plan, approval and publishing flow (FR-CNT-07..10, ADR-0037, ADR-0038):

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/private-space/plan?week=` | CTO only. `week` is a Monday (default this week, Vietnam time); other days return `422 WEEK_INVALID`. Returns `tracks` (per track: `slots`, `stats`, `request`), `rhythm`, `editable` |
| PUT | `/api/v1/private-space/plan/rhythm?track=` | `{ slots: [{ weekday 1..7, time "HH:MM"?, channel, pillar? }] }`, at most 7 slots |
| POST | `/api/v1/private-space/plan/propose` | `202`. `{ track, week_start, keywords? }`. `409 WEEK_NOT_OPEN` outside this week and next week; `409 NO_OPEN_SLOT` when no empty slot is left. Poll `GET …/plan` until `request.status` is no longer `PENDING` |
| GET | `/api/v1/private-space/plan/slots/{id}` | One slot |
| PATCH | `/api/v1/private-space/plan/slots/{id}` | Only changes the fields sent: `intake_id` (`null` to remove), `skipped`, `dismiss`. `409 SLOT_LOCKED` when the slot holds an approved post |
| POST | `/api/v1/private-space/plan/slots/{id}/accept` | Confirms the AI's proposal. Returns `{ slot, created_idea_id }`; `created_idea_id` has a value when a new idea was created |
| POST | `/api/v1/intakes/{id}/drafts/{draft_id}/approve` | `{ slot_id?, scheduled_for? }`. `409 SLOT_TAKEN` when the slot is skipped or holds another idea or post; `422 OUTLINE_NOT_POSTABLE` for outlines |
| DELETE | `/api/v1/intakes/{id}/drafts/{draft_id}/approve` | Unapproves. `409 DRAFT_POSTED` when the post is already published |
| PATCH | `/api/v1/intakes/{id}/drafts/{draft_id}` | Adds `posted_at?`, `posted_url?` together with `posted: true`. `409 DRAFT_APPROVED` when editing the text of an approved draft; `422 POSTED_IN_FUTURE` |
| GET | `/api/v1/publish/queue?channel=` | No login. `Authorization: Bearer <PUBLISH_API_KEY>`. See `docs/stable/publish-flow.md` |
| POST | `/api/v1/publish/events` | No login. Signed with `X-Intake-Timestamp` and `X-Intake-Signature`. See `docs/stable/publish-flow.md` |

The returned draft also has `approved_at`, `scheduled_for`, `posted_url`, `posted_via` (`MANUAL` or `WEBHOOK`), `publish_error`, `slot_id`.

Watch sources and signals (FR-CNT-11, FR-CNT-12, ADR-0039):

| Method | Path | Notes |
|---|---|---|
| GET, POST | `/api/v1/private-space/watch/sources` | CTO only. Add: `{ url, track: business, technical or both, label?, kind?, note? }`. `409 SOURCE_EXISTS`, `409 SOURCES_FULL` (80 sources) |
| PATCH, DELETE | `/api/v1/private-space/watch/sources/{id}` | Changes `track`, `active`, `label`, `note`; only the fields sent are changed |
| GET, PUT | `/api/v1/private-space/watch/keywords?track=` | Returns `pillars` (pillars and keywords), `request` (suggestion status), `suggested` (suggestions not yet kept). Save: `{ pillars: { "<trụ>": [từ khóa] } }` (`<pillar>`: [keywords]), at most 12 per pillar |
| POST | `/api/v1/private-space/watch/keywords/suggest?track=` | `202`. Poll `GET …/keywords` until `request.status` is no longer `PENDING`. `409 NO_PILLARS` |
| GET, PUT | `/api/v1/private-space/watch/demand?track=` | `{ wanted_per_week 0..50, weekday 1..7, time "HH:MM", lookback_days 1..30 }`. Also returns `deadline`, `window_start`, `received`, `remaining`, `accept_up_to`. `GET /api/v1/watch/config` returns the same block in each track's `demand` |
| POST | `/api/v1/private-space/prompt-preview` | CTO only (FR-CNT-14). `{ track, voice?, master_dna?, intake_id?, channel, outline?, goal?, audience?, pillar?, group_context?, angle?, source_draft_id?, context?, commercial? }`; `voice` and `master_dna` are the content currently on screen; if left empty the saved version is used. Returns `prompt_version`, `model`, `system_prompt`, `blocks` (`key`, `trust`: `CHOICE`, `AUTHOR`, `DATA`, `UNTRUSTED`; `text`, `chars`, `cuts`), `message_chars`, `placeholder`. Does not call AI, saves nothing |
| POST | `/api/v1/private-space/voice-trial` | CTO only (FR-CNT-16). `{ track, voice?, master_dna?, channel, idea? }`; `voice` and `master_dna` are the content currently on screen, `idea` is one line ≤ 500 characters (empty uses a generic scenario). Calls AI immediately (the drafting prompt with a `Trial` line), returns `{ text, prompt_version, model, message_chars }`. Saves nothing; writes one audit event `private_space.voice_tried`. `503` when AI does not respond |
| GET | `/api/v1/private-space/watch/health` | CTO only (FR-CNT-13). `last_config_at`, `last_signal_at`, and per track: `warning`, `reason` (`ROUTES_CLOSED`, `NO_SOURCES`, `NO_KEYWORDS`, `FLOW_SILENT`, `NOTHING_SENT`), `checked_at`, `received`, `remaining`, `deadline` |
| POST | `/api/v1/private-space/watch/health/check` | Runs a check now, returns the same shape |
| GET | `/api/v1/private-space/watch/signals?track=&state=` | `state`: `NEW` (default), `USED`, `DISMISSED` |
| POST | `/api/v1/private-space/watch/signals/{id}/idea` | Turns it into an idea of that track. Returns `{ signal, idea_id }` |
| DELETE | `/api/v1/private-space/watch/signals/{id}` | Dismisses the signal |
| GET | `/api/v1/watch/config` | No login. `Authorization: Bearer <WATCH_API_KEY>`. See `docs/stable/watch-flow.md` |
| POST | `/api/v1/watch/signals` | No login. Signed with `X-Intake-Timestamp` and `X-Intake-Signature`. See `docs/stable/watch-flow.md`. From ADR-0068: items also accept `project`, `via`, `priority`; `config` also returns `projects[]` and `terms[]` in each pillar |

## Project context and request details (FR-AI-12, ADR-0032)

| Method | Path | Notes |
|---|---|---|
| GET, PUT | `/api/v1/projects/{ref}/brief` | Send `{ "brief" }`, at most 4000 characters; returns `{ "brief", "ai_source": "PACK" \| "BRIEF", "pack_approved_at", "pack_sections": [tên mục] }` (section names), telling whether AI is reading the approved context pack (sections 1 and 2) or the free-text box (FR-CTX-05). CTO or the project's Project Owner; out of scope returns `404` |
| GET | `/api/v1/intakes/{id}` (addition) | Adds `details` (or `null`): `where`, `steps`, `expected`, `subtasks`, `acceptance`, `open_questions`, `related[]` with `id`, `title`, `url` |
| PATCH | `/api/v1/intakes/{id}/review` (addition) | Also accepts optional `details`: `where`, `subtasks`, `acceptance` (each list at most 12 lines, 300 characters per line). Other parts of the details stay unchanged |
| POST | `/api/v1/intakes/{id}/split` | `{ expected_version, items[] }`, 2 to 8 lines, at most 300 characters each (FR-APR-09). Returns `original` and `children`. `409 NOT_SPLITTABLE` when the request already has a decision; `409 STALE_VERSION` |

The approval snapshot (`approval_snapshots.payload`) also has a `details` key when the request has details.

The `details` part also has `split_suggested` (AI thinks the subtasks should be separate requests).

| Method | Path | Notes |
|---|---|---|
| PUT | `/api/v1/intakes/{id}/clarifications` | `{ expected_version, answers[], reanalyse }` (FR-APR-10). Each element: `question`, `answer` (at most 1000 characters) or `skipped`. `reanalyse: true` queues a new analysis. `409 DECISION_LOCKED` when already approved; `409 STALE_VERSION` |
| POST | `/api/v1/intakes/{id}/ready` | `{ expected_version }`. Moves a request that is "Needs clarification" ("Cần làm rõ") or postponed back to waiting for approval. `409 NOT_WAITING`, `409 REVIEW_REQUIRED` (missing title or summary) |

The `details` part also has `clarifications[]` with `question`, `answer`, `skipped`.

| Method | Path | Notes |
|---|---|---|
| DELETE | `/api/v1/intakes/{id}` | Deletes permanently (FR-APR-11). Returns `{ deleted, public_id, attachments_left }`. `409` with `INTAKE_DECIDED`, `INTAKE_PROCESSING`, `INTAKE_HAS_EXTERNAL`, `INTAKE_PLANNED` |
| POST | `/api/v1/intakes/{id}/duplicate` | `{ of, expected_version }`; `of` is the code or ID of the request being kept, in the same project (FR-APR-12). `409 DUPLICATE_TARGET_NOT_FOUND`, `DUPLICATE_TARGET_INVALID`, `DECISION_LOCKED` |
| POST | `/api/v1/intakes/{id}/duplicate-issue` | `{ issue, expected_version }`; `issue` is the number of an existing GitLab Issue of the project (`"22"` or `"#22"`), which must be in the loaded GitLab data (FR-APR-12, since 2026-10-19). `409 DUPLICATE_TARGET_NOT_FOUND` (not an Issue of the project), `DUPLICATE_TARGET_INVALID` (an Issue created from this same request), `DECISION_LOCKED` |
| DELETE | `/api/v1/intakes/{id}/duplicate?expected_version=N` | Removes the duplicate mark (both duplicate-of-request and duplicate-of-Issue); the request returns to waiting for approval. `409 NOT_A_DUPLICATE` |

`IntakeOut` also has `duplicate_of_id`, `duplicate_issue` (`system`, `external_id`, `title`, `url`; null when not a duplicate of an Issue) and, in `GET /intakes/{id}`, `duplicate_of` with `id`, `public_id`, `title`. MCP `get_intake` returns the same `duplicate_issue`.

## First-time setup (FR-SETUP-01..09, ADR-0069, ADR-0071)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/setup` | CTO only. Returns `completed`, `has_project`, `has_private_space`, `sample_available`. `completed` is true when setup has been marked done or a real project exists |
| POST | `/api/v1/setup/private-sample` | CTO only. Loads the fictional sample DNA set into the Private Space (opens the space if it does not exist). `422 SAMPLE_INVALID` or `SAMPLE_MISSING` when the sample set is broken; returns the status like GET |
| POST | `/api/v1/setup/complete` | CTO only. Marks setup as done; calling again is harmless; returns the status like GET. When the wizard flag is on and there is no AI route: `422 AI_KEY_REQUIRED`. `GET /setup` also has `ai_ready`, `wizard` |
| POST | `/api/v1/setup/demo-project` | CTO only, only when the wizard flag is on (off: `422 NOT_FOUND`). Loads the fictional sample project (`demo`, key `DEM`) and marks setup as done; calling again is harmless. `422 SAMPLE_MISSING`, `SAMPLE_INVALID`, `DEMO_CODE_TAKEN`. Returns the status like GET. `GET /setup` also has `has_demo`, `demo_available`; when `has_demo`, `/setup/complete` does not require `AI_KEY_REQUIRED` |
| GET | `/api/v1/showcase` | CTO only (FR-SETUP-15). Catalog of sample projects from `app/resources/showcase.json`: `{version, groups, items[]}`, each entry has `key`, `kind` (`demo`/`real`), `name`, `summary`, `repo_url`, `languages`, `license`, `state` (`off`/`on`/`archived`), `project_code`, `sample_requests`, `in_catalog`. |
| PUT | `/api/v1/showcase/{key}` | CTO only (FR-SETUP-15). Body `{enabled}`. Enabling for the first time creates the project (`real`) or loads the sample project (`demo`); disabling sets the project to `INACTIVE`, enabling again restores the same project. `404 NOT_FOUND` when the key is not in the catalog, `409 PROJECT_CODE_TAKEN` when the project code is already taken. |
| DELETE | `/api/v1/showcase/{key}/samples` | CTO only (FR-SETUP-16). Deletes the entry's test requests (flag `test_data`, still waiting for approval); returns `{removed}`. |
| GET | `/api/v1/setup/status` | Public. `{needs_bootstrap}`; true when `FIRST_RUN_WIZARD` is on and the first account has not been created (FR-SETUP-05, ADR-0071) |
| POST | `/api/v1/setup/bootstrap` | Public, one-time, CSRF-exempt, rate limited. Body `{cto:{email,display_name,password}, owner:{...}\|null}`. Sets the CTO's session and CSRF cookies. `404` when the flag is off, `409 BOOTSTRAP_DONE`, `422` for a short password or duplicate email (FR-SETUP-06) |

## LLM keys and per-task routes (FR-AI-15..19, ADR-0070)

All CTO only. Keys are only accepted on create or edit; responses only have `key_hint` (last 4 characters) and `key_ok` (false when it cannot be decrypted).

| Method | Path | Notes |
|---|---|---|
| GET | `/api/v1/ai/providers` | Provider list: `id`, `name`, `base_url`, `enabled`, `key_hint`, `key_ok`, `extra_body`, `last_test_at`, `last_test_ok`, `last_test_error` |
| POST | `/api/v1/ai/providers` | `{ name (≤32), base_url, api_key, enabled?, extra_body? }`. `422 AI_BASE_URL_INVALID`, `409 AI_PROVIDER_NAME_TAKEN` |
| PATCH | `/api/v1/ai/providers/{id}` | Same fields as above, all optional; an empty `api_key` keeps the old key |
| DELETE | `/api/v1/ai/providers/{id}` | `409 PROVIDER_IN_USE` when a route still points to it |
| POST | `/api/v1/ai/providers/{id}/test` | Calls `GET {base_url}/models`. Returns `ok`, `error` (codes: `AUTH`, `TIMEOUT`, `HTTP_<n>`, `NETWORK`, `KEY_UNREADABLE`), `models[]` |
| POST | `/api/v1/ai/providers/{id}/probe` | `{ kind, model }` (`kind`: `vision` or `stt`). Tests the model with a sample image (the number 482) or 1.5 seconds of sample audio; stores the result per (provider, model, kind). Returns `kind`, `model`, `ok`, `error` (`NOT_SUPPORTED`, `NOT_READ`, `AUTH`, `TIMEOUT`, `NETWORK`, `KEY_UNREADABLE`, `QUOTA` (the provider returns 429: quota exhausted or the model is outside the key's plan), `MODEL_NOT_FOUND` (returns 404: wrong model name or the model is discontinued for new keys), `PROVIDER_TRANSIENT` (returns 5xx during the image test), `HTTP_<n>`), `checked_at`. Only `NOT_SUPPORTED` and `NOT_READ` from the image test make the `vision` route skip the `default` model (FR-AI-22). `422 AI_PROBE_KIND_INVALID`, `422 AI_MODEL_INVALID`. CTO only (FR-AI-21) |
| GET | `/api/v1/ai/routes` | Seven rows `default`, `normalize`, `report`, `meeting`, `vision`, `content`, `stt` (`stt` does not fall back to `default`; when unset it shows the ElevenLabs key from `.env` with `source: env`): `task`, `provider_id`, `provider_name`, `model`, `source` (`route`, `default`, `env`, `none`), `check_ok`, `check_error`, `checked_at` (the sample test result of the model currently serving; the `default` row carries the image test result). `vision` does not fall back to `default` when that model failed the image test (FR-AI-22) |
| PUT | `/api/v1/ai/routes/{task}` | `{ provider_id, model }`; `provider_id: null` deletes the route. `404 AI_TASK_UNKNOWN`, `422 AI_PROVIDER_NOT_FOUND` |

`GET /api/v1/operations/status` also has `ai_configured` and `ai_source`; the old fields are unchanged.

`POST /api/v1/auth/login` accepts an email or account name in the `subject` field (FR-SETUP-07).
