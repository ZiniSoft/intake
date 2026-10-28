# Quy ước URL state cho giao diện danh sách

Tài liệu này là quy tắc bắt buộc khi tạo mới hoặc sửa một module có danh sách, bộ lọc, tìm kiếm, sắp xếp hoặc phân trang. Mục tiêu là để người dùng refresh, dùng Back/Forward và chép liên kết cho người khác mà vẫn mở đúng ngữ cảnh đang xem.

## 1. Trạng thái nào phải nằm trên URL

- Mọi trạng thái làm thay đổi tập kết quả hoặc cách nhìn có ý nghĩa chia sẻ phải là query param: dự án/phạm vi, trạng thái, đích, ưu tiên, từ khóa, ngày, tab/view, sort và vị trí trang.
- Trạng thái chỉ phục vụ thao tác tạm thời không đưa lên URL: dialog đang mở, dòng đang hover, draft chưa lưu, loading và thông báo nhất thời.
- Dùng key ổn định, viết thường, có nghĩa nghiệp vụ. Giá trị chia sẻ ưu tiên mã ổn định như `project=<code>`; không lộ UUID nội bộ nếu đã có mã công khai.
- Giá trị mặc định phải được bỏ khỏi URL để link chuẩn ngắn và tránh nhiều URL cho cùng một màn hình.

## 2. Filter, tìm kiếm và browser history

- Chọn filter, sort, tab hoặc ngày bằng hành động rõ ràng phải tạo một history entry (`push`) để Back/Forward khôi phục từng lựa chọn.
- Từ khóa gõ liên tục phải debounce và thay history entry hiện tại (`replace`), không tạo một entry cho mỗi phím.
- Mỗi khi filter, search, sort hoặc page size thay đổi, phải xóa toàn bộ trạng thái phân trang trước khi gọi API.
- Link cũ có thể được đọc để tương thích, nhưng phải chuẩn hóa về key/value hiện hành bằng `replace`.
- Giá trị không hợp lệ phải được bỏ khỏi URL. Giá trị hợp lệ nhưng người dùng không có quyền phải hiện empty/error state rõ ràng, không âm thầm đổi sang phạm vi khác.

## 3. Keyset pagination

- API tiếp tục dùng cursor làm nguồn sự thật; UI không biến `page` thành offset.
- Từ trang 2 trở đi URL phải có đủ cặp `page=<số hiển thị>` và `cursor=<opaque>`; chỉ `page` là không đủ để phục hồi dữ liệu.
- Trang 1 bỏ cả `page` và `cursor`. Hai param thiếu một, `page` sai định dạng hoặc cursor bị API trả `INVALID_CURSOR` thì chuẩn hóa về trang 1 bằng `replace` và báo ngắn cho người dùng.
- Nút Tiếp ghi page/cursor mới lên URL. Nút Trước dùng cursor đã thấy trong phiên; nếu mở trực tiếp một trang sâu và không có cursor trang trước, đưa về trang đầu thay vì đoán offset hoặc tải sai dữ liệu.
- Cursor là chuỗi opaque: không parse, sửa, log nội dung hay dùng làm định danh nghiệp vụ.

## 4. Chia sẻ và khả năng phục hồi

- Nút “Chép liên kết” phải chép URL chuẩn hiện tại, gồm cả filter và vị trí trang nếu đang ở trang sau.
- Refresh và mở link ở tab/máy khác phải gọi API với đúng params trên URL.
- Back/Forward phải phục hồi màn hình từ URL, không dựa riêng vào component state hoặc `localStorage`.
- Nếu dữ liệu đổi làm cursor hết hạn, màn hình về trang 1 có thông báo; không để người dùng mắc kẹt ở lỗi kỹ thuật.

## 5. Cách triển khai và kiểm thử

- Với React, dùng `useSearchParams`; helper dùng chung cho keyset pagination nằm ở `frontend/src/list-url.ts`.
- Query cache key phải chứa mọi URL state ảnh hưởng request, kể cả cursor.
- Test tối thiểu: mặc định không có param; filter giữ được sau refresh; đổi filter xóa page/cursor; trang 2 có đủ page/cursor; link thiếu/sai param về trang 1; `INVALID_CURSOR` về trang 1; Back/Forward phục hồi; chép link giữ đủ trạng thái.
- Review module danh sách mới không đạt nếu trạng thái chia sẻ vẫn chỉ nằm trong React state.
