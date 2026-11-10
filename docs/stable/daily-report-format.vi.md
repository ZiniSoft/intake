[English](daily-report-format.md) | Tiếng Việt

# Định dạng báo cáo cuối ngày (Daily Report)

Viết cho nhân sự của công ty. Thư báo cáo được bộ quy tắc của Intake đọc tự động; viết đúng khuôn thì task gắn đúng Issue, đúng giờ, vào thẳng kế hoạch ngày hôm sau mà không ai phải sửa tay.

## 1. Tiêu đề thư

```
DAILY REPORT | 2026-10-09 | Nguyen Van A | ORBIT-WEB
```

Bốn phần, cách nhau bằng `|`: chữ `DAILY REPORT`, ngày `YYYY-MM-DD`, họ tên (như đã đăng ký trong Intake), mã dự án **viết hoa** (nhiều dự án thì cách nhau bằng dấu phẩy: `ORBIT-WEB, ORBIT-API`).

## 2. Thân thư

```
ORBIT-WEB | Ember Web

[DONE] Lập danh sách sửa trang hướng dẫn index.html | Thời gian: 1.5 giờ | Tiến độ: 100%
GitLab #8
Bước tiếp theo: Chờ duyệt báo cáo, sau đó sửa README theo 12 đề xuất

[IN_PROGRESS] Chụp ảnh minh họa từng bước cho hướng dẫn cài | Thời gian: 2.5 giờ | Tiến độ: 60%
GitLab #14
Bước tiếp theo: Chụp nốt 4 bước còn lại trên Windows

[PLANNED] Chèn ảnh vào README.md và index.html, quay video hướng dẫn | Thời gian dự kiến: 4 giờ
GitLab #14

[BLOCKED] Đồng bộ CRM | Thời gian: 0.5 giờ | Tiến độ: 20%
GitLab #21
Vấn đề: Chờ API key của khách

Tổng thời gian: 4.5 giờ
```

Quy tắc:
- Mỗi dự án một dòng tiêu đề `MÃ-DỰ-ÁN | Tên dự án` (mã viết hoa), rồi các task của dự án đó.
- Mỗi task bắt đầu bằng **một trong sáu trạng thái** trong ngoặc vuông: `PLANNED`, `IN_PROGRESS`, `PENDING_REVIEW`, `DONE`, `BLOCKED`, `CANCELLED`.
- Trên cùng dòng, sau tiêu đề task: `| Thời gian: X giờ | Tiến độ: N%`. Task `PLANNED` ghi `Thời gian dự kiến: X giờ` thay cho `Thời gian`. `DONE` thì `Tiến độ: 100%`.
- **Số Issue trên một dòng riêng, dạng `GitLab #8`** (dự án dùng GitHub cũng ghi `GitLab #n` — Intake hiểu là Issue của dự án). Task phát triển nào cũng phải có; không có thì Intake cảnh báo và task không vào được kế hoạch.
- Tùy chọn, mỗi thứ một dòng: `Bước tiếp theo: …`, `Vấn đề: …` (bắt buộc với `BLOCKED`), `Intake: KIN-26W41-007`, `Deadline/Milestone: …`, `Dependency: …`, link bằng chứng (dán nguyên URL). Dòng `Plane:` trong báo cáo cũ chỉ còn là dữ liệu lịch sử và không được parser dùng cho việc mới.
- Cuối thư: `Tổng thời gian: X giờ` — bằng tổng giờ các task không phải `PLANNED`.
- Chữ ký, lời chào để sau dòng `--`; mọi thứ sau `--` không được đọc.

## 3. Đúng và sai

| ĐÚNG | SAI (Intake đọc nhầm hoặc bỏ qua) |
|---|---|
| `DAILY REPORT \| 2026-10-09 \| Nguyen Van A \| ORBIT-WEB` | `Daily report 9/10` · thiếu ngày hoặc mã dự án · `orbit-web` viết thường trong thân thư |
| `ORBIT-WEB \| Ember Web` trên dòng riêng trước các task | Không có dòng dự án → `PROJECT_SECTION_MISSING` |
| `[DONE] Lập danh sách sửa trang hướng dẫn \| Thời gian: 1.5 giờ \| Tiến độ: 100%` | `Xong: Lập danh sách…` · `[Done]` không có `|` tách giờ · `[DONE]` mà `Tiến độ: 90%` |
| `GitLab #8` trên dòng riêng ngay dưới task | `[#8 KIN-26W41-007] Lập danh sách…` · `Issue: https://gitlab…/work_items/17` · `Issue #8:` trong tiêu đề (Intake **đã học** đọc được ba dạng này, nhưng đó là dự phòng; không ghi gì cả là sai hẳn) |
| `Thời gian: 1.5 giờ` (dấu chấm hoặc phẩy đều được) | `1h30`, `90 phút`, `1,5h` |
| `[PLANNED] … \| Thời gian dự kiến: 4 giờ` | `[PLANNED] … \| Thời gian: 4 giờ` (bị tính thành giờ đã làm) |
| `[BLOCKED] … ` + dòng `Vấn đề: Chờ API key của khách` | `[BLOCKED]` không nói vướng gì |
| `Tổng thời gian: 4.5 giờ` bằng tổng các task | Thiếu dòng tổng → cảnh báo; tổng lệch quá 15 phút → cảnh báo |
| Một task = một dòng trạng thái + vài dòng phụ | Gộp hai việc vào một `[DONE]` · ghi kết quả thành đoạn văn dài không có `[STATUS]` |
| `Intake: KIN-26W41-007` khi task đến từ một yêu cầu Intake | Mã Intake viết trong ngoặc ở tiêu đề (đọc được, nhưng lẫn với số Issue) |

## 4. Gửi lại trong ngày

Gửi thư mới cho **cùng ngày báo cáo** thì bản mới **thay** bản cũ: bản cũ thành phiên bản trước (vẫn xem được, không dùng cho kế hoạch), bản mới về trạng thái chờ CTO xác nhận lại, kể cả khi bản cũ đã được xác nhận. Chỉ cùng một thư bị gửi lại (cùng Message-ID) mới bị bỏ qua; thư mới dù nội dung y hệt vẫn thành bản mới. Vì vậy: viết sai thì cứ gửi lại cả thư, không gửi thư "bổ sung" chỉ có vài task — thư bổ sung sẽ thay cả báo cáo.

## 5. Hạn

Gửi trước giờ chốt (23:30 theo cấu hình); sau giờ đó thư vẫn được đọc nhưng đánh dấu trễ. Cuối tuần chỉ cần báo cáo khi có OT hoặc có việc thật.
