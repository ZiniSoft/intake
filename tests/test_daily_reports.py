from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import EmailMessage, Project, ReportItem
from app.modules.reports.service import daily_report_service, parse_daily_report
from app.queue.celery_app import celery_app


client = TestClient(app, headers={"X-User-Subject": "cto"})


VALID_BODY = """BÁO CÁO NGÀY
Ngày: 2026-10-06 | Nhân sự: Report Test | Tổng thời gian: 4 giờ

=== ORBIT | Orbit ===
[DONE] Hoàn thiện API | Thời gian: 4 giờ | Tiến độ: 100%
Tham chiếu: GitLab #321 | Plane: Không có | Intake: Không có
Kết quả:
- API đã hoàn tất

[PLANNED] Tiếp tục kiểm thử | Thời gian dự kiến: 4 giờ
Tham chiếu: GitLab #321 | Plane: Không có | Intake: Không có
Deadline/Milestone: 2026-10-07
Dependency: Không có
Mục tiêu:
- Hoàn tất kiểm thử
"""


def _project_id() -> str:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        assert project is not None
        return str(project.id)


def _create_member(email: str, display_name: str) -> dict:
    response = client.post(
        "/api/v1/planning/members",
        json={
            "display_name": display_name,
            "email_reference": email,
            "project_mappings": [{
                "project_id": _project_id(),
                "gitlab_user_external_id": "77",
                "role": "Developer",
            }],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["data"]


def test_daily_report_parser_extracts_delivery_and_plan() -> None:
    parsed = parse_daily_report(
        "DAILY REPORT | 2026-10-06 | Report Test | ORBIT",
        VALID_BODY,
    )
    assert parsed.status == "VALID"
    assert parsed.report_date.isoformat() == "2026-10-06"
    assert parsed.total_hours == 4
    assert len(parsed.items) == 2
    assert parsed.items[0].work_status == "DONE"
    assert parsed.items[0].gitlab_issue_external_id == "321"
    assert parsed.items[1].planned_hours == 4
    assert parsed.items[1].deadline_text == "2026-10-07"


def test_daily_report_ingestion_is_idempotent_and_preserves_revisions() -> None:
    member = _create_member("report-test@example.test", "Report Test")
    payload = {
        "mailbox": "report@example.test",
        "uid_validity": "20261001",
        "uid": "1001",
        "message_id": "<report-1001@example.test>",
        "sender_address": "report-test@example.test",
        "sender_name": "Report Test",
        "subject": "DAILY REPORT | 2026-10-06 | Report Test | ORBIT",
        "body": VALID_BODY,
        "received_at": "2026-10-06T10:30:00Z",
    }
    first = client.post("/api/v1/reports/daily/ingest", json=payload)
    assert first.status_code == 201, first.text
    assert first.json()["data"]["status"] == "VALID"
    assert first.json()["data"]["revision"] == 1
    assert first.json()["data"]["item_count"] == 2

    duplicate = client.post("/api/v1/reports/daily/ingest", json=payload)
    assert duplicate.status_code == 201
    assert duplicate.json()["data"]["id"] == first.json()["data"]["id"]
    assert duplicate.json()["data"]["duplicate"] is True

    message_id_duplicate = client.post(
        "/api/v1/reports/daily/ingest",
        json={**payload, "uid": "1009"},
    )
    assert message_id_duplicate.status_code == 201
    assert message_id_duplicate.json()["data"]["id"] == first.json()["data"]["id"]
    assert message_id_duplicate.json()["data"]["duplicate"] is True

    revision_payload = {
        **payload,
        "uid": "1002",
        "message_id": "<report-1002@example.test>",
        "received_at": "2026-10-06T17:00:00Z",
    }
    revision = client.post("/api/v1/reports/daily/ingest", json=revision_payload)
    assert revision.status_code == 201, revision.text
    assert revision.json()["data"]["revision"] == 2
    assert revision.json()["data"]["is_late"] is True

    listed = client.get(f"/api/v1/reports/daily?report_date=2026-10-06&member_id={member['id']}")
    assert listed.status_code == 200
    assert len(listed.json()["data"]) == 1
    assert listed.json()["data"][0]["revision"] == 2

    with get_session() as session:
        messages = session.scalars(select(EmailMessage).where(
            EmailMessage.member_id == member["id"],
            EmailMessage.report_date == datetime(2026, 10, 6, tzinfo=timezone.utc).date(),
        ).order_by(EmailMessage.revision)).all()
        assert [row.is_current for row in messages] == [False, True]
        assert messages[0].subject_ciphertext != payload["subject"]
        old_items = session.scalars(select(ReportItem).where(
            ReportItem.email_message_id == messages[0].id,
        )).all()
        assert old_items and all(not item.is_current for item in old_items)

    snapshot = daily_report_service.create_snapshot(datetime(2026, 10, 6, tzinfo=timezone.utc).date())
    assert snapshot["item_count"] == 2
    assert snapshot["duplicate"] is False
    repeated_snapshot = daily_report_service.create_snapshot(datetime(2026, 10, 6, tzinfo=timezone.utc).date())
    assert repeated_snapshot["id"] == snapshot["id"]
    assert repeated_snapshot["duplicate"] is True


def test_planning_run_warns_but_continues_when_report_is_missing() -> None:
    member = _create_member("missing-report@example.test", "Missing Report")
    response = client.post(
        "/api/v1/planning/runs",
        json={"plan_date": "2026-10-08", "project_ids": [_project_id()]},
    )
    assert response.status_code == 201, response.text
    run = response.json()["data"]
    warnings = [warning for warning in run["warnings"] if warning["member_id"] == member["id"]]
    assert any(warning["code"] == "REPORT_MISSING" for warning in warnings)
    assert run["status"] == "DRAFT"


def test_daily_scheduler_uses_vietnam_timezone_and_required_slots() -> None:
    assert celery_app.conf.timezone == "Asia/Ho_Chi_Minh"
    assert set(celery_app.conf.beat_schedule) == {
        "daily-report-ai-rescue-scan",
        "meeting-note-scan",
        "watch-health-check-12h",
        "watch-topics-tick",
        "daily-report-snapshot-2330",
        "daily-planning-preflight-0645",
        "project-context-0650",
        "daily-planning-create-0700",
        "board-snapshot-2355",
        "personal-nightly-2358",
    }


FREE_TEXT_BODY = """Chào anh,
Hôm nay em làm Orbit: sửa xong lỗi đăng nhập (issue 412), mất khoảng 3 tiếng.
Ngày mai em tiếp tục phần báo cáo tuần, đang bị chặn vì chưa có dữ liệu mẫu.
"""


def _ingest_free_text(uid: str, sender: str = "rescue-test@example.test") -> dict:
    return daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid=uid,
        message_id=f"<rescue-{uid}@example.test>", sender_address=sender, sender_name="Rescue Test",
        subject="Báo cáo ngày 7/10", body=FREE_TEXT_BODY,
        received_at=datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc),
    )


