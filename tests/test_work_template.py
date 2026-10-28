"""A pipeline on the board (FR-WRK-08..09, ADR-0066): the VIDEO template makes six steps, the last two close only with a
link or a reason, a step sent back from acceptance says why in the discussion, and the parent follows its steps."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, AuditEvent, WorkComment, WorkItem, WorkLink

cto = TestClient(app, headers={"X-User-Subject": "cto"})
MCP = "/api/v1/mcp-server"


def _cleanup(parent_ids: list[str], token_ids: list[str] | None = None) -> None:
    with get_session() as session:
        ids = set(parent_ids)
        for parent in parent_ids:
            ids |= {str(row.id) for row in session.scalars(select(WorkItem).where(WorkItem.parent_id == parent)).all()}
        for work_id in ids:
            for model in (WorkComment, WorkLink):
                for row in session.scalars(select(model).where(model.work_id == work_id)).all():
                    session.delete(row)
            for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id)).all():
                session.delete(row)
        session.flush()
        for work_id in ids:
            row = session.get(WorkItem, work_id)
            if row is not None and row.parent_id:
                session.delete(row)
        session.flush()
        for work_id in ids:
            row = session.get(WorkItem, work_id)
            if row is not None:
                session.delete(row)
        for token_id in token_ids or []:
            row = session.get(ApiToken, token_id)
            if row is not None:
                session.delete(row)
        session.commit()


def _move(work: dict, status: str, note: str | None = None):
    current = cto.get(f"/api/v1/work/{work['id']}").json()["data"]
    return cto.post(f"/api/v1/work/{work['id']}/move", json={"status": status, "expected_version": current["version"], "note": note})


def test_a_video_follows_six_steps_and_closes_only_with_evidence_or_a_reason() -> None:
    made = cto.post("/api/v1/work", json={"project": "orbit", "title": "Video giới thiệu bản 5.0", "priority": "P2", "status": "READY", "template": "VIDEO"})
    assert made.status_code == 201, made.text
    parent = made.json()["data"]
    try:
        assert parent["template"] == "VIDEO" and parent["steps_total"] == 6 and parent["steps_done"] == 0
        detail = cto.get(f"/api/v1/work/{parent['id']}").json()["data"]
        steps = detail["steps"]
        assert [s["step"] for s in steps] == ["BRIEF", "SCRIPT", "SHOOT", "EDIT", "REVIEW", "PUBLISH"]
        assert [s["step_label"] for s in steps] == ["Brief", "Kịch bản", "Quay", "Dựng", "Duyệt", "Đăng"]
        assert [s["evidence_required"] for s in steps] == [False] * 4 + [True, True] and all(s["status"] == "READY" and s["parent_code"] == parent["code"] for s in steps)
        assert steps[0]["title"] == "Video giới thiệu bản 5.0 · Brief" and steps[0]["code"] != parent["code"]
        board = cto.get("/api/v1/work", params={"project": "orbit"}).json()["data"]
        assert sum(1 for row in board if row.get("parent_id") == parent["id"]) == 6, "the steps come with the board"
        assert "STEPS_OPEN" in _move(parent, "DONE").text, "a parent does not close over open steps"

        # The parent follows: doing when a step is doing.
        assert _move(steps[0], "IN_PROGRESS").status_code == 200
        assert cto.get(f"/api/v1/work/{parent['id']}").json()["data"]["status"] == "IN_PROGRESS"
        for step in steps[:4]:
            assert _move(step, "DONE").status_code == 200, step["step"]
        assert cto.get(f"/api/v1/work/{parent['id']}").json()["data"]["steps_done"] == 4

        # Duyệt: no link, no reason: refused; a reason closes it and is remembered as missing evidence.
        refused = _move(steps[4], "DONE")
        assert refused.status_code == 422 and "EVIDENCE_REQUIRED" in refused.text
        assert _move(steps[4], "ACCEPTANCE").status_code == 200
        back = _move(steps[4], "IN_PROGRESS")
        assert back.status_code == 422 and "NOTE_REQUIRED" in back.text, "sending a step back needs a word"
        assert _move(steps[4], "IN_PROGRESS", "Thiếu phụ đề ở cảnh 2").status_code == 200
        review = cto.get(f"/api/v1/work/{steps[4]['id']}").json()["data"]
        assert review["comments"][-1]["body"] == "Trả lại: Thiếu phụ đề ở cảnh 2" and review["history"][0]["details"]["sent_back"] is True
        assert _move(steps[4], "DONE", "Khách duyệt qua Zalo, không có link").status_code == 200
        with get_session() as session:
            closed = session.scalar(select(AuditEvent).where(AuditEvent.entity_id == steps[4]["id"], AuditEvent.event_type == "work.moved").order_by(AuditEvent.created_at.desc()))
            assert closed.details["evidence_missing"] is True and closed.details["to"] == "DONE"

        # Đăng: a link is the evidence.
        assert cto.post(f"/api/v1/work/{steps[5]['id']}/links", json={"url": "https://www.facebook.com/acme/posts/test-123", "note": "Bài đã đăng"}).status_code == 201
        assert _move(steps[5], "DONE").status_code == 200
        parent_after = cto.get(f"/api/v1/work/{parent['id']}").json()["data"]
        assert parent_after["status"] == "DONE" and parent_after["steps_done"] == 6 and parent_after["closed_note"] == "Mọi bước đã xong"
        assert parent_after["history"][0]["actor_name"] == "hệ thống"

        # Dropping a parent drops its open steps.
        second = cto.post("/api/v1/work", json={"project": "orbit", "title": "Video bị bỏ", "template": "VIDEO"}).json()["data"]
        try:
            assert _move(second, "CANCELLED", "Đổi kế hoạch").status_code == 200
            assert {s["status"] for s in cto.get(f"/api/v1/work/{second['id']}").json()["data"]["steps"]} == {"CANCELLED"}
        finally:
            _cleanup([second["id"]])
    finally:
        _cleanup([parent["id"]])


def test_an_agent_makes_a_video_pipeline_with_its_steps() -> None:
    token = cto.post("/api/v1/auth/tokens", json={"name": "test agent video"}).json()["data"]
    agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
    parent_id = None
    try:
        answer = agent.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "create_work", "arguments": {"project": "orbit", "title": "Video hướng dẫn nghiệm thu", "template": "VIDEO", "status": "READY"}}}).json()
        made = answer["result"]["structuredContent"]
        parent_id = made["id"]
        assert made["template"] == "VIDEO" and [s["label"] for s in made["steps"]] == ["Brief", "Kịch bản", "Quay", "Dựng", "Duyệt", "Đăng"]
        bad = agent.post(MCP, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "create_work", "arguments": {"project": "orbit", "title": "x", "template": "PODCAST"}}}).json()
        assert "ARGUMENT_INVALID" in bad["result"]["content"][0]["text"]
        listed = agent.post(MCP, json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "list_work", "arguments": {"project": "orbit", "status": "READY"}}}).json()["result"]["structuredContent"]
        assert any(row["parent_code"] == made["code"] and row["step"] == "BRIEF" for row in listed["items"])
    finally:
        _cleanup([parent_id] if parent_id else [], token_ids=[token["id"]])
