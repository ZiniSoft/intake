# API và integration contracts

_Target + runtime contract 1.2 | Đối chiếu OpenAPI ngày 2026-10-01_

Các bảng ghi **runtime** chỉ liệt kê endpoint hiện có trong OpenAPI. Endpoint target chưa có code nằm ở mục 12; trạng thái kiểm chứng xem `PRODUCTION-READINESS.md`.

## 1. Auth

| Method | Path | Quyền | Kết quả |
|---|---|---|---|
| POST | `/api/v1/auth/login` | Public; rate limit là target chưa triển khai | Password và optional OTP/recovery; đặt session + CSRF cookie, cùng hạn 7 ngày (`expires_in` = 604800; `ACCESS_TOKEN_TTL_MINUTES`, FR-ID-09) |
| POST | `/api/v1/auth/password-reset/request` | Public; rate limit theo IP và cooldown theo tài khoản | Nhận username hoặc email; luôn trả 202 cùng thông báo. Nếu tài khoản active tồn tại, gửi link Mailgun một lần; không lộ account enumeration |
| POST | `/api/v1/auth/password-reset/confirm` | Public + reset token | Nhận token và mật khẩu mới ≥8 ký tự; token lưu dạng hash, hết hạn 30 phút, chỉ dùng một lần; tăng `auth_version` để vô hiệu cookie cũ |
| POST | `/api/v1/auth/logout` | Authenticated | Xóa session/CSRF cookie; persistent server-side revocation là target |
| GET | `/api/v1/auth/me` | Authenticated | Role-safe identity |
| POST | `/api/v1/auth/mfa/setup` | Authenticated + step-up | Nhận mật khẩu hiện tại và OTP hiện tại khi MFA đã bật; tạo pending secret 10 phút mà không đổi factor đang hoạt động |
| POST | `/api/v1/auth/mfa/confirm` | Authenticated | Xác nhận pending TOTP, đổi factor nguyên tử, tăng `auth_version`, thu hồi token cá nhân cũ và cấp lại cookie cho trình duyệt vừa xác minh |
| POST | `/api/v1/auth/mfa/recovery-codes` | Authenticated + MFA đã bật + step-up | Nhận mật khẩu và OTP hiện tại; rotate recovery code đã hash |

### Phân quyền theo dự án (ADR-0022)

- `GET /auth/me` trả `role`, `project_ids` (`null` với CTO, danh sách với Project Owner) và `must_change_password`. Khi `must_change_password` là true, mọi API nghiệp vụ trả 403 `PASSWORD_CHANGE_REQUIRED` cho tới khi gọi `POST /auth/password`.
- Project Owner gọi một tài nguyên của dự án không được cấp nhận 404 như thể nó không tồn tại. Danh sách (`/intakes`, `/approvals`, `/meetings`, `/projects`) và phần `summary` chỉ tính trong phạm vi.
- Chỉ CTO: `/users`, `/reports/*`, `/planning/*`, `/operations/*`, `POST`/`PATCH /projects`, `/projects/integration-probes`, thuật ngữ chung.
- `PUT /projects/{code}/team` nhận `owner_member_id` (hoặc null) và `member_ids`; Owner tự được thêm vào Member. Khi việc chọn Owner tạo hoặc mở lại tài khoản, response có `issued` gồm tên đăng nhập và `temporary_password`, đúng một lần. Lỗi: `OWNER_EMAIL_REQUIRED`, `MEMBER_NOT_ACTIVE`. Owner là hồ sơ nhân sự của CTO thì `issued` là `null`, không tạo tài khoản, không cấp quyền thêm (FR-PLAN-37).
- `POST /users/{id}/reset-password` cũng trả `temporary_password` một lần. `POST /users` và `PATCH /users/{id}` từ chối cấp dự án (`PROJECTS_ASSIGNED_ON_PROJECT`).

## 2. Project catalog

Runtime chỉ có `GET /api/v1/projects` cho CTO. Project và integration mapping hiện được seed/cấu hình bằng environment; CRUD/test API là target chưa triển khai.

