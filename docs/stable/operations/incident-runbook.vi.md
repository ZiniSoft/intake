[English](incident-runbook.md) | Tiếng Việt

# Incident runbook 1.2

## 1. Mức độ

| Mức | Ví dụ | Hành động |
|---|---|---|
| P0 | Data leak, mất dữ liệu, tạo external item hàng loạt, credential lộ | Dừng side-effect, cô lập, CTO chỉ huy |
| P1 | Intake/queue/database unavailable, sync lỗi diện rộng | Dừng rollout, khôi phục dịch vụ |
| P2 | Một project/job lỗi, có workaround | Khoanh vùng và retry có kiểm soát |
| P3 | Lỗi UI/quan sát nhỏ | Backlog theo ưu tiên |

## 2. Quy trình chung

1. Ghi thời điểm, người phát hiện, request/job/project IDs.
2. Bảo toàn log/audit đã redact; không sao chép raw data tùy tiện.
3. Ngăn side effect tiếp tục bằng cách dừng đúng worker hoặc disable project integration.
4. Phân loại dữ liệu, availability hay external duplication.
5. Khắc phục và kiểm tra negative case.
6. Khôi phục worker theo từng phần, theo dõi queue/job.
7. Post-incident: nguyên nhân, phạm vi, evidence, hành động phòng ngừa và owner.

## 3. Playbook ngắn

### UModelVerse lỗi

- Kiểm HTTP/error code đã redact và key/model allowlist.
- 400/401/403: sửa cấu hình, không ép fallback.
- Timeout/429/5xx: kiểm queue backoff và số lần retry; pilot không có fallback provider (ADR-0011), run hết lượt chuyển `FAILED` để CTO xử lý lại khi provider phục hồi.
- Không retry tay nhiều lần khi job đang có lease.

### GitLab/GitHub tạo trùng

- Disable integration của project bị ảnh hưởng.
- So external ID/marker với idempotency key và payload hash.
- Không tự động xóa external item; CTO quyết định record chuẩn và liên kết lại audit.

### Redis mất kết nối

- Giữ API nếu PostgreSQL/outbox còn khỏe.
- Khôi phục Redis/worker; dispatcher publish lại event NEW/RETRY.
- Kiểm không duplicate processing run/job.

### Planning sync một phần hoặc thất bại

- Xem per-Issue job; không retry toàn run và không rollback Issue đã `SUCCEEDED`.
- Chỉ dùng UI/API retry cho job `FAILED` còn lượt; job `PENDING/RUNNING/RETRY` phải để worker/lease xử lý.
- Nếu lỗi mapping/payload, sửa nguyên nhân trước; runtime 1.2 chưa có amendment UI cho run đã duyệt nên không sửa trực tiếp snapshot/job payload trong database.
- Disable GitLab integration hoặc dừng integration worker nếu phát hiện update sai hàng loạt.

### Daily Report/IMAPS lỗi

- Planning Run vẫn tiếp tục từ GitLab read model và phải hiển thị `REPORT_MISSING`, `REPORT_MALFORMED` hoặc `REPORT_LATE` phù hợp.
- Không đổi sang SMTP hoặc đánh dấu mailbox read; worker chỉ dùng `BODY.PEEK[]`.
- Nếu identity nhân sự chưa map, xử lý `REPORT_IDENTITY_UNMAPPED`; không tự gán report theo display name mơ hồ.

### PostgreSQL lỗi

- API chuyển not-ready; dừng worker ghi.
- Khôi phục service hoặc restore theo backup runbook.
- Không chạy migration sửa nóng ngoài version control.

### SeaweedFS lỗi

- Chặn upload mới và xử lý attachment.
- Text-only intake có thể tiếp tục nếu policy cho phép và UI hiển thị degraded mode.
- Kiểm DB-object reconciliation sau khôi phục.

### Credential lộ

- Thu hồi/rotate ngay; disable workload liên quan.
- Rà audit/provider logs và phạm vi thời gian.
- Cập nhật secret injection; không chỉ xóa secret khỏi file hiện tại.