def _ai_report():
    from app.services.ai_processor import AIReportExtraction

    return AIReportExtraction.model_validate({
        "report_date": "2026-10-07",
        "employee_name": "Rescue Test",
        "total_hours": 3,
        "items": [
            {"project_code": "Orbit", "work_status": "DONE", "title": "Sửa lỗi đăng nhập",
             "worked_hours": 3, "progress_percent": 100, "gitlab_issue": "412"},
            {"project_code": "Orbit", "work_status": "BLOCKED", "title": "Báo cáo tuần",
             "blocker_detail": "Chưa có dữ liệu mẫu"},
        ],
    })


def test_malformed_report_is_queued_for_ai_rescue_but_valid_report_is_not() -> None:
    _create_member("rescue-test@example.test", "Rescue Test")
    malformed = _ingest_free_text("2001")
    assert malformed["status"] == "MALFORMED"
    assert malformed["item_count"] == 0
    assert malformed["id"] in daily_report_service.pending_ai_rescues(limit=100)

    with get_session() as session:
        valid_ids = {
            str(row.id) for row in session.scalars(select(EmailMessage).where(EmailMessage.status == "VALID")).all()
        }
    assert not valid_ids & set(daily_report_service.pending_ai_rescues(limit=100))


def test_ai_rescue_creates_flagged_items_and_is_idempotent(monkeypatch) -> None:
    from app.services import ai_processor
    from app.workers import ai_tasks

    malformed = _ingest_free_text("2002", sender="rescue-two@example.test")
    calls: list[str] = []

    async def fake_extract_report(source_text: str):
        calls.append(source_text)
        return _ai_report()

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_report", fake_extract_report)

    assert ai_tasks.execute_report_rescue(malformed["id"]) == "SUCCEEDED"
    assert "Subject: Báo cáo ngày 7/10" in calls[0] and "issue 412" in calls[0]

    with get_session() as session:
        row = session.get(EmailMessage, malformed["id"])
        assert row.parse_version == "daily-report-ai-v1"
        assert row.report_date.isoformat() == "2026-10-07"
        assert not any(issue["code"] == "REPORT_DATE_ASSUMED" for issue in row.parse_errors)
        codes = {issue["code"]: issue["severity"] for issue in row.parse_errors}
        assert codes["REPORT_AI_PARSED"] == "WARNING"
        assert codes["INVALID_SUBJECT"] == "WARNING"
        items = session.scalars(select(ReportItem).where(
            ReportItem.email_message_id == row.id, ReportItem.is_current.is_(True),
        ).order_by(ReportItem.title)).all()
        assert [item.work_status for item in items] == ["BLOCKED", "DONE"]
        assert items[1].gitlab_issue_external_id == "412"
        assert float(items[1].worked_hours) == 3
        assert items[0].blocker is True and items[0].blocker_detail == "Chưa có dữ liệu mẫu"
        assert all(item.progress_evidence["parsed_by"] == "AI" for item in items)
        assert all(item.project_id == _project_id() for item in items)

    assert ai_tasks.execute_report_rescue(malformed["id"]) == "SKIPPED"
    assert len(calls) == 1
    assert malformed["id"] not in daily_report_service.pending_ai_rescues(limit=100)


