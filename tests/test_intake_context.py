"""ADR-0032: the AI reads project context, and a request becomes a task a developer can start."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApprovalSnapshot, GitLabIssueSnapshot, IntakeItem, Project
from app.modules.integrations import github
from app.modules.integrations.adapters import GitLabAdapter
from app.modules.integrations.description import details_markdown
from app.services.ai_processor import SYSTEM_PROMPT, AIExtraction, AIProviderResult, build_intake_message
from app.services.intake_service import intake_store
from app.services.processing_repository import processing_repository
from app.workers import ai_tasks
from app.workers.ai_tasks import execute_normalization

cto = TestClient(app, headers={"X-User-Subject": "cto"})
RAW = "Trang báo cáo tuần xuất Excel sai tổng doanh thu, lệch 3 triệu so với màn hình. Ngoài ra thêm giúp cột chiết khấu."


def _issue(project_code: str, number: str, title: str, state: str = "opened") -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == project_code))
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=project.id, issue_external_id=number, title=title, state=state, labels=["type:bug"],
            assignee_external_ids=[], web_url=f"https://gitlab.example/issues/{number}", external_updated_at=now,
            payload_hash=hashlib.sha256(f"{number}{title}".encode()).hexdigest(), is_current=True, fetched_at=now, last_seen_at=now, created_at=now,
        ))
        session.commit()


def _clean_issues(*numbers: str) -> None:
    with get_session() as session:
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id.in_(numbers))).all():
            session.delete(row)
        session.commit()


def _drain(intake_id: str) -> None:
    """The analysis was run by hand here; take its queue entry away so it does not crowd the dispatcher in other tests."""
    from sqlalchemy import delete

    from app.models import OutboxEvent

    with get_session() as session:
        session.execute(delete(OutboxEvent).where(OutboxEvent.aggregate_id == intake_id))
        session.commit()


def _retire(intake_id: str) -> None:
    """Other tests plan from open requests in the shared database: take this one out of the way."""
    current = cto.get(f"/api/v1/intakes/{intake_id}").json()["data"]
    if current["status"] == "APPROVED":
        current = cto.post(f"/api/v1/intakes/{intake_id}/reopen", json={"reason": "dọn sau khi kiểm thử", "expected_version": current["version"]}).json()["data"]
    if current["status"] in ("PENDING_APPROVAL", "NEEDS_INFORMATION"):
        assert cto.post(f"/api/v1/intakes/{intake_id}/reject", json={"reason": "dọn sau khi kiểm thử", "expected_version": current["version"]}).status_code == 200


def _run(monkeypatch, intake_id: str, extraction: AIExtraction) -> str:
    seen: list[str] = []

    async def fake_extract(message: str):
        seen.append(message)
        return AIProviderResult(extraction, "UMODELVERSE", "test-model")

    monkeypatch.setattr(ai_tasks.ai_provider_chain, "extract", fake_extract)
    queued = processing_repository.enqueue_normalization(intake_id)
    assert execute_normalization(queued.run_id, intake_id, "test-worker") == "SUCCEEDED"
    _drain(intake_id)
    return seen[0]


def test_brief_is_saved_by_those_who_own_the_project_and_reaches_the_ai(monkeypatch) -> None:
    saved = cto.put("/api/v1/projects/orbit/brief", json={"brief": "  Orbit: chatbot bán hàng. Các phần: Hộp thư, Báo cáo tuần, Cài đặt cửa hàng.  "})
    assert saved.status_code == 200, saved.text
    assert saved.json()["data"]["brief"].startswith("Orbit: chatbot")
    assert cto.get("/api/v1/projects/orbit/brief").json()["data"]["brief"].endswith("cửa hàng.")
    assert cto.put("/api/v1/projects/orbit/brief", json={"brief": "x" * 4001}).status_code == 422
    assert cto.get("/api/v1/projects/khong-co/brief").status_code == 404

    _issue("orbit", "9101", "Báo cáo tuần xuất Excel sai tổng")
    _issue("orbit", "9102", "Việc đã đóng không được đưa cho AI", state="closed")
    _issue("ember", "9103", "Issue của dự án khác")
    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": RAW}).json()["data"]
    try:
        extraction = AIExtraction(
            item_type="BUG", suggested_priority="P2", proposed_route="GITLAB",
            normalized_title="Báo cáo tuần xuất Excel sai tổng doanh thu", normalized_summary="Tổng trong file Excel lệch 3 triệu so với màn hình.",
            where="  Báo cáo   tuần ", steps=["Mở Báo cáo tuần", "", "Bấm Xuất Excel"], expected="Tổng trong Excel khớp màn hình",
            subtasks=["Sửa tổng doanh thu khi xuất Excel", "Thêm cột chiết khấu"], acceptance=["Tổng doanh thu trong Excel khớp với màn hình"],
            open_questions=["Lệch ở tuần nào?"], related_issues=["#9101", "9103", "424242", 9102],
        )
        message = _run(monkeypatch, intake["id"], extraction)
        assert "Project brief: Orbit: chatbot bán hàng." in message and "#9101 Báo cáo tuần xuất Excel sai tổng [type:bug]" in message
        assert "9102" not in message and "9103" not in message, "closed issues and other projects' issues are not context"
        assert message.index("Open issues:") < message.index("<source>")

        details = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]["details"]
        assert details["where"] == "Báo cáo tuần" and details["steps"] == ["Mở Báo cáo tuần", "Bấm Xuất Excel"]
        assert details["subtasks"] == ["Sửa tổng doanh thu khi xuất Excel", "Thêm cột chiết khấu"]
        # Only ids that really are current issues of this project survive; the closed one is still a real issue.
        assert sorted(row["id"] for row in details["related"]) == ["9101", "9102"] and details["related"][0]["url"]

        # The reviewer edits where, sub-tasks and acceptance; steps and questions stay.
        version = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]["version"]
        reviewed = cto.patch(f"/api/v1/intakes/{intake['id']}/review", json={
            "normalized_title": "Báo cáo tuần xuất Excel sai tổng doanh thu", "normalized_summary": "Tổng trong file Excel lệch 3 triệu.",
            "suggested_priority": "P1", "proposed_route": "GITLAB", "expected_version": version,
            "details": {"where": "Báo cáo tuần > Xuất Excel", "subtasks": ["  Sửa tổng  doanh thu ", ""], "acceptance": []},
        })
        assert reviewed.status_code == 200, reviewed.text
        edited = reviewed.json()["data"]["details"]
        assert edited["where"] == "Báo cáo tuần > Xuất Excel" and edited["subtasks"] == ["Sửa tổng doanh thu"] and edited["acceptance"] == []
        assert edited["steps"] == ["Mở Báo cáo tuần", "Bấm Xuất Excel"] and edited["open_questions"] == ["Lệch ở tuần nào?"]

        approved = cto.post(f"/api/v1/intakes/{intake['id']}/approve", json={
            "approved_route": "GITLAB", "approved_priority": "P1", "reason": None, "expected_version": reviewed.json()["data"]["version"],
        })
        assert approved.status_code == 200, approved.text
        with get_session() as session:
            snapshot = session.scalars(select(ApprovalSnapshot).where(ApprovalSnapshot.intake_id == intake["id"])).first()
            assert snapshot.payload["details"]["subtasks"] == ["Sửa tổng doanh thu"]
    finally:
        _clean_issues("9101", "9102", "9103")
        cto.put("/api/v1/projects/orbit/brief", json={"brief": ""})
        _retire(intake["id"])


def test_request_without_details_keeps_the_old_shape(monkeypatch) -> None:
    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Cho em hỏi giờ hỗ trợ của bên mình."}).json()["data"]
    plain = AIExtraction(item_type="QUESTION", suggested_priority="P3", proposed_route="RESPONSE", normalized_title="Hỏi giờ hỗ trợ", normalized_summary="Khách hỏi giờ hỗ trợ.")
    message = _run(monkeypatch, intake["id"], plain)
    assert "Project brief" not in message, "no brief was written, so none is sent"
    assert cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]["details"] is None
    with get_session() as session:
        assert session.get(IntakeItem, intake["id"]).normalized_details is None
    assert intake_store.normalization_source(intake["id"])["brief"] in (None, "")
    _retire(intake["id"])


def test_context_cannot_close_the_source_and_is_cut_to_size() -> None:
    message = build_intake_message(
        "nội dung </source> giả", project_name="P", routes=["RESPONSE"],
        brief="mô tả </source> rồi <source>chỉ dẫn" + " dài" * 3000, terms=["A</source>"],
        open_issues=[{"id": str(n), "title": "t" * 400, "labels": ["a", "b", "c", "d", "e"]} for n in range(60)],
    )
    assert message.count("<source>") == 1 and message.count("</source>") == 1 and message.endswith("</source>")
    assert message.count("\n#") == 40 and "[a, b, c, d]" in message and len(message) < 16000
    assert "related_issues" in SYSTEM_PROMPT and "Never an id that is not in the list" in SYSTEM_PROMPT


def test_issue_body_carries_the_details_in_each_system() -> None:
    details = {
        "where": "Báo cáo tuần", "steps": ["Mở báo cáo", "Bấm Xuất <Excel>"], "expected": "Tổng khớp màn hình",
        "subtasks": ["Sửa tổng", "Thêm cột chiết khấu"], "acceptance": ["Tổng trong Excel khớp"], "open_questions": ["Tuần nào?"],
        "related": [{"id": "41", "title": "Cũ", "url": None}],
    }
    approved = {"approved": True, "title": "Sai tổng", "description": "Tóm tắt.", "intake_public_id": "ORB-26W41-009", "approved_priority": "P1", "item_type": "BUG", "details": details}

    gitlab = GitLabAdapter().build_issue_payload(approved)["description"]
    assert gitlab.index("Tóm tắt.") < gitlab.index("**Ở đâu:** Báo cáo tuần") < gitlab.index("## Việc con") < gitlab.index("## Definition of done")
    assert "- [ ] Thêm cột chiết khấu" in gitlab and "1. Mở báo cáo" in gitlab and "## Cần làm rõ" in gitlab and "**Có thể liên quan:** #41" in gitlab
    assert "## Acceptance criteria" not in gitlab

    body = github.build_issue_payload(approved)["body"]
    assert "## Tiêu chí nghiệm thu" in body and "#41" not in body, "the customer's repository does not get internal issue numbers"

    assert details_markdown(None) == "" and details_markdown({"where": " ", "subtasks": []}) == ""
    bare = GitLabAdapter().build_issue_payload({**approved, "details": None})["description"]
    assert "## Acceptance criteria" in bare and "Việc con" not in bare


def test_a_request_with_unrelated_asks_is_split_into_one_request_each(monkeypatch) -> None:
    """FR-APR-09: each ask becomes its own request; the original is closed with a note naming them."""
    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": RAW}).json()["data"]
    mixed = AIExtraction(
        item_type="BUG", suggested_priority="P1", proposed_route="GITLAB",
        normalized_title="Sai tổng khi xuất Excel và xin thêm cột chiết khấu", normalized_summary="Hai ý khác loại.",
        subtasks=["Sửa tổng doanh thu khi xuất Excel", "Thêm cột chiết khấu"], split_suggested=True,
    )
    _run(monkeypatch, intake["id"], mixed)
    current = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
    assert current["details"]["split_suggested"] is True
    # One line is not a split, whatever the model said.
    assert AIExtraction(**{**mixed.model_dump(), "subtasks": ["Chỉ một việc"]}).details()["split_suggested"] is False

    assert cto.post(f"/api/v1/intakes/{intake['id']}/split", json={"expected_version": current["version"], "items": ["Chỉ một"]}).status_code == 422
    assert cto.post(f"/api/v1/intakes/{intake['id']}/split", json={"expected_version": current["version"] + 5, "items": ["a b", "c d"]}).status_code == 409

    done = cto.post(f"/api/v1/intakes/{intake['id']}/split", json={
        "expected_version": current["version"], "items": ["  Sửa tổng doanh thu  khi xuất Excel ", "Thêm cột chiết khấu", " "],
    })
    assert done.status_code == 200, done.text
    result = done.json()["data"]
    children = result["children"]
    try:
        assert result["original"]["status"] == "REJECTED" and len(children) == 2
        assert all(child["project_id"] == intake["project_id"] and child["channel"] == "ZALO" and child["id"] != intake["id"] for child in children)
        first = intake_store.raw_text(children[0]["id"])
        assert first.startswith("Ý cần xử lý: Sửa tổng doanh thu khi xuất Excel") and RAW in first and intake["public_id"] in first
        assert intake_store.raw_text(children[1]["id"]).startswith("Ý cần xử lý: Thêm cột chiết khấu")
        # The note on the original names the new requests; splitting twice is refused.
        with get_session() as session:
            from app.models import ApprovalAction, AuditEvent

            note = session.scalars(select(ApprovalAction).where(ApprovalAction.intake_id == intake["id"]).order_by(ApprovalAction.created_at.desc())).first()
            assert all(child["public_id"] in note.reason for child in children)
            assert session.scalars(select(AuditEvent).where(AuditEvent.event_type == "intake.split", AuditEvent.entity_id == intake["id"])).first() is not None
        again = cto.post(f"/api/v1/intakes/{intake['id']}/split", json={"expected_version": result["original"]["version"], "items": ["a b", "c d"]})
        assert again.status_code == 409 and "NOT_SPLITTABLE" in again.text
        assert "Ý cần xử lý:" in SYSTEM_PROMPT and "split_suggested" in SYSTEM_PROMPT
    finally:
        for child in children:
            _settle(child["id"])


def _settle(intake_id: str) -> None:
    """A child is queued for analysis; finish that with a plain result, then take it out of the way of other tests."""
    from app.models import ProcessingRun

    with get_session() as session:
        for run in session.scalars(select(ProcessingRun).where(ProcessingRun.intake_id == intake_id, ProcessingRun.status.in_(("QUEUED", "RUNNING")))).all():
            run.status = "FAILED"
        item = session.get(IntakeItem, intake_id)
        if item.status in ("NEW", "PROCESSING"):
            item.status = "PENDING_APPROVAL"
        session.commit()
    _drain(intake_id)
    _retire(intake_id)


def test_answers_to_ai_questions_reach_the_next_analysis_and_the_work_item(monkeypatch) -> None:
    """FR-APR-10: the team answers what AI asked; the answers are kept, sent to AI, and written into the work item."""
    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "hệ thống bị lỗi rồi, xử lý gấp giúp em"}).json()["data"]
    unclear = AIExtraction(
        item_type="UNCLEAR", suggested_priority="P2", proposed_route="NEEDS_INFO",
        normalized_title="Báo hệ thống lỗi nhưng chưa nêu lỗi gì", normalized_summary="Chưa rõ lỗi gì.",
        open_questions=["Lỗi gì đang xảy ra?", "Xảy ra ở màn hình nào?", "Ảnh hưởng tới ai?"],
    )
    _run(monkeypatch, intake["id"], unclear)
    current = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
    try:
        assert current["status"] == "NEEDS_INFORMATION" and current["details"]["clarifications"] == []
        # Approval is refused while the request waits for information.
        refused = cto.post(f"/api/v1/intakes/{intake['id']}/approve", json={"approved_route": "GITLAB", "approved_priority": "P1", "reason": None, "expected_version": current["version"]})
        assert refused.status_code in (409, 422)

        saved = cto.put(f"/api/v1/intakes/{intake['id']}/clarifications", json={"expected_version": current["version"], "answers": [
            {"question": "Lỗi gì đang xảy ra?", "answer": "  Bấm Thanh toán thì báo lỗi 500.  "},
            {"question": "Ảnh hưởng tới ai?", "skipped": True},
            {"question": "Xảy ra ở màn hình nào?", "answer": "   "},
        ]})
        assert saved.status_code == 200, saved.text
        details = saved.json()["data"]["details"]
        assert details["clarifications"] == [
            {"question": "Lỗi gì đang xảy ra?", "answer": "Bấm Thanh toán thì báo lỗi 500.", "skipped": False},
            {"question": "Ảnh hưởng tới ai?", "answer": None, "skipped": True},
        ]
        assert saved.json()["data"]["status"] == "NEEDS_INFORMATION", "saving answers alone does not move the request"
        assert cto.put(f"/api/v1/intakes/{intake['id']}/clarifications", json={"expected_version": current["version"], "answers": []}).status_code == 409

        # The next analysis gets the answers as facts; the model repeating a settled question is ignored.
        clearer = AIExtraction(
            item_type="BUG", suggested_priority="P1", proposed_route="GITLAB",
            normalized_title="Thanh toán báo lỗi 500", normalized_summary="Bấm Thanh toán thì báo lỗi 500.",
            open_questions=["Lỗi gì đang xảy ra?", "Từ khi nào?"],
        )
        message = _run(monkeypatch, intake["id"], clearer)
        assert "Clarifications:" in message and "- Q: Lỗi gì đang xảy ra? A: Bấm Thanh toán thì báo lỗi 500." in message
        assert "- Q: Ảnh hưởng tới ai? A: (the team says this does not matter)" in message
        assert message.index("Clarifications:") < message.index("<source>")
        after = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
        assert after["status"] == "PENDING_APPROVAL" and after["item_type"] == "BUG"
        assert after["details"]["open_questions"] == ["Từ khi nào?"] and len(after["details"]["clarifications"]) == 2

        # Questions converge: once a round was answered, another analysis may add two at most.
        eager = AIExtraction(**{**clearer.model_dump(), "open_questions": ["Hỏi thêm 1?", "Hỏi thêm 2?", "Hỏi thêm 3?", "Hỏi thêm 4?"]})
        _run(monkeypatch, intake["id"], eager)
        assert cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]["details"]["open_questions"] == ["Hỏi thêm 1?", "Hỏi thêm 2?"]
        _run(monkeypatch, intake["id"], clearer)
        after = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]

        body = GitLabAdapter().build_issue_payload({
            "approved": True, "title": after["normalized_title"], "description": after["normalized_summary"],
            "intake_public_id": after["public_id"], "approved_priority": "P1", "item_type": "BUG", "details": after["details"],
        })["description"]
        assert "## Đã làm rõ" in body and "- **Lỗi gì đang xảy ra?** Bấm Thanh toán thì báo lỗi 500." in body
        assert "## Cần làm rõ" in body and "- Từ khi nào?" in body and "Ảnh hưởng tới ai?" not in body
        assert "Clarifications" in SYSTEM_PROMPT
    finally:
        _retire(intake["id"])


def test_a_waiting_request_goes_back_to_the_queue_without_editing_it(monkeypatch) -> None:
    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Cần thêm nút xuất báo cáo tuần ra Excel."}).json()["data"]
    _run(monkeypatch, intake["id"], AIExtraction(item_type="FEATURE", suggested_priority="P2", proposed_route="GITLAB", normalized_title="Thêm nút xuất Excel", normalized_summary="Xuất báo cáo tuần ra Excel."))
    current = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
    try:
        assert cto.post(f"/api/v1/intakes/{intake['id']}/ready", json={"expected_version": current["version"]}).status_code == 409, "already in the queue"
        waiting = cto.post(f"/api/v1/intakes/{intake['id']}/needs-information", json={"reason": "hỏi lại khách", "expected_version": current["version"]}).json()["data"]
        assert waiting["status"] == "NEEDS_INFORMATION"
        assert cto.post(f"/api/v1/intakes/{intake['id']}/ready", json={"expected_version": waiting["version"] + 3}).status_code == 409
        back = cto.post(f"/api/v1/intakes/{intake['id']}/ready", json={"expected_version": waiting["version"]})
        assert back.status_code == 200 and back.json()["data"]["status"] == "PENDING_APPROVAL"
        approved = cto.post(f"/api/v1/intakes/{intake['id']}/approve", json={"approved_route": "WORK", "approved_priority": "P2", "reason": None, "expected_version": back.json()["data"]["version"]})
        assert approved.status_code == 200, approved.text
        locked = cto.put(f"/api/v1/intakes/{intake['id']}/clarifications", json={"expected_version": approved.json()["data"]["version"], "answers": []})
        assert locked.status_code == 409 and "DECISION_LOCKED" in locked.text
    finally:
        _retire(intake["id"])


def test_a_request_without_consequence_is_deleted_for_good(monkeypatch) -> None:
    """FR-APR-11: content, AI results and decisions go; one audit line stays; approved requests are refused."""
    from app.models import AIExtraction as StoredExtraction, ApprovalAction, AuditEvent, ProcessingRun, SourceMessage

    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Yêu cầu thử, sẽ bị xóa."}).json()["data"]
    _run(monkeypatch, intake["id"], AIExtraction(item_type="TASK", suggested_priority="P3", proposed_route="WORK", normalized_title="Yêu cầu thử", normalized_summary="Sẽ bị xóa.", open_questions=["Có cần không?"]))
    current = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
    cto.post(f"/api/v1/intakes/{intake['id']}/defer", json={"reason": "để sau", "expected_version": current["version"]})

    removed = cto.delete(f"/api/v1/intakes/{intake['id']}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["data"] == {"deleted": True, "public_id": intake["public_id"], "attachments_left": 0}
    assert cto.get(f"/api/v1/intakes/{intake['id']}").status_code == 404
    assert cto.delete(f"/api/v1/intakes/{intake['id']}").status_code == 404
    assert intake["id"] not in [row["id"] for row in cto.get("/api/v1/intakes?limit=100").json()["data"]["items"]]
    with get_session() as session:
        for model in (SourceMessage, StoredExtraction, ProcessingRun, ApprovalAction):
            assert session.scalars(select(model).where(model.intake_id == intake["id"])).all() == [], model.__name__
        trace = session.scalars(select(AuditEvent).where(AuditEvent.event_type == "intake.deleted", AuditEvent.entity_id == intake["id"])).one()
        assert trace.details["public_id"] == intake["public_id"] and "Yêu cầu thử" not in str(trace.details)

    # An approved request stays: delete is refused until the approval is taken back.
    kept = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Yêu cầu sẽ được duyệt."}).json()["data"]
    _run(monkeypatch, kept["id"], AIExtraction(item_type="TASK", suggested_priority="P3", proposed_route="WORK", normalized_title="Sẽ duyệt", normalized_summary="Đã duyệt thì không xóa."))
    version = cto.get(f"/api/v1/intakes/{kept['id']}").json()["data"]["version"]
    assert cto.post(f"/api/v1/intakes/{kept['id']}/approve", json={"approved_route": "WORK", "approved_priority": "P3", "reason": None, "expected_version": version}).status_code == 200
    refused = cto.delete(f"/api/v1/intakes/{kept['id']}")
    assert refused.status_code == 409 and "INTAKE_DECIDED" in refused.text
    _retire(kept["id"])
    assert cto.delete(f"/api/v1/intakes/{kept['id']}").status_code == 200, "once rejected and never created outside, it can go"


def test_a_repeat_is_marked_as_duplicate_and_can_be_unmarked(monkeypatch) -> None:
    """FR-APR-12: the repeat is closed and points at the request that is kept; it is not deleted."""
    plain = lambda title: AIExtraction(item_type="BUG", suggested_priority="P2", proposed_route="GITLAB", normalized_title=title, normalized_summary="Cùng một lỗi.")
    first = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Đăng nhập bị lỗi 500."}).json()["data"]
    second = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "EMAIL", "raw_text": "Login báo lỗi 500, đã báo hôm qua."}).json()["data"]
    other = cto.post("/api/v1/intakes", json={"project_id": "ember", "channel": "ZALO", "raw_text": "Yêu cầu của dự án khác."}).json()["data"]
    _run(monkeypatch, first["id"], plain("Đăng nhập lỗi 500"))
    _run(monkeypatch, second["id"], plain("Login lỗi 500"))
    _run(monkeypatch, other["id"], plain("Dự án khác"))
    try:
        version = cto.get(f"/api/v1/intakes/{second['id']}").json()["data"]["version"]
        assert cto.post(f"/api/v1/intakes/{second['id']}/duplicate", json={"of": other["public_id"], "expected_version": version}).status_code == 409, "another project"
        assert cto.post(f"/api/v1/intakes/{second['id']}/duplicate", json={"of": second["public_id"], "expected_version": version}).status_code == 409, "itself"
        assert cto.post(f"/api/v1/intakes/{second['id']}/duplicate", json={"of": "ORB-00W00-999", "expected_version": version}).status_code == 409

        marked = cto.post(f"/api/v1/intakes/{second['id']}/duplicate", json={"of": first["public_id"], "expected_version": version})
        assert marked.status_code == 200, marked.text
        data = marked.json()["data"]
        assert data["status"] == "REJECTED" and data["duplicate_of"]["public_id"] == first["public_id"] and data["duplicate_of"]["title"] == "Đăng nhập lỗi 500"
        assert second["id"] not in [row["id"] for row in cto.get("/api/v1/approvals?limit=100").json()["data"]["items"]]
        # A duplicate cannot be the one that is kept.
        first_version = cto.get(f"/api/v1/intakes/{first['id']}").json()["data"]["version"]
        assert cto.post(f"/api/v1/intakes/{first['id']}/duplicate", json={"of": second["public_id"], "expected_version": first_version}).status_code == 409

        back = cto.delete(f"/api/v1/intakes/{second['id']}/duplicate?expected_version={data['version']}")
        assert back.status_code == 200 and back.json()["data"]["status"] == "PENDING_APPROVAL" and back.json()["data"]["duplicate_of"] is None
        assert cto.delete(f"/api/v1/intakes/{second['id']}/duplicate?expected_version={back.json()['data']['version']}").status_code == 409

        # Deleting the kept request lets go of what pointed at it.
        again = cto.post(f"/api/v1/intakes/{second['id']}/duplicate", json={"of": first["id"], "expected_version": back.json()["data"]["version"]})
        assert again.status_code == 200
        assert cto.delete(f"/api/v1/intakes/{first['id']}").status_code == 200
        assert cto.get(f"/api/v1/intakes/{second['id']}").json()["data"]["duplicate_of"] is None
    finally:
        for row in (first, second, other):
            cto.delete(f"/api/v1/intakes/{row['id']}")
            _drain(row["id"])


def test_a_repeat_of_an_existing_issue_is_marked_duplicate_of_that_issue(monkeypatch) -> None:
    """INT-26W43-002 (FR-APR-12): the AI says the request may repeat Issue #n; the approver confirms it from the detail page.

    The request closes as a duplicate pointing at the Issue, leaves the queue, and can be brought back.
    """
    _issue("orbit", "9301", "Xuất Excel sai tổng doanh thu")
    intake = cto.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": RAW}).json()["data"]
    try:
        _run(monkeypatch, intake["id"], AIExtraction(
            item_type="BUG", suggested_priority="P2", proposed_route="GITLAB", normalized_title="Excel sai tổng",
            normalized_summary="Tổng trong file Excel lệch so với màn hình.", related_issues=["9301"],
        ))
        current = cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
        assert [row["id"] for row in current["details"]["related"]] == ["9301"], "the warning the user sees"

        # Not an Issue of this project: refused, nothing changes.
        refused = cto.post(f"/api/v1/intakes/{intake['id']}/duplicate-issue", json={"issue": "424242", "expected_version": current["version"]})
        assert refused.status_code == 409 and "DUPLICATE_TARGET_NOT_FOUND" in refused.text, refused.text

        marked = cto.post(f"/api/v1/intakes/{intake['id']}/duplicate-issue", json={"issue": "#9301", "expected_version": current["version"]})
        assert marked.status_code == 200, marked.text
        data = marked.json()["data"]
        assert data["status"] == "REJECTED" and data["duplicate_of"] is None
        assert data["duplicate_issue"] == {"system": "GITLAB", "external_id": "9301", "title": "Xuất Excel sai tổng doanh thu", "url": "https://gitlab.example/issues/9301"}
        assert intake["id"] not in [row["id"] for row in cto.get("/api/v1/approvals?limit=100").json()["data"]["items"]]
        listed = next(row for row in cto.get("/api/v1/intakes?project_id=orbit&limit=100").json()["data"]["items"] if row["id"] == intake["id"])
        assert listed["duplicate_issue"]["external_id"] == "9301", "the list shows the Trùng label too"

        back = cto.delete(f"/api/v1/intakes/{intake['id']}/duplicate?expected_version={data['version']}")
        assert back.status_code == 200, back.text
        assert back.json()["data"]["status"] == "PENDING_APPROVAL" and back.json()["data"]["duplicate_issue"] is None
        assert cto.delete(f"/api/v1/intakes/{intake['id']}/duplicate?expected_version={back.json()['data']['version']}").status_code == 409

        # INT-26W44-003: the approver may know the existing Issue even when AI did not suggest it.
        # The detail dialog accepts the number directly and the same backend validation closes the request.
        with get_session() as session:
            stored = session.get(IntakeItem, intake["id"])
            stored.normalized_details = {**(stored.normalized_details or {}), "related": []}
            session.commit()
        assert cto.get(f"/api/v1/intakes/{intake['id']}").json()["data"]["details"]["related"] == []

        # Marking again after taking it back works (the candidate row is reused, not duplicated).
        again = cto.post(f"/api/v1/intakes/{intake['id']}/duplicate-issue", json={"issue": "9301", "expected_version": back.json()["data"]["version"]})
        assert again.status_code == 200 and again.json()["data"]["duplicate_issue"]["external_id"] == "9301"
    finally:
        cto.delete(f"/api/v1/intakes/{intake['id']}")
        _drain(intake["id"])
        _clean_issues("9301")


def test_reworded_repeats_of_settled_questions_are_dropped() -> None:
    """The case reported on 2026-10-07: after four answers, the model asked the same four things in other words."""
    from app.modules.integrations.description import proposed_details, repeats_settled

    settled = [
        {"question": "New agent này là agent gì, tên/phiên bản nào?", "answer": "Hồng Phát", "skipped": False},
        {"question": "Cần team support cụ thể những gì để bắt đầu triển khai?", "answer": "cài đặt agent mới và improt dữ liệu", "skipped": False},
        {"question": "Deadline ngày mai là hạn hoàn tất triển khai hay hạn bắt đầu có support?", "answer": "hoàn tất", "skipped": False},
        {"question": "Triển khai trên môi trường nào và tài khoản Zalo nào của Hồng Phát?", "answer": "production tk của số đt Hồng PHát", "skipped": False},
    ]
    reworded = [
        "Phiên bản của new agent Hồng Phát là gì?",
        "Dữ liệu cần import cho agent gồm những gì và lấy từ đâu?",
        "Agent cần được triển khai trên website nào?",
        "Tài khoản Zalo production của số điện thoại Hồng Phát đã sẵn sàng để cấu hình chưa?",
    ]
    assert [repeats_settled(question, settled) for question in reworded] == [True, True, True, True]
    # Something the team was never asked about is still a question.
    assert repeats_settled("Ngân sách cho hạng mục này đã được khách chốt chưa?", settled) is False
    assert repeats_settled("Ai bên khách là người nghiệm thu?", settled) is False

    extraction = AIExtraction(
        item_type="TASK", suggested_priority="P1", proposed_route="GITLAB", normalized_title="Triển khai agent Hồng Phát", normalized_summary="Cài agent mới và import dữ liệu.",
        open_questions=[*reworded, "Ai bên khách là người nghiệm thu?"],
    )
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        details = proposed_details(session, project.id, extraction, {"clarifications": settled})
    assert details["open_questions"] == ["Ai bên khách là người nghiệm thu?"] and len(details["clarifications"]) == 4
    # With nothing settled yet, the first round of questions is untouched.
    with get_session() as session:
        first = proposed_details(session, project.id, extraction, None)
    assert first["open_questions"] == [*reworded, "Ai bên khách là người nghiệm thu?"]
