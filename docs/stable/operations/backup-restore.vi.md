[English](backup-restore.md) | Tiếng Việt

# Backup và restore 1.3

## 1. Mục tiêu

- RPO: tối đa 24 giờ.
- RTO: tối đa 4 giờ.
- Backup đặt trên máy khác với workstation/SSD chạy Intake.

## 2. Phạm vi backup

- PostgreSQL logical dump gồm schema và data.
- SeaweedFS master/filer metadata, volume data và S3 config cần thiết.
- File cấu hình không chứa secret hoặc secret được backup bằng kênh mã hóa riêng.
- Manifest gồm version ứng dụng, image digest, migration version và checksum backup.
- Manifest phải ghi baseline tài liệu, danh sách version trong `schema_migrations` và số lượng 33 bảng hiện hành để phát hiện restore lệch schema.

Redis không cần backup như nguồn dữ liệu nghiệp vụ; outbox/job state nằm ở PostgreSQL.

## 3. Lịch pilot

- PostgreSQL: mỗi ngày.
- SeaweedFS: mỗi ngày hoặc incremental theo công cụ backup được chọn.
- Retention tối thiểu: 7 daily + 4 weekly trong pilot.
- Backup job thất bại phải alert; file tồn tại nhưng không verify checksum không được tính là backup thành công.

## 4. Restore drill

1. Tạo môi trường restore cô lập.
2. Khôi phục PostgreSQL và SeaweedFS từ cùng recovery point.
3. Khởi động app bằng image/migration tương thích.
4. Kiểm số lượng project/intake/source/attachment và random object checksum.
5. Chạy smoke flow login, list, detail và tải attachment được phép.
6. Chạy Planning read smoke: workforce, capacity, một run không external write và GitLab read-model count.
7. Đo thời điểm backup gần nhất và tổng thời gian khôi phục.
8. Lưu evidence đã redact trong gate report.

Drill không đạt nếu mất liên kết DB-object, vượt RPO/RTO hoặc cần thao tác không được ghi trong runbook.

## 5. Encryption và access

Backup chứa Restricted data phải mã hóa at rest, chỉ CTO có quyền giải mã trong pilot. Recovery key không đặt cùng máy và cùng thư mục với backup.

### Trust boundary của file restore

- Container `backup` tạo archive từ PostgreSQL và bucket đang chạy rồi ghi vào `BACKUP_DIR`. CTO đồng bộ thư mục này ra Google Drive, tự chọn file và chạy lệnh restore; không có API hay người dùng ứng dụng nào được khởi động restore.
- Thư mục đồng bộ, tài khoản cloud, host và người có quyền Docker có thể thay hoặc chọn archive. File `.sha256` nằm cạnh archive chỉ phát hiện lỗi sao chép, không xác thực người tạo và không phải chữ ký. Vì vậy restore coi tar và `manifest.json` là dữ liệu không tin cậy ngay cả khi giải mã thành công.
- `BACKUP_PASSPHRASE` nằm trong `.env`, được Docker Compose đưa vào container `backup`, và phải có một bản recovery riêng ngoài thư mục backup. Quản trị viên host, người có quyền đọc `.env` hoặc điều khiển Docker/container có thể lấy khóa. Các quyền này đã tương đương quyền vận hành nhạy cảm và phải giới hạn cho CTO.
- Image `backup` hiện chạy lệnh restore bằng root trong container. Container có credential PostgreSQL đủ để thay database, credential S3 đủ để ghi bucket cấu hình, mount `/backups` đọc/ghi và hai mạng nội bộ `backend`, `storage`; nó không có route Internet. Root trong container không tự động là root host, nhưng có thể sửa file trong bind mount theo quyền mount.
- Namespace object được phép là bucket `S3_BUCKET` của môi trường đích với key tương đối đã chuẩn hóa. Key tuyệt đối, thành phần `.` hoặc `..`, dấu phân cách Windows, ký tự điều khiển và key trùng bị từ chối trước khi upload.

Restore giải mã thành luồng tar và tự ghi từng member. Chỉ thư mục và regular file nằm trong `/tmp/restore-work` được nhận; symlink, hard link, device, FIFO, path tuyệt đối, path traversal, tên trùng và dấu phân cách không rõ nghĩa đều bị từ chối. Mọi đường dẫn do manifest chỉ định được resolve lại dưới thư mục tương ứng, không được chứa link và phải là regular file có đúng một hard link trước khi `pg_restore` hoặc upload đọc file.

## 6. Công cụ pilot (ADR-0025)

Cấu hình trong `.env`:

| Biến | Ý nghĩa |
|---|---|
| `BACKUP_DIR` | Thư mục trên máy chạy Intake nhận file sao lưu. Trỏ vào thư mục được đồng bộ lên Google Drive. |
| `BACKUP_PASSPHRASE` | Từ 16 ký tự. Để trống thì không sao lưu. |
| `BACKUP_TIME` | Giờ chạy hằng ngày, giờ Việt Nam, mặc định `01:30`. |
| `BACKUP_KEEP_DAILY`, `BACKUP_KEEP_WEEKLY` | Số bản giữ lại, mặc định 7 và 4. |

Sau khi sửa `.env`: `docker compose up -d backup`. Chạy ngay một bản: `docker compose run --rm -e BACKUP_RUN_ONCE=1 backup`.

Giữ ở nơi khác thư mục sao lưu (ví dụ trình quản lý mật khẩu): passphrase và một bản `.env`. Thiếu passphrase thì không mở được file; thiếu `SECRET_KEY` trong `.env` thì nội dung gốc đã mã hóa trong database không đọc được.

### Khôi phục

Một lệnh, chạy trên máy đã có mã nguồn, `.env` (cùng `SECRET_KEY` và `BACKUP_PASSPHRASE` với máy cũ) và Docker:

1. Khởi động hạ tầng trống: `docker compose up -d postgres seaweed-master seaweed-volume seaweed-filer seaweed-s3`.
2. Chép file `intake-....tar.enc` và file `.sha256` vào thư mục `BACKUP_DIR`.
3. `docker compose run --rm backup python3 /opt/restore.py intake-YYYYMMDD-HHMMSS.tar.enc`
4. `docker compose up -d`, rồi kiểm tra theo mục 4 (đăng nhập, danh sách, chi tiết, tải file đính kèm, nghe lại một bản ghi họp).

Lệnh ở bước 3 kiểm checksum, giải mã, đối chiếu từng thành phần với manifest, thay toàn bộ database bằng bản trong file, nạp lại mọi file đã lưu (tự tạo bucket nếu chưa có) và in số dòng các bảng chính. Nó từ chối chạy khi database đích đã có Intake, trừ khi thêm `--overwrite`.

Ngày 2026-10-06 lệnh này đã được chạy với bản sao lưu thật vào một database và một bucket tạm trên stack pilot: 42 bảng, 17 file, số dòng khớp dữ liệu đang chạy; các trường hợp sai passphrase, thiếu file và database đã có dữ liệu đều bị từ chối đúng. Chưa làm: khởi động ứng dụng trên bản khôi phục ở một máy khác.
