[English](functional-spec.md) | Tiếng Việt

# Đặc tả chức năng

_Target behavior 1.2 | Cập nhật 2026-10-01 | Trạng thái thực thi xem PRODUCTION-READINESS và IMPLEMENTATION-INVENTORY_

## 0. Ranh giới target/runtime

Use case trong tài liệu này là hành vi đích. Runtime hiện đã khép kín text Intake, approval/sync, Daily Report parser và phần lớn Daily Planning; các phần chưa có code/live evidence vẫn giữ trong use case nhưng được liệt kê tại `IMPLEMENTATION-INVENTORY.md`. Đáng chú ý: Project Owner, Emergency Add tự tạo Issue, Planning assignment editor/amendment, auto-normalize Quick Add và live IMAPS chưa hoạt động. Chính sách đích cho các khoảng trống Planning đã được CTO chốt ngày 2026-10-01 tại ADR-0010 và bổ sung ngày 2026-10-03 tại ADR-0011 đến ADR-0014.

## 1. Persona

### CTO

Người dùng duy nhất trong pilot. Có quyền xem raw source, tạo/sửa intake, chạy/retry pipeline, quyết định priority/route, approve, sync và xem audit/operations.

### Nhân sự dự án

Không đăng nhập Intake. Nhận công việc đã duyệt qua GitLab và cập nhật delivery state tại GitLab.

### Project Owner

Chưa đăng nhập Intake trong pilot. Có thể tham gia discovery qua Plane và delivery planning qua GitLab.

Từ 2026-10-05 (ADR-0022) được CTO cấp quyền theo dự án: trong dự án được cấp thì xem nội dung gốc, tạo, phê duyệt và đồng bộ Intake, làm việc với cuộc họp; không thấy gì của dự án khác. Báo cáo ngày và Daily Planning theo dự án là đợt 2. Trước đó tài liệu ghi: phase sau có thể được cấp quyền xem và duyệt Planning Run trong các project được phân quyền. CTO luôn giữ quyền override; quyền Project Owner không được mở toàn hệ thống.

## 2. Navigation

| Màn hình | Mục đích |
|---|---|
| Login/MFA | Xác thực local account và TOTP |
| Dashboard | Việc cần CTO quyết định và hàng chờ phê duyệt; trạng thái hệ thống đã chuyển sang Cài đặt |
| New Intake | Chọn project/channel, nhập text, upload file |
| All Intakes | List có filter project/stage/priority/đích sync/tìm kiếm và cặp page/cursor trong URL có thể chia sẻ, keyset pagination tự về trang đầu khi cursor không hợp lệ, P0/P1 summary theo project, nút chép liên kết và link work item |
| Intake Detail | Raw source, attachment, pipeline, AI result, evidence, audit |
| Approval Queue | Item cần CTO quyết định |
| Sync Queue | Job chờ/chạy/lỗi và retry có kiểm soát |
| Projects | Danh sách dự án theo loại và liên kết; wizard tạo dự án bốn bước và màn hình sửa dự án (ADR-0020) |
| Reports | Báo cáo ngày: thư gốc bên cạnh task đã trích, xác nhận hoặc loại. Tóm tắt ngày/tuần theo project chưa có |
| Meetings | Danh sách cuộc họp; bản chữ theo người nói, nghe lại, tải xuống, meeting note và chuyển mục thành Intake |
| Meeting recorder | Sidebar phải ở trang tạo Intake: chọn dự án, nguồn âm, thuật ngữ, bản chữ realtime |
| Daily Planning | Tổng quan mọi dự án, thứ tự ưu tiên hoặc tùy chỉnh theo tài khoản; Planning Run theo ngày, capacity, hai lane sáng/chiều, conflict/warning và GitLab sync status |
| Capacity | Default/override theo người/ngày; họp, review, support và OT |
| Settings | Một trang có tab gom cấu hình ít dùng: Dự án, Nhân sự (gán dự án và người dùng GitLab), Thuật ngữ, Hệ thống, Tài khoản và bảo mật (MFA, recovery code) |

## 3. Use cases

### UC-01 - Tạo intake