def test_ai_rescue_failure_is_recorded_and_not_retried_forever() -> None:
    malformed = _ingest_free_text("2003", sender="rescue-three@example.test")
    daily_report_service.record_ai_rescue_failure(malformed["id"], "AI_RESULT_INVALID")

    with get_session() as session:
        row = session.get(EmailMessage, malformed["id"])
        assert row.parse_version == "daily-report-v1-ai-failed"
        assert row.status == "MALFORMED"
        assert any(issue["code"] == "REPORT_AI_RESCUE_FAILED" for issue in row.parse_errors)
        assert session.scalar(select(ReportItem).where(ReportItem.email_message_id == row.id)) is None
    assert malformed["id"] not in daily_report_service.pending_ai_rescues(limit=100)
    assert daily_report_service.ai_rescue_source(malformed["id"]) is None


def test_ai_report_contract_rejects_invented_status_and_empty_items() -> None:
    import httpx
    import json
    import pytest

    from app.services.ai_processor import AIProviderTransientError, AIReportExtraction, _parse_model

    def response(content: dict) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(content)}}]})

    valid = _parse_model(response(_ai_report().model_dump(mode="json")), "UMODELVERSE", AIReportExtraction)
    assert len(valid.items) == 2

    lenient = _parse_model(response({"items": [
        {"project_code": "AISE", "work_status": "DONE", "title": "x" * 400, "gitlab_issue": 327},
        {"project_code": "AISE", "work_status": "DONE", "title": "y", "gitlab_issue": "#318"},
        {"project_code": "AISE", "work_status": "DONE", "title": "z", "gitlab_issue": "see chat"},
        {"project_code": None, "work_status": None, "title": "not a task"},
    ]}), "UMODELVERSE", AIReportExtraction)
    assert [item.gitlab_issue for item in lenient.items] == ["327", "318", None]
    assert len(lenient.items[0].title) == 255

    for broken in (
        {"items": [{"project_code": None, "work_status": None, "title": "test mail"}]},
        {"items": []},
        {"items": [{"project_code": "ORBIT", "work_status": "ALMOST_DONE", "title": "x"}]},
        {"items": [{"project_code": "ORBIT", "work_status": "DONE", "title": "x", "worked_hours": 40}]},
    ):
        with pytest.raises(AIProviderTransientError):
            _parse_model(response(broken), "UMODELVERSE", AIReportExtraction)


