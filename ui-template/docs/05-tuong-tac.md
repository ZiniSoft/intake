# 05. Quy tắc tương tác

Mỗi quy tắc dưới đây có một chỗ trong template làm đúng như vậy. Khi phân vân, mở chỗ đó ra xem.

## Xác nhận

- **Hỏi trước** mọi việc xóa, loại, từ chối, hoặc không hoàn tác được. Dùng `ConfirmDialog`.
- Tiêu đề nêu việc và đối tượng: "Xóa An Nguyễn khỏi danh sách?". Nội dung nói hậu quả trong một hai câu. Nút xác nhận lặp lại hành động, kiểu `danger`. Nút Hủy được chọn sẵn.
- **Không hỏi** cho việc hoàn tác được dễ dàng (lưu, thêm, đổi bộ lọc) và cho việc **đưa một mục đi tiếp** trong quy trình (duyệt, giao, đánh dấu xong). Hỏi quá nhiều thì người dùng bấm mà không đọc.
- Ngoại lệ: việc đi tiếp nhưng **có tác động ra ngoài hệ thống và không rút lại được** (gửi thư cho khách, thanh toán, công bố) thì vẫn hỏi.
- Xem: `MembersTab` (xóa thành viên), `RequestDetailPage` (từ chối yêu cầu).

## Lỗi

- Lỗi của một ô hiện **ngay dưới ô đó**, thay cho lời gợi ý, và chỉ sau lần đầu người dùng bấm lưu. Không báo lỗi khi họ còn đang gõ ô đầu tiên.
- Lỗi của cả thao tác (mất mạng, máy chủ từ chối) là một `Notice` kiểu `bad` **ngay cạnh nút vừa bấm hoặc đầu form**, có nút "Thử lại" khi thử lại có ý nghĩa.
- Sau lỗi, thứ người dùng đã nhập vẫn còn nguyên.
- Xem: `MemberForm`, `LoginPage`.

## Kết quả

- Việc vừa làm xong được báo **tại nơi nó xảy ra**, nêu đích danh: "Đã lưu Giang Vũ". Không dùng thông báo nổi tự biến mất cho việc quan trọng.
- Sau khi tạo, người dùng thấy thứ vừa tạo trong danh sách.
- Khi còn bước tiếp theo, nói luôn: "Yêu cầu đã được duyệt. Bước tiếp theo là giao cho một người trong nhóm."
- Màu của thông báo kết quả: `good` khi thứ gì đó được tạo ra hoặc đi tiếp (đã thêm, đã lưu, đã duyệt); `info` khi kết quả là trung tính hoặc tiêu cực nhưng đúng ý người dùng (đã xóa, đã từ chối). `bad` chỉ dành cho việc **không làm được**.
- Nhãn trạng thái của thứ bị từ chối là `neutral`, không phải `bad`: bị từ chối là một kết quả, không phải một lỗi.

## Đang chờ

- Nút vừa bấm đổi chữ ("Đang đăng nhập…") và bị khóa cho tới khi xong. Không để bấm hai lần.
- Vùng đang tải giữ nguyên kích thước để trang không nhảy.
- Việc lâu hơn vài giây nói rõ đang làm gì.

## Trống

- Danh sách trống luôn là `EmptyState`: vì sao trống, làm gì tiếp, và nút nếu người dùng tự làm được.
- Trống vì bộ lọc khác trống vì chưa có gì: cái đầu có nút "Bỏ bộ lọc". Xem `RequestsPage`.

## Nút bị khóa

Nút bị khóa luôn có lý do viết ra bên cạnh, không chỉ trong tooltip: "Cần bật xác thực hai lớp trước". Nếu người dùng không bao giờ dùng được nút đó (thiếu quyền), ẩn nó đi thay vì khóa. Xem `AccountSections`.

## Form

- Nhãn ở trên ô. Không dùng chữ mờ trong ô thay cho nhãn; chữ mờ chỉ là ví dụ.
- Chỉ hỏi thứ thật sự cần. Thứ hiếm dùng nằm sau một lựa chọn mở rộng.
- Có giá trị mặc định hợp lý thì điền sẵn.
- Một nút chính ở cuối form, nói đúng việc ("Thêm thành viên", không phải "Lưu" khi đang thêm mới).
- Form ngắn mở ở khung bên phải. Việc có nhiều quyết định thì chia bước (`ProjectWizardPage`): luôn thấy đang ở bước nào, quay lại không mất dữ liệu, xem lại trước bước không hoàn tác được.

## Danh sách dài

- Mỗi mục một dòng; chi tiết mở khi bấm. Người dùng quét được hai mươi mục trong một màn hình.
- Thứ lặp lại ở mọi dòng (tên dự án khi cả trang thuộc một dự án) thì bỏ.
- Nhiều cảnh báo cùng loại gom thành một, kèm tên các đối tượng.
- Chia nhóm theo điều người dùng quan tâm (chủ đề, người), không theo loại dữ liệu.

## Bàn phím và trợ năng

- Mọi thứ bấm được bằng chuột cũng dùng được bằng bàn phím; thứ tự Tab theo thứ tự đọc.
- Esc đóng khung bên phải, menu chuông, hộp xác nhận.
- Ô nhập có nhãn thật (`Field`). Nút chỉ có icon có `label`.
- Vòng tiêu điểm (`:focus-visible`) không bị tắt.
- Không truyền đạt điều gì chỉ bằng màu.
