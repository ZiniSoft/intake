# Đưa Intake lên server Ubuntu (ADR-0027)

Hướng dẫn này đưa Intake từ máy đang chạy sang một VPS Ubuntu 24.04 mở ra Internet, có HTTPS, và mang toàn bộ dữ liệu sang. Làm theo đúng thứ tự.

Có hai cách đưa HTTPS vào, chọn theo server:

| Server | HTTPS do | Khác gì trong hướng dẫn |
|---|---|---|
| Đã có **Cloudflare Tunnel và Nginx** (server hiện tại) | Cloudflare và Nginx sẵn có | Bỏ bước 2. Ở bước 4 **không** thêm `COMPOSE_FILE`, `INTAKE_DOMAIN`, `ACME_EMAIL`. Làm thêm bước 7b. Firewall không cần mở 80 và 443. |
| VPS trống, mở thẳng ra Internet | Caddy trong stack | Làm đủ các bước như viết bên dưới. |

> **Không chạy hai nơi cùng lúc.** Máy cũ và server cùng chạy sẽ cùng đọc hộp thư báo cáo và cùng tạo Issue, gây trùng lặp. Bước 5 dừng máy cũ; từ đó chỉ server được chạy.

## 1. Chuẩn bị server

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER          # đăng xuất rồi đăng nhập lại
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
sudo apt install -y unattended-upgrades
```

Firewall: chỉ SSH và web. Chặn cổng gửi thư đi (runbook mục 7).

```bash
sudo ufw default deny incoming
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443
sudo ufw deny out 25/tcp && sudo ufw deny out 465/tcp && sudo ufw deny out 587/tcp
sudo ufw enable
```

SSH: đăng nhập bằng khóa, rồi tắt đăng nhập bằng mật khẩu (`PasswordAuthentication no` trong `/etc/ssh/sshd_config`, `sudo systemctl restart ssh`). Thử đăng nhập bằng khóa ở một cửa sổ khác trước khi đóng cửa sổ hiện tại.

Lưu ý: Docker tự mở cổng nó công bố, vượt qua ufw. Stack này chỉ công bố 80 và 443 ra ngoài (Caddy); các cổng khác gắn vào `127.0.0.1`. Đừng đổi `APP_BIND_ADDRESS` hay `WEB_BIND_ADDRESS`.

## 2. Trỏ tên miền

Ở Cloudflare, tạo bản ghi `A` cho `intake` trỏ về địa chỉ IP của VPS, chế độ **DNS only** (mây xám). Kiểm tra: `dig +short intake.example.com` trả về đúng IP.

## 3. Lấy mã nguồn

```bash
git clone https://github.com/ZiniSoft/intake.git intake
cd intake
```

## 4. Cấu hình

Chép `.env` và `.env.github` từ máy cũ sang thư mục `intake` trên server bằng `scp`. Không gửi qua chat hay email.

Giữ nguyên `SECRET_KEY` và `BACKUP_PASSPHRASE`. Sửa hoặc thêm trên server:

```
COMPOSE_FILE=docker-compose.yml:docker-compose.server.yml
INTAKE_DOMAIN=intake.example.com
ACME_EMAIL=<email nhận thông báo về chứng chỉ>
APP_ENV=production
COOKIE_SECURE=true
BACKUP_DIR=/srv/intake-backups
```

`APP_ENV=production` bật kiểm tra fail-closed khi khởi động. API sẽ không chạy nếu `SECRET_KEY` hoặc
`CTO_INITIAL_PASSWORD` bị thiếu, quá ngắn, còn là giá trị mẫu trong repository, hoặc nếu cookie chưa bật
`Secure`. Overlay Caddy cũng bắt buộc hai biến này ngay từ bước `docker compose config`. Với cách dùng
Cloudflare Tunnel và Nginx không nạp overlay, kiểm tra trong API vẫn áp dụng nhờ `APP_ENV=production`.

```bash
sudo mkdir -p /srv/intake-backups && sudo chown $USER /srv/intake-backups
chmod 600 .env .env.github
docker compose config --quiet && echo "cấu hình hợp lệ"
```

## 5. Dừng máy cũ và tạo bản sao lưu cuối

Trên máy cũ:

```bash
docker compose stop telegram-bot imap-worker planning-scheduler planning-worker integration-worker ai-worker outbox-dispatcher meeting-gateway api web
docker compose run --rm -e BACKUP_RUN_ONCE=1 backup
```

Lệnh thứ hai ghi `intake-<ngày>-<giờ>.tar.enc` và file `.sha256` vào thư mục sao lưu của máy cũ. Chép cả hai sang `/srv/intake-backups` trên server.

Sau bước này máy cũ không được khởi động lại các dịch vụ vừa dừng. Khi server đã chạy ổn, đặt `REPORT_IMAP_ENABLED=false` trong `.env` của máy cũ để phòng khởi động nhầm.

## 6. Nạp dữ liệu trên server

```bash
docker compose build
docker compose up -d postgres seaweed-master seaweed-volume seaweed-filer seaweed-s3
docker compose run --rm backup python3 /opt/restore.py intake-<ngày>-<giờ>.tar.enc
```

Lệnh cuối in năm dòng `1/5` tới `5/5`, kèm số dự án, tài khoản, Intake, thư, cuộc họp và kế hoạch đã nạp. Đối chiếu với máy cũ. Nếu nó dừng với "Restore stopped", làm theo lý do nó nêu; không có gì bị ghi dở vào database khi file không mở được.

## 7. Khởi động

```bash
docker compose up -d
docker compose ps
docker compose logs --tail 30 caddy     # tìm dòng "certificate obtained successfully"
```

Mở `https://intake.example.com`. Chứng chỉ được xin trong vòng một phút ở lần chạy đầu.

