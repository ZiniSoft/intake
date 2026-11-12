English | [Tiếng Việt](incident-runbook.vi.md)

# Incident runbook 1.2

## 1. Severity

| Level | Example | Action |
|---|---|---|
| P0 | Data leak, data loss, mass creation of external items, leaked credential | Stop side effects, isolate, CTO in command |
| P1 | Intake/queue/database unavailable, widespread sync errors | Stop the rollout, restore service |
| P2 | One project/job failing, a workaround exists | Contain and retry in a controlled way |
| P3 | Minor UI/observability issue | Backlog by priority |

## 2. General procedure

1. Record the time, who detected it, and the request/job/project IDs.
2. Preserve redacted logs/audit; do not copy raw data arbitrarily.
3. Stop further side effects by stopping the right worker or disabling the project integration.
4. Classify: data, availability or external duplication.
5. Fix and check the negative cases.
6. Restore workers incrementally, monitoring queues/jobs.
7. Post-incident: cause, scope, evidence, preventive actions and owner.

## 3. Short playbooks

### UModelVerse errors

- Check the redacted HTTP/error code and the key/model allowlist.
- 400/401/403: fix the configuration, do not force a fallback.
- Timeout/429/5xx: check the queue backoff and retry count; the pilot has no fallback provider (ADR-0011), a run that exhausts its attempts moves to `FAILED` for the CTO to reprocess when the provider recovers.
- Do not retry manually multiple times while the job holds a lease.

### GitLab/GitHub duplicates

- Disable the integration of the affected project.
- Compare the external ID/marker with the idempotency key and payload hash.
- Do not automatically delete external items; the CTO decides the canonical record and relinks the audit.

### Redis connection lost

- Keep the API up if PostgreSQL/outbox is still healthy.
- Restore Redis/workers; the dispatcher republishes NEW/RETRY events.
- Check that no run/job was processed twice.

### Planning sync partially or fully failed

- Look at the per-Issue jobs; do not retry the whole run and do not roll back Issues already `SUCCEEDED`.
- Only use the UI/API retry for `FAILED` jobs that still have attempts left; `PENDING/RUNNING/RETRY` jobs must be left to the worker/lease.
- If it is a mapping/payload error, fix the cause first; runtime 1.2 has no amendment UI for an approved run, so do not edit the snapshot/job payload directly in the database.
- Disable the GitLab integration or stop the integration worker if mass incorrect updates are detected.

### Daily Report/IMAPS errors

- The Planning Run continues from the GitLab read model and must show `REPORT_MISSING`, `REPORT_MALFORMED` or `REPORT_LATE` as appropriate.
- Do not switch to SMTP or mark the mailbox as read; the worker only uses `BODY.PEEK[]`.
- If a member identity is not mapped, handle `REPORT_IDENTITY_UNMAPPED`; do not assign a report automatically based on an ambiguous display name.

### PostgreSQL errors

- The API goes not-ready; stop the writing workers.
- Restore the service or restore from backup per the backup runbook.
- Do not run hot-fix migrations outside version control.

### SeaweedFS errors

- Block new uploads and attachment processing.
- Text-only intake can continue if policy allows and the UI shows degraded mode.
- Check DB-object reconciliation after recovery.

### Leaked credential

- Revoke/rotate immediately; disable related workloads.
- Review audit/provider logs and the time range.
- Update secret injection; do not just delete the secret from the current file.