1. CTO chọn project bắt buộc.
2. Chọn channel và nhập text hoặc file.
3. Server validate, encrypt raw text, lưu file quarantine và commit outbox cùng transaction.
4. UI nhận `201` với public ID và pipeline status.

Không được nhận intake nếu project inactive, payload vượt giới hạn hoặc object persistence thất bại.

### UC-02 - Xử lý AI

1. CTO hoặc policy enqueue process.
2. Dispatcher publish run ID.
3. Worker xử lý source, gọi provider chain, validate output và materialize review fields.
4. UI hiển thị provider/model, warning, evidence và terminal state.

Retry cùng input/prompt/schema không tạo extraction hiện hành trùng ngoài policy versioning.

### UC-03 - Review

CTO so raw source với AI proposal, chỉnh type/title/summary/priority/route/acceptance criteria, xử lý duplicate và ghi chú thiếu thông tin. Mọi thay đổi tăng item version.

### UC-04 - Approve

CTO phải lưu normalized review trước. CTO gửi `expected_version`; server chỉ cho approve khi item ở `PENDING_APPROVAL` và có normalized title/summary, sau đó validate route prerequisite, redaction, project mapping requirement và tạo immutable snapshot. Kết quả là `APPROVED`; chưa có external write. Approve trực tiếp từ `NEW` trả `REVIEW_REQUIRED`.

### UC-05 - Sync

CTO chọn snapshot hợp lệ và bấm Sync. API tạo idempotent sync job/outbox, trả `202`. Integration worker tạo/cập nhật GitLab hoặc GitHub Issue, lưu external link hoặc error terminal. Retry không tạo duplicate.

### UC-06 - Reject, defer, request information

- Reject: reason bắt buộc, terminal trừ khi reopen theo quyền.
- Defer: thời điểm tương lai bắt buộc.
- Request information: ít nhất một câu hỏi cụ thể.

### UC-07 - Email report

Worker đọc email mới qua IMAPS, dedupe, mã hóa/lưu, map project và tạo source cho report. Email không tự thay đổi phần trăm GitLab Issue và không tạo outbound mail.

### UC-08 - Multi-project

CTO có thể thao tác song song nhiều dự án. Project filter luôn hiển thị rõ; P0/P1, chờ duyệt, sync lỗi, tổng kết quả và phân trang đều theo project đang chọn. Worker route theo project ID trong record. Mapping thiếu/disabled làm sync fail closed.

### UC-09 - Đồng bộ lại một Intake

Một Intake có tối đa một Issue hiện hành trên tuyến delivery đã duyệt. Chọn lại tuyến đã có Issue thì lần Sync sau cập nhật Issue đó (tìm theo dấu của yêu cầu, mở lại nếu đã đóng) thay vì tạo mục thứ hai (ADR-0048). Link Plane phát sinh trước ADR-0066 vẫn được giữ và hiển thị chỉ đọc.

### UC-10 - Thu thập và đối chiếu Daily Report

1. IMAPS worker đọc liên tục mailbox `report@example.com`, dedupe và lưu encrypted email.
2. Parser kiểm subject/body theo format Daily Report, liên kết reply/update trong cùng thread và lưu lỗi theo trường.
3. Report builder tổng hợp lúc 23:30 và refresh lúc 06:45 theo `Asia/Ho_Chi_Minh`.
4. GitLab cung cấp Issue, state, assignee, priority label, milestone, due date, MR/CI/test; email cung cấp giờ làm, bước tiếp theo, blocker, rủi ro và hỗ trợ.
5. Conflict được lưu thành warning. Email `DONE` không biến GitLab Issue thành Done; blocker từ email vẫn được cảnh báo dù GitLab còn Doing.
6. Report thiếu, muộn hoặc sai format không dừng luồng. Cuối tuần chỉ kỳ vọng report của người có OT capacity hoặc work evidence.

### UC-10A - CTO xem Daily Report trước khi dùng cho kế hoạch

