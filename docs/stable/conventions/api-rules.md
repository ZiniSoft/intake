English | [Tiếng Việt](api-rules.vi.md)

# API rules 1.2

The runtime OpenAPI and `IMPLEMENTATION-INVENTORY.md` decide which endpoints are available; for example, a target route with no code yet must not be called by clients just because it appears in the specification.

## 1. URL and version

- Prefix `/api/v1`.
- Resources use plural nouns, kebab-case.
- GET has no side effects.
- State transitions use a short sub-resource when they cannot be expressed with PATCH, for example `POST /intakes/{id}/approve`.

## 2. Response contract

```json
{
  "success": true,
  "data": {},
  "request_id": "uuid"
}
```

```json
{
  "success": false,
  "error": "APPROVAL_SNAPSHOT_STALE",
  "message": "Dữ liệu đã thay đổi; hãy duyệt lại trước khi đồng bộ.",
  "details": [],
  "request_id": "uuid"
}
```

Do not return stack traces, secrets, raw prompts or raw source in errors.

## 3. Status codes

| Code | Used for |
|---|---|
| 200 | Successful read/update/action |
| 201 | Resource created |
| 202 | Job accepted and running async |
| 400 | Wrong shape/validation |
| 401 | Not authenticated |
| 403 | Identity known but lacking permission |
| 404 | Resource does not exist or is out of scope |
| 409 | Version/state/idempotency conflict |
| 413 | File/payload too large |
| 422 | Business validation failed |
| 429 | Rate limit |
| 500/503 | System error/temporary dependency error |

## 4. Pagination

Lists must have `limit` with default 20, max 100, and a keyset cursor. Minimum filters: `project_id`, `status`, `channel`, `from`, `to`. `sort_by` must be in an allowlist. Do not use deep offsets for intake/audit/job tables.

## 5. Concurrency and idempotency

- Review mutations send `expected_version`.
- Sync takes `approval_snapshot_id`; the server builds the idempotency key from project, target and snapshot/payload hash.
- A retried request must return the same result or the current state, without creating a new side effect.

## 6. Security

- Project scope comes from the resource/database and verified permissions; do not trust the body to change ownership.
- Responses use field allowlists per role.
- Attachment downloads require authorization; do not return permanent public object URLs.
- Every route declares its policy in the same change that creates the route.

