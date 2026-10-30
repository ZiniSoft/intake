# Kế hoạch kiểm thử và nghiệm thu 1.2

_Cập nhật 2026-10-01 | Test catalog là target; evidence đã chạy xem `PRODUCTION-READINESS.md` và các Gate report_

## 1. Test layers

| Layer | Phạm vi |
|---|---|
| Unit | Validator, state machine, redaction, key generation, provider classification |
| Database contract | PostgreSQL types, constraints, JSONB, TIMESTAMPTZ, indexes, locking |
| Component | API + PostgreSQL/Redis/SeaweedFS test services |
| Adapter contract | UModelVerse, OpenRouter, GitLab, GitHub, IMAPS với stub và sandbox thật |
| E2E | Browser/API xuyên suốt trên pilot topology |
| Security | Auth/MFA/session, project isolation, file safety, secret/log checks |
| Performance | Keyset list, detail, dashboard, queue claim với dataset chuẩn |
| Operations | Restart, backup/restore, rollback và incident drills |

### Evidence tự động gần nhất

- SQLite isolation: `80 passed, 2 skipped, 1 warning`.
- PostgreSQL 16 production-like: `82 passed, 1 warning`.
- Frontend Vitest: `4 passed`.
- TypeScript và Docker production build: đạt.
- Planning Chrome desktop/mobile mocked E2E: đạt, gồm per-Issue failed -> retry -> pending.
- Planning live internal mutation: tạo run + Quick Add Intake/candidate thật, dừng trước approval và dọn sạch dữ liệu test.

Các con số này là snapshot working tree ngày 2026-10-01, không thay thế Gate report/release commit.

Bổ sung ngày 2026-10-05 (commit `0064c33` trên nhánh `feature/ui-shell-email-reports`):

- SQLite isolation: `111 passed, 2 skipped`. PostgreSQL production-like chưa chạy lại sau các migration 004 đến 006.
- `frontend/e2e/intake-composer.mjs`: 10 kịch bản Chrome desktop/mobile đạt trên dev server, request ghi Intake bị mock.
- `meeting-capture.mjs` (micro giả), `meeting-upload.mjs` (file WAV), `meeting-notes.mjs` (trang Cuộc họp): đạt trên stack pilot với ElevenLabs và UModelVerse thật, dùng hội thoại tổng hợp hai giọng khoảng 32 giây.
- Chưa có: thử với Zoom/Meet/Teams thật, phiên 60 phút, cuộc họp nhiều người, gate report cho ghi âm cuộc họp, và Vitest chưa chạy lại.

## 2. Test bắt buộc

