# Quality gates 1.2

## Gate 0 - Requirement và ADR

- Requirement có mã SRS và acceptance criteria.
- Open decision ảnh hưởng kiến trúc đã được CTO chốt.
- ADR/data model/flow được cập nhật trước coding.

## Gate A - Database

- Schema, type, FK, CHECK, unique và index khớp `data-model.md`.
- Migration chạy được trên database rỗng và rollback strategy được ghi rõ.
- Test PostgreSQL thật cho JSONB, TIMESTAMPTZ, lease và concurrency.
- Với lần reset pilot: CTO duyệt đúng target volumes trước thao tác.

## Gate B - API contract

- Route trỏ tới requirement ID.
- Auth/project scope và response field allowlist.
- Pagination cap, error catalog, idempotency và optimistic concurrency.
- Smoke collection/curl có thể chạy lại.

## Gate C - Business validation

- Unit/integration suite xanh.
- Có failure injection cho rule trọng yếu.
- Không silent success hoặc retry vô hạn.

## Gate D - UI

- UI dùng API thật; mock đã gỡ khỏi flow nghiệm thu.
- Trạng thái empty/loading/error/retry/stale rõ ràng.
- Flow chính và negative flow chạy trên browser.

## Gate E - Plane integration

- UModelVerse/provider fallback contract test.
- Plane self-host E2E và duplicate protection.
- Cross-project isolation cho hai dự án.

## Gate F - GitLab integration

- GitLab self-host E2E, lookup-before-create, idempotent replay và payload redaction.
- Cross-project mapping cho hai dự án.
- Browser hiển thị external link và negative approval gate.

## Gate G - Controlled pilot

- Không P0/P1 mở.
- Backup/restore drill đạt RPO/RTO.
- Security checklist, monitoring, alert và rollback được diễn tập.
- CTO ký UAT và risk acceptance còn lại.

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

