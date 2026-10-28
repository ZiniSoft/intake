# Quy tắc API 1.2

OpenAPI runtime và `IMPLEMENTATION-INVENTORY.md` quyết định endpoint nào đang khả dụng; ví dụ target route chưa có code không được client gọi chỉ vì xuất hiện trong specification.

## 1. URL và version

- Prefix `/api/v1`.
- Resource dùng danh từ số nhiều, kebab-case.
- GET không có side effect.
- State transition dùng sub-resource ngắn khi không thể biểu diễn bằng PATCH, ví dụ `POST /intakes/{id}/approve`.

## 2. Response contract

```json
{
  "success": true,
  "data": {},
  "request_id": "uuid"
}
```

```json
{
  "success": false,
  "error": "APPROVAL_SNAPSHOT_STALE",
  "message": "Dữ liệu đã thay đổi; hãy duyệt lại trước khi đồng bộ.",
  "details": [],
  "request_id": "uuid"
}
```

Không trả stack trace, secret, raw prompt hoặc raw source trong error.

## 3. Status code

| Code | Dùng cho |
|---|---|
| 200 | Đọc/update/action thành công |
| 201 | Tạo resource |
| 202 | Job đã được nhận và chạy async |
| 400 | Shape/validation sai |
| 401 | Chưa xác thực |
| 403 | Có danh tính nhưng thiếu quyền |
| 404 | Resource không tồn tại hoặc không thuộc scope |
| 409 | Version/state/idempotency conflict |
| 413 | File/payload quá lớn |
| 422 | Business validation không đạt |
| 429 | Rate limit |
| 500/503 | Lỗi hệ thống/dependency tạm thời |

## 4. Pagination

List bắt buộc có `limit` mặc định 20, tối đa 100 và cursor keyset. Filter tối thiểu: `project_id`, `status`, `channel`, `from`, `to`. `sort_by` phải thuộc allowlist. Không dùng offset sâu cho bảng intake/audit/job.

## 5. Concurrency và idempotency

- Mutation review gửi `expected_version`.
- Sync nhận `approval_snapshot_id`; server tạo idempotency key theo project, target và snapshot/payload hash.
- Request retry phải trả cùng kết quả hoặc current state, không tạo side effect mới.

## 6. Security

- Project scope lấy từ resource/database và quyền đã xác minh, không tin body để đổi ownership.
- Response dùng field allowlist theo role.
- Download attachment bắt buộc authorization; không trả permanent public object URL.
- Mọi route khai policy cùng thay đổi tạo route.

