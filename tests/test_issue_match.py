"""Finding the Issue behind reported work (FR-RPT-07, ADR-0054): the sure rules link by themselves, the rest is a
suggestion a person takes, and work that needs no Issue stops counting as missing."""
import hashlib
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import EmailMessage, GitLabIssueSnapshot, PlanningAssignment, PlanningRun, Project, ReportItem, User, WorkforceMember
from app.modules.planning.service import _canonical_hash
from app.modules.reports import issue_match
from app.modules.reports.issue_match import similarity, tokens

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
SENDER = "issue-match-test@example.test"


def _project_id() -> str:
    with get_session() as session:
        return str(session.scalar(select(Project).where(Project.code == "orbit")).id)


def _member() -> dict:
    with get_session() as session:
        existing = session.scalar(select(WorkforceMember).where(WorkforceMember.email_reference == SENDER))
        if existing is not None:
            return {"id": str(existing.id)}
    created = cto.post("/api/v1/planning/members", json={
        "display_name": "Issue Match Test", "email_reference": SENDER,
        "project_mappings": [{"project_id": _project_id(), "gitlab_user_external_id": "77", "role": "Developer"}],
    })
    assert created.status_code == 201, created.text
    return created.json()["data"]


def _issue(issue_id: str, title: str, assignees: list[str]) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=_project_id(), issue_external_id=issue_id, title=title, state="opened", labels=["priority:p2"],
            assignee_external_ids=assignees, milestone_external_id=None, milestone_title=None, due_date=None, web_url=None,
            payload_hash=hashlib.sha256(f"issue-match:{issue_id}".encode()).hexdigest(), is_current=True, fetched_at=now, last_seen_at=now,
        ))
        session.commit()


def _report(uid: str, day: str, body_items: str) -> dict:
    body = f"BÁO CÁO NGÀY\nNgày: {day} | Nhân sự: Issue Match Test | Tổng thời gian: 4 giờ\n\n=== ORBIT | Orbit ===\n{body_items}\n"
    response = cto.post("/api/v1/reports/daily/ingest", json={
        "mailbox": "report@example.test", "uid_validity": "20261013", "uid": uid, "message_id": f"<issue-match-{uid}@example.test>",
        "sender_address": SENDER, "sender_name": "Issue Match Test", "subject": f"DAILY REPORT | {day} | Issue Match Test | ORBIT",
        "body": body, "received_at": f"{day}T10:30:00Z",
    })
    assert response.status_code == 201, response.text
    return response.json()["data"]


def _items(report_id: str) -> list[dict]:
    detail = cto.get(f"/api/v1/reports/daily/{report_id}")
    assert detail.status_code == 200, detail.text
    return detail.json()["data"]["items"]


def _cleanup(member_id: str, issue_ids: list[str], run_ids: list[str]) -> None:
    with get_session() as session:
        for row in session.scalars(select(EmailMessage).where(EmailMessage.sender_address == SENDER)).all():
            for item in session.scalars(select(ReportItem).where(ReportItem.email_message_id == row.id)).all():
                session.delete(item)
            session.delete(row)
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id.in_(issue_ids), GitLabIssueSnapshot.project_id == _project_id())).all():
            session.delete(row)
        for run_id in run_ids:
            for row in session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run_id)).all():
                session.delete(row)
            run = session.get(PlanningRun, run_id)
            if run is not None:
                session.delete(run)
        session.commit()


def test_titles_compare_without_diacritics_and_forgive_a_short_title_inside_a_long_one() -> None:
    assert tokens("Hoàn thiện API thanh toán") == {"hoan", "thien", "api", "thanh", "toan"}
    assert similarity("Hoàn thiện API thanh toán", "Hoan thien API thanh toan") == 1.0
    assert similarity("Sửa lỗi đăng nhập", "Sửa lỗi đăng nhập trang quản trị sau ba lần sai") >= 0.8
    assert similarity("Viết tài liệu", "Sửa lỗi đăng nhập") == 0.0
    assert similarity("", "gì đó") == 0.0