## 7b. Server có Cloudflare Tunnel và Nginx: chuyển tên miền về Intake

Intake nghe ở `127.0.0.1:8080`. Thêm một site vào Nginx của server từ file mẫu trong repo:

```bash
sudo cp ops/nginx/intake.conf /etc/nginx/sites-available/intake
sudo ln -s /etc/nginx/sites-available/intake /etc/nginx/sites-enabled/intake
sudo nginx -t && sudo systemctl reload nginx
curl -s -H "Host: intake.example.com" http://127.0.0.1/web-health      # phải in "ok"
```

Sửa dòng `listen` và `server_name` trong file cho khớp với cách các site khác trên server đang khai báo.

**Khi Nginx nằm trên một máy khác với máy chạy Intake** (cấu hình hiện tại: `proxy_pass http://10.0.0.10:8080`), Intake mặc định chỉ nghe ở `127.0.0.1` nên Nginx không tới được. Trên máy chạy Intake:

```bash
# trong .env
WEB_BIND_ADDRESS=10.0.0.10

docker compose up -d web
sudo ufw allow from <IP của máy Nginx> to any port 8080 proto tcp
```

Không đặt `WEB_BIND_ADDRESS=0.0.0.0` và không mở cổng 8080 cho mọi địa chỉ: ai trong mạng nội bộ cũng sẽ vào thẳng được Intake qua HTTP, bỏ qua Cloudflare. Lệnh `curl` kiểm tra ở trên khi đó chạy trên máy Nginx. Trong Cloudflare Zero Trust, thêm public hostname `intake.example.com` cho tunnel, trỏ về Nginx như các site khác.

Ba dòng trong file mẫu không được bỏ:

- `proxy_set_header Host $host;` Thiếu thì ghi âm họp bị từ chối, vì ứng dụng so tên miền của trang với tên miền nó nhận được.
- `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` Thiếu thì mọi người dùng bị tính chung một địa chỉ khi giới hạn đăng nhập.
- Hai dòng `Upgrade` và `Connection`. Thiếu thì ghi âm trực tiếp không kết nối được.

Với cách này cổng 80 và 443 của server không cần mở ra Internet: Cloudflare Tunnel tự kết nối ra ngoài. Giữ firewall chỉ mở SSH.

## 8. Kiểm tra sau khi chạy

- [ ] Đăng nhập được bằng tài khoản CTO; ổ khóa HTTPS hợp lệ.
- [ ] Danh sách Intake, một trang chi tiết và một file đính kèm mở được.
- [ ] Nghe lại được một bản ghi họp cũ; ghi âm thử một cuộc họp ngắn (trình duyệt hỏi quyền micro).
- [ ] Báo cáo ngày: bấm "Quét email ngay" chạy được.
- [ ] Cài đặt > Dự án: kiểm tra lại kết nối GitLab/GitHub của từng dự án (địa chỉ IP của server mới phải được phía đó cho phép).
- [ ] Cài đặt > Hệ thống: sao lưu báo ổn sau lần chạy 01:30 đầu tiên, hoặc chạy ngay `docker compose run --rm -e BACKUP_RUN_ONCE=1 backup`.

## 9. Bắt buộc trước khi cho người khác dùng

