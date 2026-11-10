English | [Tiếng Việt](docker-runbook.vi.md)

# Docker Compose runbook 1.2

## 1. Scope

This runbook applies to Intake on an Ubuntu Server 24.04 VM. Commands run in the repository folder that contains `docker-compose.yml`.

## 2. Before starting

1. Create `.env` from `.env.example`.
2. Replace every `change-me` value and the initial password.
3. Configure `UMODELVERSE_API_KEY`. Do not configure an OpenRouter key in the pilot (ADR-0011). Reading attached images (ADR-0061) uses `UMODELVERSE_VISION_MODEL=deepseek-v4-flash-vision-exp` in the allowlist; `ATTACHMENT_VISION_ENABLED=false` disables it, and `ATTACHMENT_PDF_MAX_PAGES` (default 8) and `AI_VISION_TIMEOUT_SECONDS` (90) are cost brakes. It changes `requirements.txt` (pymupdf) and the Compose networks (`ai-worker`, `telegram-bot` also join the `storage` network), so deploy with `bash scripts/deploy.sh` without arguments.
4. Check the endpoint/model allowlist.
5. Check `OUTBOX_MAX_ATTEMPTS` (default 8) and `AI_TASK_MAX_RETRIES` (default 3); do not set infinite retry.
6. Configure GitLab/GitHub delivery and the service account token, and only enable integration after the read-only probe passes. Only `integration-worker` receives the write token.
6a. Project context pack (ADR-0063): create a GitLab access token (project, or the common parent group of the repos) with `read_repository` scope, Reporter role, 6-month expiry, and put it in `GITLAB_REPO_READ_TOKEN` (with only this scope, `GET /projects` returning 403 is normal; the reader tries files on `main`, `master`, `develop`); for GitHub repos use `GITHUB_REPO_READ_TOKEN_<TÊN>` (fine-grained, Contents: read only) in `.env.repo`. Only `repo-reader` receives these tokens; it has no write token and no AI key. Quick check: `docker compose run --rm --no-deps repo-reader celery -A app.queue.celery_app:celery_app call intake.context.refresh-all`, then look at the "Context pack" ("Hồ sơ ngữ cảnh") block on the project page.
7. Configure IMAPS but only set `REPORT_IMAP_ENABLED=true` after the read-only credential/certificate probe passes; the default mailbox is `report@example.com`. This is a mandatory gate and must be enabled as soon as the pilot starts, not deferred to a later phase.

```bash
docker compose config --quiet
docker compose build --pull
# Bản đang chạy hiện ở nút "Có gì mới" (FR-UI-14): đặt hai biến này trước khi up.
export GIT_SHA=$(git rev-parse --short HEAD) BUILD_TIME=$(date -Iseconds)
docker compose up -d
docker compose ps
```

The four steps above are wrapped in one command (NFR-OPS-02): `bash scripts/deploy.sh` (pull `--ff-only`, build, up with `GIT_SHA`/`BUILD_TIME`, `ps`, and check `/api/v1/health/ready`, `/web-health`). Add service names after the command to build only part of the stack. The CTO's start-of-day board shows "n new entries not yet deployed" when `CHANGELOG.md` has entries newer than the running version.

```bash
```

## 3. Endpoint

- Server: `https://intake.example.com` on an Ubuntu VPS exposed to the Internet, HTTPS issued by Caddy (ADR-0027, replacing the VPN part of ADR-0014). Steps in `server-deploy.md`.
- Web: `http://127.0.0.1:8080` in the current local configuration.
- API: `http://127.0.0.1:8001`.
- Meeting gateway: `http://127.0.0.1:8002` (recording WebSocket; liveness `/gateway-health`). The web Nginx forwards `/api/v1/meetings/{id}/stream` here.
- Liveness: `/api/v1/health/live`.
- Readiness: `/api/v1/health/ready`.
- OpenAPI `/docs` is enabled only for the dev/pilot admin network; disable or protect it before expanding.

