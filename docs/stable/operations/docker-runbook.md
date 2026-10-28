# Docker Compose runbook 1.2

## 1. Phạm vi

Runbook này áp dụng cho Intake trên Ubuntu Server 24.04 VM. Các lệnh chạy tại thư mục repository có `docker-compose.yml`.

## 2. Trước khi khởi động

1. Tạo `.env` từ `.env.example`.
2. Thay toàn bộ giá trị `change-me` và initial password.
3. Cấu hình `UMODELVERSE_API_KEY`. Không cấu hình OpenRouter key trong pilot (ADR-0011). Đọc ảnh đính kèm (ADR-0061) dùng `UMODELVERSE_VISION_MODEL=deepseek-v4-flash-vision-exp` trong allowlist; `ATTACHMENT_VISION_ENABLED=false` để tắt, `ATTACHMENT_PDF_MAX_PAGES` (mặc định 8) và `AI_VISION_TIMEOUT_SECONDS` (90) là phanh chi phí. Đổi `requirements.txt` (pymupdf) và mạng Compose (`ai-worker`, `telegram-bot` vào thêm mạng `storage`) nên deploy bằng `bash scripts/deploy.sh` không tham số.
4. Kiểm tra endpoint/model allowlist.
5. Kiểm tra `OUTBOX_MAX_ATTEMPTS` (mặc định 8) và `AI_TASK_MAX_RETRIES` (mặc định 3); không đặt retry vô hạn.
6. Cấu hình GitLab/GitHub delivery, token của service account và chỉ bật integration sau khi read-only probe đạt. Chỉ `integration-worker` được nhận token ghi.
6a. Hồ sơ ngữ cảnh dự án (ADR-0063): tạo access token GitLab (project hoặc group cha chung của các repo) quyền `read_repository`, vai Reporter, hạn 6 tháng, đặt vào `GITLAB_REPO_READ_TOKEN` (chỉ scope này: `GET /projects` trả 403 là bình thường, reader thử tệp trên `main`, `master`, `develop`); repo GitHub thì `GITHUB_REPO_READ_TOKEN_<TÊN>` (fine-grained, chỉ Contents: read) trong `.env.repo`. Chỉ `repo-reader` nhận các token này; nó không có token ghi và không có khóa AI. Kiểm nhanh: `docker compose run --rm --no-deps repo-reader celery -A app.queue.celery_app:celery_app call intake.context.refresh-all` rồi xem khối "Hồ sơ ngữ cảnh" trên trang dự án.
7. Cấu hình IMAPS nhưng chỉ đặt `REPORT_IMAP_ENABLED=true` sau khi read-only credential/certificate probe đạt; mailbox mặc định `report@example.com`. Đây là gate bắt buộc và phải bật ngay khi bắt đầu pilot, không được trì hoãn sang phase sau.

```bash
docker compose config --quiet
docker compose build --pull
# Bản đang chạy hiện ở nút "Có gì mới" (FR-UI-14): đặt hai biến này trước khi up.
export GIT_SHA=$(git rev-parse --short HEAD) BUILD_TIME=$(date -Iseconds)
docker compose up -d
docker compose ps
```

Bốn bước trên gói trong một lệnh (NFR-OPS-02): `bash scripts/deploy.sh` (pull `--ff-only`, build, up với `GIT_SHA`/`BUILD_TIME`, `ps` và kiểm `/api/v1/health/ready`, `/web-health`). Thêm tên service sau lệnh để chỉ build một phần. Bảng đầu ngày của CTO ghi "n mục mới chưa deploy" khi `CHANGELOG.md` có mục mới hơn bản đang chạy.

```bash
```

## 3. Endpoint

- Server: `https://intake.example.com` trên VPS Ubuntu mở ra Internet, HTTPS do Caddy cấp (ADR-0027, thay phần VPN của ADR-0014). Các bước ở `server-deploy.md`.
- Web: `http://127.0.0.1:8080` trong cấu hình local hiện tại.
- API: `http://127.0.0.1:8001`.
- Meeting gateway: `http://127.0.0.1:8002` (WebSocket ghi âm; liveness `/gateway-health`). Nginx của web chuyển `/api/v1/meetings/{id}/stream` tới đây.
- Liveness: `/api/v1/health/live`.
- Readiness: `/api/v1/health/ready`.
- OpenAPI `/docs` chỉ bật cho dev/pilot admin network; tắt hoặc bảo vệ trước mở rộng.

