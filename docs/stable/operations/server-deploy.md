English | [Tiếng Việt](server-deploy.vi.md)

# Moving Intake to an Ubuntu server (ADR-0027)

This guide moves Intake from the machine currently running it to an Ubuntu 24.04 VPS exposed to the Internet, with HTTPS, and brings all the data along. Follow the steps in order.

There are two ways to provide HTTPS; choose based on the server:

| Server | HTTPS provided by | What differs in this guide |
|---|---|---|
| Already has **Cloudflare Tunnel and Nginx** (current server) | Existing Cloudflare and Nginx | Skip step 2. In step 4, do **not** add `COMPOSE_FILE`, `INTAKE_DOMAIN`, `ACME_EMAIL`. Also do step 7b. The firewall does not need to open 80 and 443. |
| Empty VPS, exposed directly to the Internet | Caddy in the stack | Do all the steps as written below. |

> **Do not run in two places at once.** If the old machine and the server both run, they will both read the report mailbox and both create Issues, causing duplicates. Step 5 stops the old machine; from then on only the server may run.

## 1. Prepare the server

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER          # đăng xuất rồi đăng nhập lại
sudo timedatectl set-timezone Asia/Ho_Chi_Minh
sudo apt install -y unattended-upgrades
```

Firewall: only SSH and web. Block outgoing mail ports (runbook section 7).

```bash
sudo ufw default deny incoming
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443
sudo ufw deny out 25/tcp && sudo ufw deny out 465/tcp && sudo ufw deny out 587/tcp
sudo ufw enable
```

SSH: log in with a key, then disable password login (`PasswordAuthentication no` in `/etc/ssh/sshd_config`, `sudo systemctl restart ssh`). Test key login in another window before closing the current one.

Note: Docker opens the ports it publishes itself, bypassing ufw. This stack only publishes 80 and 443 externally (Caddy); other ports are bound to `127.0.0.1`. Do not change `APP_BIND_ADDRESS` or `WEB_BIND_ADDRESS`.

## 2. Point the domain

In Cloudflare, create an `A` record for `intake` pointing to the VPS IP address, in **DNS only** mode (gray cloud). Check: `dig +short intake.example.com` returns the correct IP.

## 3. Get the source code

```bash
git clone https://github.com/ZiniSoft/intake.git intake
cd intake
```

## 4. Configuration

Copy `.env` and `.env.github` from the old machine to the `intake` folder on the server with `scp`. Do not send them via chat or email. GitHub tokens pasted in Settings > Projects (Cài đặt > Dự án) are stored in the database, encrypted with `SECRET_KEY` in `.env`: keep `SECRET_KEY` unchanged when moving machines, otherwise you must paste those tokens again.

Keep `SECRET_KEY` and `BACKUP_PASSPHRASE` unchanged. Edit or add on the server:

```
COMPOSE_FILE=docker-compose.yml:docker-compose.server.yml
INTAKE_DOMAIN=intake.example.com
ACME_EMAIL=<email nhận thông báo về chứng chỉ>
APP_ENV=production
COOKIE_SECURE=true
BACKUP_DIR=/srv/intake-backups
```

`APP_ENV=production` enables fail-closed checks at startup. The API will not run if `SECRET_KEY` or
`CTO_INITIAL_PASSWORD` is missing, too short, still the sample value from the repository, or if cookies do not have
`Secure` enabled. The Caddy overlay also requires these two variables starting at the `docker compose config` step. With the
Cloudflare Tunnel and Nginx setup, which does not load the overlay, the API check still applies thanks to `APP_ENV=production`.

```bash
sudo mkdir -p /srv/intake-backups && sudo chown $USER /srv/intake-backups
chmod 600 .env .env.github
docker compose config --quiet && echo "cấu hình hợp lệ"
```

## 5. Stop the old machine and create a final backup

On the old machine:

```bash
docker compose stop telegram-bot imap-worker planning-scheduler planning-worker integration-worker ai-worker outbox-dispatcher meeting-gateway api web
docker compose run --rm -e BACKUP_RUN_ONCE=1 backup
```

The second command writes `intake-<ngày>-<giờ>.tar.enc` and a `.sha256` file to the old machine's backup folder. Copy both to `/srv/intake-backups` on the server.

After this step the old machine must not restart the services just stopped. Once the server runs stably, set `REPORT_IMAP_ENABLED=false` in the old machine's `.env` to guard against accidental startup.

## 6. Load the data on the server

```bash
docker compose build
docker compose up -d postgres seaweed-master seaweed-volume seaweed-filer seaweed-s3
docker compose run --rm backup python3 /opt/restore.py intake-<ngày>-<giờ>.tar.enc
```

The last command prints five lines `1/5` through `5/5`, with the number of projects, accounts, Intakes, emails, meetings, and plans loaded. Compare against the old machine. If it stops with "Restore stopped", follow the reason it gives; nothing is half-written to the database when the file cannot be opened.

## 7. Start up

```bash
docker compose up -d
docker compose ps
docker compose logs --tail 30 caddy     # tìm dòng "certificate obtained successfully"
```

Open `https://intake.example.com`. The certificate is requested within one minute on the first run.

