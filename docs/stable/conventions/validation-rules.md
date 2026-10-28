# Quy tắc validation 1.2

Đây là target validation policy. Runtime 1.2 đã enforce phần lớn enum/version/project/snapshot/planning invariant nhưng chưa hoàn chỉnh kiểm tra file của ADR-0015 (magic-byte, số trang, PDF mã hóa/file nhúng), AI schema đầy đủ, question-list riêng cho needs-information và Planning amendment.

## 1. Boundary và service

API schema kiểm kiểu, format, enum, length và field allowlist. Service kiểm state transition, project ownership, snapshot validity, duplicate và các bất biến nghiệp vụ. Worker cũng gọi service invariant; không giả định dữ liệu trong queue là an toàn.

## 2. Input limits

- Chuỗi ngắn tối đa 255 ký tự; text nghiệp vụ có giới hạn riêng và server enforce.
- Batch tối đa 100 item.
- Mỗi attachment tối đa 5 MB.
- Chỉ allowlist image/PDF đã chốt; kiểm declared MIME, magic bytes và parser result.
- Tên object do server sinh; tên client chỉ lưu encrypted để hiển thị.

## 3. Project và reference

Mọi referenced ID phải tồn tại, active và thuộc project hợp lệ. Project mapping disabled hoặc thiếu credential reference phải fail closed, không rơi về project mặc định.

## 4. Approval/sync

- Approve yêu cầu item ở state cho phép và `expected_version` khớp.
- Snapshot payload phải qua schema và redaction trước khi hash.
- Sync yêu cầu snapshot chưa invalidated, version khớp, route khớp target và project integration enabled.
- Reject cần reason; defer cần future datetime; needs-information cần ít nhất một câu hỏi.

## 5. AI output

Parse JSON nghiêm ngặt, từ chối field ngoài schema ở boundary nội bộ phù hợp, cap array/string, kiểm confidence `0..1`, enum và evidence reference tồn tại. AI output không được cập nhật trực tiếp materialized fields trước deterministic validation.

## 6. Fail closed

Thiếu thông tin để quyết định quyền, project, file safety, provider policy hoặc sync validity thì từ chối và ghi error code có thể hành động. Không catch lỗi rồi đánh dấu thành công.

