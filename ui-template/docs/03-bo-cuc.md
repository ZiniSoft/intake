# 03. Bố cục và điều hướng

## Khung

Mọi màn hình sau đăng nhập nằm trong `AppShell` (`src/shell`). Trang không tự dựng khung.

```
┌──────────┬─────────────────────────────────────────┬───────────┐
│ Sidebar  │ Thanh trên: [≡] Tên trang (?)   [Nút] 🔔 │           │
│          ├─────────────────────────────────────────┤  Khung    │
│ Nhóm 1   │                                         │  bên phải │
│ Nhóm 2   │ Nội dung trang                          │  (khi mở) │
│          │                                         │           │
│ Cài đặt  │                                         │           │
│ Tài khoản│                                         │           │
└──────────┴─────────────────────────────────────────┴───────────┘
```

| Vùng | Chứa | Quy tắc |
|---|---|---|
| Sidebar | Các khu vực của ứng dụng, tối đa hai nhóm; Cài đặt, ngôn ngữ, tài khoản ở chân | Mỗi mục là một danh từ ngắn. Thứ ít dùng (cấu hình, quản lý) vào Cài đặt, không vào sidebar. Thu gọn được, trạng thái được nhớ. |
| Thanh trên | Tên trang, dấu "?", **một** nhóm nút chính của trang, chuông | Luôn dính ở đầu trang. Trang đặt nội dung vào đây qua `PageHeader`; không có tiêu đề lớn lặp lại trong nội dung. |
| Chuông | Những việc đang chờ người đăng nhập | Mỗi mục dẫn tới nơi xử lý. Việc ảnh hưởng dữ liệu hoặc bảo mật là `urgent`. Không dùng cho tin tức hay lời chào. |
| Nội dung | Các khối xếp dọc, cách nhau `--space-4` | Rộng tối đa `--page-max`. Form và trang cài đặt hẹp hơn (760px) cho dễ đọc. |
| Khung bên phải | Form thêm hoặc sửa, chi tiết phụ | Đẩy nội dung sang, **không che**. Dùng `RightPanel`. Mỗi lúc chỉ một khung. Đóng bằng nút × hoặc Esc. |

## Chọn khuôn nào

| Câu hỏi | Trả lời | Khuôn |
|---|---|---|
| Người dùng vào đây để **xử lý từng mục** (duyệt, giao, trả lời)? | Có | Danh sách một dòng (`List`). Xem `TimeOffPage`. |
| Người dùng vào đây để **tra cứu hoặc so sánh** các bản ghi theo cột? | Có | Bảng (`Table`). Xem `MembersTab`. |
| Trang chỉ có **một** danh sách? | Có | Nút thêm ở thanh trên. |
| Trang có **nhiều** khối, mỗi khối một danh sách riêng (một tab Cài đặt)? | Có | Nút thêm ở hàng tiêu đề của khối đó. |
| Mục này dùng **hằng ngày hoặc hằng tuần**? | Có | Một mục ở sidebar. |
| Mục này **thiết lập một lần** rồi hiếm khi mở lại? | Có | Một tab trong Cài đặt. |

Thông báo kết quả ("Đã lưu…") luôn nằm **ngay phía trên danh sách hoặc bảng nó nói tới**, bên dưới thẻ số liệu và thanh lọc nếu có.

## Mỗi loại trang một khuôn

**Danh sách tra cứu** (`RequestsPage`): thẻ số liệu (cũng là bộ lọc) → thanh lọc (tìm kiếm, bộ chọn, số kết quả) → danh sách. Bộ lọc nằm trong địa chỉ trang để gửi cho người khác được.

**Danh sách xử lý tại chỗ** (`TimeOffPage`): nút thêm ở thanh trên → thẻ số liệu là bộ lọc duy nhất → thanh chỉ còn số kết quả → thông báo kết quả → danh sách, mỗi dòng một nút cho việc hay làm nhất, các việc khác trong phần mở ra → form thêm ở khung bên phải.

**Chi tiết** (`RequestDetailPage`): liên kết quay lại → tiêu đề và trạng thái → dải các bước → nội dung, nguồn bên trái và kết quả bên phải, hai khối cao bằng nhau → quyết định nằm ở thanh trên.

**Quản lý** (`MembersTab`): bảng → nút thêm ở hàng tiêu đề của thẻ → form ở khung bên phải → xóa có xác nhận → kết quả báo ngay trên bảng.

**Nhiều bước** (`ProjectWizardPage`): dải bước luôn hiện → mỗi bước một nhóm câu hỏi → "Quay lại" bên trái, "Tiếp tục" bên phải → bước cuối là xem lại toàn bộ trước khi tạo.

**Cài đặt, tài khoản** (`AccountSections`): một cột các `Section`; mỗi mục một câu mô tả và một nút; form chỉ hiện khi bấm.

**Tổng quan** (`DashboardPage`): lời chào làm tên trang → những con số cần quyết định → việc đang chờ người này → một so sánh theo thời gian. Không có gì chỉ để trang trí.

**Trước đăng nhập** (`LoginPage`): một cột giữa màn hình, logo, một việc, một nút chính.

## Màn hình nhỏ

Mọi màn hình phải dùng được ở 390px, không cuộn ngang.

- Sidebar thành menu trượt từ trái, mở bằng nút ở thanh trên.
- Nút chính của trang xuống hàng thứ hai của thanh trên.
- Khung bên phải thành tấm trượt từ dưới lên.
- Lưới nhiều cột thành một cột; hai khối so sánh xếp dọc.
- Bảng cuộn ngang **bên trong thẻ của nó**, trang thì không.

## Không làm

| Đừng | Làm |
|---|---|
| Mở form trong hộp thoại che màn hình | Dùng khung bên phải; hộp thoại chỉ để xác nhận |
| Thêm mục vào sidebar cho một trang ít dùng | Đưa vào Cài đặt thành một tab |
| Hai tầng tab lồng nhau | Tách thành hai trang, hoặc dùng thanh lọc |
| Đặt nút chính ở cuối một trang dài | Đặt ở thanh trên, luôn bấm được |
| Viết tiêu đề lớn trong nội dung trang | Dùng `PageHeader`; tên trang ở thanh trên là đủ |
| Trang chỉ có một ô và rất nhiều khoảng trắng | Giới hạn chiều rộng nội dung, canh trái |