def test_report_work_outside_pilot_projects_is_grouped_under_other_project() -> None:
    _create_member("other-project@example.test", "Other Project Test")
    body = VALID_BODY.replace("=== ORBIT | Orbit ===", "=== AIVOBOT | Voice bot ===").replace("Report Test", "Other Project Test")
    result = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid="3001",
        message_id="<other-3001@example.test>", sender_address="other-project@example.test",
        sender_name="Other Project Test", subject="DAILY REPORT | 2026-10-08 | Other Project Test | AIVOBOT",
        body=body, received_at=datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc),
    )
    assert result["status"] == "VALID"
    assert not any(issue["code"] == "REPORT_PROJECT_UNMAPPED" for issue in result["issues"])
    with get_session() as session:
        other = session.scalar(select(Project).where(Project.code == "other"))
        items = session.scalars(select(ReportItem).where(ReportItem.email_message_id == result["id"])).all()
        assert items and all(item.project_id == other.id for item in items)
        assert all(item.progress_evidence["reported_project_code"] == "AIVOBOT" for item in items)
        assert session.get(EmailMessage, result["id"]).project_id == other.id
        ember = session.scalar(select(Project).where(Project.code == "ember"))
        for code in ("Ember Web", "ember_pwa", "EMBER-WEB", "Ember"):
            assert daily_report_service._resolve_project(session, code).id == ember.id
        assert daily_report_service._resolve_project(session, "Kindergarten").id == other.id
        assert daily_report_service._resolve_project(session, "INTERNAL") is None


def test_ai_rescue_scan_processes_a_bounded_batch_one_email_per_task(monkeypatch) -> None:
    from app.services import ai_processor
    from app.workers import ai_tasks

    for uid in ("4001", "4002", "4003"):
        _ingest_free_text(uid, sender=f"batch-{uid}@example.test")
    monkeypatch.setattr(ai_processor.umodelverse_adapter, "is_configured", lambda *a, **k: True)

    async def fake_extract_report(source_text: str):
        return _ai_report()

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_report", fake_extract_report)
    queued: list[dict] = []
    monkeypatch.setattr(ai_tasks.scan_daily_reports_for_rescue, "apply_async", lambda **options: queued.append(options["kwargs"]))

    pending_before = len(daily_report_service.pending_ai_rescues(limit=100))
    first = ai_tasks.scan_daily_reports_for_rescue(remaining=2)
    assert first["outcome"] == "SUCCEEDED"
    assert queued == [{"remaining": 1, "skip": [first["email_id"]]}]
    last = ai_tasks.scan_daily_reports_for_rescue(**queued[0])
    assert last["outcome"] == "SUCCEEDED" and len(queued) == 1
    assert len(daily_report_service.pending_ai_rescues(limit=100)) == pending_before - 2


def test_ai_rescue_retries_at_later_scans_then_gives_up(monkeypatch) -> None:
    from app.services import ai_processor
    from app.workers import ai_tasks

    malformed = _ingest_free_text("4101", sender="retry-4101@example.test")

    async def unavailable(source_text: str):
        raise ai_processor.AIProviderTransientError("UMODELVERSE", "UMODELVERSE_UNAVAILABLE")

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_report", unavailable)
    assert ai_tasks.process_report_rescue(malformed["id"]) == "RETRY_LATER"
    assert ai_tasks.process_report_rescue(malformed["id"]) == "RETRY_LATER"
    assert malformed["id"] in daily_report_service.pending_ai_rescues(limit=100)
    assert ai_tasks.process_report_rescue(malformed["id"]) == "FAILED"
    assert malformed["id"] not in daily_report_service.pending_ai_rescues(limit=100)
    with get_session() as session:
        codes = [issue["code"] for issue in session.get(EmailMessage, malformed["id"]).parse_errors]
        assert "REPORT_AI_RESCUE_FAILED" in codes and "REPORT_AI_RESCUE_RETRY" not in codes


def test_known_uids_let_the_worker_skip_stored_messages() -> None:
    stored = _ingest_free_text("4201", sender="known-4201@example.test")
    assert stored["duplicate"] is False
    known = daily_report_service.known_uids("report@example.test", "20261004")
    assert "4201" in known and "999999" not in known
    assert daily_report_service.known_uids("report@example.test", "other-validity") == set()


def test_items_keep_their_project_when_body_code_differs_from_subject() -> None:
    _create_member("scope-test@example.test", "Scope Test")
    body = VALID_BODY.replace("=== ORBIT | Orbit ===", "=== EMBER-WEB | Ember Web ===").replace("Report Test", "Scope Test")
    result = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid="5001",
        message_id="<scope-5001@example.test>", sender_address="scope-test@example.test",
        sender_name="Scope Test", subject="DAILY REPORT | 2026-10-09 | Scope Test | EMBER",
        body=body, received_at=datetime(2026, 10, 9, 9, 0, tzinfo=timezone.utc),
    )
    assert any(issue["code"] == "PROJECT_SCOPE_MISMATCH" for issue in result["issues"])
    with get_session() as session:
        ember = session.scalar(select(Project).where(Project.code == "ember"))
        items = session.scalars(select(ReportItem).where(ReportItem.email_message_id == result["id"])).all()
        assert items and all(item.project_id == ember.id for item in items)


