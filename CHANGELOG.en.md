# Changelog

Add an entry at the top of this file with every commit to `main`, written for Intake users rather than source-code readers. Use `## YYYY-MM-DD` for the date, `### Title \`hash\`` for each entry, `References:` for FR and ADR identifiers, and bullets for user-visible changes. Add `{cto}` to the title of CTO-only entries. Keep this file aligned with the Vietnamese `CHANGELOG.md` for every new change.

## 2026-11-11

### Intake workflow introduction video added to the README `11ba38b`
References: public documentation and demo guide.
- The English and Vietnamese READMEs, together with both public versions, now include a clickable poster that opens the introduction video on YouTube.
- The demo package includes synchronized English captions, a Vietnamese recording plan, and a Playwright recorder using English sample data. All API write operations are mocked while recording.
- Flowcharts in English documents no longer contain Vietnamese labels. The rendered video and personal voice recording are not stored in Git history.

### The repository README now has English and Vietnamese versions `f6b41eb`
References: repository root documentation.
- `README.md` is now always in English. Readers can switch to Vietnamese through the link at the top of `README.vi.md`.
- Agent instructions require both versions to be updated in the same change so their content stays aligned.

## 2026-11-10

### Quick installation and first-time setup moved to the top of the README `81826af`
References: FR-SETUP-09, ADR-0071.
- New installers immediately see prerequisites, clone commands, separate commands for Windows and Linux/macOS, and the steps to create the CTO account, connect an AI key, and submit a test request.
- The README now includes installation checks, safe operating commands, common fixes, and a separate manual Docker section for people who need customization.

### The Vietnamese documentation map now points to Vietnamese documents `23e41aa` {cto}
References: `docs/public/docs/` documentation.
- Links in the public repository's Vietnamese documentation map now open the `X.vi.md` version instead of the English version.

### SRS, interface contracts, and the data model now have English versions `6be4f42` {cto}
References: `docs/stable/` documentation.
- `SRS.md`, `interface-contracts.md`, and `data-model.md` are now in English. Their Vietnamese versions are stored in `SRS.vi.md`, `interface-contracts.vi.md`, and `data-model.vi.md`. Adding an FR identifier or changing an API requires both versions to be updated.
- All open documents in `docs/stable/` are now bilingual. ADRs, plans, and the development log remain in Vietnamese.

### Open documentation uses English by default with a Vietnamese file beside it `d029959` {cto}
References: `docs/stable/`, `docs/public/docs/`.
- Twenty-three documents, including the BRD, functional specification, flows, MCP agents, daily reports, publishing workflow, watch sources, testing and acceptance, operations, conventions, and architecture, now use English in `X.md` and Vietnamese in `X.vi.md`. Each file has a language switch at the top.
- Vietnamese documents link to Vietnamese versions of other documents. Updating a document requires both language versions to be changed in the same commit.
- English versions of the SRS, interface contracts, and data model are planned for the next update. ADRs, plans, and the development log remain in Vietnamese.

### Upload images and PDFs when attaching a work link `9d30f9b`
References: FR-WRK-10, FR-WRK-07, Issue #43, INT-26W46-001.
- In the Links section of a work card, choose Select file to upload an image (JPG, PNG, or WebP) or a PDF from the computer, up to 5 MB per file. The "What is this link?" field is used as the file note.
- Uploaded files appear with the other links and can be downloaded. Removing the link also deletes its file.
- Pasting a URL continues to work as before.

### Project page sections no longer run into each other `0fde000`
References: FR-UI-14.
- GitLab connection, GitHub token, sample project, and open-source project sections on the Projects page now have clear spacing, with text separated from section borders.
- Sections under Settings > AI and in a project's member list use the same improved spacing.

### Bulk acceptance command for older pending work `736161d` {cto}
References: FR-PLAN-31, FR-PLAN-41.
- `scripts/bulk_accept_pending.py` lets the CTO accept all pending work through a selected date in one run, including work from reports, plans, or closed tracker Issues that are not linked to an Intake request. Each item follows the same path as the Accept action: history is recorded, a comment is added, and the Issue is closed.
- The command lists work by default and applies changes only with `--apply`. Work already returned by a Project Owner is left unchanged. Options can skip P0 work (`--skip-p0`), select one project (`--project`), or exclude individual Issues (`--exclude KIN#26`).

