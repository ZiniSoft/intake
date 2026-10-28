"""Whether a request is ready for an agent: a plain score with its reasons, on the request, in the list, over MCP (FR-MCP-04)."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from pathlib import Path

from app.models import IntakeItem, Project, ProjectContextSnapshot
from app.modules.intake.readiness import agent_readiness
from tests.test_intake_reopen import _approved

cto = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"
SAMPLE = Path(__file__).resolve().parents[1] / "docs" / "agent" / "CONTEXT.md"


def test_the_score_rewards_what_an_agent_needs_and_names_what_is_missing() -> None:
    bare = agent_readiness(item_type="UNCLEAR", title="x", summary="y", details=None, fix_hints=None, project_context=None)
    assert bare["score"] == 0 and bare["band"] == "HUMAN" and "bước tái hiện" in bare["missing"] and "loại việc chưa rõ" in bare["missing"]

    full = agent_readiness(
        item_type="BUG", title="Counter P0 luôn 0", summary="Trang /intakes đếm sai",
        details={"steps": ["Mở /intakes"], "expected": "Đếm đúng", "acceptance": ["counter = 2"], "where": "/intakes", "open_questions": []},
        fix_hints="Xem _list_summary", project_context={"band": "FULL", "missing": []},
    )
    assert full["score"] == 100 and full["band"] == "READY" and full["missing"] == []

    questions = agent_readiness(
        item_type="BUG", title="a", summary="b",
        details={"steps": ["x"], "expected": "y", "acceptance": ["z"], "open_questions": ["Màn nào?", "Bản nào?", "Ai báo?", "Khi nào?"],
                 "clarifications": [{"question": "Ai báo?", "answer": "Chị Lan"}]},
        fix_hints=None, project_context={"band": "FULL", "missing": []},
    )
    assert questions["score"] == 95 - 30 and any("3 câu hỏi chưa trả lời" in row for row in questions["missing"]), "answered questions do not count against it; the penalty stops at 30"

    hands = agent_readiness(item_type="TASK", title="Quay video hướng dẫn cài đặt", summary="3 video ngắn", details={"steps": ["a"], "expected": "b", "acceptance": ["c"]}, fix_hints=None, project_context={"band": "FULL"})
    assert hands["score"] <= 30 and hands["band"] == "HUMAN" and any("không làm bằng code" in row for row in hands["missing"])

    halfway = agent_readiness(item_type="TASK", title="Thêm bộ lọc", summary="theo ngày", details={"steps": ["a"], "expected": "b"}, fix_hints=None, project_context={"band": "MISSING", "missing": ["4. Chạy, test, triển khai"]})
    assert any("thiếu 4. Chạy" in row for row in halfway["missing"])
    partial = agent_readiness(item_type="TASK", title="Thêm bộ lọc", summary="theo ngày", details={"steps": ["a"], "expected": "b"}, fix_hints=None, project_context={"band": "PARTIAL"})
    assert partial["score"] == halfway["score"] + 10, "a pack that needs work still counts for half"
    assert 40 <= halfway["score"] < 70 and halfway["band"] == "NEEDS_WORK" and "tiêu chí nghiệm thu" in halfway["missing"]


def test_the_request_the_list_and_the_agent_all_see_the_score() -> None:
    request = _approved("GITLAB")
    with get_session() as session:
        item = session.get(IntakeItem, request["id"])
        item.item_type = "BUG"
        item.normalized_details = {"steps": ["Mở màn tạo đơn", "Bấm Lưu hai lần"], "expected": "Một đơn", "acceptance": ["Không có đơn trùng"], "open_questions": []}
        session.commit()
    token = cto.post("/api/v1/auth/tokens", json={"name": "readiness test"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    try:
        shown = cto.get(f"/api/v1/intakes/{request['id']}").json()["data"]["agent_readiness"]
        assert shown["score"] == 75 and shown["band"] == "READY" and any("hồ sơ ngữ cảnh" in row for row in shown["missing"])

        # The project's context pack is full: every request of the project gains the points (FR-CTX-04).
        pasted = cto.put("/api/v1/projects/orbit/context", json={"content": SAMPLE.read_text(encoding="utf-8")})
        assert pasted.status_code == 200 and pasted.json()["data"]["band"] == "FULL", pasted.text
        after = cto.get(f"/api/v1/intakes/{request['id']}").json()["data"]["agent_readiness"]
        assert after["score"] == 95 and not any("hồ sơ ngữ cảnh" in row for row in after["missing"])
        listed = next(row for row in cto.get("/api/v1/intakes?project_id=orbit&limit=50").json()["data"]["items"] if row["id"] == request["id"])
        assert listed["agent_readiness"]["band"] == "READY"

        answer = agent.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_intake", "arguments": {"ref": request["public_id"]}}}).json()["result"]["structuredContent"]
        assert answer["agent_readiness"]["score"] == 95
        only_ready = agent.post(MCP, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_intakes", "arguments": {"project": "orbit", "readiness": "READY", "limit": 50}}}).json()["result"]["structuredContent"]["items"]
        assert all(row["agent_readiness"]["band"] == "READY" for row in only_ready) and any(row["id"] == request["id"] for row in only_ready)
        bad = agent.post(MCP, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_intakes", "arguments": {"readiness": "MAYBE"}}}).json()["result"]
        assert bad["isError"]
    finally:
        cto.delete(f"/api/v1/auth/tokens/{token['id']}")
        with get_session() as session:
            project = session.scalar(select(Project).where(Project.code == "orbit"))
            for snapshot in session.scalars(select(ProjectContextSnapshot).where(ProjectContextSnapshot.project_id == project.id)).all():
                session.delete(snapshot)
            from app.models import ExternalLink
            for link in session.scalars(select(ExternalLink).where(ExternalLink.intake_id == request["id"])).all():
                link.target_system = "PLANE"
            project = session.scalar(select(Project).where(Project.code == "orbit"))
            project.project_settings = {k: v for k, v in (project.project_settings or {}).items() if k != "agent_ready"}
            session.commit()
