# 01. Nền tảng: màu, chữ, khoảng cách

Mọi giá trị nằm trong `src/tokens.css`. Đó là file duy nhất được viết mã màu và cỡ chữ. `npm run check` báo lỗi nếu thấy `#abc`, `rgb(...)` hay `font-size: 15px` ở nơi khác.

## Nhận diện của từng dự án

Một dự án mới chỉ sửa `src/brand.ts`: tên, logo và **một** màu nhấn. Hai sắc độ của màu nhấn (`--accent-soft`, `--accent-ink`) tự tính ra. Nền trắng, chữ đen, bố cục và hình dạng component không đổi.

## Màu

| Biến | Dùng cho | Không dùng cho |
|---|---|---|
| `--paper` | Nền trang, nền thẻ | |
| `--ink` | Chữ chính, tiêu đề | |
| `--copy` | Chữ phụ, chú thích, nhãn ít quan trọng | Nội dung chính cần đọc |
| `--line` | Đường viền, đường kẻ | |
| `--fill`, `--hover` | Nền nhẹ của mục đang chọn, khi rê chuột | Nền của cả một vùng lớn |
| `--strong` | Nút chính | Chữ |
| `--accent` | Bước hiện tại, phần đã dùng trên thanh mức, điểm nhấn | Cảnh báo, lỗi, thành công |
| `--good`, `--warn`, `--bad`, `--info` (và `-soft`) | Nghĩa: xong, cần chú ý, lỗi hoặc nguy hiểm, đang diễn ra | Trang trí |

Quy tắc:

- **Màu mang nghĩa không thay bằng màu nhấn.** Cảnh báo luôn là hổ phách, lỗi luôn là đỏ, dù màu nhấn của dự án là gì.
- **Không dùng màu làm tín hiệu duy nhất.** Trạng thái luôn có chữ đi kèm (xem `Status`).
- Một màn hình thường chỉ cần đen, trắng, xám và **một** chỗ có màu. Nếu thấy mình dùng ba màu trở lên, hãy xem lại.

## Chữ

Năm cỡ, không có cỡ thứ sáu:

| Biến | Cỡ | Dùng cho |
|---|---|---|
| `--text-xl` | 24px | Tiêu đề của một bản ghi trên trang chi tiết, con số lớn trên thẻ số liệu |
| `--text-lg` | 16px | Tên trang trên thanh trên, tiêu đề thẻ |
| `--text-md` | 14px | Nội dung, ô nhập, dòng danh sách |
| `--text-sm` | 13px | Nút, thông báo, chú thích dài |
| `--text-xs` | 12px | Nhãn ô nhập, nhãn trạng thái, chữ phụ |

`--text-2xs` (10px) chỉ dành cho con số trên chuông. Ba độ đậm: 400 cho nội dung, 500 cho nút và mục đang chọn, 600 cho tiêu đề. Không in nghiêng, không gạch chân trừ liên kết trong câu, không viết hoa cả chữ.

## Khoảng cách và hình dạng

- Khoảng cách theo bậc 4: `--space-1` (4) tới `--space-8` (32). Giữa các khối trong một trang: `--space-4`. Trong một thẻ: `--space-5`.
- Bo góc: `--radius` (8) cho nút, ô nhập, thẻ; `--radius-pill` cho nhãn trạng thái. Không có góc vuông, không có góc bo lớn hơn 10 trừ tấm trượt trên điện thoại.
- Chiều cao điều khiển: `--control` (36) cho nút và ô nhập; `--control-sm` (30) cho nút trong dòng danh sách hoặc bảng. Nút và ô nhập đứng cạnh nhau phải cùng chiều cao.
- Bóng đổ (`--shadow-pop`) chỉ cho thứ nổi lên trên trang: menu chuông, hộp xác nhận, tooltip. Thẻ nằm trong trang chỉ có viền.