1. CTO mở trang Báo cáo ngày, chọn ngày và một báo cáo; thấy nhãn báo cáo do bộ quy tắc hay AI đọc và các cảnh báo.
2. CTO mở thư gốc (ghi audit). Chữ ký sau dòng `--` nằm trong mục thu gọn.
3. CTO sửa hoặc xóa từng task nếu trích sai.
4. CTO bấm "Xác nhận đúng": nút khóa lại, màn hình báo task sẽ sang Daily Planning và dẫn tới báo cáo chưa xem tiếp theo.
5. CTO bấm "Loại báo cáo": hệ thống hỏi lại vì việc loại gỡ task khỏi Planning và không hoàn tác được trên giao diện.
6. Báo cáo do AI đọc không được dùng cho Planning cho tới khi được xác nhận.

### UC-11 - Tạo Planning Run lúc 07:00

1. Scheduler tạo một run cho plan date, kể cả thứ Bảy/Chủ nhật.
2. Load capacity: ngày thường mặc định 8 giờ, cuối tuần 0 giờ, sau đó áp dụng CTO override.
3. Trừ họp, review, support và hoạt động cố định để có available capacity.
4. Sinh candidate theo thứ tự P0/P1 đã duyệt, carry-over `Doing`, review/QA, milestone gần, Issue `Ready`, rồi P2/P3 nếu còn capacity. Priority lấy từ Planning snapshot đã duyệt gần nhất có chứa Issue; nếu chưa có thì dùng GitLab priority label (ADR-0013). Runtime 1.2 mới đọc GitLab label.
5. Chia assignment vào `MORNING`/`AFTERNOON`; một task có thể xuất hiện ở cả hai slot nhưng vẫn là một primary development task.
6. Cảnh báo over-capacity, overlap, blocked dependency, source conflict và nhiều hơn một primary development task.

### UC-11A - Task trong báo cáo thành ứng viên Planning

1. Khi run được tạo hoặc mở lại lúc còn sửa được, task chưa xong (`PLANNED`, `IN_PROGRESS`, `PENDING_REVIEW`, `BLOCKED`) của báo cáo dùng được hiện ở mục "Yêu cầu cần phân loại" với nhãn "Báo cáo ngày", tên nhân sự, bước tiếp theo và số giờ nếu có.
2. Task không có GitLab Issue vẫn hiện, ở trạng thái chờ phân loại; CTO nhập số Issue trên thẻ rồi promote.
3. Task có Issue đã được planner tự đề xuất cho cùng nhân sự thì không hiện trùng.

### UC-11A.1 - Sắp thứ tự dự án trong tổng quan Daily Planning

1. CTO hoặc Project Owner mở phạm vi "Tất cả dự án"; đây là tổng quan chỉ đọc và chỉ gồm dự án phần mềm đang hoạt động trong phạm vi quyền hiện tại.
2. Chế độ mặc định "Ưu tiên xử lý" đưa dự án chưa có Project Owner lên trước với CTO, sau đó lần lượt ưu tiên dự án có việc chờ phân công, cảnh báo chưa xem và kế hoạch chưa chốt; các dự án cùng mức xếp theo tên.
3. Người dùng chọn "Tùy chỉnh" để kéo thả hoặc dùng nút lên/xuống. Server lưu danh sách ID theo tài khoản, không theo trình duyệt và không dùng chung giữa CTO với Project Owner.
4. Dự án mới hoặc vừa được cấp quyền chưa có trong danh sách đã lưu được nối sau các dự án đã xếp, theo quy tắc ưu tiên mặc định. Dự án mất quyền bị lọc khỏi response.
5. "Khôi phục ưu tiên" chuyển về `PRIORITY` và xóa danh sách tùy chỉnh; không thay đổi kế hoạch hay dữ liệu dự án.

### UC-11B - Thêm việc vào kế hoạch trong ngày (ADR-0024)

