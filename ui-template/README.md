# Bộ mẫu giao diện

Một ứng dụng React + Vite chạy được ngay, mang sẵn khung, bộ component, các trang mẫu, hai ngôn ngữ (Việt, Anh) và **bộ luật cùng công cụ kiểm tra** để AI agent dựng màn hình mới đúng chuẩn. Giao diện rút ra từ dự án Private Intake.

## Chạy thử

```
npm install
npm run dev            # http://127.0.0.1:5180
```

Đăng nhập bằng email và mật khẩu bất kỳ. Mật khẩu `sai` cho thấy trạng thái lỗi, `tam` cho thấy bước buộc đổi mật khẩu. Dữ liệu là dữ liệu mẫu trong bộ nhớ (`src/app/store.tsx`), tải lại trang là về ban đầu.

## Tạo dự án mới từ bộ mẫu

1. Chép cả thư mục này sang repo mới.
2. Sửa `src/brand.ts`: tên, logo (`public/logo.svg`), màu nhấn.
3. Thay `src/app/store.tsx` bằng lời gọi API thật. Giữ nguyên `src/ui`, `src/shell`, `src/tokens.css`.
4. Xóa các trang mẫu không dùng trong `src/pages` cùng khóa từ điển của chúng (`npm run check` sẽ chỉ ra khóa thừa). Giữ lại `/gallery`.
5. Thêm thuật ngữ nội bộ của dự án vào `checks/rules.json` để chúng không lọt lên màn hình.
6. Chạy `npm run check` và `npm run check:visual`.

## Trong này có gì

| Đường dẫn | Là gì |
|---|---|
| `AGENTS.md`, `CLAUDE.md` | Luật cho AI agent. Đọc trước tiên. |
| `docs/` | Chuẩn giao diện: nền tảng, thành phần, bố cục, cách viết, tương tác, quy trình của agent, danh sách kiểm. |
| `src/tokens.css` | Mọi màu, cỡ chữ, khoảng cách. Nguồn duy nhất. |
| `src/brand.ts` | Tên, logo, màu nhấn của dự án. |
| `src/ui/` | Bộ component. |
| `src/shell/` | Khung: sidebar, thanh trên, khung bên phải, chuông. |
| `src/i18n/` | Hai từ điển và hàm `t()`. |
| `src/pages/` | Trang mẫu cho từng loại màn hình. `TimeOffPage` do một AI agent dựng chỉ từ bộ luật này, trong lần thử nghiệm bộ mẫu. |
| `src/gallery/` | Phòng trưng bày: mọi component, mọi trạng thái. |
| `checks/` | Kiểm tra tự động và ảnh chuẩn. |

## Kiểm tra

| Lệnh | Kiểm tra gì |
|---|---|
| `npm run check` | Kiểu dữ liệu; màu và cỡ chữ ngoài `tokens.css`; chữ viết thẳng trong code; hai từ điển lệch khóa, khóa thừa, lệch `{chỗ trống}`; trang tự làm nút, ô nhập, bảng; từ cấm trên màn hình. |
| `npm run check:visual` | Chụp phòng trưng bày và thanh trên (desktop và mobile tiếng Việt, desktop tiếng Anh) rồi so với `checks/baseline`. Tự chạy máy chủ riêng ở cổng 5181. Cần Chrome trên máy; đặt `CHROME_PATH` nếu nó nằm chỗ khác. |
| `npm run check:visual -- --update` | Ghi lại ảnh chuẩn. Chỉ chạy khi thay đổi giao diện là có chủ ý. |

Giới hạn cần biết:

- Kiểm tra bằng ảnh chỉ xem phòng trưng bày và thanh trên; nó không xem sidebar (vì sidebar đổi mỗi khi dự án thêm màn hình) và không xem các trang nghiệp vụ. Nó bắt thay đổi hình dạng và bố cục của component; hai màu gần như giống nhau có thể lọt qua.
- Ảnh chuẩn được tạo trên một máy. Trên máy khác, cách vẽ chữ có thể lệch vài điểm ảnh; nới bằng `VISUAL_TOLERANCE_PIXELS` hoặc tạo lại ảnh chuẩn.
- Kiểm tra chữ chỉ bắt chữ viết trong JSX và trong các thuộc tính quen thuộc (`label`, `title`, `placeholder`…). Chữ dựng bằng cách khác có thể lọt.
- Các luật về hành vi (xác nhận trước khi xóa, lỗi đúng chỗ, nút bị khóa có lý do) không máy nào kiểm được; chúng nằm trong `docs/checklist.md` và cần người hoặc agent tự soát.

## Phông chữ

Bộ mẫu khai báo phông Cerebri Sans nhưng **không kèm file phông** vì đó là phông có bản quyền. Khi thiếu, trình duyệt dùng phông hệ thống. Dự án có giấy phép thì đặt file vào `public/fonts` và khai báo `@font-face` trong `src/base.css`.

## Quan hệ với Private Intake

Bộ mẫu là bản viết lại sạch dựa trên giao diện của Intake; Intake không dùng code ở đây. Vì vậy hai bên **không tự đồng bộ**: một quyết định giao diện mới ở Intake muốn thành chuẩn thì phải được đưa vào đây (component, phòng trưng bày, tài liệu, ảnh chuẩn), và ngược lại.