Từ 2026-10-05 (ADR-0020), chỉ CTO:

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/projects` | Danh sách kèm `kind`, liên kết GitLab/GitHub và trạng thái bật đồng bộ; không trả cấu hình Plane |
| POST | `/api/v1/projects` | `name`, `code` (chữ thường, số, gạch nối), `intake_key` (2-8 chữ in hoa), `kind`; dự án phần mềm nhận GitLab hoặc GitHub đã probe. Trường cấu hình Plane bị từ chối `422`. |
| PATCH | `/api/v1/projects/{code}` | Đổi tên, loại, trạng thái hoặc thêm liên kết; áp cùng quy tắc theo loại. Chỉ CTO: `switch_delivery: "GITHUB"` kèm `github_repository`, `github_token_ref`, `github_probe_id` đã kiểm chuyển dự án GitLab sang GitHub cho việc mới; `422 DELIVERY_SWITCH_NOT_APPLICABLE` khi dự án không phải phần mềm đang liên kết GitLab hoặc đã có GitHub, `GITHUB_LINK_REQUIRED`, `GITHUB_LINK_NOT_VERIFIED`, `DELIVERY_SYSTEM_CONFLICT` khi gửi kèm GitLab. `ProjectOut.previous_delivery { system, project_external_id, project_url, switched_at }` sau khi chuyển (FR-PRJ-13, ADR-0079) |
| GET | `/api/v1/projects/{code}/delivery-switch` | Chỉ CTO. `{ from_system: "GITLAB", to_system: "GITHUB", open_issues }` trước khi chuyển; `422 DELIVERY_SWITCH_NOT_APPLICABLE`, `404` khi không có dự án (FR-PRJ-13) |
| GET | `/api/v1/projects/{ref}/context` | CTO hoặc Project Owner của dự án. Hồ sơ ngữ cảnh như lần đọc gần nhất: `{ project_id, source (REPO|PASTED), path, sha, fetched_at, meta, sections{key: {number, title, required, to_ai, present, lines}}, score, band (FULL|PARTIAL|MISSING), missing[], stale_days, error, has_content, approved, approved_sha, approved_at, content, pending_suggestions }`; chưa có thì `band MISSING`, 6 mục thiếu (FR-CTX-03, FR-CTX-04) |
| POST | `/api/v1/projects/{ref}/context/read` | `202 { project_id, queued }`; `422 NO_MAIN_REPO` khi dự án không có GitLab/GitHub đang bật (FR-CTX-03) |
| PUT | `/api/v1/projects/{ref}/context` | `{ content }` tối đa 60 KB; lưu như bản `PASTED`, chấm điểm, chưa duyệt (FR-CTX-03) |
| POST | `/api/v1/projects/{ref}/context/approve` | Chỉ CTO; `422 CONTEXT_EMPTY` khi chưa có hồ sơ (FR-CTX-03) |
| GET | `/api/v1/projects/{ref}/context/suggestions` | CTO hoặc Project Owner của dự án. Gợi ý cho hồ sơ, mới nhất trước: `[{ id, project_id, intake_id, intake_public_id, work_log_id, text, suggested_by, suggested_by_name, agent_name, status (PENDING|APPLIED|DISMISSED), decided_by, decided_by_name, decided_at, created_at }]` (FR-CTX-04) |
| POST | `/api/v1/projects/{ref}/context/suggestions/{id}/{applied\|dismissed}` | Chỉ CTO; `409 ALREADY_DECIDED` khi đã quyết, `422 DECISION_UNKNOWN` với từ khác, 404 khi gợi ý không thuộc dự án (FR-CTX-04) |
| POST | `/api/v1/mcp-server` (thêm từ ADR-0063) | Tool `get_project_context {project}` → `{project, band, score, missing[], approved, source, sha, fetched_at, sections{key: {number, title, required, present, lines}}, content, pending_suggestions, note}`; `list_projects` trả thêm `context_band`; `log_work` nhận `context_suggestions[]` và trả `context_suggestions` (số gợi ý đã ghi) (FR-CTX-04) |
| GET | `/api/v1/agent-commands/files/context-template.md` | Công khai, khuôn hồ sơ (FR-CTX-01) |
| GET, PUT | `/api/v1/projects/{ref}/report-codes` | `{ codes: string[] }` (tối đa 20, lưu viết hoa, bỏ trùng). CTO hoặc Project Owner của dự án; `409 REPORT_CODE_TAKEN` khi mã đã là mã chính hoặc mã phụ của dự án khác. Thư báo cáo ghi mã đó về dự án này (FR-EML-12) |
| POST | `/api/v1/projects/integration-probes` | `system=GITLAB|GITHUB`, `action`, `reference`; trả 202 với probe `PENDING`. `PLANE` bị từ chối `422`. `action=ACCESS` (FR-INTG-23) nhận thêm `token_ref` cho GitHub, `reference` tùy chọn với GitLab; kết quả `{system, ok, checks:[{key, status, detail}]}`, `status` là `OK|MISSING|WARN|UNKNOWN`. GitHub `issues_write` `MISSING` có thể mang `detail` là mã nguyên nhân `public_read_only`, `read_only` hoặc `org_policy`; `metadata` `MISSING` mang `org_policy` hoặc tên repo. |
| GET | `/api/v1/projects/integration-probes/{id}` | Client hỏi lại tới khi `DONE` hoặc `FAILED` |

`action=MEMBERS` (chỉ GitLab, `reference` là đường dẫn dự án) trả danh sách người dùng đang hoạt động của dự án (`id`, `name`, `username`) để gán cho nhân sự. `PUT /api/v1/planning/members/{id}` thay toàn bộ thông tin và danh sách dự án của một nhân sự; dự án bị bỏ ra chỉ chuyển `active=false`; `gitlab_user_external_id` chỉ hợp lệ với dự án `SOFTWARE`.

GitHub (ADR-0021): probe nhận `system=GITHUB` kèm `token_ref` là tên biến token; `action=TOKENS` trả tên các biến `GITHUB_TOKEN_*` mà integration worker đang có (không bao giờ trả giá trị); `MEMBERS` trả những người có thể được giao Issue. `POST`/`PATCH /projects` nhận `github_repository`, `github_token_ref`, `github_probe_id`; gửi cả GitLab lẫn GitHub trả `DELIVERY_SYSTEM_CONFLICT`. `approved_route` của Intake nhận thêm `GITHUB`; khi duyệt, `GITLAB` và `GITHUB` được đổi cho khớp nơi giao việc của dự án.

Probe được integration worker xử lý qua task `intake.integration.probe`, không qua outbox. Liên kết chỉ được lưu khi kèm ID của một probe `CHECK` thành công cho đúng tham chiếu trong vòng 30 phút.

## 3. Intake

| Method | Path | Ghi chú |
|---|---|---|
| POST | `/api/v1/intakes` | Tạo intake + source; hỗ trợ `Idempotency-Key`. `channel` thêm `FEEDBACK` (chỉ do "Nhận" góp ý tạo, FR-FBK-03) |
| POST | `/api/v1/feedback` | Mọi vai. `{ project, text }` → `201 FeedbackOut { id, project_id, project_code, project_name, member_id, member_name, user_id, transport (WEB\|TELEGRAM\|AGENT), text, status (PENDING\|ACCEPTED\|REJECTED), intake_id, intake_public_id, decided_by, decided_by_name, decided_at, decision_note, files[{id, name, mime_type, size_bytes}], created_at }`; dự án phải là dự án nhân sự của tài khoản đang có mặt hoặc dự án mình quản (ngoài ra 404); Developer chưa gắn nhân sự `422 MEMBER_UNMAPPED`; `422 TEXT_REQUIRED` (FR-FBK-01, ADR-0064) |
| GET | `/api/v1/auth/me` | Thêm `member_id` (nhân sự gắn với tài khoản, hoặc `null`) (FR-FBK-02) |
| POST | `/api/v1/feedback/{id}/files` | Multipart `file`, ảnh hoặc PDF 5 MB, tối đa 3 (`422 TOO_MANY_FILES`); chỉ khi còn `PENDING` (`409 ALREADY_DECIDED`) (FR-FBK-01) |
| GET | `/api/v1/feedback` | `project_id?`, `status?`, `mine?`, `limit?`; `mine=true` trả góp ý của mình ở mọi dự án, không thì theo dự án mình quản; Developer luôn chỉ thấy của mình (FR-FBK-02) |
| GET | `/api/v1/feedback/{id}`, `/api/v1/feedback/{id}/files/{file_id}` | Một góp ý; tệp trả bytes `inline` (FR-FBK-02) |
| POST | `/api/v1/feedback/{id}/accept` | CTO hoặc Project Owner (`403` với Developer). `{ note? }` → Intake kênh `FEEDBACK` tạo xong, `intake_id`, `intake_public_id`; `409 ALREADY_DECIDED` (FR-FBK-03) |
| POST | `/api/v1/feedback/{id}/reject` | `{ note }` bắt buộc (`422 NOTE_REQUIRED`); `409 ALREADY_DECIDED` (FR-FBK-03) |
| GET | `/api/v1/work` | `?project=<mã hoặc id>` bắt buộc, `?include_closed=`; bảng việc nội bộ của dự án (ADR-0066, FR-WRK-02) trong phạm vi dự án của người gọi (CTO, Project Owner, nhân sự của dự án; ngoài phạm vi `404`). Mỗi dòng `WorkOut { id, code, project_id, project_code, project_name, project_kind, title, description, status: DISCUSS\|READY\|IN_PROGRESS\|ACCEPTANCE\|DONE\|CANCELLED, priority, member_id, member_name, due_date, intake_id, intake_public_id, intake_status, issue_system, issue_external_id, issue_url, outcome: null\|ISSUE_PENDING\|ISSUE, issue_pending, closed_note, comment_count, version, created_by, created_by_name, created_at, updated_at, closed_at }` |
| POST | `/api/v1/work` | CTO hoặc Project Owner. `{ project, title, description?, priority?=P3, member_id?, due_date?, status?=DISCUSS }` → `201 WorkOut`; `422 TITLE_REQUIRED\|MEMBER_NOT_IN_PROJECT\|STATUS_INVALID` (FR-WRK-01) |
| GET | `/api/v1/work/{id}` | `WorkDetail = WorkOut + comments[{ id, user_id, user_name, mine, body, created_at }] + history[{ at, actor_name, event_type, details }]` (FR-WRK-02) |
| PATCH | `/api/v1/work/{id}` | CTO hoặc Project Owner. `{ expected_version, title?, description?, priority?, member_id?, clear_member?, due_date?, clear_due? }`; `409 STALE_VERSION\|WORK_CLOSED` (FR-WRK-01) |
| POST | `/api/v1/work/{id}/move` | `{ status, expected_version, note? }`; Developer chỉ với việc giao cho mình (`403 NOT_YOUR_WORK`) giữa DISCUSS/READY/IN_PROGRESS/ACCEPTANCE (`422 MOVE_NOT_ALLOWED`); `422 NOTE_REQUIRED` khi vào CANCELLED; `409 STALE_VERSION\|WORK_LOCKED_BY_ISSUE` (FR-WRK-03) |
| POST | `/api/v1/work/{id}/comments` | `{ body }` (2..5000) → `201 WorkDetail` (FR-WRK-04) |
| DELETE | `/api/v1/work/{id}/comments/{comment_id}` | Của mình, hoặc CTO; `403 NOT_YOURS`; `204` (FR-WRK-04) |
| POST | `/api/v1/work` (thêm từ FR-WRK-08) | `template?: VIDEO` tạo kèm sáu bước là việc con; `WorkOut` thêm `template, steps_total, steps_done, parent_id, parent_code, step, step_label, step_order, evidence_required`; `WorkDetail.steps[]` trên việc mẹ; `GET /work` trả cả các bước của việc mẹ trên bảng |
| POST | `/api/v1/work/{id}/move` (thêm từ FR-WRK-09) | `422 EVIDENCE_REQUIRED` (bước cần link hoặc `note`), `422 NOTE_REQUIRED` khi trả từ ACCEPTANCE về, `409 STEPS_OPEN` khi việc mẹ còn bước mở |
| GET | `/api/v1/auth/me` (thêm từ ADR-0067) | `projects[{ id, code, name, kind }]` của người gọi và `mode: MARKETING\|FULL` (FR-MKT-03) |
| GET | `/api/v1/work` (thêm) | `?week=YYYY-MM-DD` (thứ Hai) kèm mọi bài có bản kênh đăng trong tuần (FR-MKT-04). `WorkOut` thêm `channel, format, campaign, urgent, channels[{ id, channel, publish_at, status: DRAFT\|READY\|PUBLISHED, published_url, language }], next_publish_at`; `WorkStatus` thêm `APPROVED` |
| POST | `/api/v1/work` (thêm) | `channel?, format?, campaign?, urgent?, channels[{ channel, publish_at?, language? }]` (FR-MKT-01); `PATCH /work/{id}` thêm `channel, format, campaign, clear_campaign, urgent` |
| POST, PATCH, DELETE | `/api/v1/work/{id}/channels[/{channel_id}]` | Bản kênh: thêm (`422 CHANNEL_UNKNOWN\|CHANNEL_EXISTS`), sửa `{ publish_at?, clear_publish?, status?, published_url? }` (Developer chỉ bài của mình, không đổi ngày; `422 URL_INVALID`), bỏ (`409 CHANNEL_PUBLISHED`) (FR-MKT-01) |
| GET | `/api/v1/work/review` | CTO, Project Owner: bài ở `ACCEPTANCE` trong dự án mình quản (FR-MKT-05) |
| GET | `/api/v1/work/campaigns` | `?project=` → `[{ name, count }]` (FR-MKT-06) |
| POST | `/api/v1/work/bulk` | CTO, PO. `{ project, rows[{ title, channel?, publish_at?, member_id?, campaign?, description? }] }` (1..50) → `201 [{ title, id?, code?, error? }]` (FR-MKT-06) |
| POST | `/api/v1/work/bulk-update` | CTO, PO. `{ ids (1..100), member_id?, clear_member?, publish_at?, status? }` → `{ changed, errors[{ id, error }] }` (FR-MKT-06) |
| GET, PUT | `/api/v1/channel-rules[/{code}]` | Đọc: mọi vai; sửa: CTO, `ChannelRuleUpdate` các trường của luật, `422 RULE_VALUE_INVALID`, `404` (FR-MKT-02) |
| POST | `/api/v1/meetings/{id}/note/items/work` (thêm) | mỗi mục nhận `channel?`, `publish_at?`; dự án `NON_CODE` tạo bài ở Ý tưởng kèm bản kênh mặc định (FR-MKT-07) |
| PATCH | `/api/v1/work/{id}/channels/{channel_id}` (thêm) | `text?` (tối đa 60.000), `clear_text?`; `WorkChannelOut` thêm `text`, `short_link { code, url, target_url, clicks, created_at }`. Gửi duyệt (`/move` sang `ACCEPTANCE`) trả `422 CHANNEL_TEXT_TOO_LONG` khi một bản vượt mức dài của kênh (FR-MKT-11) |
| POST | `/api/v1/work/{id}/channels/{channel_id}/link` | CTO, PO. `{ target_url }` → `PostLinkOut`; mã giữ nguyên khi gọi lại; `422 TARGET_INVALID` (FR-MKT-12) |
| GET | `/p/{code}` và `/api/v1/p/{code}` | Không đăng nhập, không envelope: `302` tới trang đích kèm UTM, ghi click; `404` khi mã lạ (FR-MKT-12) |
| GET, PUT | `/api/v1/projects/{code}/watch/pillars` | CTO, PO của dự án `NON_CODE` (`409 WATCH_NOT_FOR_PROJECT` với dự án khác, `403` Developer). PUT `{ pillars[{ name, description?, audience?, channels[], share_pct, keywords[{text, kind, priority} \| chuỗi], samples[{title?, url}], avoid? }] }` (tối đa 6; `422 PILLARS_TOO_MANY`, `PILLAR_DUPLICATE`) (FR-MKT-08) |
| GET, PUT | `/api/v1/projects/{code}/watch/settings` | `{ networks?, times?, weekdays?, scan_every_hours? }` → `{ networks, open_networks, schedule{times, weekdays}, scan_every_hours, scan_hours, max_ai_runs_per_day, ai_runs_per_week }`; `422 NETWORK_NOT_OPEN`, `SCHEDULE_INVALID` (FR-MKT-08, FR-MKT-10) |
| GET, POST, PATCH, DELETE | `/api/v1/projects/{code}/watch/sources[/{id}]` | Như `/private-space/watch/sources`, mạch luôn `content` (FR-MKT-08) |
| GET, PUT, POST | `/api/v1/projects/{code}/watch/keywords[/suggest]`, `GET, PUT …/demand`, `GET …/health`, `POST …/health/check` | Như các đường của khu riêng, cho mạch `content` của dự án (FR-MKT-08) |
| GET | `/api/v1/watch-topics?project=` | Mọi vai trong dự án. `{ week_start, has_sources, kept_this_week, refresh_left, built_at, schedule, topics[{ id, title, why, angles[], channels[], caution, pillar, score, state, ai_written, work_id, sources, signals[{ id, title, url, host, keyword, published_at, via }] }] }` (FR-MKT-09) |
| POST | `/api/v1/watch-topics/refresh?project=` | CTO, PO. `202 { status: PENDING, refresh_left }`; `429 TOPICS_LIMIT` sau 3 lần một ngày (FR-MKT-10) |
| POST | `/api/v1/watch-topics/{id}/post?project=` | CTO, PO. `{ mode: post \| series, angle?, member_id?, week? }` → `201 WorkDetail`; `409 TOPIC_CLOSED` (FR-MKT-09) |
| DELETE | `/api/v1/watch-topics/{id}?project=` | CTO, PO. Bỏ chủ đề và tín hiệu của nó (FR-MKT-09) |
| GET, PUT | `/api/v1/settings/watch-platforms[/{code}]` | Đọc: mọi vai; sửa: CTO `{ label?, enabled?, via?, note? }`, `422 PLATFORM_VALUE_INVALID` (FR-MKT-08) |
| GET, PUT | `/api/v1/settings/watch-limits` | Đọc: mọi vai; sửa: CTO `{ max_ai_runs_per_day 0..8 }` (FR-MKT-10) |
| POST | `/api/v1/watch/inbound/{connector_id}` | Không đăng nhập. `X-Intake-Token: <bí mật cổng>` hoặc Bearer; JSON ≤ 512 KB, ≤ 50 mục; `404` cổng lạ hoặc đã đóng, `401` sai bí mật, `413`, `422 BATCH_INVALID`; trả `{ accepted, duplicates, rejected[], problems[] }` (FR-MKT-13) |
| GET, POST | `/api/v1/settings/watch-connectors?project=` | Chỉ CTO. Tạo `{ project, name, kind?, via?, default_pillar?, mapping? }` → `201 ConnectorOut` kèm `token` một lần; `409 CONNECTORS_FULL`, `422 PILLAR_UNKNOWN\|MAPPING_INVALID` (FR-MKT-13) |
| PATCH, DELETE, POST | `/api/v1/settings/watch-connectors/{id}[/rotate\|/try]`, `GET …/{id}/deliveries`, `GET …/presets` | Chỉ CTO. `try` nhận payload JSON bất kỳ → `{ items[{…, would_reject[], notes[]}], problems[], would_accept }`, không lưu (FR-MKT-13) |
| GET | `/api/v1/projects/{code}/watch/connectors` | CTO, PO: `[{ id, name, kind, enabled, last_received_at, received_count, last_status }]` (FR-MKT-13) |
| GET | `/api/v1/publish/queue` (thêm) | Mục `kind: post_version` với `draft_id: work_channel:<id>`, `project`, `work`, `language`, `short_link` cho bản Đã duyệt và Sẵn sàng trên kênh bật `auto_publish` (FR-MKT-14) |
| POST | `/api/v1/publish/events` (thêm) | `draft_id` dạng `work_channel:<id>`: `POSTED` kèm `url` → bản `PUBLISHED`; `FAILED` ghi audit; `404 DRAFT_NOT_FOUND`, `409 DRAFT_NOT_APPROVED` (FR-MKT-14) |
| GET, PUT | `/api/v1/settings/publish-pause` | Đọc: mọi vai; sửa: CTO `{ paused }` (FR-MKT-14) |
| PUT | `/api/v1/channel-rules/{code}` (thêm) | `auto_publish?` (FR-MKT-14) |
| POST | `/api/v1/meetings/{id}/note/items/work` | CTO hoặc Project Owner của dự án họp. `{ items[{ item_id, member_id?, due_date?, status?: DISCUSS\|READY }] }` (1..50) → `201 { results[{ item_id, work_id, code, intake_id, error }], meeting }`; mỗi mục: Intake kênh MEETING tạo và duyệt tuyến WORK nguồn MEETING, Việc nhận người, hạn, cột (FR-REC-19). `MeetingNoteItemOut` thêm `work_id`, `work_code`, `can_become_work`; `WorkOut` thêm `meeting_id`, `meeting_title`, `meeting_at` |
| GET | `/api/v1/hints` | Mọi vai. `{ dismissed: string[] }`: các lời giới thiệu trang người gọi đã bấm "Đã hiểu" (FR-UI-17) |
| POST, DELETE | `/api/v1/hints/{key}/dismiss` | Ghi hoặc bỏ "Đã hiểu" cho `key` (`page.work`, `page.my_day`, `page.feedback`, `page.account`); `422 HINT_KEY_INVALID` (FR-UI-17) |
| POST | `/api/v1/hints/{key}/opened` | Một lượt mở hint, `204`; đếm cho thống kê (FR-UI-17) |
| GET | `/api/v1/hints/stats` | Chỉ CTO. `?days=` (1..90, mặc định 7) → `{ days, since, opened[{ key, opens, people }], dismissed[{ key, people }] }` (FR-UI-17) |
| (trang) | `/huong-dan` | Không đăng nhập: trang hướng dẫn công khai; chỉ có lần kiểm phiên sẵn có của app, không gọi `/hints` hay API dữ liệu nào. Đăng nhập: bản trong app, gọi ba endpoint `hints` ở trên. Bản tĩnh cùng nội dung trên GitHub Pages của repo công khai; `?lang=en\|vi` (FR-UI-18, ADR-0078) |
| POST | `/api/v1/work/{id}/links` | Ai thấy việc. `{ url, note? }` → `201 WorkDetail` với `links[{ id, url, note, source: USER\|AGENT, added_by, added_by_name, mine, created_at }]`; `422 URL_INVALID\|TOO_MANY_LINKS` (FR-WRK-07). `WorkOut` thêm `link_count` |
| DELETE | `/api/v1/work/{id}/links/{link_id}` | Của mình, hoặc CTO; `403 NOT_YOURS`; `204` (FR-WRK-07) |
| POST | `/api/v1/work/{id}/links/file` | Ai thấy việc. `multipart/form-data`: `file` (JPG, PNG, WebP hoặc PDF, ≤ 5 MB, magic bytes khớp `content-type`) và `note?` ≤ 300 ký tự → `201 WorkDetail`; dòng link có thêm `file_name`, `mime_type`, `size_bytes` và `url` là đường tải xuống. `422 FILE_TYPE_UNSUPPORTED\|FILE_TYPE_MISMATCH\|FILE_TOO_LARGE\|FILE_EMPTY\|TOO_MANY_LINKS` (FR-WRK-10) |
| GET | `/api/v1/work/{id}/links/{link_id}/file` | Ai thấy việc. Trả tệp với `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`; `404` khi link không có tệp (FR-WRK-10) |
| POST | `/api/v1/mcp-server` (thêm từ FR-MCP-08) | Tool `list_work`, `get_work`, `create_work` (không cho Developer), `move_work`, `comment_work`, `attach_link`; prompt `content_day`; tệp lệnh `/in-content-day` ở `agent-commands/files/in-content-day.md` |
| POST | `/api/v1/mcp-server` (thêm từ FR-MCP-09) | Tool dự án marketing: `hot_topics`, `trending`, `get_pillars`, `week_plan`, `review_queue`, `set_channel_text` (mọi vai trong dự án); `topic_to_post`, `dismiss_topic`, `refresh_topics`, `get_short_link`, `add_signals` (không cho Developer); prompt `hot_topics`, `draft_post`; tệp lệnh `in-hot-topics.md`, `in-draft-post.md` |
| POST | `/api/v1/work/{id}/issue` | CTO hoặc Project Owner, dự án SOFTWARE có đồng bộ bật. Quyết định lại yêu cầu gốc sang GitLab/GitHub (hoặc tạo yêu cầu mới) và xếp hàng đồng bộ; trả `WorkDetail` với `issue_pending=true`; `422 PROJECT_NOT_SOFTWARE\|DELIVERY_SYNC_DISABLED\|INTAKE_NOT_READY`, `409 WORK_CLOSED` (FR-WRK-05) |
| GET | `/api/v1/intakes/{id}/github-issue-link` | Liên kết tạo Issue điền sẵn trên GitHub, chỉ từ nội dung đã chuẩn hóa (FR-INTG-20). Trả `url`, `repository`, `host`, `shortened`. Lỗi 422: `NOT_NORMALIZED`, `NO_REPOSITORY`; 404 khi ngoài phạm vi |
| GET/PUT | `/api/v1/integrations/github-tokens` | Chỉ CTO (FR-INTG-21). GET trả `[{name, key_hint, used_by_projects, updated_at}]`; PUT nhận `{label, token}`, `label` được đổi thành `GITHUB_TOKEN_<TÊN>`; không trả lại giá trị token. Lỗi 422: `NAME_INVALID`, `TOKEN_INVALID`. |
| DELETE | `/api/v1/integrations/github-tokens/{name}` | Chỉ CTO. 204; 404 `NOT_FOUND`; 409 `TOKEN_IN_USE` khi một dự án đang bật còn dùng token. |
| GET/PUT | `/api/v1/integrations/gitlab-connection` | Chỉ CTO (FR-INTG-22). Trả `{configured, source: APP|ENV|NONE, base_url, key_hint, updated_at, linked_projects}`; PUT nhận `{base_url, token?}` (bỏ trống `token` để giữ token cũ) và trả thêm `projects_enabled`. Không trả lại giá trị token. Lỗi 422: `GITLAB_BASE_URL_INVALID`, `TOKEN_INVALID`, `TOKEN_REQUIRED`. |
| DELETE | `/api/v1/integrations/gitlab-connection` | Chỉ CTO. 204, quay về `GITLAB_TOKEN` trong `.env` nếu có; 404 `NOT_FOUND` khi chưa lưu. |
| POST | `/api/v1/intakes/{id}/approve` (thêm từ ADR-0066) | `approved_route` nhận `WORK`; trả `IntakeOut.work_item { id, code, status, project_id }` khi duyệt tuyến này. `PLANE` chỉ còn hợp lệ cho yêu cầu đã quyết trước đó. `GET /intakes/{id}/journey` thêm `work_item` cùng dạng; `GET /intakes/{id}/sync-status` trả `target_system=null` cho tuyến không đồng bộ (FR-WRK-06) |
| POST | `/api/v1/acceptance/{id}/evidence` | CTO hoặc Project Owner của dự án. `{ links: [{ kind?: COMMIT\|MR\|LINK, url?, ref?, note? }] }` (1..10) → thẻ nghiệm thu với `evidence_links[{id, kind, url, ref, note, source, added_by_name, created_at}]` và `evidence_check {work (CODE\|OTHER\|UNKNOWN), status (OK\|WEAK\|MISSING), why}`; `422 EVIDENCE_URL_INVALID`, `422 EVIDENCE_WRONG_REPO` (FR-PLAN-36) |
| POST | `/api/v1/acceptance/{id}/accept` | Thêm `evidence_missing_reason?`: bắt buộc khi `evidence_check.status` khác `OK` (`422 EVIDENCE_REASON_REQUIRED`); thẻ trả `evidence_missing_reason` (FR-PLAN-36) |
| PATCH | `/api/v1/planning/runs/{run}/assignments/{id}/work-status` | Thêm `evidence[]` cùng dạng; ghi vào Issue của việc với nguồn `WORKER`; trả thêm `evidence_added` (FR-PLAN-36) |
| POST | `/api/v1/mcp-server` (thêm từ ADR-0065) | `update_work_status` nhận `evidence[{kind, url, ref, note}]`; `log_work.commit` tự thành bằng chứng `WORK_LOG` của Issue gắn với yêu cầu (FR-PLAN-36) |
| GET | `/api/v1/planning/week/{...}` | `projects[].done` thêm `accepted_without_evidence` (FR-PLAN-36) || POST | `/api/v1/mcp-server` (thêm từ ADR-0064) | Tool `suggest_intake {project, text, idempotency_key, attachments?}` → `{feedback_id, project, status, created, files, note}`; lỗi `MEMBER_UNMAPPED`, `PROJECT_NOT_FOUND`, `TEXT_REQUIRED`. `tools/list` không liệt kê `create_intake` cho token Developer (FR-FBK-01) |
| GET | `/api/v1/intakes` | Keyset cursor; limit tối đa 100; project/stage/status/priority/target/channel/time/search filters. `stage` nhận `RECEIVED`, `NEEDS_INFORMATION`, `PENDING_APPROVAL`, `WAITING_PLANNING`, `IN_PROGRESS`, `PENDING_ACCEPTANCE`, `ACCEPTED`, `STOPPED`; `status` thô tiếp tục được nhận để tương thích. |
| GET | `/api/v1/intakes/{id}` | Detail không tự trả raw ciphertext. `IntakeOut.lifecycle_stage` dùng cùng phép suy ra với list/filter từ trạng thái Intake, Work, Planning và `IssueVerification`; phản hồi trực tiếp đã duyệt, Work `DONE`, Issue CTO nghiệm thu hoặc Project Owner xác nhận xong đều là `ACCEPTED`. Quyết định mẫu và ghi đóng tracker của CTO vẫn độc lập. |
| GET | `/api/v1/intakes/{id}/raw` | CTO-only + audit. Từ FR-AI-14 trả thêm `attachments[{id, index, name, mime_type, size_bytes, ocr_status, ocr_error, ocr_at, page_count, pages_read, text}]` (`text` là chữ đọc từ ảnh) |
| POST | `/api/v1/intakes/{id}/attachments` | Multipart, 5 MB/file; `415 ATTACHMENT_TYPE_MISMATCH` khi magic bytes không khớp loại khai. Trả thêm `ocr_status`. Yêu cầu đã chuẩn hóa thì tệp được đọc trong worker rồi yêu cầu chuẩn hóa lại (FR-AI-14) |
| GET | `/api/v1/intakes/{id}/attachments` | CTO hoặc Project Owner của dự án. Danh sách tệp và trạng thái đọc (`ocr_status` NONE, RUNNING, RETRY, DONE, FAILED, REJECTED, SKIPPED; `ocr_error` mã lỗi hoặc `PARTIAL`), không có bản chữ (FR-AI-14) |
| GET | `/api/v1/intakes/{id}/attachments/{aid}/file` | CTO hoặc Project Owner của dự án. Trả bytes theo MIME đã kiểm tra với `Content-Disposition: attachment`, `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`; UI dùng fetch có cookie và object URL để xem trước ảnh trong ứng dụng (FR-AI-14) |
| POST | `/api/v1/intakes/{id}/attachments/{aid}/read` | `202 { id, queued }`. Đặt tệp về chưa đọc và xếp lượt đọc lại; `queued=false` khi không có broker (FR-AI-14) |
| POST | `/api/v1/intakes/{id}/process` | `202`, idempotent job |
| GET | `/api/v1/intakes/{id}/pipeline` | Runs/stages/errors đã redact |
| PATCH | `/api/v1/intakes/{id}/review` | Sửa normalized payload + expected version |
| POST | `/api/v1/intakes/{id}/approve` | Chỉ sau normalized review; tạo snapshot |
| POST | `/api/v1/intakes/{id}/reject` | Reason required |
| POST | `/api/v1/intakes/{id}/defer` | Future datetime |
| POST | `/api/v1/intakes/{id}/needs-information` | Question list |

## 4. Approval và sync

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/approvals` | Queue có pagination/project filter. Mỗi dòng có `approval_owner` (`CTO`/`PO`) và `approval_overdue`; `?owner=CTO|PO` lọc trên trang đã đọc (FR-APR-14) |
| GET | `/api/v1/approvals/decisions` | Lịch sử quyết định trên yêu cầu (FR-APR-15), mới nhất trước, trong phạm vi dự án của người gọi: `?days=` (mặc định 7, 1 đến 365), `?before=<thời điểm>` đọc lùi (bỏ qua `days`), `?project_id=` (mã hoặc id), `?limit=` (mặc định 50, tối đa 200). Trả `{ items[], next_before, since }`; mỗi dòng `{ id, at, action: APPROVED|REJECTED|DEFERRED|NEEDS_INFORMATION|REOPENED, source: QUEUE|PLANNING, actor_id, actor_name, reason, intake_id, public_id, title, status, project_id, project_code, project_name, approved_route, approved_priority }` |
| GET | `/api/v1/intakes/{id}/sync-status` | Snapshot/job hiện hành và trạng thái target |
| POST | `/api/v1/approval-snapshots/{id}/sync` | Target phải khớp approved route |