1. CTO bấm "Thêm việc vào kế hoạch"; khung mở ở sidebar phải.
2. Việc đã có: gõ vài chữ, chọn một Issue đang mở hoặc Intake chờ duyệt. Việc mới: nhập tiêu đề, mô tả, loại, ưu tiên.
3. Chọn người làm, buổi, số giờ. Nếu việc chưa có Issue, nhập lý do; hệ thống ghi đó là quyết định phê duyệt, tạo Issue ở nơi giao việc của dự án, rồi đưa việc vào kế hoạch khi Issue có.
4. Việc từ báo cáo ngày nằm ở danh sách "Việc chờ phân công" dưới hai cột kế hoạch. Mỗi dòng có "Xếp việc" (gắn Issue có sẵn hoặc tạo mới, rồi phân công) và "Bỏ qua" (ẩn khỏi kế hoạch hôm nay, đưa lại được).
5. Khi kế hoạch còn mở, kéo thẻ sang ô sáng hoặc chiều của người khác để đổi người làm và có thể đổi buổi trong một thao tác. Người nhận phải còn thuộc dự án và có mapping tracker cho việc delivery. Nếu vượt capacity ngày, 4 giờ/buổi hoặc đã có việc phát triển chính khác, giao diện hỏi CTO/Project Owner xác nhận ngoại lệ rồi gửi lý do để lưu audit.

Luồng dưới đây (UC-12) là thiết kế trước ADR-0024; API của nó vẫn còn nhưng giao diện không dùng nữa.

### UC-12 - Unified Quick Add

CTO có ba đường vào trên cùng màn hình Planning:

1. Chọn GitLab Issue hoặc Intake item hiện hữu.
2. Nhập form nhanh để tạo Intake nguồn `MANUAL`/`MEETING`.
3. Paste chat, email khách hàng hoặc meeting note để tạo Intake; sau khi transaction tạo Intake + candidate commit, target enqueue normalize/dedupe bất đồng bộ. Lỗi enqueue được retry/hiển thị trạng thái nhưng không rollback thao tác Quick Add. Runtime 1.2 mới tạo Intake + candidate, chưa tự enqueue AI pipeline.

Item chưa có GitLab Issue phải hoàn tất triage/promote trước planning approval. Với P0, CTO dùng `Emergency Add`: nhập nội dung tối thiểu và lý do, Intake tự tạo ngay GitLab Issue mà không qua hai bước `Approve` rồi `Sync`, ghi audit và đưa Issue thành candidate (ADR-0012). `Emergency Add` vẫn là target chưa có endpoint/UI ở runtime 1.2.

### UC-13 - Duyệt và cập nhật GitLab

1. CTO review và được sửa trực tiếp priority, assignee, milestone, due date, slot và planned hours trước approval.
2. API kiểm expected version, capacity/WIP, GitLab user mapping, Issue reference và milestone hiện hữu. Thiếu milestone hoặc due date là warning: CTO acknowledge rồi vẫn duyệt được và job chỉ gửi trường có giá trị (ADR-0013). Runtime 1.2 vẫn chặn approval khi thiếu.
3. Approval tạo immutable planning snapshot và enqueue một update job cho từng Issue.
4. Integration worker cập nhật assignee, milestone và due date. Priority đã duyệt cùng chi tiết sáng/chiều chỉ lưu trong Intake ở pilot; worker không thay đổi GitLab priority label.
5. Thành công từng Issue được ghi riêng. Lỗi một Issue làm run `PARTIAL`, không rollback Issue đã thành công; retry chỉ xử lý job lỗi bằng idempotency key cũ.
6. Target: sửa kế hoạch đã duyệt tạo revision mới của toàn run, liên kết `supersedes_run_id`, tạo snapshot mới và chỉ đồng bộ per-Issue delta đã được CTO duyệt. Runtime 1.2 khóa run đã duyệt và chưa có amendment/supersede API.

### UC-13A - Dự án giao việc trên GitHub của khách hàng

1. CTO dán token của khách ở Cài đặt > Dự án, mục Token GitHub (lưu mã hóa, FR-INTG-21; token đặt trong `.env.github` vẫn dùng được), rồi trong wizard chọn loại Phần mềm, nơi giao việc "GitHub của khách hàng", token theo tên và repository; kiểm tra kết nối xong mới lưu được.
2. Khi duyệt một Intake của dự án, tuyến giao việc là GitHub; Sync tạo một Issue chỉ gồm tiêu đề và mô tả đã duyệt.
3. Mỗi sáng Issue của repository được làm mới cùng lúc với GitLab; planner đề xuất việc từ các Issue đang mở được giao cho nhân sự đã gán người dùng GitHub.
4. CTO duyệt kế hoạch; kế hoạch được lưu và xem trong Intake, không có gì được ghi lên repository của khách.

