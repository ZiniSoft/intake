English | [Tiếng Việt](security-rules.vi.md)

# Security rules 1.2

This is the security target. Current runtime gaps include auth rate limiting, persistent session revocation, full login/MFA/raw-read audit, file checks/OCR sandbox, signed downloads and production VPN/TLS; check readiness before treating a rule as enforced.

## 1. Data classes

| Class | Example | Rule |
|---|---|---|
| Restricted | Raw chat, email body, sender reference, attachment | Encrypt, CTO-only, 90-day retention |
| Confidential | Normalized requirement, report, audit | Auth + project scope |
| Secret | Password, MFA secret, API token | No plaintext in logs/DB; secret injection |
| Public/internal-safe | Intake public ID, sanitized external summary | Allowlisted fields only |

## 2. Credential separation

- AI worker: UModelVerse/OpenRouter key, no GitLab/GitHub token.
- Integration worker: GitLab/GitHub token, does not need the raw source decryption key.
- IMAPS worker: IMAP credential, no SMTP credential. Password recovery emails go only from the API via Mailgun HTTPS; the Mailgun API key is not given to any other worker.
- Customer GitHub tokens (ADR-0021): one `GITHUB_TOKEN_<TÊN>` token per repository, preferably pasted in Settings > Projects ("Cài đặt > Dự án") (stored encrypted in the database, ADR-0076, only the last 4 characters shown); the fallback is a variable in `.env.github` that only `integration-worker` loads, and the file is not committed. With the same name, the token in the database takes precedence. Tokens are fine-grained, limited to one repository, with Issues read/write and Metadata read permissions. No token is shared between two customers.
- Meeting gateway: `ELEVENLABS_API_KEY`; no GitLab/GitHub token, mailbox password or UModelVerse key. Every other service receives an empty value for this key.
- Known gap: `UMODELVERSE_API_KEY` still reaches every app container except the gateway because the services share an `env_file`.
- API: only the secrets needed for auth/encryption and no provider permissions broader than necessary.

### Per-project authorization (ADR-0022)

- Deny by default: a new route uses `require_cto` unless it is deliberately opened with `require_member`.
- A route using `require_member` must check the project of whatever it touches (`ensure_project`, or the `intake_member`/`meeting_member` dependency) and must have a test case in `tests/test_project_owner.py` that calls it with an account from another project.
- Out of scope returns 404, not 403.
- A temporary password is shown only once to the CTO and must be delivered through a secure channel; do not send it over chat together with the username.

## 3. Network

Only the reverse proxy/web is exposed inside the VPN. PostgreSQL, Redis and SeaweedFS are not published to the LAN. Egress allowlist per workload; SMTP blocked by host/container policy.

## 4. File safety

Uploads go to quarantine, with checks on size/MIME/magic bytes and PDF page count; encrypted PDFs or PDFs with embedded files are rejected. The pilot does not use malware scanning (ADR-0015). OCR runs on a separate machine on the same LAN, in a container without Internet access, non-root, with a read-only filesystem, CPU/RAM limits and a per-file timeout. The connection from Intake to the OCR machine must be authenticated; the OCR machine does not keep files/results and cannot reach back into database/Redis/SeaweedFS. Only clean objects move to the trusted pipeline. Downloads use short-lived signed URLs or an authorized API stream, always returned as an attachment, never displayed inline in the browser.

## 5. Audit

Minimum audit: login/MFA/recovery/password reset, raw reads, upload/download, process/retry, approve/reject/defer, sync, mapping/secrets reference changes, retention purge and admin actions. Audit does not contain raw content or reset tokens.

## 6. AI boundary

Meeting audio is a deliberate exception to the principle "original files do not leave the internal network": it is sent to ElevenLabs for transcription, the provider-side copy is deleted after each turn, and the Pro plan has no zero-retention mode (OD-033). Report email signatures are not sent to the AI (ADR-0019). The web container allows playing media from `blob:` (to play back decrypted recordings) and microphone/screen sharing only for its own origin.

Cloud providers are external data processors. Send only the minimum data over TLS to allowlisted endpoints; no tool/browser fetch; no secrets passed; record a provider/model/policy trace. Retention terms must be re-reviewed before production.