## 5. Create intake request

```json
{
  "project_id": "uuid",
  "channel": "ZALO",
  "raw_text": "Nội dung nguồn",
  "received_at": "2026-09-30T08:00:00Z"
}
```

Response không echo raw text. File upload là request riêng gắn intake/source.

Mọi JSON success dưới `/api/v1` được wrap bằng `success`, `data`, `request_id`. List Intake/Approval đặt `items`, `next_cursor`, `limit` bên trong `data`. Intake list còn trả `summary.total_items`, `p0_attention`, `p1_attention`, `pending_approval`, `sync_failed`; các chỉ số attention được scope theo `project_id` nếu filter project được gửi. Mỗi Intake trả `sync_targets[]` chứa trạng thái, external ID và URL mới nhất theo từng target, kèm `superseded` (lần đồng bộ thuộc quyết định đã rút lại, FR-APR-10).

## 6. Approval request

Precondition: item ở `PENDING_APPROVAL` sau khi normalized review được lưu. Nếu chưa đạt, API trả `409 REVIEW_REQUIRED` và không tạo snapshot/outbox.

```json
{
  "expected_version": 4,
  "approved_route": "GITLAB",
  "approved_priority": "P1",
  "reason": "Ready for delivery"
}
```

Normalized title/summary/priority proposal/route phải được lưu trước bằng `PATCH /intakes/{id}/review`; approval request không nhận payload tùy ý. Server tạo snapshot từ item hiện hành, tự thêm Intake ID, project reference, actor và payload hash.

## 7. Plane · lịch sử

Plane không còn adapter, cấu hình, probe, worker hay thao tác ghi. Quyết định, sync job và external link cũ vẫn được API trả về ở chế độ chỉ đọc với nhãn `Plane · lịch sử`; yêu cầu đồng bộ mới trả `ROUTE_RETIRED`.

## 8. GitLab adapter

| Intake | GitLab Issue |
|---|---|
| Approved title | Title |
| Sanitized summary/evidence | Description |
| Acceptance criteria | Checklist |
| Approved priority/type | Labels |
| Intake ID | Traceability section |
| Project mapping | GitLab project ID/path |

Token scope tối thiểu. Nếu instance không hỗ trợ idempotency header, dùng stable marker và lookup trong project trước create retry.

### GitLab label contract

Intake chỉ gửi ba label từ allowlist cố định:

- `source:intake`;
- đúng một `priority:p0|p1|p2|p3`, lấy từ quyết định đã duyệt của CTO;
- đúng một `type:bug|feature|task|tech-debt`, ánh xạ từ `item_type` đã chuẩn hóa.

`FEATURE` và `SCOPE_CHANGE` ánh xạ thành `type:feature`; `TASK`, `FEEDBACK`, `QUESTION` và `UNCLEAR` ánh xạ thành `type:task`. Giá trị priority/type ngoài allowlist phải fail closed trước khi gọi GitLab. Intake không nhận tên label tự do từ AI vì GitLab Issues API có thể tự tạo label chưa tồn tại.

## 8A. GitHub adapter (ADR-0021)

- Base `https://api.github.com`, header `Authorization: Bearer <token của dự án>`, `X-GitHub-Api-Version: 2022-11-28`.
- Tạo Issue: `POST /repos/{owner}/{repo}/issues` với chỉ `title` và `body`; `body` là mô tả đã duyệt cộng chú thích ẩn `<!-- {INTEGRATION_MARKER_PREFIX}:MÃ -->` (biến môi trường, mặc định `intake`; nơi đã có Issue giữ nguyên tiền tố cũ để nhận lại Issue). Không gửi nhãn, người phụ trách hay milestone.
- Idempotency: trước khi tạo, tìm chú thích ẩn trong 100 Issue tạo gần nhất (`GET /repos/{owner}/{repo}/issues?state=all&sort=created`).
- Đọc cho Planning: `GET /repos/{owner}/{repo}/issues?state=all` có phân trang, bỏ mục có `pull_request`.
- Không có lời gọi ghi nào khác: duyệt Planning Run không cập nhật Issue trên GitHub.
- Lỗi: 401/403 là `GITHUB_AUTH_FAILED`, 404 là `GITHUB_MAPPING_NOT_FOUND`, 429 hoặc hết hạn mức là lỗi tạm thời và được thử lại.

## 9. IMAPS contract

- TLS, hostname verification và certificate validation bắt buộc.
- Checkpoint gồm mailbox, UIDVALIDITY và last UID.
- UIDVALIDITY đổi phải reconcile, không ingest lại im lặng.
- Parse limit cho body/attachment; email vượt giới hạn được ghi trạng thái cần xử lý.
- Không gửi SMTP.

Daily Report API phục vụ backfill/kiểm chứng nội bộ, chỉ CTO:

| Method | Path | Ghi chú |
|---|---|---|
| POST | `/api/v1/reports/daily/ingest` | Ingest idempotent theo mailbox + UIDVALIDITY + UID; raw subject/body được mã hóa |
| GET | `/api/v1/reports/daily` | Lọc theo `report_date` và `member_id`; mặc định chỉ trả revision hiện hành. Project Owner: chỉ thư của người trong đội có ít nhất một việc họ thấy; `item_count`, `unlinked_items` đếm phần họ thấy; thêm `hidden_items`, `can_review` (FR-ID-08). Mỗi dòng có `unlinked_items`; chi tiết mỗi task có `issue_suggestions[{issue, title, source, confidence, reason?}]`, `issue_link_source`, `no_issue_reason` (FR-RPT-07) |
| GET | `/api/v1/reports/daily/{id}` | Chi tiết và các task đã trích; không trả subject/body |
| GET | `/api/v1/reports/daily/{id}/raw` | Thư gốc đã giải mã, ghi audit `report.raw.read`. `body` là phần báo cáo, `signature` là phần sau dòng `--` (ADR-0019); bản lưu không bị cắt |
| POST | `/api/v1/reports/daily/{id}/review` | `decision` là `CONFIRMED` hoặc `REJECTED`; loại thì task của báo cáo bị gỡ khỏi Planning |
| PATCH, DELETE | `/api/v1/reports/daily/{id}/items/{item_id}` | CTO sửa hoặc xóa từng task |

IMAP worker dùng `BODY.PEEK[]`, không đánh dấu email đã đọc. Reply/email mới cùng nhân sự và report date tạo revision mới; revision cũ và các item cũ chuyển `is_current=false`, không bị xóa.

Format chuẩn có subject `DAILY REPORT | YYYY-MM-DD | HỌ TÊN | MÃ-DỰ-ÁN...`; body dùng status allowlist `PLANNED|IN_PROGRESS|PENDING_REVIEW|DONE|BLOCKED|CANCELLED`, tham chiếu GitLab/Plane/Intake (số Issue nhận ở dạng `GitLab #19`, `Issue #19: …`, `[#8 KIN-26W41-007] …` hay `#19 …` ở đầu tiêu đề, hoặc `Issue: https://…/issues/17` (`/work_items/17`); tiền tố `[#8 KIN-…]`/`Issue #19:` được bỏ khỏi tiêu đề task; mã Intake trong tiêu đề thành `intake_reference`; định dạng chuẩn ở `docs/stable/daily-report-format.md`), giờ làm/còn lại, bước tiếp theo, evidence và blocker. Parser lỗi vẫn persist email/revision và trả issue đã sanitize; report không hợp lệ không chặn Planning Run.

## 10. Daily planning API

