English | [Tiếng Việt](deployment-topology.vi.md)

# Deployment topology 1.2

_Target production topology; local runtime evidence on 2026-10-01; domain/TLS finalized on 2026-10-03_

## 1. Pilot environment

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

| Zone | Components | Rules |
|---|---|---|
| VPN application | Intake, GitLab | HTTPS; user access only via VPN |
| Docker internal | PostgreSQL, Redis, SeaweedFS | Not published to the LAN |
| AI egress | UModelVerse SG (OpenRouter not used in the pilot, ADR-0011) | Only allowlisted HTTPS endpoints; only text and OCR'd text is sent, never original files (ADR-0015) |
| Speech-to-text egress | ElevenLabs API (ADR-0018) | Only `meeting-gateway` calls it; it is the only container holding `ELEVENLABS_API_KEY`; meeting audio leaves the internal network through this path |
| OCR egress | OCR machine on the same LAN | Only the worker processing attachments calls the exact OCR machine address, with authentication; the OCR machine has no Internet access and cannot reach back into database/Redis/SeaweedFS |
| Mail egress | `mail.example.com:993` | IMAPS only |
| SMTP | IMAPS worker | Block 25/465/587 |

Windows can use Wi-Fi while the Ubuntu VM uses an external virtual switch on the LAN card. The VM gets its own LAN IP and does not share the Windows IP.

## 3. Storage

The machine has a 2 TB SSD, no RAID. SeaweedFS with a single volume server provides no redundancy. Backup to another machine is mandatory; solar backup power reduces the risk of power loss but does not replace backups or filesystem consistency checks.

## 4. Target domains

| Domain | Location | Access |
|---|---|---|
| `mail.example.com` | Mail VPS | Public mail protocols per policy |
| `gitlab.example.com` | Self-hosted GitLab CE | VPN |
| `intake.example.com` | Ubuntu VM, pointed directly | VPN, CTO only |

Per ADR-0014, Intake serves HTTPS with free TLS certificates issued automatically via ACME. The VM accepts no connections from the Internet, so certificates must be issued via the DNS-01 challenge or an equivalent mechanism, and a reverse proxy terminating TLS is needed in front of `web`/`api`. The specific VPN product, reverse proxy and ACME client are still open under OD-004.

## 5. Container security

- Pin image digest/version; do not use `latest` for the pilot baseline.
- Run as non-root when the image supports it.
- Read-only filesystem and dropped capabilities for stateless workers where feasible.
- Healthchecks separate liveness/readiness.
- Secrets loaded from `.env` only in the pilot; before production move to a secret manager/protected file mount.
- Separate credentials per container; the AI worker does not see GitLab/GitHub tokens.

## 6. Current Compose runtime

Compose declares PostgreSQL, Redis, SeaweedFS master/volume/filer/S3/config, API, web, outbox dispatcher, AI worker, integration worker, planning worker, planning scheduler and IMAPS worker. Local binding by default is only `127.0.0.1:8080` for web and `127.0.0.1:8001` for the API; database/broker/storage are on the internal network.

The integration worker is the only container that receives GitLab/GitHub write tokens. The API, dispatcher, AI worker, planning worker/scheduler and IMAPS worker do not receive external write tokens. The IMAPS worker has its own mail egress; the runtime currently has `REPORT_IMAP_ENABLED=false`.

Compose does not yet have a reverse proxy/TLS for `intake.example.com` and does not yet have a backup job. Evidence for Gate C through Gate F was run on the Windows workstation; per ADR-0014 the critical smoke/E2E must be rerun on the Ubuntu VM before Gate G (OD-021).

