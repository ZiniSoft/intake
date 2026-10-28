"""The WORK route replaces PLANE (FR-WRK-05..06, ADR-0066): a request approved for WORK becomes a work item in the
same breath; reopening drops it; a work item asks for an Issue through the ordinary approval and sync path."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AIExtraction as StoredExtraction, ApprovalAction, ApprovalSnapshot, AuditEvent, ExternalLink, IntakeItem, ProcessingRun, Project, ProjectIntegration, SourceMessage, SyncJob, WorkComment, WorkItem
from app.services.ai_processor import AIExtraction
from app.services.intake_service import intake_store
from app.workers import integration_tasks

client = TestClient(app, headers={"X-User-Subject": "cto"})


def _intake(title: str, summary: str, route: str = "WORK") -> dict:
    created = client.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "MANUAL", "raw_text": f"{title}. {summary}"}).json()["data"]
    intake_store.process(created["id"], AIExtraction(item_type="FEATURE", suggested_priority="P3", proposed_route=route, normalized_title=title, normalized_summary=summary))
    return client.get(f"/api/v1/intakes/{created['id']}").json()["data"]


def _delivery_sync(enabled: bool) -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        mapping = session.scalar(select(ProjectIntegration).where(ProjectIntegration.project_id == project.id, ProjectIntegration.system == "GITLAB"))
        mapping.enabled = enabled
        session.commit()


def _cleanup(intake_ids: list[str], work_ids: list[str]) -> None:
    with get_session() as session:
        for work_id in work_ids:
            for row in session.scalars(select(WorkComment).where(WorkComment.work_id == work_id)).all():
                session.delete(row)
            for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id)).all():
                session.delete(row)
            row = session.get(WorkItem, work_id)
            if row is not None:
                session.delete(row)
        session.commit()
    for intake_id in intake_ids:
        client.delete(f"/api/v1/intakes/{intake_id}", params={"reason": "dọn dữ liệu test việc nội bộ"})
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            if item is not None:
                for model in (ExternalLink, SyncJob, ApprovalSnapshot, ApprovalAction, StoredExtraction, ProcessingRun, SourceMessage):
                    for child in session.scalars(select(model).where(model.intake_id == intake_id)).all():
                        session.delete(child)
                session.delete(item)
                session.commit()


def test_a_request_approved_for_work_becomes_a_work_item_and_reopening_drops_it() -> None:
    intake = _intake("Thêm báo cáo doanh thu theo tuần", "Khách muốn xem doanh thu theo tuần, không gấp.")
    work_ids: list[str] = []
    try:
        assert intake["proposed_route"] == "WORK" and intake["status"] == "PENDING_APPROVAL"
        assert intake["lifecycle_stage"] == "PENDING_APPROVAL"
        approved = client.post(f"/api/v1/intakes/{intake['id']}/approve", json={"approved_route": "WORK", "approved_priority": "P2", "reason": "Bàn với PO trước", "expected_version": intake["version"]})
        assert approved.status_code == 200, approved.text
        data = approved.json()["data"]
        assert data["status"] == "APPROVED" and data["approved_route"] == "WORK" and data["work_item"]["code"].startswith("ORB-W-") and data["work_item"]["status"] == "DISCUSS"
        assert data["lifecycle_stage"] == "WAITING_PLANNING"
        work_ids.append(data["work_item"]["id"])
        work = client.get(f"/api/v1/work/{data['work_item']['id']}").json()["data"]
        assert work["title"] == "Thêm báo cáo doanh thu theo tuần" and work["priority"] == "P2" and work["intake_public_id"] == intake["public_id"]
        assert work["description"] == "Khách muốn xem doanh thu theo tuần, không gấp."
        # Nothing to sync: the request stands as decided, with its work on the board.
        assert client.get(f"/api/v1/intakes/{intake['id']}/sync-status").json()["data"]["sync_available"] is False
        assert client.get(f"/api/v1/intakes/{intake['id']}").json()["data"]["work_item"]["id"] == work["id"]
        journey = client.get(f"/api/v1/intakes/{intake['id']}/journey").json()["data"]
        assert journey["work_item"]["code"] == work["code"] and journey["issue"] is None

        reopened = client.post(f"/api/v1/intakes/{intake['id']}/reopen", json={"reason": "Khách đổi ý, xem lại từ đầu", "expected_version": data["version"]})
        assert reopened.status_code == 200, reopened.text
        dropped = client.get(f"/api/v1/work/{work['id']}").json()["data"]
        assert dropped["status"] == "CANCELLED" and dropped["closed_note"].startswith("Intake được mở lại")
        # Decided again for WORK: the same item comes back instead of a second one.
        again = client.post(f"/api/v1/intakes/{intake['id']}/approve", json={"approved_route": "WORK", "approved_priority": "P3", "reason": "Giữ lại để bàn", "expected_version": reopened.json()["data"]["version"]}).json()["data"]
        assert again["work_item"]["id"] == work["id"] and again["work_item"]["status"] == "DISCUSS"
        with get_session() as session:
            assert session.scalar(select(WorkItem.priority).where(WorkItem.id == work["id"])) == "P3"
            assert len(session.scalars(select(WorkItem).where(WorkItem.intake_id == intake["id"])).all()) == 1
    finally:
        _cleanup([intake["id"]], work_ids)


def test_management_lifecycle_follows_internal_work_and_filters_every_intake() -> None:
    intake = _intake("Chuẩn hóa tài liệu vận hành", "Việc nội bộ cũng phải có vòng đời quản lý.")
    work_ids: list[str] = []
    try:
        approved = client.post(
            f"/api/v1/intakes/{intake['id']}/approve",
            json={"approved_route": "WORK", "approved_priority": "P2", "reason": "Đưa vào board", "expected_version": intake["version"]},
        ).json()["data"]
        work_id = approved["work_item"]["id"]
        work_ids.append(work_id)

        for work_status, expected_stage in (
            ("DISCUSS", "WAITING_PLANNING"),
            ("IN_PROGRESS", "IN_PROGRESS"),
            ("ACCEPTANCE", "PENDING_ACCEPTANCE"),
            ("DONE", "ACCEPTED"),
            ("CANCELLED", "STOPPED"),
        ):
            with get_session() as session:
                session.get(WorkItem, work_id).status = work_status
                session.commit()
            detail = client.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
            assert detail["lifecycle_stage"] == expected_stage
            page = client.get("/api/v1/intakes", params={"stage": expected_stage, "search": intake["public_id"]})
            assert page.status_code == 200, page.text
            assert [row["id"] for row in page.json()["data"]["items"]] == [intake["id"]]
    finally:
        _cleanup([intake["id"]], work_ids)


def test_direct_response_counts_as_accepted_for_every_intake() -> None:
    intake = _intake("Trả lời cách cấu hình", "Chỉ cần phản hồi, không tạo Issue.", route="RESPONSE")
    try:
        approved = client.post(
            f"/api/v1/intakes/{intake['id']}/approve",
            json={"approved_route": "RESPONSE", "approved_priority": "P3", "reason": "Đã trả lời", "expected_version": intake["version"]},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["lifecycle_stage"] == "ACCEPTED"
        page = client.get("/api/v1/intakes", params={"stage": "ACCEPTED", "search": intake["public_id"]}).json()["data"]
        assert [row["id"] for row in page["items"]] == [intake["id"]]
    finally:
        _cleanup([intake["id"]], [])


def test_a_work_item_becomes_an_issue_through_the_delivery_path(monkeypatch) -> None:
    intake = _intake("Cho xuất báo cáo tuần ra Excel", "Sau khi bàn, đội đồng ý làm.")
    work_ids: list[str] = []
    intake_ids = [intake["id"]]
    _delivery_sync(True)
    try:
        approved = client.post(f"/api/v1/intakes/{intake['id']}/approve", json={"approved_route": "WORK", "approved_priority": "P2", "reason": "Bàn trước", "expected_version": intake["version"]}).json()["data"]
        work_id = approved["work_item"]["id"]
        work_ids.append(work_id)
        owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
        assert owner.post(f"/api/v1/work/{work_id}/issue").status_code == 404

        asked = client.post(f"/api/v1/work/{work_id}/issue")
        assert asked.status_code == 200, asked.text
        assert asked.json()["data"]["issue_pending"] is True and asked.json()["data"]["status"] == "DISCUSS"
        item = client.get(f"/api/v1/intakes/{intake['id']}").json()["data"]
        assert item["status"] == "SYNC_PENDING" and item["approved_route"] == "GITLAB"
        with get_session() as session:
            actions = session.scalars(select(ApprovalAction).where(ApprovalAction.intake_id == intake["id"]).order_by(ApprovalAction.created_at)).all()
            assert [(a.action, a.source) for a in actions] == [("APPROVE", "QUEUE"), ("APPROVE", "WORK")], "one decision, no reopen in between"
            assert actions[-1].reason.startswith("Chuyển thành Issue từ Việc ORB-W-")
            snapshots = session.scalars(select(ApprovalSnapshot).where(ApprovalSnapshot.intake_id == intake["id"]).order_by(ApprovalSnapshot.created_at)).all()
            assert [(s.approved_route, s.invalidated_at is None) for s in snapshots] == [("WORK", False), ("GITLAB", True)]
            job_id = str(session.scalar(select(SyncJob.id).where(SyncJob.intake_id == intake["id"])))
        assert "WORK_CLOSED" in client.post(f"/api/v1/work/{work_id}/issue").text

        async def fake_sync(context):
            assert context.approved["title"] == "Cho xuất báo cáo tuần ra Excel"
            return {"id": "7400", "global_id": 99400, "web_url": "https://gitlab.test/orbit/-/issues/7400"}, False

        monkeypatch.setattr(integration_tasks, "_sync_gitlab", fake_sync)
        assert integration_tasks.sync_external.run(job_id) == "SUCCEEDED"
        closed = client.get(f"/api/v1/work/{work_id}").json()["data"]
        assert closed["status"] == "DONE" and closed["outcome"] == "ISSUE" and closed["issue_external_id"] == "7400" and closed["issue_url"].endswith("/7400")
        assert closed["history"][0]["event_type"] == "work.issue_created" and closed["history"][0]["actor_name"] == "hệ thống"
        locked = client.post(f"/api/v1/work/{work_id}/move", json={"status": "READY", "expected_version": closed["version"]})
        assert locked.status_code == 409 and "WORK_LOCKED_BY_ISSUE" in locked.text

        # Work written straight on the board gets a request of its own on the way to an Issue.
        fresh = client.post("/api/v1/work", json={"project": "orbit", "title": "Dọn log cũ trên máy chủ", "description": "Giữ 30 ngày.", "priority": "P3", "status": "READY"}).json()["data"]
        work_ids.append(fresh["id"])
        asked = client.post(f"/api/v1/work/{fresh['id']}/issue").json()["data"]
        assert asked["intake_id"] and asked["intake_public_id"].startswith("ORB-") and asked["issue_pending"] is True
        intake_ids.append(asked["intake_id"])
        made = client.get(f"/api/v1/intakes/{asked['intake_id']}").json()["data"]
        assert made["status"] == "SYNC_PENDING" and made["approved_route"] == "GITLAB" and made["normalized_title"] == "Dọn log cũ trên máy chủ"
    finally:
        _delivery_sync(False)
        _cleanup(intake_ids, work_ids)


def test_work_needs_a_delivery_tracker_to_become_an_issue() -> None:
    work = client.post("/api/v1/work", json={"project": "other", "title": "Ý tưởng chưa có repo"}).json()["data"]
    try:
        refused = client.post(f"/api/v1/work/{work['id']}/issue")
        assert refused.status_code == 422 and "PROJECT_NOT_SOFTWARE" in refused.text
        assert client.get(f"/api/v1/work/{work['id']}").json()["data"]["issue_pending"] is False
    finally:
        _cleanup([], [work["id"]])
