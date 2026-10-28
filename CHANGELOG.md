# Changelog

## 2026-10-27

### Initial open source release `a000003`
- Published the self-hosted source under the Apache-2.0 license.
- Replaced private migration history with a single clean baseline.

### Safer release export `a000002`
- Added a release gate for credentials and private deployment identifiers.
- Public releases start from one fresh commit without private Git history.

## 2026-10-26

### Administrator-owned AI configuration {cto} `a000001`
- Administrators can configure an OpenAI-compatible provider without exposing its key again.
- Provider credentials are encrypted and never returned by the API.