def test_placeholder_lines_are_not_work_items() -> None:
    body = VALID_BODY + """
[BLOCKED] Vấn đề: Không có
[CANCELLED] Công việc: Không có
[DONE] Không có
"""
    parsed = parse_daily_report("DAILY REPORT | 2026-10-06 | Report Test | ORBIT", body)
    assert [item.title for item in parsed.items] == ["Hoàn thiện API", "Tiếp tục kiểm thử"]
    real = parse_daily_report(
        "DAILY REPORT | 2026-10-06 | Report Test | ORBIT",
        VALID_BODY + "\n[BLOCKED] Vấn đề: Không có quyền truy cập server\n",
    )
    assert real.items[-1].work_status == "BLOCKED"


def test_issue_number_in_the_title_is_the_gitlab_reference() -> None:
    body = VALID_BODY + """
[PENDING_REVIEW] Issue #19: Thay link tài liệu | Thời gian: 0.5 giờ | Tiến độ: 90%
Bước tiếp theo: Gộp nhánh tuong.le-v5
[IN_PROGRESS] #21 - Script cài đặt | Thời gian: 1 giờ
[DONE] Đóng gói phát hành, xem issue #7 của khách | Thời gian: 1 giờ | Tiến độ: 100%
[DONE] Tham chiếu: GitLab #321 | Issue #5 trong tiêu đề không thắng | Thời gian: 1 giờ | Tiến độ: 100%
[DONE] [#8 EMB-26W41-007] Lập danh sách sửa trang hướng dẫn | Thời gian: 1.5 giờ | Tiến độ: 100%
[DONE] Viết CUSTOMIZATION.md | Thời gian: 1.5 giờ | Tiến độ: 100%
Issue: https://gitlab.example.test/2026/ember-platform/-/work_items/17
"""
    parsed = parse_daily_report("DAILY REPORT | 2026-10-06 | Report Test | ORBIT", body)
    by_title = {item.title: item for item in parsed.items}
    assert by_title["Thay link tài liệu"].gitlab_issue_external_id == "19", "the number the team writes as 'Issue #19' is the reference"
    assert by_title["Script cài đặt"].gitlab_issue_external_id == "21", "a leading '#21' too"
    assert by_title["Đóng gói phát hành, xem issue #7 của khách"].gitlab_issue_external_id == "7"
    assert by_title["Tham chiếu: GitLab #321"].gitlab_issue_external_id == "321", "an explicit GitLab reference still wins"
    bracketed = by_title["Lập danh sách sửa trang hướng dẫn"]
    assert bracketed.gitlab_issue_external_id == "8" and bracketed.intake_reference == "EMB-26W41-007", "'[#8 EMB-26W41-007]' names both the Issue and the request"
    assert by_title["Viết CUSTOMIZATION.md"].gitlab_issue_external_id == "17", "an Issue URL (issues/ or work_items/) gives the number"
    assert not any(issue.code == "GITLAB_REFERENCE_MISSING" and "Thay link" in issue.message for issue in parsed.issues)


def test_report_review_api_shows_items_audits_raw_access_and_rejects() -> None:
    from app.models import AuditEvent

    _create_member("review-test@example.test", "Review Test")
    created = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid="6001",
        message_id="<review-6001@example.test>", sender_address="review-test@example.test",
        sender_name="Review Test", subject="DAILY REPORT | 2026-10-10 | Review Test | ORBIT",
        body=VALID_BODY.replace("Report Test", "Review Test"),
        received_at=datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc),
    )
    detail = client.get(f"/api/v1/reports/daily/{created['id']}")
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["member_name"] == "Review Test" and data["parsed_by"] == "RULES" and data["review_decision"] is None
    assert [item["work_status"] for item in data["items"]] == ["DONE", "PLANNED"]
    assert data["items"][0]["project_name"] == "Orbit" and data["items"][0]["gitlab_issue"] == "321"
    assert "body" not in data and "subject" not in data

    raw = client.get(f"/api/v1/reports/daily/{created['id']}/raw")
    assert raw.status_code == 200
    assert raw.json()["data"]["subject"].startswith("DAILY REPORT | 2026-10-10")
    assert "Hoàn thiện API" in raw.json()["data"]["body"]
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "report.raw.read", AuditEvent.entity_id == created["id"],
        )) is not None

    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.get(f"/api/v1/reports/daily/{created['id']}/raw").status_code == 404
    assert client.post(f"/api/v1/reports/daily/{created['id']}/review", json={"decision": "MAYBE"}).status_code == 422

    confirmed = client.post(f"/api/v1/reports/daily/{created['id']}/review", json={"decision": "CONFIRMED"})
    assert confirmed.status_code == 200 and confirmed.json()["data"]["review_decision"] == "CONFIRMED"
    assert len(confirmed.json()["data"]["items"]) == 2

    rejected = client.post(f"/api/v1/reports/daily/{created['id']}/review", json={"decision": "REJECTED"})
    assert rejected.json()["data"]["review_decision"] == "REJECTED"
    assert rejected.json()["data"]["items"] == []
    assert client.get("/api/v1/reports/daily/00000000-0000-4000-8000-00000000dead").status_code == 404


