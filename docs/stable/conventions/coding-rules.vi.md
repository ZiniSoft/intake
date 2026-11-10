[English](coding-rules.md) | Tiếng Việt

# Quy tắc coding 1.2

## 1. Kiến trúc

- Route mỏng; business invariant ở service; persistence qua repository/unit-of-work rõ ràng.
- Module không import vòng hoặc query trực tiếp bảng của module khác tùy tiện.
- External provider qua adapter interface và contract tests.
- PostgreSQL là nguồn trạng thái; Redis chỉ broker/cache.

## 2. Database

- Schema thay đổi chỉ qua migration được review.
- Không serialize dict thủ công vào cột JSONB.
- Transaction bao gồm state change và outbox tương ứng.
- Claim job dùng lease và `SKIP LOCKED`; không giữ DB transaction trong lúc gọi mạng.
- Không N+1; list projection không lấy raw/JSON lớn.

## 3. Error và logging

- Không `except Exception: pass`.
- Phân loại permanent/transient.
- Log structured có request/job/intake/project ID và error code.
- Redact token, password, raw message, prompt và PII.

## 4. Test

- Mỗi invariant có test thành công và test tiêm lỗi.
- Provider adapter có contract test với timeout, 429, 5xx, invalid JSON, 401/403.
- Side effect ngoài có concurrency/idempotency test.
- Database behavior cần test PostgreSQL thật; SQLite chỉ dùng unit test không phụ thuộc kiểu/locking.
- Thay đổi docs và readiness evidence nằm trong cùng PR/commit series.

## 5. Quality

Code format, lint, type check, unit, integration và migration smoke phải là CI hard gate trước controlled pilot.