## 4. Observability

```bash
docker compose ps
docker compose logs --tail=200 api web outbox-dispatcher ai-worker integration-worker planning-worker planning-scheduler imap-worker meeting-gateway telegram-bot
```

Do not copy logs containing raw content/secrets into tickets. When diagnosing, use the request ID, intake public ID, job ID, and error code.

## 5. Safe restart

```bash
docker compose restart api outbox-dispatcher ai-worker integration-worker planning-worker planning-scheduler imap-worker telegram-bot
```

Restarting stateless services must not lose an accepted intake. If Redis restarts, the dispatcher must republish unfinished outbox entries.

After a restart, check that `RETRY` events progress to `PUBLISHED`; `DEAD` events and `PROCESSING_FAILED` Intakes need operator investigation, and must not be retried by hand until the cause is identified.

## 6. Update

1. Back up PostgreSQL and SeaweedFS per the runbook.
2. Pull/build the pinned images.
3. Run the migration job once.
4. Start services, check readiness, and run the smoke test.
5. On failure, stop the rollout and use the rollback plan written beforehand.

Do not use `docker compose down -v` in normal operations.

## 7. SMTP egress

The IMAPS worker may only connect to `mail.example.com:993`. Block TCP 25, 465, and 587 at the host/firewall. Containers are not given SMTP credentials.

## 8. Pilot schema reset

The initial Gate A reset is complete. During the trial phase, the next large ORM baseline may use a controlled reset instead of a data-conversion migration when the CTO approves. Each time you must still verify the exact target, present the consequences, and only delete `intake_postgres-data` if that is the approved scope; do not delete Redis/SeaweedFS and do not use `docker compose down -v`.

## 9. GitLab smoke after configuration

Confirm that `GET /api/v4/user`, project lookup, and Issue search return `200` before enabling write. Do not print tokens or sensitive response headers.

```powershell
docker compose exec -e GATE_GITLAB_PROJECT=orbit integration-worker python -m scripts.gate_gitlab_smoke
docker compose exec -e GATE_GITLAB_PROJECT=ember integration-worker python -m scripts.gate_gitlab_smoke
```

Each smoke must perform Review before Approve, return the external URL of the correct repository, and `idempotent_replay=true`. Then read the Issue back to confirm the trace marker/acceptance criteria and that the raw source was not exposed. `409 REVIEW_REQUIRED` is fail-closed by design if the script or client skips Review.

## 10. Daily Planning smoke

1. Check that `planning-scheduler` and `planning-worker` are running; Beat must have the 23:30/06:45/07:00 schedule in `Asia/Ho_Chi_Minh`.
2. Open `/planning`, create/open a run by date + scope, check capacity and source warnings.
3. Quick Add form/paste is only treated as an Intake candidate; it must be linked to the current GitLab Issue before promote.
4. Accept proposals before approval. Approval is the external-write boundary because it enqueues a GitLab update per Issue.
5. Monitor `GET /planning/runs/{id}/sync-jobs`; only retry `FAILED` jobs that still have attempt budget.
6. When the smoke is not allowed to write to GitLab, stop before approval. Live internal UI mutation currently uses this same rule.

## 11A. Connecting a project to a customer's GitHub

1. Ask the customer for a fine-grained personal access token for only that repository, with Issues: Read and write and Metadata: Read permissions.
2. Preferred: in Settings > Projects (Cài đặt > Dự án), the "GitHub token (CTO)" ("Token GitHub (CTO)") section, give it a memorable name and paste the token; no worker restart needed. Fallback: copy `.env.github.example` to `.env.github` and add the line `GITHUB_TOKEN_<TÊN>=<token>` (do not put it in `.env`).
3. Fallback only: `docker compose up -d integration-worker` so the worker picks up the new variable.
4. In Settings > Projects, create or edit a project of type Software (Phần mềm), choose "Customer's GitHub" ("GitHub của khách hàng"), choose the token by name, choose the repository, and click "Test connection" ("Kiểm tra kết nối").
5. When the customer revokes the token, creating and refreshing Issues for that project reports `GITHUB_AUTH_FAILED`; paste the token again under the same name in the GitHub Token section (or replace the value in `.env.github` and restart the worker).

