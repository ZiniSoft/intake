# Intake - guide for agents working in this repo

Intake receives customer requests (chat, email, meetings, forms, agents), lets AI normalize them, a CTO approves, creates an Issue on GitLab/GitHub, and schedules the work into a daily plan. Read `docs/stable/SRS.md` (requirements, FR-* codes) and `docs/stable/interface-contracts.md` (API) before changing behavior.

## Layout
- `app/api/routes/` - FastAPI routes; each carries `openapi_extra={"x-requirement-ids": [...]}` pointing at SRS codes (an architecture test checks this).
- `app/services/`, `app/modules/*` - domain logic by area (planning, reports, meetings, private_space, mcp, setup, work, watch...).
- `app/workers/` - Celery queues (`ai.normalize`, `integration.sync`, `planning.schedule`).
- `app/migrations/postgresql/NNN_*.sql` - append-only migrations, applied on API start; add a new file with the next number, never edit old ones.
- `frontend/src/` - React/Vite (`App.tsx`, `types.ts`, `styles.css`).
- JSON responses use the envelope `{success, data, request_id}`; errors go through `api_exception(status, code, message)`.

## Run and check
- Stack: `docker compose up -d`; Vite dev server: `cd frontend && npx vite --host 127.0.0.1 --port 5173`.
- Backend tests (SQLite): `python -m pytest -q`.
- Frontend: `cd frontend && npx tsc -b`.

## Conventions
- Branches `feature/<slug>` or `fix/<issue>-<slug>` from `main`; no direct commits to `main`.
- New requirement: add an FR code to the SRS. Architecture decision: add an ADR.
- Docs under `docs/` are bilingual: `X.md` English (default), `X.vi.md` Vietnamese, with a language switch line at the top. Update both versions in the same change.
- No secrets in files; use `.env`. Do not use real customer data for tests.
