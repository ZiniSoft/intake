# Quy tắc bảo mật 1.2

Đây là security target. Runtime gap hiện gồm auth rate limit, persistent session revocation, audit login/MFA/raw-read đầy đủ, kiểm tra file/OCR sandbox, signed download và production VPN/TLS; xem readiness trước khi coi một rule đã được thực thi.

## 1. Data classes

| Class | Ví dụ | Quy tắc |
|---|---|---|
| Restricted | Raw chat, email body, sender reference, attachment | Encrypt, CTO-only, retention 90 ngày |
| Confidential | Normalized requirement, report, audit | Auth + project scope |
| Secret | Password, MFA secret, API token | Không log/DB plaintext; secret injection |
| Public/internal-safe | Intake public ID, sanitized external summary | Chỉ field allowlist |

## 2. Credential separation

- AI worker: UModelVerse/OpenRouter key, không GitLab/GitHub token.
- Integration worker: GitLab/GitHub token, không cần raw source decryption key.
- IMAPS worker: IMAP credential, không SMTP credential. Email khôi phục mật khẩu chỉ đi từ API qua Mailgun HTTPS; API key Mailgun không cấp cho worker khác.
- Token GitHub của khách hàng (ADR-0021): một token `GITHUB_TOKEN_<TÊN>` cho mỗi repository, ưu tiên dán ở Cài đặt > Dự án (lưu mã hóa trong CSDL, ADR-0076, chỉ hiện 4 ký tự cuối); phương án dự phòng là biến trong `.env.github` mà chỉ `integration-worker` nạp, file không được commit. Cùng tên thì token trong CSDL được dùng trước. Token là fine-grained, giới hạn một repository, quyền Issues đọc/ghi và Metadata đọc. Không token nào được dùng chung giữa hai khách hàng.
- Meeting gateway: `ELEVENLABS_API_KEY`; không có GitLab/GitHub token, mật khẩu hộp thư hay UModelVerse key. Mọi service khác nhận giá trị rỗng cho key này.
- Khoảng trống đã biết: `UMODELVERSE_API_KEY` vẫn tới mọi container app trừ gateway vì các service dùng chung `env_file`.
- API: chỉ secret cần cho auth/encryption và không có quyền provider rộng hơn cần thiết.

### Phân quyền theo dự án (ADR-0022)

- Mặc định từ chối: một route mới dùng `require_cto` trừ khi được mở có chủ đích bằng `require_member`.
- Route dùng `require_member` phải kiểm tra dự án của thứ nó chạm tới (`ensure_project`, hoặc dependency `intake_member`/`meeting_member`) và phải có ca kiểm thử trong `tests/test_project_owner.py` gọi bằng tài khoản của dự án khác.
- Ngoài phạm vi trả 404, không trả 403.
- Mật khẩu tạm chỉ hiện một lần cho CTO và phải được chuyển qua kênh an toàn; không gửi qua chat cùng với tên đăng nhập.

## 3. Network

Chỉ reverse proxy/web được expose trong VPN. PostgreSQL, Redis và SeaweedFS không publish LAN. Egress allowlist theo workload; SMTP block ở host/container policy.

## 4. File safety

Upload vào quarantine, kiểm size/MIME/magic bytes, số trang PDF, từ chối PDF mã hóa hoặc có file nhúng. Pilot không dùng malware scan (ADR-0015). OCR chạy trên máy riêng cùng LAN, trong container không ra Internet, non-root, filesystem chỉ đọc, có giới hạn CPU/RAM và timeout mỗi file. Kết nối Intake tới máy OCR phải có xác thực; máy OCR không lưu lại file/kết quả và không truy cập ngược database/Redis/SeaweedFS. Chỉ clean object sang trusted pipeline. Download dùng signed URL ngắn hạn hoặc API stream có authorization, luôn trả dạng attachment, không hiển thị trực tiếp trong trình duyệt.

## 5. Audit

Audit tối thiểu: login/MFA/recovery/password reset, đọc raw, upload/download, process/retry, approve/reject/defer, sync, mapping/secrets reference change, retention purge và admin action. Audit không chứa raw content hay reset token.

## 6. AI boundary

Audio cuộc họp là ngoại lệ có chủ đích của nguyên tắc "file gốc không rời mạng nội bộ": nó được gửi tới ElevenLabs để chuyển chữ, bản sao phía nhà cung cấp được xóa sau mỗi lượt, và gói Pro không có chế độ không lưu dữ liệu (OD-033). Chữ ký thư báo cáo không được gửi cho AI (ADR-0019). Web container cho phép phát media từ `blob:` (để nghe lại bản ghi đã giải mã) và micro/chia sẻ màn hình chỉ cho chính origin.

Cloud provider là bên xử lý dữ liệu ngoài. Chỉ gửi dữ liệu tối thiểu qua TLS đến endpoint allowlist; không tool/browser fetch; không truyền secret; ghi provider/model/policy trace. Điều khoản lưu trữ phải được thẩm định lại trước production.

