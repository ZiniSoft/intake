"""The project context pack (FR-CTX-01..03, ADR-0063): split into eight sections, scored by the fixed rule, read
from the repository by the repo-reader (stubbed here), pasted for projects without one, approved by the CTO."""
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import IntakeItem, Project, ProjectContextSnapshot, ProjectContextSuggestion
from app.modules.projects import context as ctx
from app.workers import repo_tasks
from tests.test_intake_reopen import _approved

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
SAMPLE = Path(__file__).resolve().parents[1] / "docs" / "agent" / "CONTEXT.md"
MCP = "/api/v1/mcp-server"


def _clear(project_code: str) -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == project_code))
        for row in session.scalars(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project.id)).all():
            session.delete(row)
        for row in session.scalars(select(ProjectContextSuggestion).where(ProjectContextSuggestion.project_id == project.id)).all():
            session.delete(row)
        session.commit()


def test_the_intake_repo_pack_is_full_and_a_thin_pack_is_missing() -> None:
    parsed = ctx.parse_context(SAMPLE.read_text(encoding="utf-8"))
    assert parsed["meta"]["project"] == "nova" and parsed["meta"]["updated"] == "2026-10-15"
    assert all(section["present"] for section in parsed["sections"].values()), {k: v["present"] for k, v in parsed["sections"].items()}
    scored = ctx.score_context(parsed, date(2026, 10, 20))
    assert scored == {"score": 100, "band": "FULL", "missing": [], "stale": False, "stale_days": 5}
    # Older than 30 days: ten points off, still full when everything is there.
    assert ctx.score_context(parsed, date(2026, 12, 1))["score"] == 90
    thin = ctx.parse_context("---\nproject: x\nupdated: 2026-10-15\n---\n\n## 1. Sản phẩm\n- a\n- b\n- c\n\n## 4. Chạy\n- chưa có\n\n## 2. Bản đồ\n- `src/a`: màn A\n- `src/b`: màn B\n- từ: nghĩa\n")
    scored = ctx.score_context(thin, date(2026, 10, 16))
    assert scored["band"] == "MISSING" and scored["score"] == 8 + 14
    assert scored["missing"] == ["3. Môi trường và truy cập", "4. Chạy, test, triển khai", "6. Định nghĩa xong và bằng chứng", "7. Dữ liệu nhạy cảm", "8. Người quyết và điểm nóng"]
    # Section 4 needs a command in backticks, not prose.
    prose = ctx.parse_context("## 4. Chạy\n- chạy bằng docker\n- test bằng pytest\n- deploy bằng script\n")
    assert prose["sections"]["run_test_deploy"]["present"] is False
    typed = ctx.parse_context("## 4. Chạy\n- `docker compose up`\n- `pytest -q`\n- deploy: `bash scripts/deploy.sh`\n")
    assert typed["sections"]["run_test_deploy"]["present"] is True


def test_pasting_reading_and_approving_a_pack(monkeypatch) -> None:
    _clear("orbit")
    try:
        empty = cto.get("/api/v1/projects/orbit/context")
        assert empty.status_code == 200, empty.text
        assert empty.json()["data"]["band"] == "MISSING" and empty.json()["data"]["has_content"] is False and len(empty.json()["data"]["missing"]) == 6
        # Pasted by the CTO: scored like a read one; not approved yet.
        pasted = cto.put("/api/v1/projects/orbit/context", json={"content": SAMPLE.read_text(encoding="utf-8")})
        assert pasted.status_code == 200, pasted.text
        data = pasted.json()["data"]
        assert data["source"] == "PASTED" and data["band"] in ("FULL", "PARTIAL") and data["approved"] is False and data["sections"]["modules"]["present"] is True
        assert owner.get("/api/v1/projects/orbit/context").status_code == 404, "not their project"
        assert owner.post("/api/v1/projects/orbit/context/approve").status_code in (403, 404)
        approved = cto.post("/api/v1/projects/orbit/context/approve")
        assert approved.status_code == 200 and approved.json()["data"]["approved"] is True
        # The repo-reader brings a new version: the approval no longer matches, sections 1 and 2 go to the AI prompt.
        async def fake_read(repo, path):
            assert path == "docs/agent/CONTEXT.md"
            return "---\nproject: orbit\nupdated: 2026-10-15\n---\n## 1. Sản phẩm\n- bot\n- chat\n- khách\n## 2. Bản đồ\n- `app/`: lõi\n- `web/`: giao diện\n- Orbit = bot\n## 3. Môi trường\n- local\n- staging\n- prod\n## 4. Chạy\n- `make test`\n- `make run`\n- `make deploy`\n## 6. Xong\n- test\n- MR\n- CTO\n## 7. Nhạy cảm\n- a\n- b\n- c\n## 8. Người\n- PO\n- dev\n- nợ\n", "abc123"
        monkeypatch.setattr(repo_tasks, "read_context_file", fake_read)
        monkeypatch.setattr(ctx.project_context_service, "main_repo", lambda project_id: {"system": "GITLAB", "target": "2026/orbit", "token_ref": ""})
        with get_session() as session:
            project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
        result = repo_tasks.read_project_context(project_id)
        assert result["sha"] == "abc123" and result["band"] == "FULL" and result["score"] == 92, result
        shown = cto.get("/api/v1/projects/orbit/context").json()["data"]
        assert shown["source"] == "REPO" and shown["sha"] == "abc123" and shown["approved"] is False and shown["approved_sha"] is not None
        prompt_part = ctx.project_context_service.sections_for_ai(project_id)
        assert "Orbit = bot" in prompt_part and "make deploy" not in prompt_part, "sections 3 to 8 never leave"
        # A read that fails keeps the last pack and shows the error.
        async def broken(repo, path):
            raise repo_tasks.RepoReadError("CONTEXT_FILE_MISSING")
        monkeypatch.setattr(repo_tasks, "read_context_file", broken)
        failed = repo_tasks.read_project_context(project_id)
        assert failed["error"] == "CONTEXT_FILE_MISSING"
        after = cto.get("/api/v1/projects/orbit/context").json()["data"]
        assert after["error"] == "CONTEXT_FILE_MISSING" and after["sha"] == "abc123" and after["has_content"] is True
        # Asking for a read without a broker says so instead of failing.
        queued = cto.post("/api/v1/projects/orbit/context/read")
        assert queued.status_code == 202 and queued.json()["data"]["queued"] in (True, False)
    finally:
        _clear("orbit")


