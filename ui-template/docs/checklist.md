# Danh sách kiểm trước khi báo xong

Chép danh sách này vào báo cáo và đánh dấu từng dòng. Dòng nào không áp dụng thì ghi "không áp dụng" kèm lý do; dòng nào chưa làm được thì nói rõ.

## Máy kiểm
- [ ] `npm run check` không có phát hiện nào.
- [ ] `npm run check:visual` báo "same" cho mọi ảnh, hoặc thay đổi component đã được người dùng đồng ý và ảnh chuẩn đã cập nhật. (Thêm màn hình hay mục menu không làm ảnh đổi.)

## Mắt kiểm
- [ ] Đã mở màn hình ở 1440px và 390px. Không cuộn ngang ở 390px.
- [ ] Đã xem ở tiếng Việt và tiếng Anh. Không còn chữ của ngôn ngữ kia, không có chữ bị cắt hay tràn.
- [ ] Tên trang ở thanh trên đúng. Màn hình có nhiều nhất một nút chính.
- [ ] Nút và ô nhập đứng cạnh nhau cùng chiều cao.

## Trạng thái
- [ ] Trạng thái trống nói vì sao trống và làm gì tiếp.
- [ ] Trạng thái lỗi hiện đúng chỗ, nói điều gì xảy ra và làm gì tiếp; nội dung đã nhập không mất.
- [ ] Nút đang xử lý bị khóa và đổi chữ. (Màn hình còn dùng dữ liệu mẫu: ghi "không áp dụng: dữ liệu mẫu".)
- [ ] Nút bị khóa có lý do viết bên cạnh.
- [ ] Tải lại trang giữa chừng không làm vỡ màn hình.

## Hành vi
- [ ] Xóa, loại, từ chối đều hỏi trước, và nút xác nhận nói đúng việc. Một nhóm nút chỉ có một nút đỏ.
- [ ] Việc vừa làm xong được báo tại chỗ, nêu đích danh.
- [ ] Dùng được bằng bàn phím; Esc đóng khung bên phải và hộp thoại.

## Chữ
- [ ] Không có thuật ngữ nội bộ, mã lỗi, viết tắt người dùng không biết.
- [ ] Nút là động từ nói đúng việc. Nhãn không có dấu chấm cuối.
- [ ] Không ghép câu bằng cộng chuỗi; phần thay đổi dùng `{tên}`. Tiếng Anh có dạng số ít và số nhiều (`một | nhiều`).

## Phạm vi
- [ ] Không sửa `src/tokens.css`, `src/ui`, `src/shell` (hoặc đã được đồng ý, và phòng trưng bày, tài liệu, ảnh chuẩn đã cập nhật cùng).
- [ ] Không thêm thư viện giao diện.
- [ ] Báo cáo có mục "chưa kiểm tra được".
