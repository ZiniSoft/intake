# Hướng dẫn cho agent

Trong nội dung gửi cho người dùng, không dùng ký tự Unicode em dash. Dùng dấu gạch nối hoặc dấu chấm phẩy tùy nghĩa câu.

Đọc `docs/agent/CONTEXT.md` trước. Sau đó chỉ đọc tài liệu chuyên môn liên quan theo bản đồ ở `docs/README.vi.md`; không nạp toàn bộ `docs/stable/` cho một thay đổi hẹp.

## Ranh giới chính

- Intake là nguồn cho yêu cầu, phê duyệt, việc nội bộ và audit.
- GitLab hoặc GitHub là nguồn delivery. Plane chỉ còn dữ liệu và liên kết lịch sử.
- AI chỉ đề xuất. Mọi ghi ra hệ thống ngoài phải giữ đúng bước duyệt và phạm vi dự án.
- Không chạm production, không dùng dữ liệu khách để test và không in hay ghi secret.

## Khi sửa code

- Giữ thay đổi nhỏ, viết test hồi quy cho bug và cập nhật docs nếu contract hoặc trạng thái thay đổi.
- README gốc luôn song ngữ: `README.md` là bản tiếng Anh và `README.vi.md` là bản tiếng Việt; sửa cả hai bản trong cùng thay đổi.
- Route nghiệp vụ phải có `openapi_extra={"x-requirement-ids": [...]}`.
- Migration PostgreSQL chỉ thêm tệp số kế tiếp; không sửa migration cũ.
- Tôn trọng thay đổi đang có trong worktree. Không xóa artifact hoặc file chưa theo dõi nếu người dùng chưa yêu cầu.
- Phần `ui-template/` có luật riêng tại `ui-template/AGENTS.md`.

## Kiểm tra phù hợp phạm vi

- Backend: chạy pytest hẹp trước, rồi bộ rộng hơn nếu môi trường cho phép.
- Frontend: chạy `npm test` và `npm run build` trong `frontend/` khi thay đổi TypeScript/React.
- UI template: chạy `npm run check` và `npm run check:visual` theo `ui-template/AGENTS.md`.
- Nếu không thể chạy một kiểm tra, nêu rõ kiểm tra nào chưa chạy và lý do.