## 7b. Server with Cloudflare Tunnel and Nginx: route the domain to Intake

Intake listens on `127.0.0.1:8080`. Add a site to the server's Nginx from the sample file in the repo:

```bash
sudo cp ops/nginx/intake.conf /etc/nginx/sites-available/intake
sudo ln -s /etc/nginx/sites-available/intake /etc/nginx/sites-enabled/intake
sudo nginx -t && sudo systemctl reload nginx
curl -s -H "Host: intake.example.com" http://127.0.0.1/web-health      # phải in "ok"
```

Edit the `listen` and `server_name` lines in the file to match how other sites on the server are declared.

**When Nginx is on a different machine from the one running Intake** (current configuration: `proxy_pass http://10.0.0.10:8080`), Intake listens only on `127.0.0.1` by default, so Nginx cannot reach it. On the machine running Intake:

```bash
# trong .env
WEB_BIND_ADDRESS=10.0.0.10

docker compose up -d web
sudo ufw allow from <IP của máy Nginx> to any port 8080 proto tcp
```

Do not set `WEB_BIND_ADDRESS=0.0.0.0` and do not open port 8080 to all addresses: anyone on the internal network could then reach Intake directly over HTTP, bypassing Cloudflare. The `curl` check above then runs on the Nginx machine. In Cloudflare Zero Trust, add the public hostname `intake.example.com` for the tunnel, pointing to Nginx like the other sites.

Three lines in the sample file must not be removed:

- `proxy_set_header Host $host;` Without it, meeting recording is rejected, because the app compares the page's domain with the domain it receives.
- `proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;` Without it, all users are counted as one address for login rate limiting.
- The two `Upgrade` and `Connection` lines. Without them, live recording cannot connect.

With this setup the server's ports 80 and 443 do not need to be open to the Internet: Cloudflare Tunnel connects outbound by itself. Keep the firewall open only for SSH.

## 8. Checks after startup

- [ ] You can log in with the CTO account; the HTTPS padlock is valid.
- [ ] The Intake list, one detail page, and one attachment open.
- [ ] An old meeting recording plays back; record a short test meeting (the browser asks for microphone permission).
- [ ] Daily report: clicking "Scan email now" ("Quét email ngay") works.
- [ ] Settings > Projects: recheck each project's GitLab/GitHub connection (the new server's IP address must be allowed on their side).
- [ ] Settings > System (Cài đặt > Hệ thống): backup reports OK after the first 01:30 run, or run `docker compose run --rm -e BACKUP_RUN_ONCE=1 backup` right away.

## 9. Required before letting others use it

