[English](BRD.md) | Tiếng Việt

# BRD - Private Feedback Intake

_Version 2.0 | Bản dành cho mã nguồn mở | Owner: CTO/Tech Lead_

Tài liệu này mô tả mục tiêu kinh doanh. Mức triển khai thực tế được công bố riêng tại `PRODUCTION-READINESS.md` và đối chiếu code tại `IMPLEMENTATION-INVENTORY.md`.

## 1. Bối cảnh

Một công ty phần mềm nhỏ vừa phát triển sản phẩm vừa triển khai dự án cho khách. Yêu cầu khách hàng xuất hiện qua ứng dụng chat, email và họp trực tiếp; CTO tốn phần lớn thời gian mỗi ngày để đọc, phân loại và theo dõi chúng.

Yêu cầu thường được trao đổi bằng chat/email trước khi thành đặc tả. GitLab Issue nhiều khi chỉ được tạo sau khi đã xuất hiện bug. Hệ quả là khó truy vết nguồn yêu cầu, dễ bỏ sót hoặc trùng lặp, nhân sự không có hàng đợi thống nhất và báo cáo tiến độ phụ thuộc CTO tổng hợp thủ công.

## 2. Mục tiêu kinh doanh

### BR-BIZ-01 - Cổng tiếp nhận riêng tư

Tập trung text, image, PDF và email report vào một hệ thống tự lưu trữ, chỉ CTO truy cập trong giai đoạn đầu.

### BR-BIZ-02 - Chuẩn hóa yêu cầu

AI trích xuất loại yêu cầu, tóm tắt, acceptance criteria, mức ưu tiên đề xuất, route và các thông tin còn thiếu. AI không có quyền quyết định cuối cùng.

### BR-BIZ-03 - Tách việc nội bộ và delivery

- Intake quản lý idea, feature, discovery, BRD, scope change và Việc nội bộ.
- GitLab/GitHub quản lý Issue, assignee, branch, Merge Request/Pull Request, CI, test và release.
- Intake giữ nguồn gốc, phê duyệt, snapshot, trạng thái đồng bộ và audit.

### BR-BIZ-04 - Giảm tải CTO

- Giảm thời gian phân loại và theo dõi feedback thủ công.
- Mọi công việc bắt đầu phát triển phải có GitLab Issue. P0 được ưu tiên qua luồng khẩn cấp nhưng vẫn phải tạo Issue tối thiểu trước Planning approval.
- Báo cáo ngày/tuần phải chỉ ra khối lượng hoàn thành, blocker và quyết định đang chờ theo từng dự án.

### BR-BIZ-05 - Chuẩn bị cho điều phối AI Agent

Tạo dữ liệu có cấu trúc và truy vết đủ tốt để giai đoạn sau giao việc cho nhiều AI Agent trong cùng GitLab repository. Multi-agent orchestration không thuộc phạm vi triển khai hiện tại.

### BR-BIZ-06 - Daily Report thành kế hoạch triển khai

Tự động đọc Daily Report, đối chiếu GitLab/GitHub và tạo kế hoạch sáng/chiều lúc 07:00 mỗi ngày. Hệ thống vẫn lập kế hoạch khi report thiếu, muộn hoặc sai format; CTO duyệt priority, assignee, milestone và due date trước khi Intake cập nhật nơi giao việc.

## 3. Phạm vi pilot

### Trong phạm vi

- Nhiều dự án chạy song song; nơi giao việc GitLab/GitHub được cấu hình theo từng dự án.
- Local account + MFA; chỉ CTO đăng nhập Intake.
- Manual intake từ Zalo, WhatsApp và meeting.
- Ghi âm cuộc họp online hoặc tải file ghi âm, chuyển chữ có tách người nói, meeting note do AI tạo và chuyển mục thành Intake (ADR-0018, ADR-0019).
- CTO xem và xác nhận Daily Report trước khi dùng; task chưa xong trong báo cáo thành ứng viên của kế hoạch ngày kế tiếp (ADR-0019).
- IMAPS read-only cho hộp thư báo cáo do người cài đặt cấu hình.
- Tổng hợp cuối ngày lúc 23:30, refresh nguồn lúc 06:45 và tạo Planning Run lúc 07:00 theo `Asia/Ho_Chi_Minh`, kể cả thứ Bảy/Chủ nhật.
- Capacity ngày thường mặc định 8 giờ; cuối tuần mặc định 0 giờ và chỉ có OT khi CTO nhập override. Capacity khả dụng trừ họp, review, support và hoạt động cố định khác.
- Planning Run chia kế hoạch theo buổi sáng/buổi chiều, giới hạn mặc định một development task chính ở `Doing` cho mỗi người.
- Unified Quick Add từ item hiện hữu, form nhập nhanh hoặc paste nguồn; yêu cầu delivery phải có GitLab Issue trước khi kế hoạch được duyệt. Với P0, `Emergency Add` để Intake tự tạo ngay Issue tối thiểu, có lý do và audit (ADR-0012).
- CTO phê duyệt Planning Run; approval tạo snapshot bất biến và tự động enqueue cập nhật assignee, milestone và due date của GitLab Issue.
- Text, PDF và image; tối đa 5 MB cho mỗi file.
- Raw data lưu 90 ngày.
- Async queue, transactional outbox, pipeline status và retry có kiểm soát.
- Một AI provider chính qua adapter (OpenRouter hoặc nhà cung cấp tương thích); đổi provider chỉ cần đổi cấu hình.
- Intake chạy trên một máy chủ Linux riêng, HTTPS với chứng chỉ TLS hợp lệ, nên đặt sau VPN.
- CTO chỉnh sửa, duyệt và đồng bộ theo hai bước `Approve` rồi `Sync`.
- GitLab/GitHub adapter idempotent và lưu liên kết ngoài sau khi tạo thành công.
- Backup hằng ngày; mục tiêu RPO 24 giờ, RTO 4 giờ.

