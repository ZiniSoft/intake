# Deployment topology 1.2

_Target production topology; runtime local evidence ngày 2026-10-01; domain/TLS chốt ngày 2026-10-03_

## 1. Môi trường pilot

```text
Windows 11 Pro workstation
└── Hyper-V
    └── Ubuntu Server 24.04 LTS VM
        ├── Docker Engine + Compose
        ├── intake-web / intake-api
        ├── dispatcher / ai-worker / integration-worker / imaps-worker
        ├── planning-worker / planning-scheduler
        ├── PostgreSQL / Redis
        └── SeaweedFS master / volume / filer / S3 gateway

Máy OCR trong cùng LAN (ADR-0015)
└── OCR service trong container cô lập; engine chưa chọn

VPS cloud
└── Mail server: mail.example.com
```

GitLab Community: `https://gitlab.example.com`.

## 2. Network

| Zone | Thành phần | Quy tắc |
|---|---|---|
| VPN application | Intake, GitLab | HTTPS; user access chỉ qua VPN |
| Docker internal | PostgreSQL, Redis, SeaweedFS | Không publish LAN |
| AI egress | UModelVerse SG (OpenRouter không dùng trong pilot, ADR-0011) | Chỉ HTTPS endpoint allowlist; chỉ gửi text và phần chữ đã OCR, không gửi file gốc (ADR-0015) |
| Speech-to-text egress | ElevenLabs API (ADR-0018) | Chỉ `meeting-gateway` gọi; là container duy nhất giữ `ELEVENLABS_API_KEY`; audio cuộc họp rời mạng nội bộ qua đường này |
| OCR egress | Máy OCR cùng LAN | Chỉ worker xử lý attachment gọi đúng địa chỉ máy OCR, có xác thực; máy OCR không ra Internet và không truy cập ngược database/Redis/SeaweedFS |
| Mail egress | `mail.example.com:993` | IMAPS only |
| SMTP | IMAPS worker | Block 25/465/587 |

Windows có thể dùng Wi-Fi trong khi Ubuntu VM dùng external virtual switch trên card LAN. VM nhận IP LAN riêng, không dùng chung IP Windows.

## 3. Storage

Máy có SSD 2 TB, không RAID. SeaweedFS một volume server không tạo redundancy. Backup sang máy khác là bắt buộc; nguồn điện dự phòng năng lượng mặt trời giảm nguy cơ mất điện nhưng không thay thế backup hoặc filesystem consistency check.

## 4. Domain mục tiêu

| Domain | Vị trí | Access |
|---|---|---|
| `mail.example.com` | VPS mail | Public mail protocols theo policy |
| `gitlab.example.com` | Self-host GitLab CE | VPN |
| `intake.example.com` | Ubuntu VM, trỏ trực tiếp | VPN, CTO only |

Theo ADR-0014, Intake phục vụ HTTPS bằng chứng chỉ TLS miễn phí cấp tự động qua ACME. VM không nhận kết nối từ Internet, nên chứng chỉ phải cấp bằng DNS-01 challenge hoặc cơ chế tương đương, và cần một reverse proxy kết thúc TLS trước `web`/`api`. VPN product, reverse proxy và ACME client cụ thể còn mở tại OD-004.

## 5. Container security

- Pin image digest/version; không dùng `latest` cho pilot baseline.
- Chạy non-root khi image hỗ trợ.
- Read-only filesystem và drop capabilities cho stateless worker nếu khả thi.
- Healthcheck tách liveness/readiness.
- Secret nạp từ `.env` chỉ ở pilot; trước production chuyển sang secret manager/file mount bảo vệ.
- Tách credential theo container; AI worker không thấy GitLab/GitHub token.

## 6. Runtime Compose hiện hành

Compose khai báo PostgreSQL, Redis, SeaweedFS master/volume/filer/S3/config, API, web, outbox dispatcher, AI worker, integration worker, planning worker, planning scheduler và IMAPS worker. Local bind mặc định chỉ `127.0.0.1:8080` cho web và `127.0.0.1:8001` cho API; database/broker/storage ở internal network.

Integration worker là container duy nhất nhận token ghi GitLab/GitHub. API, dispatcher, AI worker, planning worker/scheduler và IMAPS worker không nhận token ghi external. IMAPS worker có mail-egress riêng; runtime hiện `REPORT_IMAP_ENABLED=false`.

Compose chưa có reverse proxy/TLS cho `intake.example.com` và chưa có backup job. Evidence Gate C đến Gate F được chạy trên workstation Windows; theo ADR-0014 phải chạy lại smoke/E2E trọng yếu trên Ubuntu VM trước Gate G (OD-021).