| ID | Test | Kết quả mong đợi |
|---|---|---|
| T-001 | Tạo text intake | DB + outbox cùng commit; response không echo raw |
| T-002 | Redis down sau DB commit | Intake vẫn còn; publish lại khi Redis phục hồi |
| T-003 | Hai dispatcher claim cùng event | Chỉ một dispatch có hiệu lực |
| T-004 | UModelVerse success | JSON valid persist bằng JSONB, provider/model trace đúng |
| T-005 | UModelVerse 429/5xx | Pilot: retry hữu hạn rồi run `FAILED`, không gọi provider khác (ADR-0011). Fallback chỉ kiểm khi được bật sau pilot |
| T-006 | UModelVerse 401/403 | Fail permanent, không retry và không gọi provider khác |
| T-007 | Invalid model ID | Chặn trước network call |
| T-008 | Approve stale version | 409, không snapshot |
| T-009 | Approve thành công | Snapshot immutable; không external write |
| T-010 | Sửa item sau approve | Snapshot invalidated; Sync bị chặn |
| T-011 | Double/concurrent Sync | Một external item |
| T-012 | Mapping project disabled | Fail closed, không route sang project khác |
| T-013 | Hai dự án song song | Không cross-project data/job/token/target |
| T-014 | File >5 MB/sai magic bytes | 413/422; không object orphan |
| T-015 | File không qua kiểm tra an toàn (ADR-0015): sai magic bytes, vượt số trang, PDF mã hóa hoặc có file nhúng | Reject + audit; không OCR/vision/cloud call |
| T-015a | OCR vượt timeout/giới hạn tài nguyên hoặc cố gọi mạng | Container bị dừng/chặn; run lỗi có trace; file khác không bị ảnh hưởng |
| T-015c | Xử lý ảnh/PDF hợp lệ | Request tới UModelVerse chỉ chứa phần chữ đã OCR; không có file gốc, base64 hay lời gọi model vision |
| T-015d | Gọi máy OCR thiếu/sai xác thực hoặc sai địa chỉ | Bị từ chối; máy OCR không còn file/kết quả sau xử lý |
| T-015b | Tải/xem attachment | Cần authorization và đúng project; response trực tiếp dạng download với `no-store`, `nosniff`; UI fetch blob đã xác thực để xem ảnh trong modal, không nhúng URL tệp trực tiếp |
| T-016 | Một trang PDF lỗi | PARTIAL + warning/evidence còn dùng được |
| T-017 | IMAPS duplicate | Một email record |
| T-018 | SMTP attempt từ worker | Network policy chặn |
| T-019 | Raw quá 90 ngày | Ciphertext/object purge + audit |
| T-020 | Restore drill | RPO <=24h, RTO <=4h |
| T-021 | Scheduler 07:00 ngày thường | Một Planning Run idempotent, timezone Việt Nam đúng |
| T-022 | Scheduler 07:00 cuối tuần không OT | Run vẫn tạo; capacity mặc định 0; không cảnh báo thiếu report cho người không OT |
| T-023 | CTO nhập OT cuối tuần | Override có reason; capacity đúng và report expectation được bật |
| T-024 | Trừ meeting/review/support/fixed | Available capacity đúng; không âm |
| T-025 | Report thiếu/muộn/sai format | Planning Run vẫn tạo từ GitLab và warning đúng mức |
| T-026 | Email DONE, GitLab Doing | GitLab state được dùng; task vẫn carry-over; `STATUS_MISMATCH` hiển thị |
| T-027 | Email có blocker, GitLab Doing | Blocker warning không bị bỏ qua |
| T-028 | Hai primary development task | Chặn approval nếu thiếu CTO override reason |
| T-029 | Morning/afternoon over-capacity hoặc overlap | Chặn/cảnh báo theo rule; override được audit |
| T-030 | Quick Add ba nguồn | Existing/form/paste đều truy vết source; item mới đi qua normalize/dedupe |
| T-031 | Assignment chưa có GitLab Issue | Planning approval fail closed; P0 dùng Emergency Add để Intake tạo ngay Issue tối thiểu (xem T-043) |
| T-032 | Planning approve stale version | 409; không snapshot/job |
| T-033 | Planning approve thành công | Immutable snapshot và đúng một job trên mỗi Issue |
| T-034 | GitLab update partial failure | Run `PARTIAL`; job thành công không rollback; retry chỉ job lỗi |
| T-035 | Double/concurrent Planning approval/retry | Không lặp assignee/milestone/due-date side effect |
| T-036 | User mapping thiếu hoặc milestone không tồn tại | Fail closed trước external update |
| T-037 | Project Owner cố approve trong phase hiện tại | 403; CTO approval vẫn hoạt động |
| T-038 | Quick Add form/paste commit nhưng enqueue tạm lỗi | Intake + candidate vẫn tồn tại; normalize/dedupe được retry, không tạo bản ghi trùng |
| T-039 | CTO sửa assignment trước approval | Sáu field priority/assignee/milestone/due date/slot/planned hours lưu đúng expected version; mapping/capacity/WIP vẫn fail closed |
| T-040 | Planning sync trong pilot | GitLab chỉ đổi assignee/milestone/due date; priority label không bị thay đổi |
| T-041 | Amendment run đã approved | Tạo revision mới + immutable snapshot, liên kết supersede; chỉ Issue có delta sinh job và retry vẫn idempotent |
| T-042 | Pilot activation IMAPS | Read-only TLS probe, ingest report thật, revision/warning và UID dedupe đạt; SMTP egress vẫn bị chặn |
| T-043 | Emergency Add P0 (ADR-0012) | Đúng một GitLab Issue tối thiểu với `priority:p0`, có lý do và audit; không phải CTO, priority khác P0, thiếu lý do hoặc retry trùng đều không tạo Issue |
| T-044 | Priority của Planner (ADR-0013) | Issue có snapshot đã duyệt dùng priority của snapshot gần nhất; Issue chưa có dùng GitLab label; hai giá trị khác nhau được hiển thị |
| T-045 | Thiếu milestone/due date (ADR-0013) | Approve bị từ chối khi warning chưa acknowledge, thành công khi đã acknowledge; job không gửi và không xóa trường thiếu |
| T-046 | Truy cập `intake.example.com` (ADR-0014) | HTTPS với chứng chỉ hợp lệ qua VPN; không truy cập được từ ngoài VPN; cookie có `Secure` |
| T-047 | Intake approval không ghi outbox (OD-017) | Approve tạo snapshot và audit, không tạo outbox event `intake.approved` |
| T-048 | Work-log CTO xác nhận và các màn hình trạng thái (INT-26W43-004) | `CONFIRMED` cùng transaction chấp nhận Issue, enqueue đóng tracker; Daily Planning, chi tiết Intake và Việc của tôi đều có `accepted_at`/"Đã nghiệm thu"; collector backfill dòng `CONFIRMED` cũ; URL Planning dùng `date`, `project`, mã Intake công khai và focus đúng thẻ |
| T-049 | Vòng đời quản lý ở Tất cả Intake | Mọi dòng luôn có một trong tám `lifecycle_stage`; filter `stage` dùng cùng nguồn sự thật; Work đi qua Chờ xếp việc/Đang thực hiện/Chờ nghiệm thu/Đã nghiệm thu, phản hồi trực tiếp và Issue được CTO nghiệm thu hoặc Project Owner xác nhận xong vào Đã nghiệm thu, các kết quả kết thúc gom Đã dừng nhưng còn lý do chi tiết |
| T-050 | CTO nghiệm thu ngay trên hành trình Intake | Journey trả `work.latest_id`; khi log mới nhất `PENDING`, CTO thấy và dùng được hai CTA ngay ở bước Nghiệm thu; xác nhận tạo nghiệm thu/xếp đóng Issue, trả lại bắt buộc lý do; PO không có CTA; sau quyết định Journey và Lịch sử xử lý cùng refresh; `CONFIRMED` thiếu `accepted_at` không còn hiện "chờ CTO kiểm" |
| T-051 | Một Issue chỉ xuất hiện một lần trong Daily Planning (INT-26W43-005) | Planner không tách việc trên 4 giờ thành hai thẻ sáng/chiều; API thêm tay và promote candidate từ chối Issue đã có bằng `ISSUE_ALREADY_PLANNED`; unique index chặn race; migration 056 giữ dòng có tiến độ cao nhất, nối lại candidate/warning, gộp giờ tối đa 4 và xóa dòng dư; `get_my_day.items[].issue_url` và thẻ Việc của tôi mở được chi tiết Issue để làm |