### Project Owners can finalize acceptance for low-risk work `bd51dd9`
References: FR-PLAN-41, ADR-0082, FR-PLAN-39.
- In projects where Project Owners can finalize work, choosing Confirm complete immediately accepts the item. Intake adds a "Project Owner accepted" comment to the Issue and closes it without waiting for the CTO.
- Work still waits for the CTO when it is marked high-risk, has P0 priority, lacks sufficient evidence, was completed or reported by that Project Owner, or was previously returned. P1 priority alone does not make work high-risk.
- The acceptance card tells Project Owners in advance whether their confirmation closes the Issue or still requires CTO review, and explains why.
- The request page identifies who accepted the work. If the Project Owner confirmed an item that still requires CTO review, the page says "Project Owner confirmed completion, awaiting CTO acceptance."
- {cto} On the Acceptance page, filter by project and choose who finalizes acceptance: CTO for all work, which is the default, or Project Owner for low-risk work. Work confirmed before this option was enabled still waits for CTO acceptance.

## 2026-11-09

### Plan by person `a4e83c6` `dda45f5`
References: FR-PLAN-40, ADR-0081.
- The new Plan by person menu item lets you select a person, view their work by day, week, or month, and navigate back through all past dates. Each day shows scheduled hours versus availability, days off, assignments across all projects, and internal work assigned to that person.
- In month view, select a day to open its details. The page summary totals hours by project, days off, and accepted work.
- Select a person's name in the People board on Today or the By person table on Last week to open that person's plan.
- Visibility follows project membership: the CTO sees everyone, Project Owners see people in their assigned projects, and Developers see teammates in shared projects. For projects you do not share with the person, only the project name and hours are visible. Another person's personal work appears only as "Personal tasks: X hours."
- This page is read-only; plans cannot be edited here.

### Clear fixes when a token lacks permissions `63ee5d7` {cto}
References: FR-INTG-23, ADR-0080.
- When Check permissions reports that a GitHub token cannot create an Issue, the screen lists common causes: Public repositories was selected, permissions were added under Organizations instead of Repositories, organization approval is pending, or the organization restricts tokens.
- A failed permission check includes a link to common token-creation problems.
- `/huong-dan` now includes a Common token problems table for GitHub and GitLab with a fix for each case. After changing GitHub permissions, users can choose Check permissions again without pasting the token again.

### Fixed "The queue is not accepting work" after a fresh installation `5879996` {cto}
References: no requirement change.
- A fresh build could install a queue library version that was incompatible with Redis, causing every background task, including request normalization, Issue creation, and connection or token checks, to report that the queue was not accepting work. The library version is now pinned, and rebuilding restores normal operation.

### Connect GitLab in the UI and verify token permissions `da1d4b1` `d711b17` `2df0f51` {cto}
References: FR-INTG-22, FR-INTG-23, FR-SETUP-17, ADR-0080.
- First-time setup now has an optional GitLab/GitHub step. Choose the company's GitLab or a customer's GitHub, paste a token, open token instructions, or choose Set up later. The Done step includes a button to return to this configuration.
- The Projects page now has a GitLab connection section for the GitLab URL and a personal access token, without editing `.env` or restarting the service. The token is encrypted and only its last four characters are shown. Existing installations using the `.env` token continue to work.
- One GitLab token with `api` and `read_repository` scopes and at least the Reporter role is sufficient. It creates Issues and reads project context files; a separate read token is now optional. The Create GitLab token link preselects both scopes.
- Check permissions beside GitLab tokens, GitHub tokens, and project repository selectors explains exactly which permission is missing, whether the project role is insufficient, or whether a token expires within 14 days. GitHub write checks do not create an Issue.
- Bilingual GitLab and GitHub token instructions are available during setup, beside token fields, and in `/huong-dan`.

### Move a project from GitLab to GitHub `762d3b2` {cto}
References: FR-PRJ-13, ADR-0079.
- On a software project linked to GitLab, the CTO can choose Move to GitHub, select a GitHub repository and token, and check the connection as with a new project. Saving requires one additional confirmation.
- The migration screen shows how many GitLab Issues remain open. They stay in GitLab and are not copied to GitHub.
- After migration, approved requests create Issues on GitHub. The GitLab link is preserved but no longer synchronized, old Issues remain available from their links, and the project page records the move date.
- Acceptance history, evidence, and plans for old GitLab Issues remain separate from new GitHub Issues that happen to use the same number.

### Open commits directly from work history for review `c1ca786`
References: FR-MCP-03.
- Commit hashes in an Intake request's work history are now links that open the corresponding commit on the project's GitLab or GitHub repository.
- The link is derived from the request's Issue. Without an Issue, the commit hash remains plain text. If a contributor records a full commit URL, that URL is preserved.
