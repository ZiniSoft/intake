# Luật giao diện cho AI agent

Dự án này dùng một chuẩn giao diện cố định. Việc của bạn là dựng màn hình **bằng những gì đã có**, không phải thiết kế lại. Người duyệt đánh giá kết quả theo chuẩn này, không theo việc nó trông mới hay đẹp hơn.

## Trước khi viết dòng code nào

1. Đọc `docs/02-thanh-phan.md` để biết có những component nào. Mở `/gallery` (chạy `npm run dev`) để thấy chúng.
2. Tìm trang mẫu gần nhất với việc được giao trong `src/pages/` và làm theo cấu trúc của nó:

| Việc được giao | Trang mẫu để theo | File | Tài liệu |
|---|---|---|---|
| Danh sách để tra cứu, có tìm kiếm và bộ lọc | `RequestsPage` | `src/pages/RequestsPage.tsx` | `docs/03-bo-cuc.md` |
| Danh sách việc cần xử lý: thêm, duyệt, từ chối, xóa ngay tại chỗ | `TimeOffPage` | `src/pages/TimeOffPage.tsx` | `docs/03-bo-cuc.md`, `docs/05-tuong-tac.md` |
| Trang chi tiết một bản ghi | `RequestDetailPage` | `src/pages/RequestsPage.tsx` | `docs/03-bo-cuc.md` |
| Bảng quản lý trong Cài đặt: thêm, sửa, xóa | `MembersTab`, `MemberForm` | `src/pages/SettingsPage.tsx` | `docs/05-tuong-tac.md` |
| Việc nhiều bước | `ProjectWizardPage` | `src/pages/SettingsPage.tsx` | `docs/05-tuong-tac.md` |
| Trang cài đặt, tài khoản | `AccountSections` | `src/pages/AccountPage.tsx` | `docs/03-bo-cuc.md` |
| Trang tổng quan, số liệu | `DashboardPage` | `src/pages/DashboardPage.tsx` | `docs/03-bo-cuc.md` |
| Màn hình trước đăng nhập | `LoginPage`, `ForcedPasswordPage` | `src/pages/LoginPage.tsx` | `docs/03-bo-cuc.md` |
| Bất cứ chữ nào hiện trên màn hình | | `src/i18n/vi.ts`, `src/i18n/en.ts` | `docs/04-cach-viet.md` |

   Khi việc được giao giống hai dòng cùng lúc, `docs/03-bo-cuc.md` (mục "Chọn khuôn nào") nói dòng nào thắng.

3. Nếu yêu cầu **thay đổi cách người dùng làm một việc** (thêm bước, đổi vị trí, gộp hay tách màn hình), hãy dừng lại và hỏi trước. Xem `docs/06-quy-trinh-agent.md`.

## Bạn được sửa ở đâu

| Nơi | Được sửa? |
|---|---|
| `src/pages/` | Có. Màn hình mới là một file ở đây. Layout riêng của các trang nằm chung trong `src/pages/pages.css`. |
| `src/app/App.tsx` | Có. Thêm mục sidebar (mảng `groups`) và `<Route>` cho màn hình mới. |
| `src/app/store.tsx` | Có. Dữ liệu mẫu trong bộ nhớ; ở dự án thật là nơi gọi API. |
| `src/i18n/vi.ts`, `src/i18n/en.ts` | Có, luôn sửa cả hai cùng lúc. |
| `checks/rules.json` | Có, để thêm từ cấm của dự án. |
| `src/tokens.css`, `src/ui/`, `src/shell/`, `src/brand.ts`, `checks/*.mjs`, `checks/baseline/` | **Không**, trừ khi người dùng đã đồng ý đổi chuẩn. |

## Sáu điều không được làm

1. **Không viết màu hay cỡ chữ.** Mọi giá trị nằm trong `src/tokens.css`. Trong CSS chỉ dùng `var(--...)`.
2. **Không viết chữ trong code.** Mọi chữ hiện trên màn hình là một khóa trong `src/i18n/vi.ts` **và** `src/i18n/en.ts`, lấy ra bằng `t('...')`.
3. **Không tự làm nút, ô nhập, thẻ, bảng, hộp thoại.** Trong `src/pages` không có `<button>`, `<input>`, `<select>`, `<textarea>`, `<dialog>`, `<table>`; dùng component trong `src/ui`.
4. **Không thêm kiểu component mới trong một trang.** Thiếu thứ gì thì thêm vào `src/ui`, thêm vào phòng trưng bày, rồi mới dùng. Nói rõ việc này trong báo cáo.
5. **Không thêm thư viện giao diện** (Tailwind, MUI, Ant, thư viện biểu đồ, thư viện icon khác `lucide-react`).
6. **Không sửa `src/tokens.css`, `src/ui/`, `src/shell/` để làm cho một màn hình vừa ý.** Thay đổi ở đó là thay đổi chuẩn và cần người quyết định.

## Trước khi báo xong

Chạy và đính kết quả vào báo cáo:

```
npm run check          # kiểu dữ liệu + luật giao diện
npm run check:visual   # ảnh phòng trưng bày so với ảnh chuẩn
```

Rồi đi hết `docs/checklist.md`. Báo cáo phải nói: đã làm gì, đã tự xem trên trình duyệt ở cỡ nào (desktop 1440, mobile 390) và ngôn ngữ nào, và **phần nào chưa kiểm tra được**. Không viết "đã xong" cho thứ bạn chưa thấy chạy.

Về `check:visual`:

- Nó chụp phòng trưng bày và thanh trên, **không chụp sidebar**. Thêm màn hình hay mục menu không làm ảnh thay đổi.
- Vì vậy nếu nó báo khác mà bạn không chủ ý đổi component nào, đó là lỗi của bạn, không phải ảnh chuẩn cũ. Chỉ chạy `-- --update` khi người dùng đã đồng ý thay đổi chuẩn.
- Nó tự chạy một máy chủ riêng ở cổng 5181, không đụng tới máy chủ dev đang chạy. Lần chạy đầu sau khi cài đặt có thể mất một phút.

## Khi luật và yêu cầu mâu thuẫn

Nói ra mâu thuẫn, đề xuất cách làm đúng chuẩn, và hỏi. Không lặng lẽ phá luật, cũng không lặng lẽ bỏ yêu cầu.