def test_the_agent_reads_the_pack_leaves_suggestions_and_the_cto_decides() -> None:
    """FR-CTX-04: get_project_context says stop or go; log_work carries what the pack lacked; the CTO decides on the
    project page; the request's readiness and the morning board count the band."""
    _clear("orbit")
    token = cto.post("/api/v1/auth/tokens", json={"name": "context pack test"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    request = None

    def call(name, arguments, id=1):
        return agent.post(MCP, json={"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).json()["result"]

    try:
        empty = call("get_project_context", {"project": "orbit"})["structuredContent"]
        assert empty["band"] == "MISSING" and len(empty["missing"]) == 6 and empty["content"] is None and "dừng" in empty["note"]
        assert next(row for row in call("list_projects", {})["structuredContent"]["projects"] if row["code"] == "orbit")["context_band"] == "MISSING"
        assert cto.put("/api/v1/projects/orbit/context", json={"content": SAMPLE.read_text(encoding="utf-8")}).status_code == 200
        full = call("get_project_context", {"project": "orbit"}, 2)["structuredContent"]
        assert full["band"] == "FULL" and full["approved"] is False and "## 4." in full["content"] and full["sections"]["run_test_deploy"]["present"] is True
        # The board shows the band next to the review readiness.
        board = cto.get(f"/api/v1/planning/overview/{date.today().isoformat()}").json()["data"]
        assert next(row for row in board["projects"] if row["code"] == "orbit")["context"]["band"] == "FULL"
        # Working on a request, the agent says what the pack lacked; it lands with the CTO, not in the repo.
        request = _approved("GITLAB")
        logged = call("log_work", {"ref": request["public_id"], "summary": "Sửa xong bộ đếm P0", "agent": "claude-code",
                                   "context_suggestions": ["Mục 4 thiếu lệnh chạy e2e", "Mục 8: ai quyết về Telegram bot"]}, 3)
        assert not logged.get("isError"), logged
        assert logged["structuredContent"]["context_suggestions"] == 2
        rows = cto.get("/api/v1/projects/orbit/context/suggestions").json()["data"]
        assert sorted(row["text"] for row in rows) == ["Mục 4 thiếu lệnh chạy e2e", "Mục 8: ai quyết về Telegram bot"]
        assert all(row["status"] == "PENDING" and row["agent_name"] == "claude-code" and row["intake_public_id"] == request["public_id"] for row in rows)
        assert cto.get("/api/v1/projects/orbit/context").json()["data"]["pending_suggestions"] == 2
        entry = cto.get(f"/api/v1/intakes/{request['id']}/work-log").json()["data"][0]
        assert entry["details"]["context_suggestions"] == ["Mục 4 thiếu lệnh chạy e2e", "Mục 8: ai quyết về Telegram bot"]
        assert owner.post(f"/api/v1/projects/orbit/context/suggestions/{rows[0]['id']}/applied").status_code in (403, 404)
        applied = cto.post(f"/api/v1/projects/orbit/context/suggestions/{rows[0]['id']}/applied")
        assert applied.status_code == 200 and applied.json()["data"]["status"] == "APPLIED" and applied.json()["data"]["decided_by_name"]
        assert cto.post(f"/api/v1/projects/orbit/context/suggestions/{rows[1]['id']}/dismissed").json()["data"]["status"] == "DISMISSED"
        assert cto.post(f"/api/v1/projects/orbit/context/suggestions/{rows[1]['id']}/applied").status_code == 409
        assert cto.post(f"/api/v1/projects/orbit/context/suggestions/{rows[1]['id']}/maybe").status_code == 422
        assert cto.get("/api/v1/projects/orbit/context").json()["data"]["pending_suggestions"] == 0
    finally:
        cto.delete(f"/api/v1/auth/tokens/{token['id']}")
        _clear("orbit")
        if request is not None:
            with get_session() as session:
                from app.models import ExternalLink, IntakeWorkLog
                for row in session.scalars(select(IntakeWorkLog).where(IntakeWorkLog.intake_id == request["id"])).all():
                    session.delete(row)
                for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == request["id"])).all():
                    link.target_system = "PLANE"
                session.commit()
