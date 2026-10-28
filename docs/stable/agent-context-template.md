# Khuôn hồ sơ ngữ cảnh dự án (`docs/agent/CONTEXT.md`)

Chép tệp này vào repo của dự án tại `docs/agent/CONTEXT.md`, điền từng mục. Giữ nguyên số thứ tự và tên mục H2: Intake nhận mục bằng số đầu dòng. Mục chưa biết ghi đúng một dòng `chưa có` để máy đếm là thiếu, đừng bỏ trống. Mục 1 và 2 được gửi lên nhà cung cấp AI khi chuẩn hóa yêu cầu; các mục khác chỉ người và agent trong repo đọc. Không ghi mật khẩu, khóa, dữ liệu khách vào tệp này.

```markdown
---
project: <mã dự án trên Intake, ví dụ orbit>
owner: <tên Project Owner>
updated: <YYYY-MM-DD>
---

## 1. Sản phẩm và người dùng
- Sản phẩm làm gì, cho ai, một đoạn.
- Vai trò người dùng và việc mỗi vai làm.
- Số đo sống còn (ví dụ: đơn/ngày, người dùng hoạt động) và ngưỡng báo động.

## 2. Bản đồ module và thuật ngữ
- <Nghiệp vụ hay màn hình>: thư mục `src/...`, điểm vào chính, tên gọi của team.
- (mỗi dòng một module; ít nhất các module hay có yêu cầu)
- Thuật ngữ riêng: <từ> = <nghĩa>.

## 3. Môi trường và truy cập
- Local: cách dựng (link tới README nếu dài).
- Staging: URL, cách lấy tài khoản thử (ai cấp), dữ liệu thử ở đâu.
- Prod: URL; không chạm từ repo; ai được deploy.
- Không được chạm: <bảng, dịch vụ, tài khoản>.

## 4. Chạy, test, triển khai
- Chạy: `<lệnh>`
- Test toàn bộ: `<lệnh>` (khoảng <phút>); test một phần: `<lệnh>`
- Dữ liệu mẫu: `<lệnh hoặc đường dẫn>`
- Build và deploy: `<lệnh>`, ai làm, có migration thì làm gì.

## 5. Quy ước mã và nhánh
- Nhánh: `<kiểu tên>` từ `<nhánh gốc>`; không commit lên `<nhánh gốc>`.
- Commit: <dòng đầu, thân, Closes #n>.
- Style, lint, format: `<lệnh>`.
- Migration, cấu hình, secret: <luật>.

## 6. Định nghĩa xong và bằng chứng
- Xong khi: test tái hiện xanh, MR được review, Issue đóng, <người> nghiệm thu.
- Bằng chứng tính trên Intake: <commit nhắc Issue | MR đã merge> (khớp cài đặt dự án).
- Việc không cần Issue: <loại nào>.

## 7. Dữ liệu nhạy cảm
- Dữ liệu khách nằm ở <bảng, bucket>; không chép vào test, không dán lên AI.
- Khóa và token ở <nơi>; không in ra log.
- Log, ảnh chụp màn hình: <che gì trước khi chia sẻ>.

## 8. Người quyết và điểm nóng
- Project Owner: <tên>; kỹ thuật chính: <tên>; leo thang: <CTO>.
- Điểm nóng: <chỗ dễ vỡ, nợ kỹ thuật, lỗi hay gặp>, mỗi dòng một ý.
- Việc đang mở lớn: <tên hay số Issue>.
```

Luật tối thiểu để một mục được tính "có": ba dòng nội dung trở lên và không phải `chưa có`; mục 4 có ít nhất một lệnh trong dấu `` ` ``. Mục bắt buộc: 2, 3, 4, 6, 7, 8. Nên có: 1, 5.