| Method | Path | Quyền/Ghi chú |
|---|---|---|
| GET | `/api/v1/planning/capacities/{date}` | CTO; capacity theo người, thành phần khấu trừ và override; `is_cto` đánh dấu hồ sơ của chính CTO (FR-PLAN-37) |
| PUT | `/api/v1/planning/capacities/{date}/{member_id}` | CTO; optimistic version, override reason bắt buộc cho OT/ngoại lệ |
| POST | `/api/v1/planning/members` | CTO; tạo workforce member và project mappings |
| GET | `/api/v1/planning/members` | CTO; danh sách workforce/mappings; mỗi dòng có `is_cto` (hồ sơ của chính CTO, FR-PLAN-37) |
| POST | `/api/v1/planning/members/me` | Chỉ CTO; tạo hồ sơ nhân sự của chính CTO (email của tài khoản, 0 giờ mặc định) hoặc nối hồ sơ đã mang email đó, ghi `users.member_id`; bấm lại trả cùng `WorkforceMemberOut`; `422 MEMBER_HAS_ACCOUNT` khi hồ sơ đó đã thuộc tài khoản khác (FR-PLAN-37) |
| POST | `/api/v1/planning/runs` | CTO/scheduler; idempotent theo plan date + scope |
| GET | `/api/v1/planning/days/{plan_date}` | Chỉ đọc (FR-UI-12): kế hoạch của ngày đã mở chưa và đến đâu. Trả `run_id`, `status`, `assigned`, `waiting`; chưa có kế hoạch thì `run_id` là `null`. Không bao giờ mở kế hoạch. `?project_id=` cho một dự án; Project Owner bắt buộc truyền dự án của mình, ngoài phạm vi trả `404` |
| GET | `/api/v1/planning/runs/{id}` | Run, candidates, assignments, warning và conflict. Từ 2026-10-15 mỗi assignment có `issue_url` (trang Issue trên tracker, từ bản đọc GitLab/GitHub) và mỗi candidate có `intake_public_id`, `issue_url`, để giao diện gắn link riêng cho mã Intake và số Issue (FR-PLAN-33). Từ 2026-10-19 candidate có `accepted_at`: thời điểm CTO nghiệm thu Issue của dòng đó (null khi chưa); dòng `DONE_ELSEWHERE` có `accepted_at` không hiện trên Daily Planning (FR-PLAN-34) Từ 2026-10-20 mỗi assignment cũng có `accepted_at` (CTO đã nghiệm thu Issue của việc; giao diện vẽ thẻ là đã xong, không đổi giờ). |
| POST | `/api/v1/planning/runs/{id}/assignments` | CTO; thêm assignment có expected run version. Một `(run, project, Issue)` chỉ có một assignment; thêm lại trả `422 ISSUE_ALREADY_PLANNED` (FR-PLAN-04). |
| POST | `/api/v1/planning/runs/{id}/accept-proposals` | CTO; copy `proposed_*` sang `approved_*` bằng expected version, chưa sync GitLab |
| POST | `/api/v1/planning/runs/{id}/quick-add` | CTO; chọn existing reference hoặc tạo Intake từ form/paste; hỗ trợ `Idempotency-Key` |
| POST | `/api/v1/planning/runs/{id}/quick-add/{candidate_id}/promote` | CTO; gắn GitLab Issue hiện hành và chuyển candidate thành proposal assignment; Issue đã có assignment trong run trả `422 ISSUE_ALREADY_PLANNED` (FR-PLAN-04). |
| POST | `/api/v1/planning/runs/{id}/approve` | CTO; tạo immutable snapshot và enqueue GitLab update jobs |
| GET | `/api/v1/planning/runs/{id}/sync-jobs` | Per-Issue status/error đã redact |
| POST | `/api/v1/planning/runs/{id}/sync-jobs/{job_id}/retry` | CTO; chỉ failed job còn lượt retry và thuộc đúng Planning Run |

Planning run create request:

```json
{
  "plan_date": "2026-10-03",
  "project_ids": ["uuid"],
  "timezone": "Asia/Ho_Chi_Minh"
}
```

Quick Add dùng một contract thống nhất:

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

`mode=FORM` yêu cầu `title`, `content` tùy chọn; `mode=PASTE` yêu cầu `content` và nhận `channel` thuộc `ZALO|WHATSAPP|EMAIL|MEETING|MANUAL`. Hai mode này tạo Intake và candidate `PENDING_TRIAGE` trong cùng transaction. Target đã chốt sẽ enqueue normalize/dedupe bất đồng bộ sau commit, không chặn response Quick Add; runtime 1.2 chưa enqueue bước này. Existing GitLab Issue đang mở tạo candidate `READY`; existing Intake/Plane chỉ `READY` khi đã có GitLab link khớp read model hiện hành.

Promotion yêu cầu `member_id`, `slot`, `planned_hours` và GitLab Issue đang mở. Kết quả tạo assignment chỉ có `proposed_*`; CTO vẫn phải gọi `accept-proposals`, rồi `approve`. Form/paste không được đi thẳng thành delivery assignment nếu chưa có GitLab Issue.

Mốc 06:45 gọi task `intake.planning.refresh-gitlab` trên integration queue. Task phân trang `state=all`, lưu snapshot nội bộ và không ghi GitLab. Mốc 07:00 chỉ đọc snapshot hiện hành, xếp ưu tiên theo carry-over email, priority và due date. Target theo ADR-0013: priority lấy từ Planning snapshot đã duyệt gần nhất có chứa Issue, GitLab priority label là dự phòng; runtime 1.2 mới đọc priority label. Planner tạo tối đa một primary Issue/người, chia tối đa 4 giờ mỗi lane. Proposal không trở thành quyết định cho tới khi CTO gọi `accept-proposals`, sau đó vẫn cần `approve` riêng.

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

Approval fail closed khi có assignment thiếu GitLab Issue, thiếu GitLab user mapping hoặc chọn milestone không tồn tại. Thiếu milestone hoặc due date không chặn: warning `GITLAB_MILESTONE_MISSING` / `GITLAB_DUE_DATE_MISSING` phải được đánh dấu đã xem (`acknowledged_warning_ids`), nếu không `422 WARNING_UNACKNOWLEDGED`; job cập nhật GitLab chỉ gửi trường có giá trị (ADR-0013, thực hiện 2026-10-13).

### GitLab planning update contract

Mỗi job chỉ cập nhật một Issue và payload allowlist gồm:

```json
{
  "issue_external_id": "125",
  "assignee_external_id": "42",
  "milestone_external_id": "9",
  "due_date": "2026-10-03"
}
```

- Không tạo milestone mới.
- `milestone_external_id` và `due_date` là tùy chọn; trường thiếu không được gửi và không bị xóa trên GitLab (ADR-0013).
- Không cập nhật priority label trong pilot; priority CTO duyệt chỉ nằm trong Planning snapshot.
- Không ghi raw email/chat hoặc chi tiết ca sáng/chiều vào GitLab.
- Adapter đọc lại Issue trước update, lưu before/after allowlist và dùng stable idempotency key theo planning snapshot + Issue.
- Lỗi một Issue không rollback Issue khác; retry dùng cùng idempotency key và chỉ job lỗi.

Candidate nguồn `REPORT` (ADR-0019): `POST /api/v1/planning/runs` tạo run hoặc trả run hiện có của ngày và phạm vi đó. Trong cả hai trường hợp, nếu run còn sửa được, task chưa xong của Daily Report dùng được được thêm thành candidate và `version` của run tăng khi có candidate mới. Promote dùng cùng endpoint với Quick Add và vẫn yêu cầu GitLab Issue đang mở.

Quyền hằng ngày của Project Owner (FR-ID-08, ADR-0026). Các route sau nhận cả Project Owner, trong phạm vi đội và dự án của họ; ngoài phạm vi trả 404:

- `GET /api/v1/reports/daily`, `GET /api/v1/reports/daily/{id}`, `GET .../raw`, `POST .../review`, `PATCH` và `DELETE .../items/{item_id}`.
- `GET /api/v1/planning/members` (chỉ đội của họ), `GET /api/v1/planning/capacities/{date}?project_id=` (bắt buộc nêu dự án), `PUT /api/v1/planning/capacities/{date}/{member_id}`.
- `POST /api/v1/planning/runs` (phạm vi phải là dự án của họ), `GET /api/v1/planning/runs/{id}`, `POST .../assignments`, `GET .../work-items`, `POST .../work`, `POST .../candidates/{id}/assign`, `POST .../candidates/{id}/dismiss|restore`.
- `POST .../work` với việc chưa có Issue và `POST .../candidates/{id}/assign` với `issue_mode=CREATE` trả 403 `CTO_APPROVAL_REQUIRED` cho Project Owner.
- Mỗi assignment trong Planning Run có thêm `title` (tiêu đề Issue trong read model, null nếu chưa có).

Đổi lại quyết định (FR-APR-08, ADR-0028): `POST /api/v1/intakes/{id}/reopen` với `reason` (từ 5 ký tự) và `expected_version`; cùng phạm vi với phê duyệt. Trả Intake ở `PENDING_APPROVAL`. 409 `SYNC_LOCKED`, `NOT_DECIDED`, `INTAKE_PLANNED`, hoặc lệch phiên bản. Hành trình của Intake có thêm `previous_targets` (các mục đã tạo theo quyết định cũ). Từ ADR-0028, `POST .../work` và `POST .../candidates/{id}/assign` không còn trả `CTO_APPROVAL_REQUIRED` cho Project Owner.

Nơi phê duyệt (FR-APR-07), chỉ CTO: `GET /api/v1/approvals/sources?weeks=4` (1 đến 12 tuần) trả danh sách tuần, mới nhất trước, mỗi tuần có `week_start` (thứ Hai, giờ Việt Nam), `from_queue` và `from_planning`. Chỉ đếm hành động `APPROVE`.

Quét hộp thư báo cáo (FR-EML-12, FR-EML-14), chỉ CTO:

- `GET /api/v1/reports/mailbox` trả `enabled`, `mailbox`, `poll_minutes`, `current` (lần quét đang chờ hoặc đang chạy) và `last` (lần quét xong gần nhất). Mỗi lần quét có `trigger` (`SCHEDULED`/`MANUAL`), `status` (`PENDING`/`RUNNING`/`DONE`/`FAILED`), `ingested`, `duplicates`, `failed`, `error_code`, `created_at`, `completed_at`.
- `POST /api/v1/reports/mailbox/scan` trả 202 với cùng cấu trúc; nếu đã có lần quét đang mở thì dùng lại lần đó. 409 `MAILBOX_DISABLED` khi quét hộp thư đang tắt. Yêu cầu không được worker nhận sau 5 phút bị đóng với `WORKER_UNAVAILABLE`.

Hành trình của một yêu cầu (FR-UI-09): `GET /api/v1/intakes/{id}/journey`, cùng phạm vi với xem Intake (CTO hoặc Project Owner của dự án, ngoài phạm vi trả 404). Trả `intake_id`, `intake_public_id`, `project_id`, `received_at`, `channel`, `decision` (`action`, `at`, `by`, `route`, `priority`), `issue` (`system` GITLAB/GITHUB, `external_id`, `url`), `other_target`, `sync_status`, `accepted_at`, `plans` (tối đa 6 lần xếp gần nhất: `plan_date`, `run_id`, `member_name`, `slot`, `planned_hours`, `settled`, `work_status`, `accepted_at`) và `waiting_in_plan`. Mỗi assignment trong Planning Run có thêm `intake_id` và `intake_public_id` (null nếu Issue không sinh từ Intake). Giao diện tạo deep-link `/planning?date=YYYY-MM-DD&project=<uuid>&intake=INT-...` bằng lần xếp mới nhất.