### Ngoài phạm vi pilot

- Tự đọc trực tiếp private chat Zalo/WhatsApp.
- Gửi email hoặc phản hồi khách hàng tự động.
- Project Owner đăng nhập Intake.
- Project Owner phê duyệt Planning Run; quyền này chỉ mở ở phase sau và phải giới hạn theo project.
- Đồng bộ hai chiều đầy đủ GitLab/GitHub.
- AI tự duyệt hoặc tự tạo công việc ngoài hệ thống.
- Multi-agent viết code, review và sửa lỗi.
- High availability hoặc zero downtime.

## 4. Nguyên tắc nghiệp vụ

1. Raw source thuộc Intake.
2. Discovery và việc không phải code thuộc Intake; delivery thuộc GitLab/GitHub.
3. AI chỉ đề xuất; CTO chịu trách nhiệm quyết định.
4. `Approve` khóa snapshot nhưng không tạo dữ liệu ngoài.
5. `Sync` chỉ dùng snapshot đã duyệt; sửa payload làm mất hiệu lực approval trước đó.
6. Mỗi dữ liệu nghiệp vụ phải gắn `project_id`; không dùng project mặc định toàn hệ thống.
7. Không đưa raw chat, số điện thoại, email cá nhân hoặc secret vào GitLab/GitHub.
8. Retry không được tạo trùng external item.
9. Email là nguồn report/ngoại lệ, không phải nguồn duy nhất của phần trăm tiến độ.
10. GitLab là nguồn sự thật cho trạng thái delivery.
11. Khi email và GitLab mâu thuẫn, GitLab quyết định task, trạng thái, assignee, milestone và due date; email bổ sung thời gian, bước tiếp theo, blocker, rủi ro và yêu cầu hỗ trợ. Priority lấy từ Planning snapshot đã duyệt gần nhất, GitLab label là dự phòng (ADR-0013). Mâu thuẫn luôn được hiển thị, không bị ghi đè im lặng.
12. Report thiếu, muộn hoặc sai format không chặn Planning Run.
13. Planning approval khác intake approval: CTO duyệt Planning Run sẽ khóa snapshot và enqueue GitLab update jobs; retry phải idempotent và lỗi một Issue không rollback Issue đã cập nhật thành công.
14. Chi tiết sáng/chiều thuộc Intake; GitLab chỉ nhận assignee, milestone và due date theo khả năng của API.

## 5. Vai trò

| Vai trò | Trách nhiệm trong pilot |
|---|---|
| CTO | Nhập/kiểm tra raw data, sửa AI result, quyết định P0-P3, approve, sync và xử lý xung đột |
| Nhân sự dự án | Chọn và cập nhật GitLab Issue; báo blocker; không truy cập Intake |
| Project Owner | Phối hợp scope và quản lý dự án trong Intake theo quyền được cấp |
| AI worker | Chuẩn hóa, đề xuất và ghi evidence; không có credential ghi GitLab/GitHub |
| Integration worker | Chỉ xử lý sync job từ snapshot đã duyệt |

Trong phase hiện tại, chỉ CTO được duyệt Planning Run và chốt priority, assignee, milestone, due date. Data model và authorization phải sẵn sàng để phase sau cấp quyền Project Owner theo project; CTO vẫn giữ quyền override.

## 6. Chỉ số thành công

| ID | Chỉ số pilot | Mục tiêu ban đầu |
|---|---|---|
| KPI-01 | Intake không bị mất sau khi API/Redis restart | 100% |
| KPI-02 | Sync retry không tạo trùng GitLab/GitHub Issue | 100% |
| KPI-03 | Công việc dev bắt đầu có GitLab Issue | 100%, kể cả P0 qua luồng khẩn cấp có audit |
| KPI-04 | AI result có provider/model/prompt/schema trace | 100% |
| KPI-05 | Raw data quá hạn được purge | Trong 24 giờ sau mốc 90 ngày |
| KPI-06 | Khôi phục từ backup | RPO <= 24 giờ, RTO <= 4 giờ trong restore drill |
| KPI-07 | Tách dữ liệu giữa các dự án | Không có cross-project leak trong test |
| KPI-08 | Planning Run đúng lịch | Tạo lúc 07:00 hằng ngày; lỗi report không chặn run |
| KPI-09 | Planning GitLab sync | Retry không cập nhật trùng; trạng thái từng Issue truy vết được |
| KPI-10 | Capacity/WIP | Không có phân bổ vượt capacity hoặc quá một development task chính mà thiếu CTO override có lý do |

## 7. Tiêu chí hoàn tất

Bản triển khai chỉ được coi là đạt khi các requirement bắt buộc trong SRS đạt `VERIFIED`, không còn P0/P1 mở, restore drill đạt mục tiêu và CTO hoàn thành UAT cho cả luồng thành công lẫn lỗi có kiểm soát.