def test_undated_report_uses_received_date_so_a_resend_replaces_it() -> None:
    _create_member("undated-test@example.test", "Undated Test")
    first = _ingest_free_text("7001", sender="undated-test@example.test")
    assert first["report_date"].isoformat() == "2026-10-07"
    assert any(issue["code"] == "REPORT_DATE_ASSUMED" for issue in first["issues"])
    second = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid="7002",
        message_id="<rescue-7002@example.test>", sender_address="undated-test@example.test", sender_name="Undated Test",
        subject="Báo cáo ngày 7/10 (gửi lại)", body=FREE_TEXT_BODY,
        received_at=datetime(2026, 10, 7, 9, 5, tzinfo=timezone.utc),
    )
    assert second["revision"] == 2
    with get_session() as session:
        assert session.get(EmailMessage, first["id"]).is_current is False
    assert first["id"] not in daily_report_service.pending_ai_rescues(limit=100)
    assert second["id"] in daily_report_service.pending_ai_rescues(limit=100)


def test_done_without_percent_and_scope_mismatch_are_warnings_and_late_cutoff_is_2330() -> None:
    _create_member("soft-rules@example.test", "Soft Rules")
    body = VALID_BODY.replace("| Tiến độ: 100%", "").replace("Report Test", "Soft Rules")
    on_time = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid="7101",
        message_id="<soft-7101@example.test>", sender_address="soft-rules@example.test", sender_name="Soft Rules",
        subject="DAILY REPORT | 2026-10-11 | Soft Rules | ORBIT", body=body,
        received_at=datetime(2026, 10, 11, 15, 0, tzinfo=timezone.utc),
    )
    assert on_time["status"] == "WARNING"
    assert {issue["severity"] for issue in on_time["issues"] if issue["code"] == "DONE_PROGRESS_INVALID"} == {"WARNING"}
    assert on_time["is_late"] is False
    late = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid="7102",
        message_id="<soft-7102@example.test>", sender_address="soft-rules@example.test", sender_name="Soft Rules",
        subject="DAILY REPORT | 2026-10-11 | Soft Rules | ORBIT", body=body,
        received_at=datetime(2026, 10, 11, 16, 45, tzinfo=timezone.utc),
    )
    assert late["is_late"] is True


def test_ai_read_report_is_not_usable_for_planning_until_confirmed(monkeypatch) -> None:
    from app.modules.reports.service import usable_for_planning
    from app.services import ai_processor
    from app.workers import ai_tasks

    _create_member("gate-test@example.test", "Gate Test")
    malformed = _ingest_free_text("7201", sender="gate-test@example.test")

    async def fake_extract_report(source_text: str):
        return _ai_report().model_copy(update={"employee_name": "Gate Test"})

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_report", fake_extract_report)
    assert ai_tasks.execute_report_rescue(malformed["id"]) == "SUCCEEDED"
    with get_session() as session:
        assert usable_for_planning(session.get(EmailMessage, malformed["id"])) is False
    listed = client.get(f"/api/v1/reports/daily/{malformed['id']}").json()["data"]
    assert listed["parsed_by"] == "AI" and listed["usable_for_planning"] is False

    snapshot = daily_report_service.create_snapshot(datetime(2026, 10, 7, tzinfo=timezone.utc).date())
    with get_session() as session:
        unreviewed = session.scalars(select(ReportItem).where(ReportItem.email_message_id == malformed["id"])).all()
        assert unreviewed and all(item.report_run_id != snapshot["id"] for item in unreviewed)

    confirmed = client.post(f"/api/v1/reports/daily/{malformed['id']}/review", json={"decision": "CONFIRMED"})
    assert confirmed.json()["data"]["usable_for_planning"] is True
    with get_session() as session:
        assert usable_for_planning(session.get(EmailMessage, malformed["id"])) is True


