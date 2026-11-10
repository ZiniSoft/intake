English | [Tiếng Việt](coding-rules.vi.md)

# Coding rules 1.2

## 1. Architecture

- Thin routes; business invariants in services; persistence through an explicit repository/unit-of-work.
- Modules do not have circular imports or arbitrarily query another module's tables directly.
- External providers go through an adapter interface and contract tests.
- PostgreSQL is the source of state; Redis is only a broker/cache.

## 2. Database

- Schema changes only through reviewed migrations.
- Do not manually serialize dicts into JSONB columns.
- A transaction includes the state change and its corresponding outbox entry.
- Job claims use a lease and `SKIP LOCKED`; do not hold a DB transaction during network calls.
- No N+1; list projections do not fetch raw/large JSON.

## 3. Errors and logging

- No `except Exception: pass`.
- Classify permanent/transient.
- Structured logs with request/job/intake/project ID and error code.
- Redact tokens, passwords, raw messages, prompts and PII.

## 4. Tests

- Each invariant has a success test and a fault-injection test.
- Provider adapters have contract tests for timeout, 429, 5xx, invalid JSON, 401/403.
- External side effects have concurrency/idempotency tests.
- Database behavior needs real PostgreSQL tests; SQLite is only for unit tests that do not depend on types/locking.
- Docs changes and readiness evidence go in the same PR/commit series.

## 5. Quality

Code format, lint, type check, unit, integration and migration smoke must be CI hard gates before the controlled pilot.

