# Contributing

Thanks for helping. Read `docs/stable/SRS.md` (requirements, FR-* codes) and `docs/stable/interface-contracts.md` (API) before changing behavior.

## Workflow
1. Fork, then branch from `main`: `feature/<slug>` or `fix/<issue>-<slug>`.
2. Run the checks below.
3. Open a pull request using the template. Keep commits focused; explain the reason in the body.

## Checks
```bash
python -m pytest -q          # backend, uses SQLite
cd frontend && npx tsc -b    # frontend types
```

## Rules
- Every API route carries `openapi_extra={"x-requirement-ids": [...]}` pointing at SRS codes; an architecture test checks it.
- Migrations are append-only: add `app/migrations/postgresql/NNN_*.sql`, never edit an old one.
- A new requirement gets an FR code in the SRS; an architecture decision gets an ADR.
- Code and comments in English. The UI is Vietnamese for now; internationalization is planned.
- No secrets in files and no real customer data in tests or fixtures.

By contributing you agree your work is licensed under Apache-2.0.