1. **Enable two-factor authentication for the CTO account** (Settings > Account & security (Cài đặt > Tài khoản & bảo mật)) and create recovery codes.
2. **Change the CTO password** if it is still the initial password in `.env`.
3. **Move backups off the VPS.** For example with rclone and Google Drive:
   ```bash
   sudo apt install -y rclone && rclone config        # tạo remote tên "gdrive"
   (crontab -l 2>/dev/null; echo '15 2 * * * rclone copy /srv/intake-backups gdrive:intake-backups --max-age 48h') | crontab -
   ```
   Backups are already encrypted, so they are safe on Drive. Keep the passphrase and a copy of `.env` somewhere else (a password manager).
4. Confirm from an outside machine: ports 8001, 8002, 8080, 5432 are **not** open (`nc -zv <ip> 8001` must fail).

## Later updates

```bash
cd intake && git pull
docker compose run --rm -e BACKUP_RUN_ONCE=1 backup    # sao lưu trước
bash scripts/deploy.sh    # pull --ff-only, build, up với GIT_SHA/BUILD_TIME, kiểm sức khỏe (NFR-OPS-02)
```

Database migrations run automatically when `api` starts. Do not use `docker compose down -v`: that command deletes all data.

## Troubleshooting

| Symptom | Check |
|---|---|
| Browser reports an invalid certificate (Caddy setup) | `docker compose logs caddy`. Usually DNS is not pointed correctly, the record has proxy enabled (orange cloud), or ports 80/443 are blocked. |
| 502 error from Cloudflare or Nginx (Tunnel setup) | `curl -s http://127.0.0.1:8080/web-health` on the server. If it does not print "ok", check `docker compose ps web`; if it prints "ok", check `sudo nginx -t` and the tunnel's public hostname. |
| Live recording does not connect | The server's Nginx is missing `Host`, `Upgrade`, or `Connection` (step 7b). |
| Login reports "Too many login attempts" ("Quá nhiều lần đăng nhập") | The limit is 10 attempts per minute per address. Wait one minute. |
| Logged out right after logging in | `COOKIE_SECURE=true` but the site is opened with `http://`. Use `https://`. |
| Original content cannot be read after loading data | `SECRET_KEY` on the server differs from the old machine. Fix `.env` then `docker compose up -d`. |
| `api` does not start | `docker compose logs --tail 50 api`. |

The verification status of this guide is in ADR-0027, Runtime note section: the steps on a real server have never been run.

## Social listening for marketing projects and short links (ADR-0068, 2026-10-18)

- `.env` on the server: `WATCH_API_KEY` and `WATCH_WEBHOOK_SECRET` (existing since ADR-0039) now also serve marketing projects; add `SHORT_LINK_BASE` (for example `https://go.example.com`) once the short domain points to the server. If left empty, links appear in relative form `/p/<mã>` on the Intake domain.
- nginx: the web container already forwards `/p/` to the API. For the short domain, uncomment the last `server` block in `ops/nginx/intake.conf`, set `server_name`, point DNS, and issue a certificate like the main domain.
- Scan flow: import `docs/stable/flows/watch-rss.n8n.json` into n8n, set three n8n environment variables (`INTAKE_WATCH_API_KEY`, `INTAKE_WATCH_WEBHOOK_SECRET`, optional `YOUTUBE_API_KEY`), and edit `base` in the Config node. Instagram and Threads channels are enabled after Meta app review; scraping services for Facebook and TikTok are installed by the CTO in n8n, then the channel is opened in Settings > Scan sources (Cài đặt > Nguồn quét).
- The new beat `watch-topics-tick` runs in `planning-scheduler`; the AI task `intake.watch.topics` runs in `ai-worker`. After `git pull`, run `bash scripts/deploy.sh` as usual; migration 052 runs automatically when the API starts.
- The intake endpoint (FR-MKT-13) needs no environment variable: the secret is stored in a table, and the CTO creates it in Settings > Scan sources. Auto-publishing marketing posts (FR-MKT-14) uses `PUBLISH_API_KEY` and `PUBLISH_WEBHOOK_SECRET` from ADR-0038: set them before enabling "Auto-publish" ("Tự đăng") for any channel; the publish flow reads `GET /api/v1/publish/queue` and reports back to `POST /api/v1/publish/events` as described in `docs/stable/publish-flow.md`.