1. **Bật xác thực hai lớp cho tài khoản CTO** (Cài đặt > Tài khoản & bảo mật) và tạo mã khôi phục.
2. **Đổi mật khẩu CTO** nếu nó vẫn là mật khẩu khởi tạo trong `.env`.
3. **Đưa bản sao lưu ra khỏi VPS.** Ví dụ với rclone và Google Drive:
   ```bash
   sudo apt install -y rclone && rclone config        # tạo remote tên "gdrive"
   (crontab -l 2>/dev/null; echo '15 2 * * * rclone copy /srv/intake-backups gdrive:intake-backups --max-age 48h') | crontab -
   ```
   Bản sao lưu đã được mã hóa nên an toàn khi nằm trên Drive. Giữ passphrase và một bản `.env` ở nơi khác (trình quản lý mật khẩu).
4. Xác nhận từ một máy ngoài: cổng 8001, 8002, 8080, 5432 **không** mở (`nc -zv <ip> 8001` phải thất bại).

## Cập nhật về sau

```bash
cd intake && git pull
docker compose run --rm -e BACKUP_RUN_ONCE=1 backup    # sao lưu trước
bash scripts/deploy.sh    # pull --ff-only, build, up với GIT_SHA/BUILD_TIME, kiểm sức khỏe (NFR-OPS-02)
```

Migration database tự chạy khi `api` khởi động. Không dùng `docker compose down -v`: lệnh đó xóa toàn bộ dữ liệu.

## Khi có sự cố

| Triệu chứng | Xem |
|---|---|
| Trình duyệt báo chứng chỉ không hợp lệ (cách dùng Caddy) | `docker compose logs caddy`. Thường do DNS chưa trỏ đúng, bản ghi đang bật proxy (mây cam), hoặc cổng 80/443 bị chặn. |
| Lỗi 502 từ Cloudflare hoặc Nginx (cách dùng Tunnel) | `curl -s http://127.0.0.1:8080/web-health` trên server. Không ra "ok" thì `docker compose ps web`; ra "ok" thì xem `sudo nginx -t` và public hostname của tunnel. |
| Ghi âm trực tiếp không kết nối | Nginx của server thiếu `Host`, `Upgrade` hoặc `Connection` (bước 7b). |
| Đăng nhập báo "Quá nhiều lần đăng nhập" | Giới hạn 10 lần mỗi phút cho mỗi địa chỉ. Chờ một phút. |
| Đăng nhập xong bị đẩy ra ngay | `COOKIE_SECURE=true` nhưng đang mở bằng `http://`. Dùng `https://`. |
| Nội dung gốc không đọc được sau khi nạp dữ liệu | `SECRET_KEY` trên server khác máy cũ. Sửa `.env` cho đúng rồi `docker compose up -d`. |
| `api` không lên | `docker compose logs --tail 50 api`. |

Tình trạng kiểm chứng của hướng dẫn này nằm ở ADR-0027, mục Runtime note: các bước trên server thật chưa được chạy lần nào.

## Nghe cho dự án marketing và link rút gọn (ADR-0068, 2026-10-18)

- `.env` trên server: `WATCH_API_KEY` và `WATCH_WEBHOOK_SECRET` (đã có từ ADR-0039) nay phục vụ cả dự án marketing; thêm `SHORT_LINK_BASE` (ví dụ `https://go.example.com`) khi tên miền ngắn đã trỏ về máy chủ. Để trống thì link hiện dạng tương đối `/p/<mã>` trên tên miền Intake.
- nginx: container web đã chuyển `/p/` sang API. Cho tên miền ngắn, bỏ comment khối `server` cuối `ops/nginx/intake.conf`, đặt `server_name`, trỏ DNS, cấp chứng chỉ như tên miền chính.
- Luồng quét: nhập `docs/stable/flows/watch-rss.n8n.json` vào n8n, đặt ba biến môi trường của n8n (`INTAKE_WATCH_API_KEY`, `INTAKE_WATCH_WEBHOOK_SECRET`, `YOUTUBE_API_KEY` tùy chọn), sửa `base` ở node Config. Kênh Instagram, Threads bật sau app review Meta; dịch vụ cào cho Facebook, TikTok do CTO cài trong n8n rồi mở kênh ở Cài đặt > Nguồn quét.
- Beat mới `watch-topics-tick` chạy trong `planning-scheduler`; task AI `intake.watch.topics` ở `ai-worker`. Sau `git pull`, `bash scripts/deploy.sh` như thường lệ; migration 052 tự chạy khi API khởi động.
- Cổng nhận (FR-MKT-13) không cần biến môi trường: bí mật nằm trong bảng, CTO tạo ở Cài đặt > Nguồn quét. Tự đăng bài marketing (FR-MKT-14) dùng `PUBLISH_API_KEY` và `PUBLISH_WEBHOOK_SECRET` của ADR-0038: đặt trước khi bật "Tự đăng" cho kênh nào; luồng đăng đọc `GET /api/v1/publish/queue` và báo về `POST /api/v1/publish/events` như `docs/stable/publish-flow.md`.
