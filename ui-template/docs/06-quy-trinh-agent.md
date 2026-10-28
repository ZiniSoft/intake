# 06. Cách AI agent làm việc với giao diện

Chuẩn giao diện chỉ giữ được khi cách làm việc cũng theo chuẩn. Tài liệu này dành cho agent và cho người giao việc cho agent.

## 1. Phân loại yêu cầu trước khi làm

| Loại | Ví dụ | Cách làm |
|---|---|---|
| **Sửa cho đúng** | Chữ tràn, nút lệch, ô không cùng chiều cao, câu chữ sai | Làm ngay. Đối chiếu với phòng trưng bày và sửa về đúng chuẩn. |
| **Thêm theo khuôn có sẵn** | Thêm một trang danh sách, một tab cài đặt, một form | Làm ngay, theo trang mẫu tương ứng trong `AGENTS.md`. |
| **Đổi cách người dùng làm một việc** | Gộp hai màn hình, thêm bước, đổi vị trí một chức năng, đổi cách sắp xếp | **Dừng. Phân tích và hỏi trước.** |
| **Đổi chuẩn** | Thêm kiểu component, đổi màu, đổi khung | **Dừng. Hỏi trước.** Nếu được đồng ý: sửa `src/ui`, phòng trưng bày, tài liệu và ảnh chuẩn cùng lúc. |

## 2. Khi phải hỏi: phân tích trước, hỏi sau

Người dùng không muốn một danh sách câu hỏi trống. Họ muốn thấy bạn đã hiểu vấn đề.

1. **Nói vấn đề bằng điều quan sát được** trên màn hình hiện tại: "mở một thẻ làm cả hàng bị kéo cao", không phải "bố cục chưa tối ưu".
2. **Đề xuất một hướng**, có lý do.
3. **Hỏi tối đa bốn câu**, mỗi câu có 2 đến 4 lựa chọn cụ thể và một lựa chọn bạn khuyên. Mỗi lựa chọn nói hệ quả của nó. Với lựa chọn về bố cục, kèm bản vẽ bằng ký tự.
4. Không hỏi điều tự tra được trong code, và không hỏi điều có mặc định hợp lý: chọn mặc định, nói ra, làm tiếp.

## 3. Trong khi làm

- Đọc trang mẫu trước, chép cấu trúc của nó rồi sửa, đừng viết từ trang trắng.
- Thêm chữ vào **cả hai** từ điển cùng lúc.
- Layout riêng của trang để trong `src/pages/pages.css` (một file chung cho mọi trang), dùng lớp của riêng trang và chỉ dùng biến. Không viết bộ chọn `.ui-...` hay `.shell-...` ở đó. Thứ dùng lại được thuộc về `src/ui`.
- Không "tiện tay" sửa thứ ngoài yêu cầu. Thấy chỗ sai chuẩn ở nơi khác thì ghi vào báo cáo.

## 4. Kiểm tra trước khi báo

1. `npm run check` và `npm run check:visual` đều sạch.
2. **Tự mở màn hình trên trình duyệt** ở 1440px và 390px, tiếng Việt và tiếng Anh. Code biên dịch được chưa có nghĩa là màn hình đúng.
3. Đi hết đường chính và ít nhất: trạng thái trống, trạng thái lỗi, tải lại trang giữa chừng.
   Dữ liệu mẫu trong bộ nhớ không bao giờ chậm và không bao giờ lỗi. Với màn hình còn dùng dữ liệu mẫu, ghi "không áp dụng: dữ liệu mẫu" cho trạng thái đang chờ và lỗi của thao tác. Khi nối API thật, hai trạng thái đó là bắt buộc.
4. Đi hết `docs/checklist.md`.

## 5. Báo cáo

Câu đầu tiên là kết quả. Sau đó:

- **Đã đổi gì**, mô tả theo điều người dùng thấy, không theo tên file.
- **Đã kiểm tra thế nào**: lệnh đã chạy và kết quả, cỡ màn hình và ngôn ngữ đã xem.
- **Chưa kiểm tra được gì**, và vì sao. Đây là phần bắt buộc. "Chưa bấm lưu vì sẽ ghi dữ liệu thật" là một câu trả lời tốt; im lặng thì không.
- **Điều người dùng cần quyết định hoặc làm tiếp**, nếu có.

Không viết "hoàn hảo", "đã xong hết". Không báo một việc là xong khi bạn chưa thấy nó chạy.

## 6. Khi chuẩn thay đổi

Một thay đổi chuẩn gồm đủ bốn thứ trong cùng một lần: code trong `src/ui` hoặc `src/shell`, khối tương ứng trong phòng trưng bày, dòng tương ứng trong tài liệu, và ảnh chuẩn mới (`npm run check:visual -- --update`). Thiếu một thứ là chuẩn và thực tế bắt đầu lệch nhau.