Thêm việc trong ngày (ADR-0024), chỉ CTO:

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/planning/runs/{id}/work-items?search=` | Issue đang mở và Intake chờ duyệt của các dự án trong run; mỗi dòng cho biết đã có trong kế hoạch chưa và có cần tạo Issue không |
| POST | `/api/v1/planning/runs/{id}/work` | `source` là `ISSUE`, `INTAKE` hoặc `NEW`; `member_id`, `slot`, `planned_hours` tùy chọn nhưng phải đi cùng nhau. `reason` bắt buộc khi phải tạo Issue. Trả `state`: `PLANNED`, `WAITING_ASSIGNMENT` (kèm `assignment_error` nếu phân công không vừa) hoặc `CREATING_ISSUE` |
| POST | `/api/v1/planning/runs/{id}/candidates/{cid}/assign` | Xếp một việc đang chờ: `issue_mode=EXISTING` gắn một Issue có sẵn, `CREATE` tạo Issue mới kèm `reason` |
| POST | `/api/v1/planning/runs/{id}/assignments/{aid}/unassign` | `{ expected_run_version }` (FR-PLAN-16). Bỏ việc đã xếp khỏi ngày khi run còn sửa được; việc quay về candidate `READY` (candidate gốc nếu đi từ danh sách chờ, hoặc candidate mới từ Issue) với ưu tiên và giờ; cảnh báo gắn với việc đó bị xóa; `409 PLANNING_RUN_IMMUTABLE`, `409 PLANNING_VERSION_CONFLICT`, `422 PLANNING_ASSIGNMENT_NOT_FOUND`. Trả cả run |
| POST | `/api/v1/planning/runs/{id}/assignments/{aid}/move` | `{ expected_run_version, slot, member_id?, override_reason? }` (FR-PLAN-04). Đổi buổi; có `member_id` thì đồng thời đổi người làm trong run đang mở, cập nhật mapping assignee tracker, candidate/cảnh báo và audit. Từ chối nếu người không hoạt động/không thuộc dự án, thiếu mapping delivery, quá capacity ngày, quá 4 giờ trong buổi hoặc đã có việc phát triển chính khác (`MEMBER_NOT_ACTIVE`, `MEMBER_NOT_IN_PROJECT`, `GITLAB_ASSIGNEE_REQUIRED`, `OVER_CAPACITY`, `SLOT_OVER_CAPACITY`, `MULTIPLE_PRIMARY_DOING`). CTO/Project Owner có thể gửi `override_reason` sau bước xác nhận để vượt ba giới hạn capacity/4 giờ/việc chính; lý do được lưu trên assignment và audit, vai khác nhận `PLANNING_OVERRIDE_FORBIDDEN`. Trả cả run |
| POST | `/api/v1/planning/runs/{id}/candidates/{cid}/done` | `{ note }` (3..500 ký tự, `422 NOTE_REQUIRED`). CTO hoặc Project Owner của dự án. Việc chờ đã làm rồi ngoài kế hoạch: `status REJECTED`, `summary` "Đã làm xong ngoài kế hoạch: <ghi chú>", trả thêm `acceptance_queued`; kế hoạch đã chốt vẫn nhận (FR-PLAN-34) |
| POST | `/api/v1/planning/runs/{id}/candidates/{cid}/dismiss` và `/restore` | Ẩn một việc chờ khỏi run của ngày đó, hoặc đưa lại |
| POST | `/api/v1/planning/runs/{run_id}/reopen` | CTO hoặc Project Owner của dự án. `{ expected_version }`. Kế hoạch đã chốt (APPROVED, SYNCING, SYNCED, SYNC_FAILED, PARTIAL) thành bản mới: `201` trả Planning Run mới (`revision + 1`, `supersedes_run_id`, trạng thái `REVIEW_REQUIRED`, việc, giờ, ưu tiên, trạng thái việc đã báo và cảnh báo đã xem chép sang; bản cũ thành `SUPERSEDED`, vẫn đọc được). `422 PLANNING_RUN_OPEN` khi đang mở, `PLANNING_RUN_SUPERSEDED` khi đã có bản mới hơn, `PLANNING_SYNC_IN_PROGRESS` khi job GitLab của bản cũ chưa xong, `409 PLANNING_VERSION_CONFLICT`. Chốt lại chỉ tạo job cho Issue có `after_state` khác job `SUCCEEDED` gần nhất trong chuỗi bản cũ (FR-PLAN-18) |
| POST | `/api/v1/planning/runs/{run_id}/verifications/{verification_id}/{accept\|reject}` | Chỉ CTO (FR-PLAN-22). `{ expected_version, reason? }`; `reject` bắt buộc `reason`. Trả cả Planning Run (`verifications[]` với `level` 0–5, `level_name`, `evidence {commits, merge_requests, merged, pipeline, links}`, `acceptance[]` từ Intake, `decision`). `409 PLANNING_VERSION_CONFLICT`, `409 VERIFICATION_DECIDED`, `422 REASON_REQUIRED`. Chưa xong → candidate `source_type=VERIFICATION` "Làm lại" và cảnh báo `ISSUE_NOT_DONE_AFTER_CLOSE`; không ghi gì lên GitLab |
| PUT | `/api/v1/planning/projects/{project_ref}/done-evidence` | Chỉ CTO. `{ done_evidence: COMMIT \| MR }` (FR-PLAN-22); `ProjectOut.done_evidence` đọc lại |

Khi phải tạo Issue, API ghi approval action và snapshot của Intake rồi xếp hàng sync job như luồng thường; integration worker tạo Issue, và lúc sync thành công Issue được thêm vào read model cùng việc phân công đã ghi. Lỗi riêng: `ADD_WORK_REASON_REQUIRED`, `DELIVERY_SYNC_DISABLED`, `ASSIGNMENT_INCOMPLETE`, `INTAKE_NOT_READY`.

## 10A. Meeting API (ADR-0018, ADR-0019)

Chỉ CTO. Mọi response JSON dùng envelope chung.

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/meetings/speech` | Nhà cung cấp giọng nói đã cấu hình chưa, có chữ trực tiếp không (`{configured, live_text}`) |
| GET, POST, DELETE | `/api/v1/meetings/glossary` | Thuật ngữ chung hoặc theo dự án |
| POST | `/api/v1/meetings` | `project_id` bắt buộc (`MEETING_PROJECT_REQUIRED`), `source` là `TAB_AND_MIC`, `MIC` hoặc `FILE`, `title` tùy chọn; trả 409 khi `MEETING_CAPTURE_ENABLED=false` |
| GET | `/api/v1/meetings`, `/api/v1/meetings/{id}` | Danh sách; chi tiết gồm bản chữ, người nói, tóm tắt và mục note |
| POST | `/api/v1/meetings/{id}/audio?sequence=N` | Multipart một đoạn audio, tối đa 5 MB, phải đúng thứ tự; tổng không quá `MEETING_MAX_AUDIO_MB` |
| GET | `/api/v1/meetings/{id}/audio` | Bản ghi đã giải mã, ghi audit; `?download=true` trả `Content-Disposition: attachment` |
| POST | `/api/v1/meetings/{id}/finish` | Kết thúc và xếp hàng chuyển chữ có tách người nói. Thân tùy chọn `{ duration_seconds }` (FR-REC-14): thời lượng trình duyệt đo được, server lấy giá trị nhỏ hơn giữa nó và đồng hồ của mình; không có thân thì dùng đồng hồ server. Gọi lại trên cuộc họp đã kết thúc không đổi gì |
| POST | `/api/v1/meetings/{id}/audio?sequence=` | Nhận đoạn kế tiếp đúng thứ tự; đoạn đã có trả `200` không đổi; `409 AUDIO_CHUNK_OUT_OF_ORDER` kèm "Expected chunk N" để trình duyệt bỏ các đoạn server đã giữ; `409 MEETING_NOT_RECORDING` khi cuộc họp đã kết thúc (FR-REC-14) |
| PATCH | `/api/v1/meetings/{id}/project` | Đổi dự án của cuộc họp; mọi mục chưa thành Intake đổi theo |
| POST | `/api/v1/meetings` với `continues_meeting_id` | Phần kế tiếp của một cuộc họp đã tới giới hạn phút: cùng dự án, `part_number` + 1, tiêu đề "(phần n)"; `MeetingOut` có `series_id`, `part_number`, `transcript_error`, `note_error`; chi tiết có `parts[]` (FR-REC-17, FR-REC-18) |
| POST | `/api/v1/meetings/{id}/note/items/{item_id}/intake?full_transcript=` | Intake từ một mục, kèm đoạn bản chữ quanh chủ đề; `full_transcript=true` gửi cả bản chữ (FR-REC-15) |
| POST | `/api/v1/meetings/{id}/note/items/intakes` | `{ item_ids[], full_transcript }` → `{ results[{item_id, intake_id, error}], meeting }`; `201` kể cả khi có mục lỗi (FR-REC-16) |
| POST | `/api/v1/meetings/{id}/transcript/retry` | Gửi lại tệp cho dịch vụ chuyển chữ khi `transcript_status` là FAILED hoặc SKIPPED; `409 TRANSCRIPT_RETRY_NOT_ALLOWED` nếu không (FR-REC-18) |
| PATCH | `/api/v1/meetings/{id}` | Đổi tên (FR-REC-12): `{ "title" }`, 1 đến 200 ký tự, khoảng trắng thừa được gộp |
| DELETE | `/api/v1/meetings/{id}` | Xóa hẳn bản ghi âm, bản chữ và note (FR-REC-12). Trả `{ deleted, intakes_kept }`. `409 MEETING_BUSY` khi đang ghi, đang chuyển chữ, hoặc bản sao phía dịch vụ chuyển chữ chưa xóa xong |
| PATCH | `/api/v1/meetings/{id}/speakers` | Đặt tên thật cho "Thành viên N" |
| PATCH | `/api/v1/meetings/{id}/note` | Sửa tóm tắt |
| POST | `/api/v1/meetings/{id}/note/regenerate` | Tạo lại note; mục đã thành Intake được giữ |
| POST, GET | `/api/v1/meetings` (bổ sung) | `POST` nhận thêm `kind`: `MEETING` (mặc định) hoặc `DICTATION` (nói để nhập: kết thúc là xong, không tách người nói, không note). `GET` mặc định chỉ trả `MEETING`; `?include_dictation=true` trả cả hai. Mỗi bản ghi có `kind` |
| POST | `/api/v1/meetings/{id}/rewrite` | `202`. Yêu cầu AI viết lại bản chữ thành một yêu cầu gọn (FR-REC-11); worker thực hiện. Đang chạy thì không tạo lần thứ hai. `409 MEETING_HAS_NO_TRANSCRIPT` khi chưa kết thúc hoặc không có chữ |
| GET | `/api/v1/meetings/{id}/rewrite` | Đọc kết quả: `rewrite_status` (`NONE`, `PENDING`, `DONE`, `FAILED`), `rewrite_text`, `rewrite_error`. Dùng để hỏi lại định kỳ, không ghi audit mở bản chữ |
| PATCH, DELETE | `/api/v1/meetings/{id}/note/items/{item_id}` | Sửa hoặc xóa một mục |
| POST | `/api/v1/meetings/{id}/note/items/{item_id}/intake` | Tạo Intake kênh `MEETING` từ mục, idempotent theo mục, rồi enqueue normalize |

WebSocket `/api/v1/meetings/{id}/stream` do dịch vụ `meeting-gateway` phục vụ, không phải API: xác thực bằng cookie phiên và kiểm tra origin, nhận PCM 16 kHz từ trình duyệt, chuyển tiếp tới ElevenLabs Scribe Realtime và trả các dòng chữ đã chốt. Chỉ gateway giữ `ELEVENLABS_API_KEY`.

Nhà cung cấp ngoài: realtime `wss://api.elevenlabs.io/v1/speech-to-text/realtime`; batch `POST /v1/speech-to-text` có `diarize`; xóa `DELETE /v1/speech-to-text/transcripts/{id}` (thử lại vì trả 404 trong vài giây đầu).

## 11. Internal events

| Event | Payload tối thiểu |
|---|---|
| `intake.normalization.requested.v1` | `run_id`, `intake_id` |
| `integration.sync.requested.v1` | `sync_job_id` |
| `planning.gitlab-update.requested.v1` | `planning_sync_job_id` |

Đây là ba outbox event runtime hiện được dispatcher route sang Celery. Xử lý sau cuộc họp không dùng outbox: gateway tự quét việc chuyển chữ 15 giây một lần, AI worker quét việc tạo note mỗi phút, cả hai claim bằng trạng thái trên bảng `meetings` với tối đa 3 lần thử. Completion/approval/retention/planning lifecycle hiện ghi audit hoặc chạy trực tiếp, chưa phải outbox event. Quyết định 2026-10-03 (OD-017): Intake approval chỉ ghi audit, không ghi outbox event `intake.approved`; runtime 1.2 vẫn còn ghi event này mà không có dispatcher route, cần gỡ trong code. Event version là một phần tên; consumer phải idempotent.

## 12. Target contract chưa có OpenAPI operation

Các endpoint sau vẫn là thiết kế đích, chưa được client coi là khả dụng:

- Xóa dự án và gỡ liên kết (tạo, sửa và kiểm tra kết nối đã có từ ADR-0020).
- `GET /intakes/{id}/approval-snapshots`.
- Global `GET /sync-jobs` và `POST /sync-jobs/{id}/retry` cho Intake sync.
- `POST /planning/runs/{id}/refresh`.
- `PATCH /planning/runs/{id}/assignments/{assignment_id}`.
- Planning amendment tạo revision mới toàn run, liên kết supersede và sync per-Issue delta.
- Emergency Add cho P0 theo ADR-0012: chỉ CTO, bắt buộc lý do, idempotent; integration worker tạo ngay GitLab Issue tối thiểu với label allowlist và `priority:p0`, không qua approval snapshot của Intake item; kết quả là Planning candidate.

Khi triển khai phải thêm requirement ID, OpenAPI contract test và cập nhật inventory/readiness trong cùng thay đổi.