## 3. Performance baseline

Dataset chuẩn tối thiểu: 2 projects, 100.000 intakes, 300.000 source messages, 100.000 processing runs và representative audit volume.

- List p95 <= 500 ms với indexed project/status/cursor query.
- Detail p95 <= 800 ms, không tải binary/raw history mặc định.
- Worker claim không full-table scan; `EXPLAIN ANALYZE` lưu trong evidence.
- Concurrent create/process/sync không duplicate và không deadlock ngoài retry policy.

## 4. Security acceptance

- Không secret trong repository/image/log.
- Project Owner giả lập không đọc raw/approve/sync.
- Cross-project ID trả 404 hoặc policy-safe response.
- Session/recovery code rotation hoạt động.
- Attachment download authorization và signed URL expiry.
- AI worker không có GitLab/GitHub token; IMAPS worker không có SMTP credential.

## 5. UAT

CTO thực hiện tối thiểu trên ít nhất hai dự án:

1. Tạo intake text và attachment.
2. Xem pipeline/provenance.
3. Sửa kết quả, approve và xác nhận chưa có external item.
4. Sync đúng project và kiểm liên kết.
5. Thử stale snapshot, duplicate click, provider failure và project mapping thiếu.
6. Xem report/blocker và audit.
7. Tạo Planning Run ngày thường và cuối tuần, nhập OT override và kiểm capacity sáng/chiều.
8. Thử report thiếu/sai/muộn, conflict email/GitLab và xác nhận run vẫn tạo với warning.
9. Quick Add từ existing item, form và paste; xác nhận mọi delivery assignment có GitLab Issue.
10. Duyệt Planning Run và kiểm assignee/milestone/due date trên đúng GitLab project.
11. Fault-inject một Issue update lỗi, xác nhận `PARTIAL`, retry riêng và không rollback Issue đã thành công.

## 6. Go/no-go

### Go

Tất cả MUST trong phạm vi controlled pilot đạt `VERIFIED`, không P0/P1, backup/restore đạt và CTO ký Gate G.

### Conditional go

Chỉ áp dụng với SHOULD/P2 có workaround, owner/deadline và risk acceptance bằng văn bản.

### No-go

Có khả năng leak/cross-project, mất accepted intake, duplicate external side effect, file chưa scan đi cloud, restore không đạt hoặc requirement trạng thái bị báo cao hơn evidence.