def test_cto_can_edit_and_remove_single_report_items() -> None:
    from app.models import AuditEvent

    _create_member("edit-test@example.test", "Edit Test")
    created = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261004", uid="7301",
        message_id="<edit-7301@example.test>", sender_address="edit-test@example.test", sender_name="Edit Test",
        subject="DAILY REPORT | 2026-10-12 | Edit Test | ORBIT", body=VALID_BODY.replace("Report Test", "Edit Test"),
        received_at=datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc),
    )
    base = f"/api/v1/reports/daily/{created['id']}"
    items = client.get(base).json()["data"]["items"]
    done = next(row for row in items if row["work_status"] == "DONE")
    planned = next(row for row in items if row["work_status"] == "PLANNED")

    updated = client.patch(f"{base}/items/{done['id']}", json={
        "work_status": "BLOCKED", "title": "API chờ quyền truy cập", "worked_hours": 2.5,
        "gitlab_issue": "412", "blocker_detail": "Chưa có quyền server", "project_code": "ember",
    })
    assert updated.status_code == 200, updated.text
    item = next(row for row in updated.json()["data"]["items"] if row["id"] == done["id"])
    assert item["work_status"] == "BLOCKED" and item["title"] == "API chờ quyền truy cập"
    assert item["worked_hours"] == 2.5 and item["gitlab_issue"] == "412" and item["project_name"] == "Ember"
    assert item["edited"] is True and item["blocker_detail"] == "Chưa có quyền server"
    with get_session() as session:
        row = session.get(ReportItem, done["id"])
        assert row.blocker is True and row.category == "DELIVERY"
        assert session.scalar(select(AuditEvent).where(
            AuditEvent.event_type == "report.item.updated", AuditEvent.entity_id == done["id"],
        )) is not None

    assert client.patch(f"{base}/items/{done['id']}", json={"work_status": "ALMOST"}).status_code == 422
    assert client.patch(f"{base}/items/{done['id']}", json={"worked_hours": 30}).status_code == 422
    assert client.patch(f"{base}/items/{done['id']}", json={"project_code": "nope"}).status_code == 422
    assert client.patch(f"{base}/items/{done['id']}", json={"title": None}).status_code == 422
    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.patch(f"{base}/items/{done['id']}", json={"title": "x"}).status_code == 404

    removed = client.delete(f"{base}/items/{planned['id']}")
    assert removed.status_code == 200
    assert [row["id"] for row in removed.json()["data"]["items"]] == [done["id"]]
    assert client.delete(f"{base}/items/{planned['id']}").status_code == 404


def test_signature_is_split_off_for_display_and_ai_but_the_stored_email_is_kept() -> None:
    from app.modules.reports.service import split_signature
    from app.models import EmailMessage
    from app.services.raw_crypto import decrypt

    signature = "Doan Tran Email Signature\nThank you & regards.\n*M:* +84 900 000 000"
    content, found = split_signature(f"{VALID_BODY}\n-- \n{signature}\n")
    assert content == VALID_BODY.rstrip() and found == signature
    # A "--" line in the middle of the report is not a signature: report content follows it.
    middle = f"việc A\n--\n{VALID_BODY}"
    assert split_signature(middle) == (middle, None)
    assert split_signature(VALID_BODY) == (VALID_BODY, None)
    assert split_signature(f"{VALID_BODY}\n--\n") == (f"{VALID_BODY}\n--\n", None)

    _create_member("signature-test@example.test", "Signature Test")
    body = f"không theo mẫu, hôm nay làm việc A\n--\n{signature}"
    created = daily_report_service.ingest(
        mailbox="report@example.test", uid_validity="20261005", uid="7001",
        message_id="<signature-7001@example.test>", sender_address="signature-test@example.test",
        sender_name="Signature Test", subject="bao cao", body=body,
        received_at=datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc),
    )
    with get_session() as session:
        assert decrypt(session.get(EmailMessage, created["id"]).body_ciphertext) == body
    for_ai = daily_report_service.ai_rescue_source(created["id"])
    assert for_ai is not None and "việc A" in for_ai and "+84 900 000 000" not in for_ai and "Thank you" not in for_ai

    raw = client.get(f"/api/v1/reports/daily/{created['id']}/raw").json()["data"]
    assert raw["body"] == "không theo mẫu, hôm nay làm việc A" and raw["signature"] == signature


