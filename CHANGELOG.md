# Changelog

## 2026-10-31

### Private CTO content settings stay isolated `4023061`
- Moved posting-channel and watch-source configuration out of general Settings and into a clearly marked BETA area under the CTO's private space.
- Channel rules, watch platforms, AI-run limits and inbound connectors now belong to the private project and cannot change company or customer projects.
- The private BETA explains that scanning and publishing are not automatic yet, hides inactive auto-publishing controls, and defaults to disabled in public installations.

### Account and deployment security hardening
- Production startup now rejects unsafe signing secrets and bootstrap passwords, requires secure session cookies, and keeps development and test setup lightweight.
- Password changes, email resets and temporary-password replacement revoke older web sessions and personal API tokens in the same transaction.
- Replacing an active MFA factor or regenerating recovery codes requires the current password and factor; confirming the replacement rotates older credentials.

### Safer backup restore and Telegram operations
- Restore validates archive members and manifest paths before extraction, rejecting traversal, absolute paths, Windows separators, links, duplicates and special files before database or object-storage tools run.
- Telegram transport failures expose only stable error codes and exception classes; request URLs, bot-token shapes and tracebacks are redacted from operational logs and surfaced delivery errors.

### Project team controls
- Project Owners can add active people to projects they manage, while administrators can edit staff profiles and remove one membership without deleting the person, account or history.
- Project membership views now distinguish unlinked accounts and keep owner-removal safeguards explicit.

### Dependency update automation paused
- Dependabot version-update pull requests are paused for Python, frontend npm and GitHub Actions by setting their open pull request limit to zero. Repository security alerts remain controlled separately in GitHub settings.

### Docker image includes the public agent command
- Fixed fresh public clones failing to build because the Dockerfile referenced an agent command that the release export had omitted.
- Kept the public `/fix-issue` command available to the application while continuing to exclude private `.claude` project settings.

### Project Owner role explained during first-run setup
- The optional Project Owner account now explains that it can review requests, plan and assign work, and track progress only for assigned projects.
- Installers can skip the account and assign a Project Owner later from project settings; the role does not have system-wide administrator access.

### Easier AI model setup
- AI settings now keep provider forms and task rows away from panel edges and align provider, model and save controls consistently on desktop and mobile.
- Adding a provider automatically checks the connection and loads its model list. The model field explains how to search the loaded list or enter a model ID manually when the provider does not expose one.
- First-run setup asks only for the default model; optional per-task overrides are grouped under advanced settings with a plain-language description of each task.

## 2026-10-30

### English public walkthrough foundation `7a6c827`
- Added English coverage for sign-in, request capture and review, the request journey, primary navigation and the Daily Planning actions used by the public walkthrough. Open the English path with `?lang=en`; the browser remembers the choice.
- Added reproducible storyboard, narration, captions, poster and recording-safety runbook built around a fictional project and least-privilege demo repository.
- Added English and Vietnamese lifecycle diagrams to the public README.

### Per-account Daily Planning project order `7a6c827`
- The all-projects view now prioritizes projects that need attention and lets each account save a custom order with drag-and-drop or accessible move buttons.
- Saved order is restricted to projects the account can see; newly visible projects are appended using the default priority rules.

### Safer and more reproducible public export `7a6c827`
- Expanded secret detection for common cloud, GitHub, GitLab, OpenAI-compatible and Slack token formats.
- Removed private-install compatibility literals from the fresh public tree while preserving only the published project identity and deployment URL.
- Added focused export regression coverage and ignored local databases, secret directories, private backups and demo recording artifacts.
- Restricted CI to read-only repository contents, cancelled superseded runs and paused automatic dependency pull requests until maintainers explicitly restore review capacity.
- Added a fictional Nova project context so agent workflows can be documented without private project names, hosts or access details.

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