### UC-14 - Ghi âm cuộc họp và meeting note

1. CTO mở "Ghi âm họp", chọn dự án của cuộc họp (bắt buộc) và nguồn âm: tab cuộc họp + micro, chỉ micro, hoặc tải file có sẵn.
2. Trong lúc họp, bản chữ hiện dần; thuật ngữ chung và của dự án được nạp để nhận đúng tên riêng.
3. Sau khi kết thúc, hệ thống chuyển chữ lại có tách người nói ("Thành viên 1, 2…"), xóa bản sao phía ElevenLabs và AI tạo meeting note gồm tóm tắt và bốn nhóm: quyết định; yêu cầu, bug, thay đổi phạm vi; việc cần làm; câu hỏi mở và rủi ro.
4. Ở trang Cuộc họp, CTO đặt tên thật cho người nói, nghe lại hoặc tải bản ghi, sửa tóm tắt và từng mục, tạo lại note, đổi dự án của cuộc họp.
5. CTO bấm "Tạo Intake" trên một yêu cầu, bug, thay đổi phạm vi hoặc việc cần làm; Intake kênh `MEETING` đi qua pipeline và chờ phê duyệt như mọi Intake.
6. Audio, bản chữ và note bị purge theo retention 90 ngày.

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

Planning Run đã approved không bị sửa tại chỗ. Mọi amendment tạo revision mới cho toàn run, liên kết `supersedes_run_id`; snapshot cũ bất biến và chỉ per-Issue delta của revision mới được enqueue.

Mọi transition khác phải trả `409 INVALID_STATE_TRANSITION`.

## 5. Classification và route

| Type | Mô tả | Route mặc định |
|---|---|---|
| BUG | Actual khác expected | GitLab nếu có evidence/AC |
| TASK | Việc đã nằm trong scope | GitLab nếu đủ dữ liệu |
| FEATURE | Nhu cầu mới cần discovery | Việc nội bộ |
| SCOPE_CHANGE | Thay đổi cam kết/phạm vi | Việc nội bộ |
| FEEDBACK | Ý kiến chưa đủ thành requirement | Response hoặc needs info |
| QUESTION | Cần phản hồi/thông tin | Response draft |
| UNCLEAR | Không đủ phân loại | Needs information |

## 6. Priority

AI chỉ đề xuất. CTO quyết định P0-P3 trong pilot.

| Priority | Tiêu chí |
|---|---|
| P0 | Outage, data loss, critical security hoặc business stop nghiêm trọng |
| P1 | Ảnh hưởng cam kết gần/nhiều người dùng, không có workaround hợp lý |
| P2 | Công việc kế hoạch thông thường hoặc bug có workaround |
| P3 | Cải tiến, tối ưu, nice-to-have hoặc backlog nghiên cứu |

## 7. UX rules

- Luôn hiển thị project và public ID trên detail/review/sync.
- Phân biệt AI suggestion với CTO-approved value.
- Hiển thị rõ `Approve` không đồng nghĩa `Synced`.
- Warning `PARTIAL`, stale snapshot và lỗi provider không được ẩn; pilot không có provider fallback (ADR-0011).
- Action nguy hiểm có confirmation và kết quả idempotent.
- Không render raw HTML từ chat/email nếu chưa sanitize.
- Planning luôn hiển thị source-of-truth cạnh giá trị self-report và không tự ẩn conflict.
- Lane sáng/chiều hiển thị planned hours, work type, primary/secondary và capacity còn lại.
- `Approve & Sync` phải nêu rõ sẽ cập nhật assignee, milestone và due date trên GitLab.
- Per-Issue sync failure có retry riêng; không trình bày `PARTIAL` như đã đồng bộ hoàn tất.
- Giao diện mặc định English và có bộ chọn `EN | VI` trước lẫn sau đăng nhập. Lựa chọn chỉ lưu trong trình duyệt đó. Chữ của ứng dụng theo locale đã chọn; yêu cầu và bằng chứng do người dùng nhập giữ nguyên ngôn ngữ nguồn (FR-UI-19, ADR-0083).