## Khu riêng và nháp bài đăng (FR-CNT-01..03, ADR-0031)

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/private-space` | Chỉ CTO. Trả `project` (hoặc `null` khi chưa mở), `voice`, `counts` (`ideas`, `no_draft`, `drafted`, `posted`, `dropped`, `unposted_drafts`) |
| POST | `/api/v1/private-space` | Chỉ CTO. Mở khu riêng: tạo một dự án `IDEA` đánh dấu riêng tư. Gọi lại trả cùng khu đó |
| GET | `/api/v1/private-space/ideas?state=&search=` | Chỉ CTO. `state`: `ALL` (mặc định, không gồm ý đã bỏ), `NO_DRAFT`, `DRAFTED`, `POSTED`, `DROPPED` |
| PUT | `/api/v1/private-space/voice` | Chỉ CTO. Lưu giọng và định vị; tối đa 5 trụ (mỗi trụ 80 ký tự), 8 bài mẫu (mỗi bài 20 đến 4000 ký tự) |
| GET | `/api/v1/intakes/{id}/drafts` | Người xem được Intake. Nháp mới nhất trước |
| POST | `/api/v1/intakes/{id}/drafts` | `202`. `{ channel, angle?, source_draft_id? }`; `source_draft_id` là nháp cần chỉnh sang kênh khác. `409 DRAFTS_NOT_FOR_KIND` với dự án phần mềm; `409 SOURCE_DRAFT_NOT_READY` |
| PATCH | `/api/v1/intakes/{id}/drafts/{draft_id}` | `{ text?, posted? }`. `409 DRAFT_NOT_READY` khi nháp chưa soạn xong |
| DELETE | `/api/v1/intakes/{id}/drafts/{draft_id}` | `204` |

Các API liệt kê và đếm của công ty (`/intakes`, `/approvals`, `/projects`, `/meetings`) không bao giờ trả dữ liệu của dự án riêng tư.

Mạch nội dung và lựa chọn trước khi soạn (FR-CNT-04, ADR-0035):

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/private-space` | Thêm `master_dna` (tài liệu chung, tối đa 40.000 ký tự) và `voices`: `{ business, technical }`, mỗi giọng có `name`, `direction_note`, `references` (tối đa 2, mỗi cái `title` và `text` ≤ 20.000 ký tự), không còn `dna`. `voice` vẫn là giọng của mạch `business` (ADR-0042) |
| GET/POST/DELETE | `/api/v1/auth/tokens[/{id}]` | Chỉ phiên đăng nhập (CTO, Project Owner), không qua token (FR-MCP-01). `POST { name }` → `201` `{ id, name, prefix, token, created_at, expires_at }`, `token` chỉ trả một lần; `409` khi đã có 10 token; `DELETE` → `204`, `404` nếu không phải của mình. Token dùng như `Authorization: Bearer itk_…` cho mọi route với quyền của người tạo |
| GET/POST | `/api/v1/intakes/{id}/work-log` | CTO hoặc PO của dự án (FR-MCP-03). `POST { summary (5–1.000), details { cause, changes[], tests, branch, commit, verify_steps[], deploy_steps[], worked_on? YYYY-MM-DD, actual_minutes? 0..1440, deployed? }, agent_name? }` → `201`. Ngày/phút là thực tế, không tạo hay cộng vào Daily Planning. Mục có `review_decision` `PENDING|CONFIRMED|RETURNED`, `review_note`, `reviewed_by_name`, `actor_name`, `agent_name`, `commit_url` (trang commit trên GitLab/GitHub dựng từ địa chỉ Issue của yêu cầu; `commit` đã là link thì giữ nguyên; `null` khi không biết repo) |
| POST | `/api/v1/intakes/{id}/work-log/{log_id}/review` | Chỉ CTO. `{ decision: CONFIRMED|RETURNED, note? }`; `RETURNED` bắt buộc `note` (`422 NOTE_REQUIRED`); `409 ALREADY_REVIEWED`. `CONFIRMED` với Issue giao hàng hiện hành đồng thời tạo/chấp nhận `IssueVerification` nguồn `WORK_LOG`, đặt `sync_status=PENDING` rồi enqueue task đóng Issue sau commit. |
| GET | `/api/v1/changelog` | `{ build {sha, built_at}, latest, entries[{date, title, commits[], refs[], bullets[], cto_only}], behind }` đọc từ `CHANGELOG.md`; mục `cto_only` ẩn với Project Owner (FR-UI-14). `behind`: số mục mới hơn bản đang chạy, chỉ CTO, `null` khi không biết (FR-UI-15) |
| POST | `/api/v1/reports/daily/{id}/items/{item_id}/issue` | CTO hoặc Project Owner (người gửi thuộc đội mình). `{ gitlab_issue? , no_issue_reason? MEETING|SUPPORT|REVIEW|LEARNING|OTHER }`: có `gitlab_issue` thì gắn (nguồn lấy từ gợi ý nếu trùng, không thì `MANUAL`), chỉ có lý do thì "không cần Issue", rỗng thì bỏ cả hai. Trả chi tiết báo cáo (FR-RPT-07) |
| POST | `/api/v1/reports/daily/{id}/link-sure` | Gắn mọi việc có gợi ý từ 0,9 trong thư; trả chi tiết báo cáo (FR-RPT-07) |
| POST | `/api/v1/reports/daily/{id}/suggest-issues` | Tính lại gợi ý theo luật, phần chưa rõ gửi AI qua hàng `ai.normalize`; trả `{ items, linked, suggested, for_ai[], ai_queued }` (FR-RPT-07) |
| POST | `/api/v1/reports/issue-suggestions/backfill?days=14` | Chỉ CTO. Chạy gợi ý cho mọi báo cáo còn việc chưa gắn trong `days` ngày; trả tổng kèm `reports` (FR-RPT-07) |
| GET | `/api/v1/planning/week/{day}` | CTO hoặc Project Owner (dự án mình). Tuần chứa `day`: `{ week_start, week_end, days_passed, projects[{id, code, name, people, hours{available, planned, reported}, plans{total, closed}, done{reported, issues_closed, accepted, rejected, work_logs_confirmed}, items{reported, without_issue}, reports{expected, received, missing, late}, requests{new, approved, approved_within_24h, from_planning, avg_wait_hours, avg_to_issue_hours}, board{days, ready_days, no_work_days, overdue_days, max_approvals_overdue, max_stuck, escalated_days}}], people[{member_id, display_name, hours, done_reported, items, reports, projects[{id, name, planned, reported}]}], process{...}, cto_days[{date, minutes}] (chỉ CTO), text }` (FR-PLAN-29) |
| POST | `/api/v1/planning/board-snapshots/{day}` | Chỉ CTO. Ghi (hoặc thay) ảnh chụp bảng đầu ngày của ngày đó; trả `{ snapshot_date, projects }` (FR-PLAN-30) |
| GET | `/api/v1/acceptance` | CTO hoặc Project Owner (dự án mình); `?project_id=`. `source` thêm `PLAN` (báo xong trên kế hoạch ngày, FR-PLAN-34); mỗi việc có `source_note` (ghi chú lúc Hủy việc chờ, chép lên Issue khi CTO chấp nhận). `{ plan_date, sample_size, pending_total, today[], more[], decided[] }`, mỗi mục `{ id, source REPORT|CLOSED, project_id, project_name, issue_external_id, title, web_url, state, closed_at, assignee_*, reporter_*, reported_on, reported_hours, report_item_title, priority, level, level_name, done_evidence, evidence, evidence_fetched_at, intake_*, acceptance[], picked_on, decision, reason, decided_at, decided_by_name, po_decision, po_reason, po_decided_at, po_decided_by_name, sync_status, sync_error, synced_at }`. CTO: `today` là mẫu của ngày (gọi là tự chọn), `more` phần còn lại, `decided` 7 ngày; Project Owner: `today` là mọi việc chưa xác nhận của dự án mình (FR-PLAN-31) |
| POST | `/api/v1/acceptance/{id}/accept` hoặc `/reject` | `{ reason? }` (bắt buộc khi reject, `422 REASON_REQUIRED`). CTO ghi `decision`, Project Owner ghi `po_decision`; `409 VERIFICATION_DECIDED` khi đã quyết. Reject: việc về kế hoạch đang mở dạng "Làm lại". CTO accept: `sync_status = PENDING`, task ghi chú và đóng Issue; trả mục kèm `sync_queued` (FR-PLAN-31) |
| POST | `/api/v1/acceptance/sample?extra=5` | Chỉ CTO. Thêm `extra` việc vào mẫu hôm nay; trả `{ added }` (FR-PLAN-31) |
| POST | `/api/v1/acceptance/collect` | Chỉ CTO. Gom việc báo xong và Issue đóng; đồng thời đối soát work-log `CONFIRMED` cũ chưa có nghiệm thu chính thức, chấp nhận và enqueue đóng Issue. Trả `{ from_reports, from_closed, from_work_logs }` (FR-PLAN-31, FR-MCP-03) |
| PUT | `/api/v1/planning/projects/{project_ref}/acceptance-policy` | Chỉ CTO. `{ acceptance_policy: CTO_ALWAYS\|PO_FINAL_LOW_RISK }` (giá trị khác `422`) → `{ project_id, acceptance_policy }`; ghi `planning.acceptance-policy.changed`. `GET /projects` trả thêm `acceptance_policy`. Thẻ nghiệm thu (`GET /acceptance`, accept, reject) trả thêm `final_by (CTO\|PO\|null)`, `acceptance_policy`, `needs_cto_acceptance`, `po_final_blockers[]` (`POLICY`, `HARD`, `P0`, `EVIDENCE`, `NOT_OWNER`, `SELF`, `REJECTED_BEFORE`). Project Owner accept khi không có lý do: `decision ACCEPTED`, `final_by PO`, `sync_status PENDING`, đóng Issue như CTO. `GET /intakes/{id}/journey` `verification` thêm `po_decision`, `po_decided_at`, `po_decided_by_name`, `final_by`, `accepted_by_name` (FR-PLAN-41) |
| POST | `/api/v1/planning/projects/{ref}/tracker-users/lookup` | CTO hoặc Project Owner (dự án mình). `202 { probe_id, status, system }`: nhờ integration-worker đọc danh sách người dùng của tracker (API không giữ token); `422 TRACKER_NOT_CONFIGURED` khi dự án chưa bật GitLab/GitHub (FR-PLAN-32) |
| GET | `/api/v1/notify/telegram` | Chỉ CTO. `{ bot_username, bot_seen_at, projects[{id, code, name, chat_title, linked, linked_at}], members[{id, display_name, username, linked, linked_at, invite_pending}], holidays[{day, note}] }` (FR-NTF-02, FR-NTF-03) |
| POST | `/api/v1/notify/telegram/members/{member_id}/invite` | Chỉ CTO. Tạo (hoặc tạo lại) mã mời dùng một lần; `{ member_id, code, link, linked }`, `link` null khi chưa đặt `TELEGRAM_BOT_USERNAME`; `404` không có nhân sự (FR-NTF-03) |
| DELETE | `/api/v1/notify/telegram/members/{member_id}/link` | Chỉ CTO. Bỏ gắn Telegram của nhân sự, xóa mã mời đang mở; `204` (FR-NTF-03) |
| DELETE | `/api/v1/notify/telegram/projects/{ref}/link` | Chỉ CTO. Bỏ gắn nhóm của dự án (`ref` là id hoặc mã); `204` (FR-NTF-02) |
| GET | `/api/v1/notify/holidays` | Chỉ CTO. `[{day, note}]` (FR-NTF-04) |
| PUT | `/api/v1/notify/holidays` | Chỉ CTO. `{ days: [{day, note?}] }` (tối đa 60) thay toàn bộ danh sách; trùng ngày giữ dòng đầu; trả danh sách mới (FR-NTF-04) |
| GET | `/api/v1/notify/telegram/messages?days=7` | Chỉ CTO (`days` 1..60). `[{id, kind, for_date, slot, status SENT\|FAILED, error, sent_at, project_name, member_name}]`, mới nhất trước; `error` chỉ chứa mã Telegram ổn định và loại exception, không chứa nguyên văn lỗi vận chuyển hay bot token (FR-NTF-01, FR-NTF-05) |
| POST | `/api/v1/planning/proposals` | `{ project (mã hoặc id), plan_date, issue?, intake?, text?, hours?, slot? }`. CTO, Project Owner (dự án mình), Developer (dự án mình có mặt, ngoài ra `404`); tài khoản chưa gắn nhân sự `422 MEMBER_UNMAPPED`. `201` trả candidate kèm `created`, `run_id`, `project_name`, `project_code`, `plan_date`; `409 PLANNING_RUN_IMMUTABLE` khi kế hoạch ngày đó đã chốt; `422 GITLAB_ISSUE_NOT_FOUND`, `GITLAB_ISSUE_CLOSED`, `CANDIDATE_ALREADY_PLANNED`, `INTAKE_NOT_FOUND`, `PROPOSAL_TEXT_REQUIRED` (FR-PLAN-35) |
| GET | `/api/v1/planning/people/{plan_date}` (đổi) | CTO: mọi người; Project Owner: người trong đội dự án mình, mỗi người kèm `projects[{id, name, hours, run_status}]` của mọi dự án có giờ, kể cả dự án của Project Owner khác (FR-PLAN-28) |
| GET | `/api/v1/planning/capacities/{date}` (thêm) | Mỗi dòng có `planned_elsewhere[{project_id, project_name, hours}]` bên cạnh `planned_elsewhere_hours` (FR-PLAN-28); `GET /planning/day-plans/{date}` cho `elsewhere[]` trên `people[]` và `free[]` |
| PATCH | `/api/v1/planning/runs/{run_id}/assignments/{assignment_id}/work-status` | `{ status: PLANNED|IN_PROGRESS|DONE|BLOCKED, note? }`. CTO: mọi việc; Project Owner: dự án mình; Developer: việc của chính mình (ngoài ra `404`). Kế hoạch đã chốt vẫn nhận. Trả `{ assignment_id, issue, work_status, previous, at, work_status_note, acceptance_queued }`; `DONE` của việc có Issue tạo một việc chờ Nghiệm thu nguồn `PLAN` nếu Issue chưa có việc chờ (FR-PLAN-34) |
| GET | `/api/v1/planning/my-day/{plan_date}` | CTO, Project Owner, Developer (tài khoản đã gắn nhân sự, ngoài ra `422 MEMBER_UNMAPPED`). Cùng dữ liệu tool `get_my_day`: `{ date, member, items[{assignment_id, project, project_name, issue, issue_url, title, intake, priority, slot, hours, work_type, primary, work_status, work_status_note, plan_closed}], personal[], note?, hint? }` (FR-PLAN-34, FR-MCP-06). Từ 2026-10-20 mỗi item có `accepted_at`; từ 2026-10-21 `issue_url` mở chi tiết Issue từ thẻ Việc của tôi. |
| GET | `/api/v1/planning/day-plans/{plan_date}` | CTO (mọi dự án) hoặc Project Owner (dự án mình). Chỉ đọc, không mở kế hoạch. `{ plan_date, projects[{id, code, name, owner_name, run{...}|null, people[...], free[...], off[], waiting[...], off_plan[{id, intake_id, intake_public_id, title, issue, issue_url, executor, review_decision, worked_on, actual_minutes, deployed, accepted_at}]}], project_order{mode: PRIORITY|CUSTOM, project_ids[]}, totals{projects, unclosed, free_hours, free_people, waiting, off_plan, off_plan_actual_minutes} }` (FR-PLAN-33). `project_order` là tùy chọn của tài khoản hiện tại và đã lọc theo phạm vi dự án người gọi. `off_plan` là work-log của ngày không có assignment tương ứng; chỉ hiển thị lịch sử thực tế, không cộng vào giờ kế hoạch. Từ 2026-10-20 mỗi thẻ việc trong `people[].assignments[]` có `accepted_at`. |
| PUT | `/api/v1/planning/project-order` | CTO hoặc Project Owner. `{ mode: PRIORITY|CUSTOM, project_ids[] }`; lưu riêng theo tài khoản. `PRIORITY` luôn xóa danh sách ID. `CUSTOM` chỉ nhận dự án phần mềm đang hoạt động mà người gọi được thấy; ID trùng trả `422 PROJECT_ORDER_DUPLICATE`, dự án ngoài phạm vi trả `422 PROJECT_ORDER_PROJECT_NOT_VISIBLE` (FR-PLAN-33, FR-ID-08). |
| GET | `/api/v1/planning/projects/{ref}/tracker-users?probe=&issue=` | `{ status PENDING|DONE|FAILED, error_code, users[{id, name, username, mapped_member_id, suggested_member_id}], unmapped[{member_id, display_name, suggested_user_id}], issue_assignees[] }`; probe của dự án khác trả `FAILED PROBE_NOT_FOUND` (FR-PLAN-32) |
| POST | `/api/v1/planning/projects/{ref}/tracker-users/auto-map?probe=` | Điền mapping cho người khớp duy nhất từ probe đã xong; `409 PROBE_NOT_DONE` khi chưa về; trả `{ filled, names[], unmapped }` (FR-PLAN-32) |
| PUT | `/api/v1/planning/projects/{ref}/members/{member_id}/tracker-user` | CTO hoặc Project Owner. `{ gitlab_user_external_id }` (null để bỏ); `404` khi không phải dự án mình hoặc người không trong dự án (FR-PLAN-32) |
| GET | `/api/v1/planning/people/{plan_date}` | Chỉ CTO. `{ plan_date, over, free, people[{member_id, display_name, available_hours, planned_hours, free_hours, state OVER|FREE|OK|OFF, projects[{id, name, hours, run_status}]}] }`: giờ đã xếp qua mọi kế hoạch chưa bị thay của ngày (FR-PLAN-28) |
| GET | `/api/v1/planning/people` | Mọi vai đăng nhập. Người được xem kế hoạch theo người: `{ me, members[{member_id, display_name, is_me}] }`, nhân sự đang hoạt động, người xem đứng đầu. CTO: mọi người; người khác: chính mình và người chung dự án (dự án được giao và dự án mình là thành viên) (FR-PLAN-40, ADR-0081) |
| GET | `/api/v1/planning/people/{member_id}/plan?from=&to=` | Mọi vai đăng nhập, chỉ đọc, tối đa 62 ngày (`422 RANGE_TOO_LONG`, `422 RANGE_INVALID`); người ngoài phạm vi `404 MEMBER_NOT_FOUND`. `{ member{member_id, display_name, is_me}, from, to, days[{date, capacity_hours, personal_hours, available_hours, planned_hours, off, items[], hidden_projects[{name, hours}]}], totals{planned_hours, available_hours, personal_hours, off_days, by_project[{name, hours, visible}], work_status{PLANNED, IN_PROGRESS, DONE, BLOCKED}, accepted, work_items{<status>: n}} }`. `items[]` theo `kind`: `ASSIGNMENT {id, run_id, run_status, project_id, project, project_name, title, issue, issue_url, intake, priority, slot, hours, work_type, status, accepted_at}`, `WORK_ITEM {id, code, title, status, priority, project_id, project, project_name, channel, urgent, due_date, closed}` (đã đóng ở ngày đóng, còn mở ở hạn), `PERSONAL {id, title, hours, status, start_time}` (chỉ khi xem chính mình). Dự án người xem không có mặt chỉ hiện trong `hidden_projects` và `by_project.visible=false` (FR-PLAN-40, ADR-0081) |
| GET | `/api/v1/planning/overview/{plan_date}` | Chỉ đọc, không mở kế hoạch. Mỗi dự án phần mềm một dòng: `readiness {state, reasons[]}`, `context {band, score, missing[], approved}` (FR-CTX-04), `reports`, `approvals`, `unsynced`, `stuck`, `meetings`, `plan` (kế hoạch riêng của dự án hoặc kế hoạch tổng còn chứa nó), `acceptance`, `gitlab`, `people_off[]`, `unassigned[]`, `carry_over`, `plan.made_by`, `approvals {pending, urgent, cto, po, overdue, has_owner}`, `overdue {approvals, waiting, work_log, p0_open}`, `attention`; đầu trang `overdue_total` và `cto_time {today_minutes, actions_today, avg7_minutes, days[]}` (chỉ CTO, `null` với Project Owner); Project Owner chỉ thấy dự án của mình (FR-PLAN-23, FR-PLAN-26, FR-APR-14, FR-PLAN-27, FR-UI-15). `POST /runs/{id}/approve`, `/accept-proposals`, `GET /runs/{id}/sync-jobs`: CTO hoặc Project Owner của dự án (FR-PLAN-25) |
| PUT | `/api/v1/planning/projects/{project_ref}/agent-ready` | Chỉ CTO. `{ agent_ready: bool }` (FR-MCP-04); `ProjectOut.agent_ready`. `IntakeOut.agent_readiness { score, band: READY|NEEDS_WORK|HUMAN, reasons[], missing[] }` có ở chi tiết và danh sách |
| PATCH | `/api/v1/intakes/{id}/fix-hints` | CTO hoặc PO. `{ fix_hints }` ≤ 2.000 ký tự, trống để xóa; trả `IntakeOut` (có `fix_hints`). Hành trình (`/journey`) có `work { entries, latest_id, latest_decision, latest_at, latest_by, off_plan, worked_on, actual_minutes, deployed }` và `unlogged_evidence { commits, merge_requests, links }|null`; UI dùng `latest_id` để CTO quyết work-log `PENDING` ngay tại bước Nghiệm thu. `unlogged_evidence` chỉ mở luồng ghi nhận kết quả, không tự nghiệm thu. |
| PATCH | `/api/v1/intakes/{id}/hard-flag` | Chỉ CTO (403 với vai khác). `{ needs_cto_acceptance: bool }`; trả `IntakeOut`. Đổi giá trị ghi `intake.hard_flag_changed`. `POST /intakes` và `approve` nhận cùng trường, bỏ qua nếu không phải CTO; MCP `create_intake` nhận `needs_cto_acceptance` (CTO), `get_intake` trả lại. FR-PLAN-39. |
| POST | `/api/v1/mcp-server` | MCP Streamable HTTP (FR-MCP-02): thân JSON-RPC 2.0 (đơn hoặc lô), trả JSON cùng dạng, không bọc envelope; thông báo trả `202`. Chỉ nhận `Bearer itk_…` (`401` với cookie/phiên). Phương thức: `initialize`, `ping`, `tools/list`, `tools/call`; lỗi JSON-RPC `-32601/-32600/-32700`. Kết quả tool: `content[0].text` (JSON) và `structuredContent`; lỗi nghiệp vụ `isError: true` với `MÃ: lời` |
| POST | `/api/v1/mcp-server` (thêm từ ADR-0062) | Tool `propose_work` `{project, date?, issue?, intake?, text?, hours?, slot?}` cho mọi vai có nhân sự; `get_my_day` trả thêm `projects[{id, code, name}]` (FR-PLAN-35) |
| POST | `/api/v1/mcp-server` (thêm từ ADR-0061) | `create_intake` nhận `attachments[{name?, mime_type, data_base64}]` tối đa 3 tệp, mỗi tệp 5 MB, loại image/png, image/jpeg, image/webp, application/pdf; kiểm magic bytes trước khi tạo yêu cầu (`ATTACHMENT_TYPE_MISMATCH`); trả thêm `attachments` (số tệp đã nhận) (FR-AI-14) |
| POST | `/api/v1/mcp-server` (thêm từ ADR-0058) | `tools/list` chỉ liệt kê tool người gọi dùng được (`get_cto_board`, `list_work_log_pending` chỉ CTO). Tool mới: `get_my_day {date?}` → `{date, member, items[{assignment_id, project, project_name, issue, issue_url, title, intake, priority, slot, hours, work_type, primary, work_status, work_status_note, plan_closed}], note, hint}`, lỗi `MEMBER_UNMAPPED`; `update_work_status {assignment_id | issue + date?, status PLANNED\|IN_PROGRESS\|DONE\|BLOCKED, note?}` → `{assignment_id, issue, work_status, previous, at}`, lỗi `ASSIGNMENT_NOT_FOUND` (kể cả việc của người khác); `get_cto_board {date?}` → `{plan_date, overdue_total, missing_projects, projects[]}`; `get_week_summary {week_of?}` → `{week_start, week_end, days_passed, text, projects, people, process}`; `list_work_log_pending {limit?}` → `{pending, entries[{log_id, intake, title, project, summary, agent, branch, commit, verify_steps, deploy_steps, created_at}]}`. `prompts/list` → `today`, `end_day`, `week`, và `board` (CTO); `prompts/get {name, arguments{date? | week_of?}}` → một tin `user` (FR-MCP-06, FR-MCP-07) |
| PATCH | `/api/v1/users/{id}` (thêm 2026-10-14) | `member_id` gắn tài khoản với nhân sự đang hoạt động chưa có tài khoản khác (`""` bỏ gắn; Developer không bỏ được): `MEMBER_REQUIRED`, `MEMBER_HAS_ACCOUNT`. `AccountOut` thêm `member_name`. Tài khoản CTO sửa được dòng của mình (FR-NTF-06) |
| GET | `/api/v1/agent-commands/install.sh`, `/install.ps1`, `/files/{name}.md` | Công khai, text: dòng cài và tệp lệnh ngắn (`in-today`, `in-end-day`, `in-week`, `in-board`, `fix-issue`); không có dữ liệu hay bí mật (FR-MCP-07) |
| GET | `/api/v1/auth/agent-commands` | Phiên đăng nhập (mọi vai). `{ commands[{name, slash (/in-...), mcp_slash, description, when, codex}], install{bash, powershell, repo} }`: prompt của server theo vai dưới dạng lệnh Claude Code, câu nhắc Codex, lúc dùng; thêm `fix_issue` của repo. `AccountOut` thêm `agent_last_used_at` (FR-MCP-07) |
| POST | `/api/v1/users` (thêm từ ADR-0058) | `{ subject, role PROJECT_OWNER\|DEVELOPER = PROJECT_OWNER, member_id? , email?, display_name? }`: `DEVELOPER` lấy email và tên từ nhân sự `member_id` (lỗi `MEMBER_REQUIRED`, `MEMBER_HAS_ACCOUNT`, `MEMBER_EMAIL_REQUIRED`); `projects` của tài khoản Developer là dự án của nhân sự. `GET /auth/tokens`, `POST /auth/tokens`, `DELETE /auth/tokens/{id}` mở cho Developer (FR-MCP-05) |
| GET | `/api/v1/personal-tasks?from=&to=` | Mọi vai có đăng nhập (CTO, Project Owner, Developer). Việc riêng của chính người gọi trong khoảng ngày (mặc định hôm nay và 7 ngày tới, tối đa 92 ngày): `[{id, task_date, title, note, hours, start_time, remind_at, status PLANNED\|DONE\|SKIPPED, done_at, created_at, updated_at}]` (FR-PER-01) |
| POST | `/api/v1/personal-tasks` | `{ title, task_date, hours?, start_time?, remind_at?, note?, important?, urgent? (null = tự tính) }`; `422 TIME_INVALID`, `HOURS_INVALID`, `TITLE_REQUIRED`. `201` trả việc kèm `important, urgent, urgent_effective, quadrant 1..4, quadrant_label` (FR-PER-01, FR-PER-04) |
| PATCH | `/api/v1/personal-tasks/{id}` | Các trường trên, `status`, `task_date: null` (bỏ ngày, về ma trận), `archived` (true lưu trữ, false khôi phục); `404` khi không phải của mình (FR-PER-01, FR-PER-05) |
| GET | `/api/v1/personal-tasks/matrix?week_of=` | `{ week_start, week_end, today, tasks[], summary{today_open, today_hours, quadrants[{quadrant, label, open, hours}], rolled_over, undated, overdue} }`: việc trong tuần, chưa có ngày và tồn từ trước, mỗi việc kèm `rollover_count` (FR-PER-05) |
| POST | `/api/v1/personal-tasks/{id}/delegate` | `{ member_id, project_id, task_date, hours? }`. CTO: mọi nhân sự; Project Owner: `project_id` phải trong dự án mình (`404` nếu không); Developer `403`. Mở kế hoạch của dự án cho ngày đó nếu chưa có, thêm việc `SUPPORT` không Issue cho nhân sự; trả việc riêng với `status DELEGATED`, `delegated_member_name`, `delegated_assignment_id`, `plan{run_id, project_id, plan_date}`. `422 TASK_NOT_OPEN`, `MEMBER_REQUIRED`, hoặc mã của Planning (`PLANNING_RUN_IMMUTABLE`, `OVER_CAPACITY`) (FR-PER-06) |
| GET/POST/PATCH | `/api/v1/personal-tasks` (thêm từ FR-PER-06) | `repeat_rule` `WEEKLY:<0-6>` (Thứ Hai 0) hoặc `MONTHLY:<1-31>`, `""` dừng lặp; `422 REPEAT_INVALID`. Ra thêm `repeat_label`, `done_quadrant`, `delegated_*`. `GET /planning/week/{monday}` của CTO trả `personal{done[], open[], done_total, done_hours, delegated, rollovers, schedule_share}` |
| GET | `/api/v1/personal-tasks/archived` | Việc đã lưu trữ của chính mình, mới nhất trước (FR-PER-05) |
| DELETE | `/api/v1/personal-tasks/{id}` | `204`; `404` khi không phải của mình (FR-PER-01) |
| GET | `/api/v1/planning/capacities/{date}` (thêm từ ADR-0060) | Mỗi dòng thêm `personal_hours`; `available_hours` đã trừ giờ việc riêng (FR-PER-02) |
| POST | `/api/v1/mcp-server` (thêm từ ADR-0060) | `get_my_day` trả thêm `personal[{task_id, title, hours, start_time, remind_at, status, note}]`; tool `add_personal_task {title, date?, hours?, start_time?, remind_at?, note?}` và `update_personal_task {task_id, status?, title?, date?, hours?, start_time?, remind_at?, note?}` (FR-PER-03) |
| PUT | `/api/v1/private-space/master-dna` | `{ text }`. Lưu Master DNA dùng chung |
| PUT | `/api/v1/private-space/voice?track=` | `track`: `business` (mặc định) hoặc `technical`; lưu giọng của riêng mạch đó. `default_channel` nhận cả kênh dài |
| GET | `/api/v1/private-space/ideas?track=` | Thêm lọc theo mạch; mỗi ý có `track` (hoặc `null`) |
| GET, PUT | `/api/v1/private-space/ideas/{id}/track` | Chỉ CTO. `{ track }`, `null` là chưa xếp. `404 IDEA_NOT_FOUND` khi không phải ý của khu riêng |
| POST | `/api/v1/intakes/{id}/drafts` | Thêm `context?` (`REAL`, `EXAMPLE`, `SOURCE`) và `commercial?` (`NONE`, `SPONSORED`, `AFFILIATE`; khác `NONE` chỉ ở mạch `technical`, nếu không `422 COMMERCIAL_NOT_FOR_TRACK`). `source_draft_id` với `track` khác nháp nguồn là chuyển thể sang hướng kia; không nêu `track` thì giữ hướng của nháp nguồn. Thêm `track?`, `goal?` (`AUTHORITY`, `DISCUSSION`, `REACH`, `CONVERSATION`), `audience?` (`SME`, `AGENCY`, `CONSULTANT`, `DEVELOPER`), `pillar?` (tối đa 120 ký tự), `group_context?` (`FNB`, `EDUCATION`, `RETAIL`, `SERVICE`, `AGENCY`, `CONSULTING`). Có `group_context` thì kênh thành `FACEBOOK_GROUP` và `audience` bị bỏ. Không nêu `track` thì theo mạch của ý, rồi tới `business`. Nháp trả về mang các trường này |

