# 04. Cách viết

Chữ trên màn hình là một phần của giao diện, và là phần người dùng đọc nhiều nhất.

## Nơi để chữ

- Mọi chữ hiện trên màn hình là một khóa trong `src/i18n/vi.ts` và `src/i18n/en.ts`. Tiếng Việt là bản gốc; tiếng Anh phải có đúng những khóa đó (thiếu là lỗi build).
- Khóa đặt theo màn hình: `requests.rejectTitle`, `members.emailHelp`. Chữ dùng ở nhiều nơi nằm ở `common.*`.
- Phần thay đổi viết bằng `{tên}`: `'{count} yêu cầu'`, dùng `t('requests.count', { count })`. **Không ghép câu bằng phép cộng chuỗi**: thứ tự từ ở hai ngôn ngữ khác nhau.
- **Số ít và số nhiều:** tiếng Anh viết hai dạng trong cùng một khóa, cách nhau bằng ` | `: `'{count} request | {count} requests'`. Dạng đầu dùng khi `count` là 1. Tiếng Việt chỉ có một dạng nên viết một lần. Không tạo hai khóa (`count`, `countOne`).
- Ngày và số dùng `useFormat()` để theo ngôn ngữ đang chọn. Ngày không kèm giờ lưu ở dạng `2026-10-12` và `format.date` hiểu đó là ngày ấy tại nơi người dùng đang ở.
- Ô chọn ngày của trình duyệt (`type="date"`) hiện theo cài đặt của máy người dùng, không theo ngôn ngữ đang chọn trong ứng dụng. Chấp nhận điều đó; không tự làm ô chọn ngày.
- Dữ liệu (tên người, tiêu đề yêu cầu, tên dự án) không phải chữ giao diện và không dịch.

## Sáu quy tắc cho cả hai ngôn ngữ

1. **Nói bằng từ của người dùng, không phải từ của hệ thống.** Người dùng không biết tên bảng, tên trạng thái hay tên chức năng nội bộ.
2. **Nói điều xảy ra và việc cần làm, theo thứ tự đó.** Một thông báo lỗi có hai phần: điều gì không được, và làm gì tiếp.
3. **Nút là một động từ và nói đúng việc nó làm.** Nút xác nhận lặp lại hành động, không phải "OK" hay "Đồng ý".
4. **Một ý một câu. Nhiều ý thì gạch đầu dòng.** Tooltip và phần giải thích không viết thành đoạn văn.
5. **Viết thường, chỉ viết hoa chữ đầu câu và tên riêng.** Nhãn và nút không có dấu chấm cuối.
6. **Con số đi kèm đơn vị và nghĩa.** "còn 2h / 6h", không phải "2/6".

## Viết thế này, đừng viết thế kia

| Đừng viết | Hãy viết | Vì |
|---|---|---|
| Lưu capacity | Lưu giờ làm | Từ nội bộ |
| Lý do override | Lý do | Từ nội bộ, lại là tiếng Anh |
| MFA chưa bật | Chưa bật xác thực hai lớp | Viết tắt người dùng không biết |
| Đã xảy ra lỗi | Không lưu được. Mất kết nối tới máy chủ; nội dung bạn nhập vẫn còn nguyên. | Không nói điều gì và làm gì tiếp |
| Bạn có chắc không? | Xóa dự án "Cổng khách hàng"? | Không nói sẽ xảy ra điều gì |
| OK / Đồng ý | Xóa dự án | Nút phải nói việc nó làm |
| Vui lòng nhập email hợp lệ | Email chưa đúng dạng ten@congty.com | Lễ nghi thừa, không chỉ cách sửa |
| REPORT_MISSING | Chưa có báo cáo ngày hôm trước | Mã lỗi không phải lời nói |
| Không có dữ liệu | Chưa có thành viên nào. Thêm người đầu tiên để bắt đầu giao việc. | Không nói vì sao và làm gì |
| v0 · 8h mặc định | (bỏ) | Thông tin hệ thống, người dùng không cần |
| Thành công! | Đã lưu An Nguyễn | Nói cụ thể điều đã xảy ra, không cảm thán |

| Don't write | Write | Why |
|---|---|---|
| Please enter a valid email | The email should look like name@company.com | No "please"; say how to fix it |
| Oops! Something went wrong | Could not save. The connection was lost; what you typed is still here. | Say what happened and what is next |
| Are you sure? | Delete the project "Customer portal"? | Say what will happen |
| OK / Yes | Delete project | The button names its action |
| Submit | Add member | The button names its action |
| Simply click Add | Add the first person to start assigning work | No "simply" or "just" |
| Invalid input | The code is exactly three letters | State the rule, not the verdict |

## Giọng

Bình tĩnh, rõ, ngang hàng. Không cảm thán, không biểu tượng cảm xúc, không xin lỗi thay cho máy, không đổ lỗi cho người dùng ("bạn đã nhập sai" → "email chưa đúng dạng…").

Tiếng Việt xưng "bạn". Tiếng Anh dùng "you", câu ngắn, từ thông dụng, chính tả Anh (colour, summarised) cho thống nhất.

## Từ không xuất hiện trên màn hình

Danh sách nằm ở `checks/rules.json` và được `npm run check` kiểm tra trong cả hai từ điển. Khi một dự án có thuật ngữ nội bộ mới cần tránh, thêm vào đó.
