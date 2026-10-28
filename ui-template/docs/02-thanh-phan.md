# 02. Thành phần

Mọi component nằm trong `src/ui` và hiện đủ trạng thái ở `/gallery`. Màn hình chỉ ghép từ chúng. `npm run check` báo lỗi khi một trang tự dùng `<button>`, `<input>`, `<table>`... hoặc dùng lớp CSS `ui-*`.

| Cần | Dùng | Ghi nhớ |
|---|---|---|
| Một hành động | `Button` | `primary`: hành động chính, **mỗi màn hình hoặc form chỉ một**. `secondary`: còn lại. `danger`: xóa, loại, từ chối. `quiet`: việc phụ trong một dòng (Sửa, Hủy). |
| Đi tới trang khác, trông như nút | `LinkButton` | Không dùng `Button` chỉ để chuyển trang. |
| Nút chỉ có icon | `IconButton` | Bắt buộc có `label`. Chỉ dùng cho hành động ai cũng hiểu (đóng, tải lại, menu). |
| Nhập liệu | `Field` bọc `Input`, `Select`, `Textarea` | Nhãn ở trên. `help` giải thích, `error` thay cho `help` khi sai. |
| Một khối nội dung | `Panel` | Có `title` thì có hàng tiêu đề; `action` nằm bên phải hàng đó. `flush` khi nội dung tự có lề (danh sách, bảng). |
| Trạng thái của một thứ | `Status` | Hai ba từ. `tone` theo nghĩa, không theo sở thích. |
| Báo một điều | `Notice` | Đặt ngay cạnh thứ nó nói tới. `title` nói điều gì xảy ra, nội dung nói nghĩa là gì hoặc làm gì tiếp. |
| Chưa có dữ liệu | `EmptyState` | Nói vì sao trống và bước tiếp theo. Có nút nếu người dùng tự làm được. |
| Danh sách việc để xử lý | `List` + `ListRow` | Mỗi mục một dòng. Dòng mở được có mũi tên nhỏ ở cuối. Xem "Nút trong một dòng" bên dưới. |
| Thanh phía trên danh sách | `FilterBar`, `SearchInput` | Ô tìm và bộ chọn bên trái, số kết quả bên phải. Khi thẻ số liệu đã lọc được theo chiều duy nhất thì không thêm bộ chọn trùng; `FilterBar` chỉ còn số kết quả. |
| So sánh theo cột | `Table` | Cột cuối có thể chứa nút nhỏ. Không dùng bảng cho danh sách việc cần làm. |
| Chuyển giữa các phần của cùng một thứ | `Tabs` | Tab nằm trong địa chỉ trang. Chuyển giữa các thứ khác nhau là việc của sidebar. |
| Hỏi trước khi làm điều không hoàn tác được | `ConfirmDialog` | Xem `docs/05-tuong-tac.md`. |
| Giải thích quy tắc của trang | `HelpTip` (qua `help` của `PageHeader`) | Một câu, hoặc danh sách ý. Không viết đoạn văn. |
| Con số trả lời một câu hỏi | `StatCard` | Bấm được thì lọc danh sách bên dưới. |
| Thứ gì đó đang ở bước nào | `Steps` | Bốn trạng thái: `done`, `now`, `todo`, `skip`. Mỗi bước ghi điều đã xảy ra. |
| Đã dùng bao nhiêu trên tổng | `Meter` | Các thanh cạnh nhau dùng chung `scale`. |
| So sánh vài con số theo thời gian | `Bars` | Luôn có con số viết bên cạnh. |
| Một mục trong trang cài đặt | `Section` | Một câu mô tả, một nút. Form chỉ mở khi được yêu cầu. |

## Nút trong một dòng

- **Trên dòng, luôn hiện: tối đa một nút**, là việc người dùng làm nhiều nhất với mục đó và đưa nó đi tiếp (Mở, Duyệt, Tạo việc). Kiểu `secondary`, cỡ `sm`.
- **Trong phần mở ra:** các việc còn lại. Việc tiêu cực chính (Không duyệt, Từ chối) là `danger` cỡ `sm`. Sửa và Xóa là `quiet`.
- **Một nhóm nút chỉ có một nút đỏ.** Khi có cả từ chối lẫn xóa, từ chối là `danger`, xóa là `quiet`. Cả hai vẫn hỏi xác nhận.
- Trong bảng (`Table`), cột cuối chứa Sửa (`secondary`, `sm`) và Xóa (`danger`, `sm`): ở đó chỉ có một nút đỏ nên giữ nguyên.

## Khi thiếu một component

1. Kiểm tra lại: phần lớn nhu cầu là một cách ghép của những thứ trên.
2. Nếu thật sự thiếu: thêm vào `src/ui` (kiểu trong `ui.css`, chỉ dùng biến), thêm một khối vào `GalleryPage` với mọi trạng thái, thêm một dòng vào bảng trên.
3. Chạy `npm run check:visual -- --update` **sau khi người dùng đồng ý**, và nói rõ trong báo cáo rằng chuẩn đã có thêm một component.

## Không làm

| Đừng | Vì |
|---|---|
| Hai nút `primary` cạnh nhau | Người dùng không biết đâu là việc chính |
| Nút bị khóa mà không nói lý do | Người dùng không biết phải làm gì để mở khóa. Viết lý do vào câu mô tả bên cạnh |
| Icon thay cho chữ trên nút hành động | Icon không tự nói nghĩa. Icon đi kèm chữ, không thay chữ |
| Thẻ lồng trong thẻ | Rối. Dùng đường kẻ hoặc khoảng cách để chia trong một thẻ |
| Nhiều `Notice` cùng loại xếp chồng | Gom thành một, liệt kê các đối tượng trong nội dung |
| Thanh tiến độ mỗi cái một thang | Người xem so sánh sai. Dùng chung `scale` |
| Hai nút đỏ cạnh nhau | Không biết nút nào nguy hiểm hơn. Giữ một nút đỏ, nút kia `quiet` |
| Sửa kiểu của component từ stylesheet của trang (`.ui-...`) | Chuẩn bị lệch mà không ai thấy. Sửa trong `src/ui`, hoặc bọc bằng phần tử riêng của trang |