def test_unfinished_report_items_become_planning_candidates_once() -> None:
    member = _create_member("carry-test@example.test", "Carry Test")
    late_member = _create_member("carry-late@example.test", "Carry Late")
    body = """BÁO CÁO NGÀY
Ngày: 2026-11-10 | Nhân sự: Carry Test | Tổng thời gian: 6 giờ

=== ORBIT | Orbit ===
[DONE] Việc đã xong | Thời gian: 4 giờ | Tiến độ: 100%
[IN_PROGRESS] Việc đang làm chưa có Issue | Thời gian: 2 giờ | Tiến độ: 50%
[PLANNED] Việc dự kiến ngày mai | Thời gian dự kiến: 3 giờ
"""

    def ingest(uid: str, sender: str, name: str) -> None:
        daily_report_service.ingest(
            mailbox="report@example.test", uid_validity="20261110", uid=uid,
            message_id=f"<carry-{uid}@example.test>", sender_address=sender, sender_name=name,
            subject=f"DAILY REPORT | 2026-11-10 | {name} | ORBIT", body=body.replace("Carry Test", name),
            received_at=datetime(2026, 11, 10, 11, 0, tzinfo=timezone.utc),
        )

    def report_candidates() -> list[dict]:
        run = client.post("/api/v1/planning/runs", json={"plan_date": "2026-11-11", "project_ids": ["orbit"]})
        assert run.status_code in (200, 201), run.text
        return [item for item in run.json()["data"]["candidates"] if item["source_type"] == "REPORT"]

    ingest("8101", "carry-test@example.test", "Carry Test")
    first = report_candidates()
    assert sorted(item["title"] for item in first) == ["Việc dự kiến ngày mai", "Việc đang làm chưa có Issue"]
    assert all(item["member_id"] == member["id"] and item["status"] == "PENDING_TRIAGE" for item in first)
    assert all(item["gitlab_issue_external_id"] is None and item["source_reference"] == "Daily Report 2026-11-10" for item in first)
    assert {item["title"]: item["requested_hours"] for item in first}["Việc dự kiến ngày mai"] == 3

    assert len(report_candidates()) == 2
    # A report that arrives after the run was created still reaches the editable run.
    ingest("8102", "carry-late@example.test", "Carry Late")
    later = report_candidates()
    assert len(later) == 4 and sum(item["member_id"] == late_member["id"] for item in later) == 2


def test_the_rescue_prompt_keeps_task_lines_whole() -> None:
    """Titles were coming back clipped mid-sentence: the model was told to be concise. It is now told to keep the line."""
    from app.services.ai_processor import REPORT_SYSTEM_PROMPT
    assert "exactly as the person wrote it" in REPORT_SYSTEM_PROMPT and "never shortened" in REPORT_SYSTEM_PROMPT
    assert "concise task title" not in REPORT_SYSTEM_PROMPT


def test_a_task_written_twice_in_one_report_is_one_task() -> None:
    """FR-EML-04: today's line and tomorrow's line for the same task merge; the furthest status stays, hours add up."""
    parsed = parse_daily_report(
        "DAILY REPORT | 2026-10-06 | Report Test | ORBIT",
        "ORBIT | Orbit\n\n"
        "[IN_PROGRESS] Kích hoạt giấy phép Envato | Thời gian: 1.5 giờ | Tiến độ: 40%\nBước tiếp theo: gửi mã cho khách\n\n"
        "[PLANNED] Kích hoạt giấy phép Envato. | Thời gian dự kiến: 2 giờ\nGitLab #31\n\n"
        "[PLANNED] Viết hướng dẫn cài đặt | Thời gian dự kiến: 1 giờ\n\n"
        "Tổng thời gian: 1.5 giờ\n",
    )
    titles = [item.title for item in parsed.items]
    assert titles == ["Kích hoạt giấy phép Envato", "Viết hướng dẫn cài đặt"], titles
    merged = parsed.items[0]
    assert merged.work_status == "IN_PROGRESS" and merged.worked_hours == 1.5 and merged.planned_hours == 2.0
    assert merged.gitlab_issue_external_id == "31" and merged.next_step == "gửi mã cho khách"
