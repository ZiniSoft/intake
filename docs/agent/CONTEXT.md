---
project: nova
owner: Project Owner
updated: 2026-10-15
---

## 1. Sản phẩm và người dùng
- Nova Labs là sản phẩm mẫu giúp một nhóm nhỏ tiếp nhận và theo dõi yêu cầu công việc.
- Người gửi tạo yêu cầu; Project Owner làm rõ và ưu tiên; thành viên thực hiện công việc.
- Số đo chính là thời gian phản hồi, số việc quá hạn và tỷ lệ hoàn thành trong tuần.

## 2. Bản đồ module và thuật ngữ
- Intake API: thư mục `app/`, điểm vào `app/main.py`, xử lý yêu cầu và phân quyền.
- Web client: thư mục `frontend/`, hiển thị danh sách, chi tiết và cài đặt.
- Intake = yêu cầu đầu vào; Project Owner = người chịu trách nhiệm quyết định của dự án.

## 3. Môi trường và truy cập
- Local: dựng theo `README.md` với dữ liệu mẫu, không dùng dữ liệu khách hàng.
- Staging: `https://staging.example.test`; tài khoản thử do quản trị viên cấp.
- Production: không truy cập từ repo; chỉ người vận hành được triển khai và phục hồi.

## 4. Chạy, test, triển khai
- Chạy local: `docker compose up --build`.
- Test toàn bộ: `python -m pytest -q`; kiểm tra frontend: `cd frontend && npm run check`.
- Build và deploy theo runbook; migration phải được review và backup trước khi áp dụng.

## 5. Quy ước mã và nhánh
- Nhánh tính năng dùng tiền tố `feature/` từ `main`; không commit trực tiếp lên `main`.
- Commit mô tả một thay đổi; merge request phải gắn với issue tương ứng.
- Secret chỉ nằm trong biến môi trường hoặc secret manager, không nằm trong source hay log.

## 6. Định nghĩa xong và bằng chứng
- Xong khi test tái hiện xanh, review hoàn tất và tiêu chí chấp nhận được kiểm tra.
- Bằng chứng là commit hoặc merge request liên kết với issue.
- Thay đổi tài liệu nhỏ có thể không cần issue nhưng vẫn cần review.

## 7. Dữ liệu nhạy cảm
- Dữ liệu khách nằm trong database và object storage; không chép vào fixture hoặc prompt AI.
- Khóa và token nằm trong secret manager; không in giá trị ra log hay phản hồi API.
- Log và ảnh chụp phải che email, tên khách hàng, URL nội bộ và định danh tài khoản.

## 8. Người quyết và điểm nóng
- Project Owner quyết định phạm vi; kỹ thuật chính quyết định triển khai; sự cố được leo thang cho quản trị viên.
- Điểm nóng là phân quyền, migration, xử lý tệp đính kèm và tích hợp dịch vụ ngoài.
- Việc lớn đang mở phải có issue, người phụ trách và tiêu chí hoàn thành rõ ràng.