Bài dài và sổ ghi chú (FR-CNT-05, FR-CNT-06, ADR-0036):

| Method | Path | Ghi chú |
|---|---|---|
| POST | `/api/v1/intakes/{id}/drafts` | `channel` thêm `BLOG`, `VIDEO_SCRIPT`; `goal` thêm `FOLLOW`; `audience` thêm `AI_USER`; `outline?` (chỉ với hai kênh dài, nếu không `422 OUTLINE_NOT_FOR_CHANNEL`). `source_draft_id` trỏ tới một dàn ý thì bài được viết theo dàn ý đó. Nháp trả về có `kind`: `POST` hoặc `OUTLINE` |
| PATCH | `/api/v1/intakes/{id}/drafts/{draft_id}` | `text` tối đa 30.000 ký tự |
| GET | `/api/v1/private-space/notes?track=` | Chỉ CTO. Ghi chú của một mạch, theo thứ tự `FACT`, `PROOF`, `DECISION`, `RESULT` |
| POST | `/api/v1/private-space/notes` | `201`. `{ track, kind, text }`, `text` 3 đến 1.000 ký tự. `409 NOTES_FULL` khi mạch đã có 60 ghi chú |
| DELETE | `/api/v1/private-space/notes/{note_id}` | `204`; `404 NOTE_NOT_FOUND` |

