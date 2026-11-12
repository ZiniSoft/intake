English | [Tiếng Việt](README.vi.md)

# Intake - Documentation map

The documentation currently in force is in `stable/`.

- [BRD](stable/BRD.md): business goals and scope.
- [SRS](stable/SRS.md): requirements with traceability IDs (FR-*, NFR-*). The `ADR-nnnn` IDs in the documents point to the project's architecture decision records, which are not yet published in this repository.
- [Functional spec](stable/functional-spec.md), [Interface contracts](stable/interface-contracts.md), [Data model](stable/data-model.md), [Flows](stable/flows.md)
- [Daily report format](stable/daily-report-format.md), [MCP agents](stable/mcp-agents.md), [Watch flow](stable/watch-flow.md), [Publish flow](stable/publish-flow.md)
- [Test and acceptance](stable/test-and-acceptance.md)
- [Fictional Nova agent context](agent/CONTEXT.md): a safe public example for repository-aware agent workflows.
- Conventions: [API](stable/conventions/api-rules.md), [validation](stable/conventions/validation-rules.md), [coding](stable/conventions/coding-rules.md), [UI URL state](stable/conventions/ui-url-state.md), [security](stable/conventions/security-rules.md), [review checkpoints](stable/conventions/review-checkpoints.md)
- Operations: [Docker runbook](stable/operations/docker-runbook.md), [server deploy](stable/operations/server-deploy.md), [backup and restore](stable/operations/backup-restore.md), [incident runbook](stable/operations/incident-runbook.md)

Update rules: new requirements get an ID in the SRS before coding; every new API points to at least one requirement ID; documentation is bilingual (`X.md` English by default, `X.vi.md` Vietnamese; update both), code and commits in English.