## 4. Quan sát

```bash
docker compose ps
docker compose logs --tail=200 api web outbox-dispatcher ai-worker integration-worker planning-worker planning-scheduler imap-worker meeting-gateway telegram-bot
```

Không copy log có raw content/secret ra ticket. Khi cần chẩn đoán, dùng request ID, intake public ID, job ID và error code.

## 5. Restart an toàn

```bash
docker compose restart api outbox-dispatcher ai-worker integration-worker planning-worker planning-scheduler imap-worker telegram-bot
```

Restart stateless service không được làm mất accepted intake. Nếu Redis restart, dispatcher phải publish lại outbox chưa hoàn tất.

Sau restart, kiểm tra các event `RETRY` có tiến tới `PUBLISHED`; event `DEAD` và Intake `PROCESSING_FAILED` cần operator điều tra, không retry tay khi chưa xác định nguyên nhân.

## 6. Update

1. Backup PostgreSQL và SeaweedFS theo runbook.
2. Pull/build image đã pin.
3. Chạy migration job một lần.
4. Start service, kiểm readiness và smoke test.
5. Nếu lỗi, dừng rollout và dùng rollback plan đã ghi trước.

Không dùng `docker compose down -v` trong vận hành thông thường.

## 7. SMTP egress

IMAPS worker chỉ được kết nối `mail.example.com:993`. Chặn TCP 25, 465 và 587 ở host/firewall. Container không được cấp SMTP credential.

## 8. Reset schema pilot

Gate A reset ban đầu đã hoàn tất. Trong giai đoạn thử nghiệm, ORM baseline lớn tiếp theo có thể dùng controlled reset thay migration chuyển đổi dữ liệu khi CTO chấp thuận. Mỗi lần vẫn phải xác minh exact target, trình hậu quả và chỉ xóa `intake_postgres-data` nếu đó là phạm vi được duyệt; không xóa Redis/SeaweedFS và không dùng `docker compose down -v`.

## 9. GitLab smoke sau cấu hình

Xác nhận `GET /api/v4/user`, project lookup và Issue search trả `200` trước khi bật write. Không in token hoặc response header nhạy cảm.

```powershell
docker compose exec -e GATE_GITLAB_PROJECT=orbit integration-worker python -m scripts.gate_gitlab_smoke
docker compose exec -e GATE_GITLAB_PROJECT=ember integration-worker python -m scripts.gate_gitlab_smoke
```

Mỗi smoke phải thực hiện Review trước Approve, trả external URL đúng repository và `idempotent_replay=true`. Sau đó đọc lại Issue để xác nhận trace marker/acceptance criteria và raw source không bị đưa ra ngoài. `409 REVIEW_REQUIRED` là fail-closed đúng thiết kế nếu script hoặc client bỏ qua Review.

## 10. Daily Planning smoke

1. Kiểm tra `planning-scheduler` và `planning-worker` đang chạy; Beat phải có lịch 23:30/06:45/07:00 theo `Asia/Ho_Chi_Minh`.
2. Mở `/planning`, tạo/mở run theo ngày + scope, kiểm capacity và warning nguồn.
3. Quick Add form/paste chỉ được coi là Intake candidate; phải liên kết GitLab Issue hiện hành trước promote.
4. Accept proposals trước approval. Approval là external-write boundary vì sẽ enqueue GitLab update per Issue.
5. Theo dõi `GET /planning/runs/{id}/sync-jobs`; chỉ retry job `FAILED` còn attempt budget.
6. Khi smoke không được phép ghi GitLab, dừng trước approval. Live internal UI mutation hiện dùng chính quy tắc này.

## 11A. Nối một dự án với GitHub của khách hàng

1. Xin khách một fine-grained personal access token chỉ cho đúng repository, quyền Issues: Read and write và Metadata: Read.
2. Chép `.env.github.example` thành `.env.github` (nếu chưa có) và thêm một dòng `GITHUB_TOKEN_<TÊN>=<token>`. Không đặt token này vào `.env`.
3. `docker compose up -d integration-worker` để worker nhận biến mới.
4. Trong Cài đặt > Dự án, tạo hoặc sửa dự án loại Phần mềm, chọn "GitHub của khách hàng", chọn token theo tên, chọn repository và bấm "Kiểm tra kết nối".
5. Khi khách thu hồi token, việc tạo và làm mới Issue của dự án đó báo `GITHUB_AUTH_FAILED`; thay giá trị trong `.env.github` rồi khởi động lại worker.