Kế hoạch tuần, duyệt và luồng đăng (FR-CNT-07..10, ADR-0037, ADR-0038):

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/private-space/plan?week=` | Chỉ CTO. `week` là một ngày thứ Hai (mặc định tuần này, giờ Việt Nam); ngày khác trả `422 WEEK_INVALID`. Trả `tracks` (mỗi mạch: `slots`, `stats`, `request`), `rhythm`, `editable` |
| PUT | `/api/v1/private-space/plan/rhythm?track=` | `{ slots: [{ weekday 1..7, time "HH:MM"?, channel, pillar? }] }`, tối đa 7 ô |
| POST | `/api/v1/private-space/plan/propose` | `202`. `{ track, week_start, keywords? }`. `409 WEEK_NOT_OPEN` ngoài tuần này và tuần sau; `409 NO_OPEN_SLOT` khi không còn ô trống. Hỏi lại `GET …/plan` tới khi `request.status` khác `PENDING` |
| GET | `/api/v1/private-space/plan/slots/{id}` | Một ô |
| PATCH | `/api/v1/private-space/plan/slots/{id}` | Chỉ đổi trường được gửi: `intake_id` (`null` để gỡ), `skipped`, `dismiss`. `409 SLOT_LOCKED` khi ô đang giữ bài đã duyệt |
| POST | `/api/v1/private-space/plan/slots/{id}/accept` | Chốt đề xuất của AI. Trả `{ slot, created_idea_id }`; `created_idea_id` có giá trị khi một ý mới được tạo |
| POST | `/api/v1/intakes/{id}/drafts/{draft_id}/approve` | `{ slot_id?, scheduled_for? }`. `409 SLOT_TAKEN` khi ô bị bỏ qua hoặc đang giữ ý hay bài khác; `422 OUTLINE_NOT_POSTABLE` với dàn ý |
| DELETE | `/api/v1/intakes/{id}/drafts/{draft_id}/approve` | Bỏ duyệt. `409 DRAFT_POSTED` khi bài đã đăng |
| PATCH | `/api/v1/intakes/{id}/drafts/{draft_id}` | Thêm `posted_at?`, `posted_url?` đi cùng `posted: true`. `409 DRAFT_APPROVED` khi sửa chữ của nháp đã duyệt; `422 POSTED_IN_FUTURE` |
| GET | `/api/v1/publish/queue?channel=` | Không qua đăng nhập. `Authorization: Bearer <PUBLISH_API_KEY>`. Xem `docs/stable/publish-flow.md` |
| POST | `/api/v1/publish/events` | Không qua đăng nhập. Ký bằng `X-Intake-Timestamp` và `X-Intake-Signature`. Xem `docs/stable/publish-flow.md` |

Nháp trả về có thêm `approved_at`, `scheduled_for`, `posted_url`, `posted_via` (`MANUAL` hoặc `WEBHOOK`), `publish_error`, `slot_id`.

Nguồn theo dõi và tín hiệu (FR-CNT-11, FR-CNT-12, ADR-0039):

| Method | Path | Ghi chú |
|---|---|---|
| GET, POST | `/api/v1/private-space/watch/sources` | Chỉ CTO. Thêm: `{ url, track: business, technical hoặc both, label?, kind?, note? }`. `409 SOURCE_EXISTS`, `409 SOURCES_FULL` (80 nguồn) |
| PATCH, DELETE | `/api/v1/private-space/watch/sources/{id}` | Đổi `track`, `active`, `label`, `note`; chỉ trường được gửi mới đổi |
| GET, PUT | `/api/v1/private-space/watch/keywords?track=` | Trả `pillars` (trụ và từ khóa), `request` (trạng thái gợi ý), `suggested` (gợi ý chưa giữ). Lưu: `{ pillars: { "<trụ>": [từ khóa] } }`, tối đa 12 mỗi trụ |
| POST | `/api/v1/private-space/watch/keywords/suggest?track=` | `202`. Hỏi lại `GET …/keywords` tới khi `request.status` khác `PENDING`. `409 NO_PILLARS` |
| GET, PUT | `/api/v1/private-space/watch/demand?track=` | `{ wanted_per_week 0..50, weekday 1..7, time "HH:MM", lookback_days 1..30 }`. Trả thêm `deadline`, `window_start`, `received`, `remaining`, `accept_up_to`. `GET /api/v1/watch/config` trả cùng khối này ở `demand` của mỗi mạch |
| POST | `/api/v1/private-space/prompt-preview` | Chỉ CTO (FR-CNT-14). `{ track, voice?, master_dna?, intake_id?, channel, outline?, goal?, audience?, pillar?, group_context?, angle?, source_draft_id?, context?, commercial? }`; `voice` và `master_dna` là nội dung đang có trên màn hình, bỏ trống thì dùng bản đã lưu. Trả `prompt_version`, `model`, `system_prompt`, `blocks` (`key`, `trust`: `CHOICE`, `AUTHOR`, `DATA`, `UNTRUSTED`; `text`, `chars`, `cuts`), `message_chars`, `placeholder`. Không gọi AI, không lưu |
| POST | `/api/v1/private-space/voice-trial` | Chỉ CTO (FR-CNT-16). `{ track, voice?, master_dna?, channel, idea? }`; `voice` và `master_dna` là nội dung đang có trên màn hình, `idea` một dòng ≤ 500 ký tự (trống thì dùng một tình huống chung). Gọi AI ngay (prompt soạn nháp với dòng `Trial`), trả `{ text, prompt_version, model, message_chars }`. Không lưu gì; ghi một sự kiện kiểm toán `private_space.voice_tried`. `503` khi AI không trả lời |
| GET | `/api/v1/private-space/watch/health` | Chỉ CTO (FR-CNT-13). `last_config_at`, `last_signal_at`, và mỗi mạch: `warning`, `reason` (`ROUTES_CLOSED`, `NO_SOURCES`, `NO_KEYWORDS`, `FLOW_SILENT`, `NOTHING_SENT`), `checked_at`, `received`, `remaining`, `deadline` |
| POST | `/api/v1/private-space/watch/health/check` | Chạy lượt kiểm ngay, trả cùng dạng |
| GET | `/api/v1/private-space/watch/signals?track=&state=` | `state`: `NEW` (mặc định), `USED`, `DISMISSED` |
| POST | `/api/v1/private-space/watch/signals/{id}/idea` | Chuyển thành ý của mạch đó. Trả `{ signal, idea_id }` |
| DELETE | `/api/v1/private-space/watch/signals/{id}` | Bỏ tín hiệu |
| GET | `/api/v1/watch/config` | Không qua đăng nhập. `Authorization: Bearer <WATCH_API_KEY>`. Xem `docs/stable/watch-flow.md` |
| POST | `/api/v1/watch/signals` | Không qua đăng nhập. Ký bằng `X-Intake-Timestamp` và `X-Intake-Signature`. Xem `docs/stable/watch-flow.md`. Từ ADR-0068: mục nhận thêm `project`, `via`, `priority`; `config` trả thêm `projects[]` và `terms[]` trong mỗi trụ |

## Ngữ cảnh dự án và chi tiết của yêu cầu (FR-AI-12, ADR-0032)

| Method | Path | Ghi chú |
|---|---|---|
| GET, PUT | `/api/v1/projects/{ref}/brief` | Gửi `{ "brief" }`, tối đa 4000 ký tự; trả `{ "brief", "ai_source": "PACK" \| "BRIEF", "pack_approved_at", "pack_sections": [tên mục] }` cho biết AI đang đọc hồ sơ ngữ cảnh đã duyệt (mục 1 và 2) hay ô tự do (FR-CTX-05). CTO hoặc Project Owner của dự án; ngoài phạm vi trả `404` |
| GET | `/api/v1/intakes/{id}` (bổ sung) | Thêm `details` (hoặc `null`): `where`, `steps`, `expected`, `subtasks`, `acceptance`, `open_questions`, `related[]` gồm `id`, `title`, `url` |
| PATCH | `/api/v1/intakes/{id}/review` (bổ sung) | Nhận thêm `details` tùy chọn: `where`, `subtasks`, `acceptance` (mỗi danh sách tối đa 12 dòng, mỗi dòng 300 ký tự). Các phần khác của chi tiết giữ nguyên |

Bản phê duyệt (`approval_snapshots.payload`) có thêm khóa `details` khi yêu cầu có chi tiết.
| POST | `/api/v1/intakes/{id}/split` | `{ expected_version, items[] }`, 2 đến 8 dòng, mỗi dòng tối đa 300 ký tự (FR-APR-09). Trả `original` và `children`. `409 NOT_SPLITTABLE` khi yêu cầu đã có quyết định; `409 STALE_VERSION` |

Phần `details` có thêm `split_suggested` (AI cho rằng các việc con nên là yêu cầu riêng).

| Method | Path | Ghi chú |
|---|---|---|
| PUT | `/api/v1/intakes/{id}/clarifications` | `{ expected_version, answers[], reanalyse }` (FR-APR-10). Mỗi phần tử: `question`, `answer` (tối đa 1000 ký tự) hoặc `skipped`. `reanalyse: true` thì xếp hàng phân tích lại. `409 DECISION_LOCKED` khi đã duyệt; `409 STALE_VERSION` |
| POST | `/api/v1/intakes/{id}/ready` | `{ expected_version }`. Đưa yêu cầu đang "Cần làm rõ" hoặc đang hoãn về chờ duyệt. `409 NOT_WAITING`, `409 REVIEW_REQUIRED` (thiếu tiêu đề hoặc tóm tắt) |

Phần `details` có thêm `clarifications[]` gồm `question`, `answer`, `skipped`.

| Method | Path | Ghi chú |
|---|---|---|
| DELETE | `/api/v1/intakes/{id}` | Xóa hẳn (FR-APR-11). Trả `{ deleted, public_id, attachments_left }`. `409` với `INTAKE_DECIDED`, `INTAKE_PROCESSING`, `INTAKE_HAS_EXTERNAL`, `INTAKE_PLANNED` |
| POST | `/api/v1/intakes/{id}/duplicate` | `{ of, expected_version }`; `of` là mã hoặc ID của yêu cầu được giữ, cùng dự án (FR-APR-12). `409 DUPLICATE_TARGET_NOT_FOUND`, `DUPLICATE_TARGET_INVALID`, `DECISION_LOCKED` |
| POST | `/api/v1/intakes/{id}/duplicate-issue` | `{ issue, expected_version }`; `issue` là số Issue GitLab đang có của dự án (`"22"` hoặc `"#22"`), phải có trong dữ liệu GitLab đã tải (FR-APR-12, từ 2026-10-19). `409 DUPLICATE_TARGET_NOT_FOUND` (không phải Issue của dự án), `DUPLICATE_TARGET_INVALID` (Issue tạo từ chính yêu cầu), `DECISION_LOCKED` |
| DELETE | `/api/v1/intakes/{id}/duplicate?expected_version=N` | Bỏ đánh dấu trùng (cả trùng yêu cầu và trùng Issue); yêu cầu về chờ duyệt. `409 NOT_A_DUPLICATE` |

`IntakeOut` có thêm `duplicate_of_id`, `duplicate_issue` (`system`, `external_id`, `title`, `url`; null khi không trùng Issue) và, ở `GET /intakes/{id}`, `duplicate_of` gồm `id`, `public_id`, `title`. MCP `get_intake` trả cùng `duplicate_issue`.

## Thiết lập lần đầu (FR-SETUP-01..09, ADR-0069, ADR-0071)

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/setup` | Chỉ CTO. Trả `completed`, `has_project`, `has_private_space`, `sample_available`. `completed` đúng khi đã đánh dấu hoặc đã có dự án thật |
| POST | `/api/v1/setup/private-sample` | Chỉ CTO. Nạp bộ DNA mẫu hư cấu vào khu riêng (mở khu nếu chưa có). `422 SAMPLE_INVALID` hoặc `SAMPLE_MISSING` khi bộ mẫu hỏng; trả trạng thái như GET |
| POST | `/api/v1/setup/complete` | Chỉ CTO. Đánh dấu đã thiết lập, gọi lại vô hại; trả trạng thái như GET. Khi cờ wizard bật mà chưa có route AI: `422 AI_KEY_REQUIRED`. `GET /setup` có thêm `ai_ready`, `wizard` |
| POST | `/api/v1/setup/demo-project` | Chỉ CTO, chỉ khi cờ wizard bật (tắt: `422 NOT_FOUND`). Nạp dự án mẫu hư cấu (`demo`, khóa `DEM`) và đánh dấu đã thiết lập; gọi lại vô hại. `422 SAMPLE_MISSING`, `SAMPLE_INVALID`, `DEMO_CODE_TAKEN`. Trả trạng thái như GET. `GET /setup` có thêm `has_demo`, `demo_available`; khi `has_demo`, `/setup/complete` không đòi `AI_KEY_REQUIRED` |
| GET | `/api/v1/showcase` | Chỉ CTO (FR-SETUP-15). Danh mục dự án mẫu từ `app/resources/showcase.json`: `{version, groups, items[]}`, mỗi mục có `key`, `kind` (`demo`/`real`), `name`, `summary`, `repo_url`, `languages`, `license`, `state` (`off`/`on`/`archived`), `project_code`, `sample_requests`, `in_catalog`. |
| PUT | `/api/v1/showcase/{key}` | Chỉ CTO (FR-SETUP-15). Body `{enabled}`. Bật lần đầu tạo dự án (`real`) hoặc nạp dự án mẫu (`demo`); tắt đặt dự án `INACTIVE`, bật lại khôi phục đúng dự án. `404 NOT_FOUND` khi khóa không có trong danh mục, `409 PROJECT_CODE_TAKEN` khi mã dự án đã bị chiếm. |
| DELETE | `/api/v1/showcase/{key}/samples` | Chỉ CTO (FR-SETUP-16). Xóa các yêu cầu thử (cờ `test_data`, còn chờ duyệt) của mục; trả `{removed}`. |
| GET | `/api/v1/setup/status` | Công khai. `{needs_bootstrap}`; đúng khi `FIRST_RUN_WIZARD` bật và chưa tạo tài khoản đầu (FR-SETUP-05, ADR-0071) |
| POST | `/api/v1/setup/bootstrap` | Công khai, một lần, miễn CSRF, có giới hạn tốc độ. Body `{cto:{email,display_name,password}, owner:{...}\|null}`. Đặt cookie phiên và CSRF của CTO. `404` khi cờ tắt, `409 BOOTSTRAP_DONE`, `422` mật khẩu ngắn hoặc email trùng (FR-SETUP-06) |

## Khóa LLM và route theo tác vụ (FR-AI-15..19, ADR-0070)

Tất cả chỉ CTO. Khóa chỉ nhận khi tạo hoặc sửa; response chỉ có `key_hint` (4 ký tự cuối) và `key_ok` (sai khi không giải mã được).

| Method | Path | Ghi chú |
|---|---|---|
| GET | `/api/v1/ai/providers` | Danh sách provider: `id`, `name`, `base_url`, `enabled`, `key_hint`, `key_ok`, `extra_body`, `last_test_at`, `last_test_ok`, `last_test_error` |
| POST | `/api/v1/ai/providers` | `{ name (≤32), base_url, api_key, enabled?, extra_body? }`. `422 AI_BASE_URL_INVALID`, `409 AI_PROVIDER_NAME_TAKEN` |
| PATCH | `/api/v1/ai/providers/{id}` | Các trường như trên, đều tùy chọn; `api_key` để trống thì giữ khóa cũ |
| DELETE | `/api/v1/ai/providers/{id}` | `409 PROVIDER_IN_USE` khi còn route trỏ tới |
| POST | `/api/v1/ai/providers/{id}/test` | Gọi `GET {base_url}/models`. Trả `ok`, `error` (mã: `AUTH`, `TIMEOUT`, `HTTP_<n>`, `NETWORK`, `KEY_UNREADABLE`), `models[]` |
| POST | `/api/v1/ai/providers/{id}/probe` | `{ kind, model }` (`kind`: `vision` hoặc `stt`). Thử model bằng ảnh mẫu (số 482) hoặc 1,5 giây âm thanh mẫu; lưu kết quả theo (provider, model, kind). Trả `kind`, `model`, `ok`, `error` (`NOT_SUPPORTED`, `NOT_READ`, `AUTH`, `TIMEOUT`, `NETWORK`, `KEY_UNREADABLE`, `QUOTA` (nhà cung cấp trả 429: hết hạn mức hoặc model ngoài gói của khóa), `MODEL_NOT_FOUND` (trả 404: sai tên model hoặc model đã ngừng cho khóa mới), `PROVIDER_TRANSIENT` (trả 5xx khi thử ảnh), `HTTP_<n>`), `checked_at`. Chỉ `NOT_SUPPORTED` và `NOT_READ` của lần thử ảnh làm route `vision` bỏ qua model của `default` (FR-AI-22). `422 AI_PROBE_KIND_INVALID`, `422 AI_MODEL_INVALID`. Chỉ CTO (FR-AI-21) |
| GET | `/api/v1/ai/routes` | Bảy dòng `default`, `normalize`, `report`, `meeting`, `vision`, `content`, `stt` (`stt` không rơi về `default`; chưa đặt thì hiện khóa ElevenLabs của `.env` với `source: env`): `task`, `provider_id`, `provider_name`, `model`, `source` (`route`, `default`, `env`, `none`), `check_ok`, `check_error`, `checked_at` (kết quả thử mẫu của model đang phục vụ; dòng `default` mang kết quả thử ảnh). `vision` không rơi về `default` khi model đó đã thử ảnh hỏng (FR-AI-22) |
| PUT | `/api/v1/ai/routes/{task}` | `{ provider_id, model }`; `provider_id: null` xóa route. `404 AI_TASK_UNKNOWN`, `422 AI_PROVIDER_NOT_FOUND` |

`GET /api/v1/operations/status` có thêm `ai_configured` và `ai_source`; các trường cũ giữ nguyên.

`POST /api/v1/auth/login` nhận email hoặc tên tài khoản trong trường `subject` (FR-SETUP-07).
