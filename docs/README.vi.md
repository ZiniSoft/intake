[English](README.md) | Tiếng Việt

# Intake - Bản đồ tài liệu

Tài liệu đang áp dụng nằm trong `stable/`.

- [BRD](stable/BRD.vi.md): mục tiêu và phạm vi kinh doanh.
- [SRS](stable/SRS.vi.md): yêu cầu có mã truy vết (FR-*, NFR-*). Các mã `ADR-nnnn` trong tài liệu trỏ tới bản ghi quyết định kiến trúc của dự án, chưa được công bố trong repo này.
- [Functional spec](stable/functional-spec.vi.md), [Interface contracts](stable/interface-contracts.vi.md), [Data model](stable/data-model.vi.md), [Flows](stable/flows.vi.md)
- [Daily report format](stable/daily-report-format.vi.md), [MCP agents](stable/mcp-agents.vi.md), [Watch flow](stable/watch-flow.vi.md), [Publish flow](stable/publish-flow.vi.md)
- [Test and acceptance](stable/test-and-acceptance.vi.md)
- [Fictional Nova agent context](agent/CONTEXT.md): a safe public example for repository-aware agent workflows.
- Quy ước: [API](stable/conventions/api-rules.vi.md), [validation](stable/conventions/validation-rules.vi.md), [coding](stable/conventions/coding-rules.vi.md), [UI URL state](stable/conventions/ui-url-state.vi.md), [security](stable/conventions/security-rules.vi.md), [review checkpoints](stable/conventions/review-checkpoints.vi.md)
- Vận hành: [Docker runbook](stable/operations/docker-runbook.vi.md), [server deploy](stable/operations/server-deploy.vi.md), [backup và restore](stable/operations/backup-restore.vi.md), [incident runbook](stable/operations/incident-runbook.vi.md)

Quy tắc cập nhật: yêu cầu mới có mã trong SRS trước khi code; mọi API mới trỏ tới ít nhất một mã yêu cầu; tài liệu song ngữ (`X.md` tiếng Anh mặc định, `X.vi.md` tiếng Việt; sửa cả hai bản), mã và commit bằng tiếng Anh.
