# Database migrations

- PostgreSQL migrations chạy từ `postgresql/` theo thứ tự tên file.
- SQLite chỉ dùng cho unit/API tests và được tạo từ SQLAlchemy metadata.
- Bộ migration `001` đến `005` cũ đã được thay bằng baseline PostgreSQL vì dữ liệu pilot được phép reset theo ADR-0007.
- Không chạy baseline mới trên database legacy chưa reset.
- Daily Planning 1.1 được gộp trực tiếp vào `001_gate_a_baseline.sql`; không có migration nâng cấp dữ liệu pilot cũ.
- PostgreSQL đã từng chạy baseline cũ phải được reset sạch trước khi kiểm chứng Planning schema. Không tự reset trong test/unit flow.
