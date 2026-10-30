# Intake - Bản đồ tài liệu

Tài liệu đang áp dụng nằm trong `stable/`.

- [BRD](stable/BRD.md): mục tiêu và phạm vi kinh doanh.
- [SRS](stable/SRS.md): yêu cầu có mã truy vết (FR-*, NFR-*). Các mã `ADR-nnnn` trong tài liệu trỏ tới bản ghi quyết định kiến trúc của dự án, chưa được công bố trong repo này.
- [Functional spec](stable/functional-spec.md), [Interface contracts](stable/interface-contracts.md), [Data model](stable/data-model.md), [Flows](stable/flows.md)
- [Daily report format](stable/daily-report-format.md), [MCP agents](stable/mcp-agents.md), [Watch flow](stable/watch-flow.md), [Publish flow](stable/publish-flow.md)
- [Test and acceptance](stable/test-and-acceptance.md)
- [Fictional Nova agent context](agent/CONTEXT.md): a safe public example for repository-aware agent workflows.
- Quy ước: [API](stable/conventions/api-rules.md), [validation](stable/conventions/validation-rules.md), [coding](stable/conventions/coding-rules.md), [UI URL state](stable/conventions/ui-url-state.md), [security](stable/conventions/security-rules.md), [review checkpoints](stable/conventions/review-checkpoints.md)
- Vận hành: [Docker runbook](stable/operations/docker-runbook.md), [server deploy](stable/operations/server-deploy.md), [backup và restore](stable/operations/backup-restore.md), [incident runbook](stable/operations/incident-runbook.md)

Quy tắc cập nhật: yêu cầu mới có mã trong SRS trước khi code; mọi API mới trỏ tới ít nhất một mã yêu cầu; tài liệu kỹ thuật viết bằng tiếng Việt, mã và commit bằng tiếng Anh.