## 12. Ghi âm cuộc họp

1. Bật bằng `MEETING_CAPTURE_ENABLED=true` và đặt `ELEVENLABS_API_KEY` trong `.env`; chỉ `meeting-gateway` nhận key này.
2. Sau khi đổi code hoặc `nginx.conf`, build lại đúng service: `docker compose up -d --build api meeting-gateway ai-worker web`. Cổng 8080 phục vụ bản đã build, không phải working tree.
3. Kiểm tra nhanh: trang Cuộc họp mở được, một bản ghi thử đi tới `Bản chữ: Xong` và `Note: Xong`, và nút "Nghe lại" phát được trên cổng 8080 (CSP phải có `media-src 'self' blob:`).
4. Ba kịch bản trình duyệt `frontend/e2e/meeting-capture.mjs`, `meeting-upload.mjs`, `meeting-notes.mjs` gọi ElevenLabs và UModelVerse thật và ghi dữ liệu vào database đang chạy; không chạy trong CI.
5. Font giao diện là Cerebri Sans có bản quyền: file `.woff2` phải được chép vào `frontend/public/fonts/` trước khi build, nếu không giao diện dùng font hệ thống.

## Nhắc việc qua Telegram (ADR-0057)

1. Tạo bot với @BotFather (`/newbot`), lấy token và username. Trong BotFather tắt "Group Privacy" (`/setprivacy`, chọn Disable) để bot đọc được lệnh `/lien-ket` trong nhóm.
2. Trên server, ghi vào `.env`: `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_BOT_USERNAME=` (không có `@`), `APP_PUBLIC_URL=https://intake.example.com`. Không in token ra log hay chat.
3. `bash scripts/deploy.sh api telegram-bot` (hoặc `docker compose up -d telegram-bot`). Log phải có `bot @<username> ready`; Cài đặt > Hệ thống hiện bot "ok".
4. Mỗi dự án: thêm bot vào nhóm Telegram của dự án, gõ `/lien-ket <mã dự án>`; bot trả lời tên dự án. Đổi nhóm: `/huy-lien-ket` ở nhóm cũ. Dùng một nhóm chung: bật "Chủ đề" (Topics) trong cài đặt nhóm, tạo mỗi dự án một chủ đề, mở chủ đề đó rồi gõ `/lien-ket <mã dự án>`; bot trả lời và nhắc trong chính chủ đề đó.
5. Mỗi người: Cài đặt > Nhân sự > "Link mời Telegram", chép link gửi cho người đó; họ bấm link và nhấn Start. Dòng nhân sự hiện "Telegram @username".
6. Ngày nghỉ: Cài đặt > Hệ thống > Nhắc việc qua Telegram, mỗi dòng một ngày `YYYY-MM-DD`.
7. Kiểm ngay sau khi gắn, trên server (lệnh chạy trong container `telegram-bot`, nơi duy nhất có token):
   ```bash
   docker compose run --rm --no-deps telegram-bot python -m app.workers.telegram_bot test                       # một dòng thử tới mọi nhóm, chủ đề và người đã gắn
   docker compose run --rm --no-deps telegram-bot python -m app.workers.telegram_bot preview --at "2026-10-14 17:30"   # in ra tin của mốc đó, không gửi
   docker compose run --rm --no-deps telegram-bot python -m app.workers.telegram_bot send --at "2026-10-14 17:30"      # gửi thật tin của mốc đó ngay bây giờ
   ```
   `send` ghi nhật ký như lượt thật, nên mốc đó sẽ không gửi lại khi tới giờ. `preview` chỉ có tin khi mốc là ngày làm việc và đúng cửa sổ 20 phút sau giờ (08:00, 08:30, 09:30, 17:30).
8. Khi nghi tin không đi: `docker compose logs --tail=100 telegram-bot`; bảng `telegram_messages` ghi `FAILED` kèm lỗi, Cài đặt > Hệ thống liệt kê năm lỗi gần nhất. Token lộ: tạo token mới ở BotFather (`/revoke`), sửa `.env`, `docker compose up -d telegram-bot`.