## 12. Meeting recording

1. Enable with `MEETING_CAPTURE_ENABLED=true` and set `ELEVENLABS_API_KEY` in `.env`; only `meeting-gateway` receives this key.
2. After changing code or `nginx.conf`, rebuild exactly the affected services: `docker compose up -d --build api meeting-gateway ai-worker web`. Port 8080 serves the built version, not the working tree.
3. Quick check: the Meetings (Cuộc họp) page opens, a test recording reaches `Bản chữ: Xong` and `Note: Xong`, and the "Play back" ("Nghe lại") button plays on port 8080 (the CSP must include `media-src 'self' blob:`).
4. The three browser scripts `frontend/e2e/meeting-capture.mjs`, `meeting-upload.mjs`, `meeting-notes.mjs` call real ElevenLabs and UModelVerse and write data to the running database; do not run them in CI.
5. The UI font is the licensed Cerebri Sans: the `.woff2` files must be copied into `frontend/public/fonts/` before building, otherwise the UI uses the system font.

## Task reminders via Telegram (ADR-0057)

1. Create a bot with @BotFather (`/newbot`), get the token and username. In BotFather, turn off "Group Privacy" (`/setprivacy`, choose Disable) so the bot can read the `/lien-ket` command in groups.
2. On the server, write to `.env`: `TELEGRAM_BOT_TOKEN=`, `TELEGRAM_BOT_USERNAME=` (without `@`), `APP_PUBLIC_URL=https://intake.example.com`. Do not print the token to logs or chat.
3. `bash scripts/deploy.sh api telegram-bot` (or `docker compose up -d telegram-bot`). The log must contain `bot @<username> ready`; Settings > System (Cài đặt > Hệ thống) shows the bot as "ok".
4. Per project: add the bot to the project's Telegram group and type `/lien-ket <mã dự án>`; the bot replies with the project name. To change groups: `/huy-lien-ket` in the old group. To use one shared group: enable "Topics" ("Chủ đề") in the group settings, create one topic per project, open that topic, then type `/lien-ket <mã dự án>`; the bot replies and sends reminders within that topic.
5. Per person: Settings > Members > "Telegram invite link" (Cài đặt > Nhân sự > "Link mời Telegram"), copy the link and send it to that person; they open the link and press Start. The member row shows "Telegram @username".
6. Days off: Settings > System > Task reminders via Telegram (Nhắc việc qua Telegram), one `YYYY-MM-DD` date per line.
7. Check right after linking, on the server (commands run in the `telegram-bot` container, the only place with the token):
   ```bash
   docker compose run --rm --no-deps telegram-bot python -m app.workers.telegram_bot test                       # một dòng thử tới mọi nhóm, chủ đề và người đã gắn
   docker compose run --rm --no-deps telegram-bot python -m app.workers.telegram_bot preview --at "2026-10-14 17:30"   # in ra tin của mốc đó, không gửi
   docker compose run --rm --no-deps telegram-bot python -m app.workers.telegram_bot send --at "2026-10-14 17:30"      # gửi thật tin của mốc đó ngay bây giờ
   ```
   `send` writes the log like a real run, so that time slot will not be sent again when its time comes. `preview` only has a message when the slot is a working day and within the 20-minute window after the time (08:00, 08:30, 09:30, 17:30).
8. When you suspect messages are not going out: `docker compose logs --tail=100 telegram-bot`; the `telegram_messages` table records `FAILED` with the error, and Settings > System lists the five most recent errors. Leaked token: create a new token in BotFather (`/revoke`), edit `.env`, `docker compose up -d telegram-bot`.
