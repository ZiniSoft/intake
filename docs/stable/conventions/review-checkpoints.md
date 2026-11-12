English | [Tiếng Việt](review-checkpoints.vi.md)

# Quality gates 1.2

## Gate 0 - Requirements and ADR

- Requirements have an SRS ID and acceptance criteria.
- Open decisions affecting the architecture have been finalized by the CTO.
- ADR/data model/flow are updated before coding.

## Gate A - Database

- Schema, types, FK, CHECK, unique and indexes match `data-model.md`.
- Migrations run on an empty database and the rollback strategy is documented.
- Real PostgreSQL tests for JSONB, TIMESTAMPTZ, lease and concurrency.
- For a pilot reset: the CTO approves the exact target volumes before the operation.

## Gate B - API contract

- Routes point to requirement IDs.
- Auth/project scope and response field allowlist.
- Pagination cap, error catalog, idempotency and optimistic concurrency.
- Smoke collection/curl can be rerun.

## Gate C - Business validation

- Unit/integration suite green.
- Failure injection for critical rules.
- No silent success or infinite retries.

## Gate D - UI

- The UI uses the real API; mocks have been removed from the acceptance flow.
- Clear empty/loading/error/retry/stale states.
- Main flow and negative flows run in the browser.

## Gate E - Plane integration

- UModelVerse/provider fallback contract test.
- Self-hosted Plane E2E and duplicate protection.
- Cross-project isolation for two projects.

## Gate F - GitLab integration

- Self-hosted GitLab E2E, lookup-before-create, idempotent replay and payload redaction.
- Cross-project mapping for two projects.
- The browser shows the external link and the negative approval gate.

## Gate G - Controlled pilot

- No open P0/P1.
- Backup/restore drill meets RPO/RTO.
- Security checklist, monitoring, alerts and rollback have been rehearsed.
- The CTO signs off UAT and the remaining risk acceptance.

## Gate report

```markdown
## Gate <0-G> - <module> - <date>
1. REQUIREMENTS: mã đã phủ; mã còn thiếu
2. DOC DRIFT: điểm lệch và file đã sửa
3. EVIDENCE: commit, lệnh, test count, kết quả, screenshot/log đã redact
4. FAILURES INJECTED: các ca lỗi đã kiểm
5. DEBT/RISK: hậu quả, owner, deadline
6. DECISION: APPROVED | REJECTED | CONDITIONAL
```