def test_the_rules_link_what_is_sure_and_suggest_the_rest() -> None:
    member = _member()
    _issue("9501", "Hoàn thiện API thanh toán", ["77"])
    _issue("9502", "Sửa lỗi đăng nhập trang quản trị", [])
    run_ids: list[str] = []
    try:
        # Day one: the person wrote the number, so the item is linked from the text.
        first = _report("im-1", "2026-10-06", "[DONE] Hoàn thiện API thanh toán | Thời gian: 4 giờ | Tiến độ: 100%\nTham chiếu: GitLab #9501 | Plane: Không có | Intake: Không có")
        assert first["unlinked_items"] == 0
        # Day two: same work again without a number, plus a new item that only an open Issue resembles.
        second = _report("im-2", "2026-10-07", "[IN_PROGRESS] Hoàn thiện API thanh toán | Thời gian: 2 giờ | Tiến độ: 60%\n\n[DONE] Sửa lỗi đăng nhập | Thời gian: 2 giờ | Tiến độ: 100%\n\n[DONE] Họp với khách | Thời gian: 1 giờ | Tiến độ: 100%")
        items = {row["title"]: row for row in _items(second["id"])}
        assert items["Hoàn thiện API thanh toán"]["gitlab_issue"] == "9501" and items["Hoàn thiện API thanh toán"]["issue_link_source"] == "RULE_PREVIOUS"
        login = items["Sửa lỗi đăng nhập"]
        assert login["gitlab_issue"] is None
        assert login["issue_suggestions"] and login["issue_suggestions"][0]["issue"] == "9502" and login["issue_suggestions"][0]["source"] == "RULE_ISSUE"
        assert second["unlinked_items"] == 2
        # The person takes the suggestion for one and says the other needs no Issue.
        taken = cto.post(f"/api/v1/reports/daily/{second['id']}/items/{login['id']}/issue", json={"gitlab_issue": "9502"})
        assert taken.status_code == 200, taken.text
        meeting = items["Họp với khách"]
        marked = cto.post(f"/api/v1/reports/daily/{second['id']}/items/{meeting['id']}/issue", json={"no_issue_reason": "MEETING"})
        assert marked.status_code == 200, marked.text
        after = {row["title"]: row for row in marked.json()["data"]["items"]}
        assert after["Sửa lỗi đăng nhập"]["gitlab_issue"] == "9502" and after["Sửa lỗi đăng nhập"]["issue_link_source"] == "RULE_ISSUE"
        assert after["Họp với khách"]["no_issue_reason"] == "MEETING" and marked.json()["data"]["unlinked_items"] == 0
        # Day three (a date no other test plans for): one planned Issue, one reported piece of work, no title in common: the plan decides.
        with get_session() as session:
            cto_user = session.scalar(select(User).where(User.auth_subject == "cto"))
            now = datetime.now(timezone.utc)
            run = PlanningRun(
                id=str(uuid4()), plan_date=date(2031, 3, 10), timezone="Asia/Ho_Chi_Minh", project_scope=[_project_id()], scope_hash=_canonical_hash([_project_id()]),
                status="APPROVED", version=1, revision=1, source_snapshot_at=now, created_by=str(cto_user.id), created_at=now, updated_at=now,
            )
            session.add(run)
            session.flush()
            session.add(PlanningAssignment(
                id=str(uuid4()), planning_run_id=run.id, project_id=_project_id(), member_id=member["id"], slot="MORNING", work_type="DEVELOPMENT",
                is_primary=True, planned_hours=4, source_type="GITLAB", source_reference="#9502", gitlab_issue_external_id="9502",
            ))
            session.commit()
            run_ids.append(str(run.id))
        third = _report("im-3", "2031-03-10", "[DONE] Viết tài liệu cho phần đã sửa | Thời gian: 4 giờ | Tiến độ: 100%")
        doc = _items(third["id"])[0]
        assert doc["gitlab_issue"] == "9502" and doc["issue_link_source"] == "RULE_PLAN"
        assert doc["issue_suggestions"][0]["confidence"] == 0.95
    finally:
        _cleanup(member["id"], ["9501", "9502"], run_ids)


def test_ai_answers_only_suggest_and_the_sure_button_takes_what_is_sure() -> None:
    member = _member()
    _issue("9503", "Tối ưu truy vấn báo cáo tuần", [])
    try:
        report = _report("im-4", "2026-10-09", "[DONE] Làm nhanh phần thống kê | Thời gian: 3 giờ | Tiến độ: 100%\n\n[IN_PROGRESS] Việc chưa rõ | Thời gian: 1 giờ | Tiến độ: 10%")
        items = {row["title"]: row for row in _items(report["id"])}
        fast, vague = items["Làm nhanh phần thống kê"], items["Việc chưa rõ"]
        assert fast["gitlab_issue"] is None
        context = issue_match.ai_context(report["id"], [fast["id"], vague["id"]])
        assert context is not None and {row["title"] for row in context["items"]} == {"Làm nhanh phần thống kê", "Việc chưa rõ"}
        assert any(row["issue"] == "9503" for row in context["issues"])
        applied = issue_match.apply_ai_matches(report["id"], [
            {"item_id": fast["id"], "issue": "#9503", "confidence": 0.99, "reason": "cùng phần thống kê"},
            {"item_id": vague["id"], "issue": "424242", "confidence": 0.2, "reason": "đoán"},
        ], provider="UMODELVERSE", model="test")
        assert applied == 1
        items = {row["title"]: row for row in _items(report["id"])}
        best = items["Làm nhanh phần thống kê"]["issue_suggestions"][0]
        assert best["source"] == "AI" and best["issue"] == "9503" and best["confidence"] == 0.85
        assert items["Làm nhanh phần thống kê"]["gitlab_issue"] is None
        # 0.85 is below the sure line, so the bulk button leaves it; a suggestion at 0.9 goes.
        with get_session() as session:
            row = session.get(ReportItem, vague["id"])
            row.issue_suggestions = [{"issue": "9503", "title": "x", "source": "RULE_ISSUE", "confidence": 0.9}]
            session.commit()
        bulk = cto.post(f"/api/v1/reports/daily/{report['id']}/link-sure")
        assert bulk.status_code == 200, bulk.text
        after = {row["title"]: row for row in bulk.json()["data"]["items"]}
        assert after["Việc chưa rõ"]["gitlab_issue"] == "9503" and after["Làm nhanh phần thống kê"]["gitlab_issue"] is None
        again = cto.post(f"/api/v1/reports/daily/{report['id']}/suggest-issues")
        assert again.status_code == 200, again.text
        assert again.json()["data"]["items"] == 1
        assert cto.post("/api/v1/reports/issue-suggestions/backfill?days=30").status_code == 200
        assert owner.post("/api/v1/reports/issue-suggestions/backfill").status_code == 403
    finally:
        _cleanup(member["id"], ["9503"], [])
