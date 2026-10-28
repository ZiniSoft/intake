"""Adding work to an open Planning Run in one step (ADR-0024)."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db import get_session
from app.main import app
from app.models import ApprovalAction, GitLabIssueSnapshot, IntakeItem, Project, ProjectIntegration, SyncJob
from app.workers import integration_tasks


client = TestClient(app, headers={"X-User-Subject": "cto"})
DAY = "2026-12-29"


def _issue(project_code: str, issue_id: str, title: str) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == project_code))
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=project.id, issue_external_id=issue_id, title=title, state="opened",
            labels=["priority:p2"], assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None,
            web_url=None, payload_hash=hashlib.sha256(f"add-work:{issue_id}".encode()).hexdigest(),
            is_current=True, fetched_at=now, last_seen_at=now,
        ))
        session.commit()


def _delivery_sync(project_code: str, enabled: bool) -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == project_code))
        mapping = session.scalar(select(ProjectIntegration).where(ProjectIntegration.project_id == project.id, ProjectIntegration.system == "GITLAB"))
        mapping.enabled = enabled
        session.commit()


def _run() -> dict:
    return client.post("/api/v1/planning/runs", json={"plan_date": DAY, "project_ids": ["orbit"]}).json()["data"]


def _add(run: dict, **body):
    return client.post(f"/api/v1/planning/runs/{run['id']}/work", json={"expected_run_version": _run()["version"], "project_id": "orbit", **body})


def test_existing_and_new_work_reach_todays_plan_in_one_step(monkeypatch) -> None:
    member = client.post("/api/v1/planning/members", json={
        "display_name": "Add Work Dev", "email_reference": "add.work@example.test",
        "project_mappings": [{"project_id": "orbit", "gitlab_user_external_id": "501"}],
    }).json()["data"]
    _issue("orbit", "7001", "Sửa lỗi xuất báo cáo tuần")
    _issue("orbit", "7002", "Tối ưu trang thống kê")
    run = _run()
    assert run["assignments"] == []

    # Find the work by a few words of its title or by its number; no ID has to be remembered.
    found = client.get(f"/api/v1/planning/runs/{run['id']}/work-items?search=báo cáo").json()["data"]
    assert [(row["kind"], row["issue_external_id"], row["already_planned"]) for row in found] == [("ISSUE", "7001", False)]
    assert client.get(f"/api/v1/planning/runs/{run['id']}/work-items?search=%237002").json()["data"][0]["title"] == "Tối ưu trang thống kê"

    # One step: choose the Issue, the person, the slot and the hours.
    planned = _add(run, source="ISSUE", issue_external_id="7001", member_id=member["id"], slot="MORNING", planned_hours=3)
    assert planned.status_code == 201, planned.text
    assert planned.json()["data"]["state"] == "PLANNED" and planned.json()["data"]["candidate"]["status"] == "ASSIGNED"
    assert planned.json()["data"]["added_as_secondary"] is False
    assignments = _run()["assignments"]
    assert [(a["gitlab_issue_external_id"], a["member_id"], a["slot"], a["planned_hours"]) for a in assignments] == [("7001", member["id"], "MORNING", 3)]
    assert client.get(f"/api/v1/planning/runs/{run['id']}/work-items?search=7001").json()["data"][0]["already_planned"] is True

    # Without a person the work waits in the run; an assignment that does not fit is reported, not lost.
    waiting = _add(run, source="ISSUE", issue_external_id="7002")
    assert waiting.json()["data"]["state"] == "WAITING_ASSIGNMENT" and waiting.json()["data"]["assignment_error"] is None
    too_much = _add(run, source="ISSUE", issue_external_id="7002", member_id=member["id"], slot="MORNING", planned_hours=4)
    assert too_much.json()["data"]["state"] == "WAITING_ASSIGNMENT" and too_much.json()["data"]["assignment_error"] == "SLOT_OVER_CAPACITY"
    assert "ASSIGNMENT_INCOMPLETE" in _add(run, source="ISSUE", issue_external_id="7002", member_id=member["id"]).text

    # New work that exists nowhere: refused without a reason or without a tracker, and nothing is created.
    with get_session() as session:
        before = session.scalar(select(func.count()).select_from(IntakeItem))
    new_work = {"source": "NEW", "title": "Khách báo không gửi được OTP", "content": "Từ 8h30 khách không nhận được OTP khi đăng nhập.", "item_type": "BUG", "priority": "P1",
                "member_id": member["id"], "slot": "AFTERNOON", "planned_hours": 2}
    assert "ADD_WORK_REASON_REQUIRED" in _add(run, **new_work).text
    assert "DELIVERY_SYNC_DISABLED" in _add(run, **new_work, reason="Khách đang không đăng nhập được").text
    assert "WORK_TITLE_REQUIRED" in _add(run, **{**new_work, "title": "  "}, reason="Khách đang không đăng nhập được").text
    with get_session() as session:
        assert session.scalar(select(func.count()).select_from(IntakeItem)) == before

    _delivery_sync("orbit", True)
    try:
        created = _add(run, **new_work, reason="Khách đang không đăng nhập được")
        assert created.status_code == 201, created.text
        data = created.json()["data"]
        assert data["state"] == "CREATING_ISSUE" and data["candidate"]["status"] == "PENDING_TRIAGE" and data["candidate"]["member_id"] == member["id"]
        intake_id = data["candidate"]["intake_id"]
        with get_session() as session:
            item = session.get(IntakeItem, intake_id)
            # The CTO's confirmation is recorded as the approval, with the reason.
            assert item.status in ("APPROVED", "SYNC_PENDING") and item.approved_route == "GITLAB" and item.approved_priority == "P1" and item.item_type == "BUG"
            action = session.scalar(select(ApprovalAction).where(ApprovalAction.intake_id == intake_id))
            assert action.source == "PLANNING"
            assert action.action == "APPROVE" and "Khách đang không đăng nhập được" in action.reason
            job = session.scalar(select(SyncJob).where(SyncJob.intake_id == intake_id))
            assert job.target_system == "GITLAB" and job.status == "PENDING"
            job_id = str(job.id)
        assert len(_run()["assignments"]) == 1

        async def fake_sync(context):
            assert context.approved["title"] == "Khách báo không gửi được OTP"
            return {"id": "7100", "global_id": 99100, "web_url": "https://gitlab.test/orbit/-/issues/7100"}, False

        monkeypatch.setattr(integration_tasks, "_sync_gitlab", fake_sync)
        assert integration_tasks.sync_external.run(job_id) == "SUCCEEDED"
        # As soon as the Issue exists it is plannable and the remembered assignment is made.
        after = _run()
        new_assignment = next(a for a in after["assignments"] if a["gitlab_issue_external_id"] == "7100")
        assert (new_assignment["member_id"], new_assignment["slot"], new_assignment["planned_hours"]) == (member["id"], "AFTERNOON", 2)
        # The person already had a main Issue, so the urgent work sits next to it as secondary work.
        assert new_assignment["is_primary"] is False and assignments[0]["is_primary"] is True
        candidate = next(c for c in after["candidates"] if c["intake_id"] == intake_id)
        assert candidate["status"] == "ASSIGNED" and candidate["gitlab_issue_external_id"] == "7100"
        # The waiting line shows when the Intake was created, not when the entry was listed today.
        assert candidate["intake_public_id"].startswith("ORB-") and candidate["origin_at"] is not None
        assert candidate["origin_at"] <= candidate["created_at"]
        with get_session() as session:
            snapshot = session.scalar(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == "7100", GitLabIssueSnapshot.is_current.is_(True)))
            assert snapshot.state == "opened" and snapshot.labels == ["priority:p1"] and snapshot.title == "Khách báo không gửi được OTP"
        assert client.get(f"/api/v1/planning/runs/{run['id']}/work-items?search=OTP").json()["data"][0]["already_planned"] is True

        # An Intake that is still waiting for approval can be picked the same way.
        intake = client.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Cần thêm nút tải lại danh sách"}).json()["data"]
        with get_session() as session:
            item = session.get(IntakeItem, intake["id"])
            item.status, item.item_type, item.normalized_title, item.normalized_summary = "PENDING_APPROVAL", "TASK", "Thêm nút tải lại danh sách", "Cần thêm nút tải lại danh sách."
            session.commit()
        listed = client.get(f"/api/v1/planning/runs/{run['id']}/work-items?search=tải lại").json()["data"]
        assert [(row["kind"], row["needs_issue"]) for row in listed] == [("INTAKE", True)]
        picked = _add(run, source="INTAKE", intake_id=intake["id"], priority="P2", reason="Đã trao đổi trực tiếp với khách")
        assert picked.status_code == 201 and picked.json()["data"]["state"] == "CREATING_ISSUE"
    finally:
        _delivery_sync("orbit", False)

    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.get(f"/api/v1/planning/runs/{run['id']}/work-items").status_code == 404
    assert owner.post(f"/api/v1/planning/runs/{run['id']}/work", json={"expected_run_version": 1, "project_id": "orbit", "source": "ISSUE", "issue_external_id": "7001"}).status_code == 404
    assert client.get("/api/v1/planning/runs/00000000-0000-4000-8000-00000000dead/work-items").status_code == 404


def test_waiting_work_can_be_linked_created_dismissed_and_restored(monkeypatch) -> None:
    from app.models import PlanningCandidate, PlanningRun

    member = client.post("/api/v1/planning/members", json={
        "display_name": "Waiting Dev", "email_reference": "waiting.dev@example.test",
        "project_mappings": [{"project_id": "orbit", "gitlab_user_external_id": "502"}],
    }).json()["data"]
    _issue("orbit", "7201", "Gộp nhánh phát hành")
    day = "2026-12-30"
    run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]

    def current() -> dict:
        return client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]

    # Two entries without an Issue, as a daily report produces them.
    now = datetime.now(timezone.utc)
    ids = []
    with get_session() as session:
        row = session.get(PlanningRun, run["id"])
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        for title in ("Gộp nhánh single-school-v5", "Chốt bản phát hành 5.0.0"):
            candidate = PlanningCandidate(
                id=str(uuid4()), planning_run_id=row.id, project_id=project.id, member_id=member["id"], source_type="REPORT",
                source_reference="Daily Report 2026-12-29", title=title, summary="Trạng thái báo cáo: PLANNED", status="PENDING_TRIAGE",
                created_by=row.created_by, created_at=now, updated_at=now,
            )
            session.add(candidate)
            ids.append(candidate.id)
        session.commit()
    base = f"/api/v1/planning/runs/{run['id']}/candidates"
    assign = {"member_id": member["id"], "slot": "MORNING", "planned_hours": 2}

    # The work usually has an Issue already and the report just did not name it: link it.
    assert "WORK_REFERENCE_REQUIRED" in client.post(f"{base}/{ids[0]}/assign", json={"expected_run_version": current()["version"], **assign}).text
    linked = client.post(f"{base}/{ids[0]}/assign", json={"expected_run_version": current()["version"], **assign, "issue_external_id": "#7201"})
    assert linked.status_code == 200, linked.text
    assert linked.json()["data"]["state"] == "PLANNED" and linked.json()["data"]["candidate"]["gitlab_issue_external_id"] == "7201"
    assert [(a["gitlab_issue_external_id"], a["slot"], a["planned_hours"]) for a in current()["assignments"]] == [("7201", "MORNING", 2)]

    # Dismissing hides an entry from this day's plan; it can be brought back.
    dismissed = client.post(f"{base}/{ids[1]}/dismiss")
    assert dismissed.status_code == 200 and dismissed.json()["data"]["status"] == "REJECTED"
    assert client.post(f"{base}/{ids[1]}/restore").json()["data"]["status"] == "PENDING_TRIAGE"
    assert "CANDIDATE_ALREADY_PLANNED" in client.post(f"{base}/{ids[0]}/dismiss").text
    assert client.post(f"{base}/{ids[1]}/delete").status_code == 422

    # Or there really is no Issue: one is created, with a reason, and the work is assigned when it exists.
    create = {"expected_run_version": current()["version"], **assign, "slot": "AFTERNOON", "issue_mode": "CREATE", "priority": "P2"}
    assert "ADD_WORK_REASON_REQUIRED" in client.post(f"{base}/{ids[1]}/assign", json=create).text
    with get_session() as session:
        assert session.get(PlanningCandidate, ids[1]).intake_id is None
    _delivery_sync("orbit", True)
    try:
        started = client.post(f"{base}/{ids[1]}/assign", json={**create, "expected_run_version": current()["version"], "reason": "Việc đã thống nhất trong buổi họp sáng"})
        assert started.status_code == 200, started.text
        data = started.json()["data"]
        assert data["state"] == "CREATING_ISSUE" and data["candidate"]["id"] == ids[1] and data["candidate"]["intake_id"]
        with get_session() as session:
            job_id = str(session.scalar(select(SyncJob.id).where(SyncJob.intake_id == data["candidate"]["intake_id"])))

        async def fake_sync(context):
            assert context.approved["title"] == "Chốt bản phát hành 5.0.0"
            return {"id": "7300", "global_id": 99300, "web_url": "https://gitlab.test/orbit/-/issues/7300"}, False

        monkeypatch.setattr(integration_tasks, "_sync_gitlab", fake_sync)
        assert integration_tasks.sync_external.run(job_id) == "SUCCEEDED"
    finally:
        _delivery_sync("orbit", False)
    after = current()
    # Same entry, now planned; no duplicate entry was made for it.
    assert sorted((a["gitlab_issue_external_id"], a["slot"], a["is_primary"]) for a in after["assignments"]) == [("7201", "MORNING", True), ("7300", "AFTERNOON", False)]
    assert [c["status"] for c in after["candidates"] if c["id"] in ids] == ["ASSIGNED", "ASSIGNED"] and len([c for c in after["candidates"] if c["title"] == "Chốt bản phát hành 5.0.0"]) == 1
    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.post(f"{base}/{ids[1]}/dismiss").status_code == 404


def test_request_journey_links_intake_issue_and_plan() -> None:
    from app.models import ExternalLink

    created = client.post("/api/v1/intakes", json={"project_id": "orbit", "channel": "ZALO", "raw_text": "Hành trình của một yêu cầu"}).json()["data"]
    start = client.get(f"/api/v1/intakes/{created['id']}/journey")
    assert start.status_code == 200, start.text
    data = start.json()["data"]
    assert data["channel"] == "ZALO" and data["decision"] is None and data["issue"] is None and data["plans"] == [] and data["waiting_in_plan"] is None

    # The synced request of the first test: approved by the CTO, has an Issue, sits in a plan that is not settled yet.
    with get_session() as session:
        link = session.scalar(select(ExternalLink).where(ExternalLink.external_id == "7100"))
        intake_id = str(link.intake_id)
    journey = client.get(f"/api/v1/intakes/{intake_id}/journey").json()["data"]
    assert journey["decision"]["action"] == "APPROVE" and journey["decision"]["route"] == "GITLAB" and journey["decision"]["by"]
    assert journey["issue"] == {"system": "GITLAB", "external_id": "7100", "url": "https://gitlab.test/orbit/-/issues/7100"}
    assert [(p["plan_date"], p["member_name"], p["slot"], p["planned_hours"], p["settled"]) for p in journey["plans"]] == [(DAY, "Add Work Dev", "AFTERNOON", 2, False)]

    # And the plan points back at the request it came from.
    run = _run()
    from_intake = next(a for a in run["assignments"] if a["gitlab_issue_external_id"] == "7100")
    assert from_intake["intake_id"] == intake_id and from_intake["intake_public_id"].startswith("ORB-")
    assert next(a for a in run["assignments"] if a["gitlab_issue_external_id"] == "7001")["intake_id"] is None

    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.get(f"/api/v1/intakes/{intake_id}/journey").status_code == 404
    assert client.get("/api/v1/intakes/00000000-0000-4000-8000-00000000dead/journey").status_code == 404


def test_approvals_are_counted_by_where_they_were_given() -> None:
    weeks = client.get("/api/v1/approvals/sources?weeks=2").json()["data"]
    assert len(weeks) == 2 and weeks[0]["week_start"] > weeks[1]["week_start"]
    with get_session() as session:
        approvals = session.scalars(select(ApprovalAction).where(ApprovalAction.action == "APPROVE")).all()
    recent = sum(week["from_queue"] + week["from_planning"] for week in weeks)
    assert recent == len(approvals)
    assert sum(week["from_planning"] for week in weeks) == sum(1 for action in approvals if action.source == "PLANNING") >= 1
    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.get("/api/v1/approvals/sources").status_code == 403


def test_issue_picker_offers_the_persons_and_similar_issues_first() -> None:
    """Scheduling a waiting entry: likely Issues first, with who has them and where to open them (FR-PLAN-16)."""
    from datetime import date

    from app.models import PlanningCandidate, User, WorkforceMember, WorkforceProjectMembership

    day = "2026-12-30"
    run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        author = WorkforceMember(id=str(uuid4()), display_name="Picker Author", status="ACTIVE", default_weekday_hours=8, created_at=now, updated_at=now)
        other = WorkforceMember(id=str(uuid4()), display_name="Picker Other", status="ACTIVE", default_weekday_hours=8, created_at=now, updated_at=now)
        session.add_all([author, other])
        session.flush()
        session.add_all([
            WorkforceProjectMembership(id=str(uuid4()), member_id=author.id, project_id=project.id, gitlab_user_external_id="9101", active=True, created_at=now),
            WorkforceProjectMembership(id=str(uuid4()), member_id=other.id, project_id=project.id, gitlab_user_external_id="9102", active=True, created_at=now),
        ])

        def issue(number: str, title: str, assignees: list[str], **extra) -> None:
            session.add(GitLabIssueSnapshot(
                id=str(uuid4()), project_id=project.id, issue_external_id=number, title=title, state="opened", labels=["priority:p2"],
                assignee_external_ids=assignees, milestone_external_id=None, milestone_title=extra.get("milestone"), due_date=extra.get("due"),
                web_url=f"https://gitlab.test/orbit/-/issues/{number}", payload_hash=hashlib.sha256(f"picker:{number}".encode()).hexdigest(),
                is_current=True, fetched_at=now, last_seen_at=now,
            ))

        issue("9201", "Trang thanh toán bị treo khi tải", ["9102"])
        issue("9202", "Viết hướng dẫn cài đặt production cho khách", [], milestone="v2.1", due=date(2026, 12, 31))
        issue("9203", "Dọn log cũ", ["9101"])
        candidate = PlanningCandidate(
            id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=author.id, source_type="REPORT",
            source_reference=f"picker-{uuid4().hex[:8]}", title="Hướng dẫn cài production và chốt ngày phát hành", status="PENDING_TRIAGE",
            created_by=session.scalar(select(User.id).where(User.auth_subject == "cto")), created_at=now, updated_at=now,
        )
        session.add(candidate)
        session.commit()
        candidate_id = str(candidate.id)

    rows = client.get(f"/api/v1/planning/runs/{run['id']}/work-items?candidate_id={candidate_id}").json()["data"]
    assert all(row["kind"] == "ISSUE" for row in rows)
    mine = [row for row in rows if row["issue_external_id"] in ("9201", "9202", "9203")]
    assert [row["issue_external_id"] for row in mine] == ["9203", "9202", "9201"]
    by_id = {row["issue_external_id"]: row for row in mine}
    # The author's own Issue first, then the one about the same thing, then somebody else's.
    assert (by_id["9203"]["suggested"], by_id["9203"]["assignee_names"]) == ("PERSON", ["Picker Author"])
    assert (by_id["9202"]["suggested"], by_id["9202"]["milestone"], by_id["9202"]["due_date"]) == ("TITLE", "v2.1", "2026-12-31")
    assert (by_id["9201"]["suggested"], by_id["9201"]["assigned_to_other"], by_id["9201"]["assignee_names"]) == (None, True, ["Picker Other"])
    assert by_id["9202"]["url"] == "https://gitlab.test/orbit/-/issues/9202"
    # Without a waiting entry the list is unchanged in kind and carries the same extra facts.
    plain = client.get(f"/api/v1/planning/runs/{run['id']}/work-items?search=9202").json()["data"]
    assert plain[0]["url"].endswith("/9202") and plain[0]["suggested"] is None
    # Other tests plan this project from its open Issues; leave none of these behind.
    with get_session() as session:
        for snapshot in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id.in_(("9201", "9202", "9203")))):
            session.delete(snapshot)
        for membership in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.gitlab_user_external_id.in_(("9101", "9102")))):
            session.delete(membership)
        for member in session.scalars(select(WorkforceMember).where(WorkforceMember.display_name.in_(("Picker Author", "Picker Other")))):
            member.status = "INACTIVE"
        session.commit()


def test_assignment_moves_between_morning_and_afternoon() -> None:
    """Work already placed can change half of the day; the four-hour limit of a half still holds (FR-PLAN-04)."""
    from app.models import AuditEvent, PlanningAssignment, WorkforceMember

    day = "2026-12-31"
    run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
    base = f"/api/v1/planning/runs/{run['id']}"
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        member = WorkforceMember(id=str(uuid4()), display_name="Mover", status="ACTIVE", default_weekday_hours=8, created_at=now, updated_at=now)
        session.add(member)
        session.flush()

        def place(slot: str, hours: float, issue: str) -> str:
            row = PlanningAssignment(
                id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=member.id, slot=slot, work_type="DEVELOPMENT",
                is_primary=False, planned_hours=hours, source_type="GITLAB", source_reference=f"move-{issue}", gitlab_issue_external_id=issue,
                version=1, created_at=now, updated_at=now,
            )
            session.add(row)
            return str(row.id)

        small, big, afternoon = place("MORNING", 1, "9301"), place("MORNING", 3, "9302"), place("AFTERNOON", 2, "9303")
        session.commit()
    version = client.get(base).json()["data"]["version"]

    moved = client.post(f"{base}/assignments/{small}/move", json={"expected_run_version": version, "slot": "AFTERNOON"})
    assert moved.status_code == 200, moved.text
    data = moved.json()["data"]
    assert next(a for a in data["assignments"] if a["id"] == small)["slot"] == "AFTERNOON" and data["version"] == version + 1
    # 3h more would make the afternoon 6h for this person.
    full = client.post(f"{base}/assignments/{big}/move", json={"expected_run_version": data["version"], "slot": "AFTERNOON"})
    assert full.status_code == 422 and "SLOT_OVER_CAPACITY" in full.text
    # A stale page is told to reload; moving to where it already is changes nothing.
    assert "PLANNING_VERSION_CONFLICT" in client.post(f"{base}/assignments/{afternoon}/move", json={"expected_run_version": version, "slot": "MORNING"}).text
    same = client.post(f"{base}/assignments/{afternoon}/move", json={"expected_run_version": data["version"], "slot": "AFTERNOON"})
    assert same.status_code == 200 and same.json()["data"]["version"] == data["version"]
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "planning.assignment.moved", AuditEvent.entity_id == small)).details["to"] == "AFTERNOON"
    owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert owner.post(f"{base}/assignments/{small}/move", json={"expected_run_version": data["version"], "slot": "MORNING"}).status_code == 404


def test_assignment_moves_to_another_project_member() -> None:
    """Dropping a card on another person's cell changes both the member and tracker assignee (FR-PLAN-04)."""
    from app.models import (
        AuditEvent,
        PlanningAssignment,
        PlanningCandidate,
        PlanningWarning,
        WorkforceMember,
        WorkforceProjectMembership,
    )

    day = "2027-01-06"
    run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
    base = f"/api/v1/planning/runs/{run['id']}"
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        source = WorkforceMember(id=str(uuid4()), display_name="Drag Source", status="ACTIVE", default_weekday_hours=8, created_at=now, updated_at=now)
        target = WorkforceMember(id=str(uuid4()), display_name="Drag Target", status="ACTIVE", default_weekday_hours=8, created_at=now, updated_at=now)
        session.add_all((source, target))
        session.flush()
        session.add_all((
            WorkforceProjectMembership(id=str(uuid4()), member_id=source.id, project_id=project.id, gitlab_user_external_id="9501", active=True, created_at=now),
            WorkforceProjectMembership(id=str(uuid4()), member_id=target.id, project_id=project.id, gitlab_user_external_id="9502", active=True, created_at=now),
        ))
        assignment = PlanningAssignment(
            id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=source.id, slot="MORNING", work_type="DEVELOPMENT",
            is_primary=False, planned_hours=2, source_type="GITLAB", source_reference="move-person-9501", gitlab_issue_external_id="9501",
            proposed_assignee_external_id="9501", approved_assignee_external_id="9501", version=1, created_at=now, updated_at=now,
        )
        session.add(assignment)
        session.flush()
        session.add_all((
            PlanningCandidate(
                id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=source.id, intake_id=None, assignment_id=assignment.id,
                source_type="GITLAB", source_reference="move-person-9501", gitlab_issue_external_id="9501", title="Kéo sang người khác",
                summary=None, status="ASSIGNED", requested_hours=2, target_slot="MORNING", idempotency_key_hash=None, request_hash=None,
                created_by="00000000-0000-4000-8000-000000000001", created_at=now, updated_at=now,
            ),
            PlanningWarning(
                id=str(uuid4()), planning_run_id=run["id"], assignment_id=assignment.id, member_id=source.id, project_id=project.id,
                code="GITLAB_DUE_DATE_MISSING", severity="WARNING", source_values={}, message="x", created_at=now,
            ),
        ))
        session.commit()
        assignment_id, source_id, target_id = str(assignment.id), str(source.id), str(target.id)

    version = client.get(base).json()["data"]["version"]
    moved = client.post(
        f"{base}/assignments/{assignment_id}/move",
        json={"expected_run_version": version, "slot": "AFTERNOON", "member_id": target_id},
    )
    assert moved.status_code == 200, moved.text
    data = moved.json()["data"]
    row = next(item for item in data["assignments"] if item["id"] == assignment_id)
    assert (row["member_id"], row["slot"]) == (target_id, "AFTERNOON")
    assert (row["proposed_assignee_external_id"], row["approved_assignee_external_id"]) == ("9502", "9502")
    candidate = next(item for item in data["candidates"] if item["assignment_id"] == assignment_id)
    warning = next(item for item in data["warnings"] if item["assignment_id"] == assignment_id)
    assert (candidate["member_id"], candidate["target_slot"], warning["member_id"]) == (target_id, "AFTERNOON", target_id)
    with get_session() as session:
        audit = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "planning.assignment.moved", AuditEvent.entity_id == assignment_id))
        assert audit.details == {
            "run_id": run["id"], "from": "MORNING", "to": "AFTERNOON",
            "from_member_id": source_id, "to_member_id": target_id,
            "override_reason": None,
        }
        for member in session.scalars(select(WorkforceMember).where(WorkforceMember.display_name.in_(("Drag Source", "Drag Target")))).all():
            member.status = "INACTIVE"
        session.commit()


def test_assignment_move_to_overloaded_member_requires_and_audits_planner_override() -> None:
    """A planner can confirm an overloaded cross-person drop, but the first attempt must be blocked."""
    from app.models import AuditEvent, PlanningAssignment, WorkforceMember, WorkforceProjectMembership

    day = "2027-01-07"
    run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
    base = f"/api/v1/planning/runs/{run['id']}"
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        source = WorkforceMember(id=str(uuid4()), display_name="Override Source", status="ACTIVE", default_weekday_hours=8, created_at=now, updated_at=now)
        target = WorkforceMember(id=str(uuid4()), display_name="Override Target", status="ACTIVE", default_weekday_hours=1, created_at=now, updated_at=now)
        session.add_all((source, target))
        session.flush()
        session.add_all((
            WorkforceProjectMembership(id=str(uuid4()), member_id=source.id, project_id=project.id, gitlab_user_external_id="9601", active=True, created_at=now),
            WorkforceProjectMembership(id=str(uuid4()), member_id=target.id, project_id=project.id, gitlab_user_external_id="9602", active=True, created_at=now),
        ))
        assignment = PlanningAssignment(
            id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=source.id, slot="MORNING", work_type="DEVELOPMENT",
            is_primary=False, planned_hours=2, source_type="GITLAB", source_reference="move-override-9601", gitlab_issue_external_id="9601",
            proposed_assignee_external_id="9601", approved_assignee_external_id="9601", version=1, created_at=now, updated_at=now,
        )
        session.add(assignment)
        session.commit()
        assignment_id, target_id = str(assignment.id), str(target.id)

    version = client.get(base).json()["data"]["version"]
    blocked = client.post(
        f"{base}/assignments/{assignment_id}/move",
        json={"expected_run_version": version, "slot": "AFTERNOON", "member_id": target_id},
    )
    assert blocked.status_code == 422 and "OVER_CAPACITY" in blocked.text

    reason = "Người xếp việc xác nhận đổi người dù vượt giới hạn giờ trong ngày"
    moved = client.post(
        f"{base}/assignments/{assignment_id}/move",
        json={"expected_run_version": version, "slot": "AFTERNOON", "member_id": target_id, "override_reason": reason},
    )
    assert moved.status_code == 200, moved.text
    row = next(item for item in moved.json()["data"]["assignments"] if item["id"] == assignment_id)
    assert (row["member_id"], row["slot"], row["override_reason"]) == (target_id, "AFTERNOON", reason)
    with get_session() as session:
        audit = session.scalar(select(AuditEvent).where(AuditEvent.event_type == "planning.assignment.moved", AuditEvent.entity_id == assignment_id))
        assert audit.details["override_reason"] == reason
        for member in session.scalars(select(WorkforceMember).where(WorkforceMember.display_name.in_(("Override Source", "Override Target")))).all():
            member.status = "INACTIVE"
        session.commit()


def test_placed_work_goes_back_to_the_waiting_list_while_the_day_is_open() -> None:
    """Something more urgent came up: a placed Issue returns to "waiting", with its priority and hours, without the person (FR-PLAN-16)."""
    from app.models import AuditEvent, PlanningAssignment, PlanningCandidate, PlanningWarning, WorkforceMember

    day = "2027-01-20"
    run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": ["orbit"]}).json()["data"]
    base = f"/api/v1/planning/runs/{run['id']}"
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "orbit"))
        member = WorkforceMember(id=str(uuid4()), display_name="Unassign Test", status="ACTIVE", default_weekday_hours=8, created_at=now, updated_at=now)
        session.add(member)
        session.flush()
        placed = PlanningAssignment(
            id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=member.id, slot="MORNING", work_type="DEVELOPMENT",
            is_primary=True, planned_hours=4, source_type="GITLAB", source_reference="unassign-9401", gitlab_issue_external_id="9401",
            proposed_priority="P1", version=1, created_at=now, updated_at=now,
        )
        session.add(placed)
        session.flush()
        session.add(PlanningWarning(
            id=str(uuid4()), planning_run_id=run["id"], assignment_id=placed.id, member_id=member.id, project_id=project.id,
            code="GITLAB_MILESTONE_MISSING", severity="WARNING", source_values={}, message="x", created_at=now,
        ))
        # A second one came through the waiting list and still points at its candidate.
        through = PlanningAssignment(
            id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=member.id, slot="AFTERNOON", work_type="DEVELOPMENT",
            is_primary=False, planned_hours=2, source_type="GITLAB", source_reference="unassign-9402", gitlab_issue_external_id="9402",
            version=1, created_at=now, updated_at=now,
        )
        session.add(through)
        session.flush()
        session.add(PlanningCandidate(
            id=str(uuid4()), planning_run_id=run["id"], project_id=project.id, member_id=member.id, intake_id=None, assignment_id=through.id,
            source_type="GITLAB", source_reference="unassign-9402", gitlab_issue_external_id="9402", title="Việc qua danh sách chờ",
            summary=None, status="ASSIGNED", proposed_priority="P2", requested_hours=2, target_slot="AFTERNOON", idempotency_key_hash=None,
            request_hash=None, created_by=run["id"][:0] or "00000000-0000-4000-8000-000000000001", created_at=now, updated_at=now,
        ))
        session.commit()
        placed_id, through_id = placed.id, through.id
    version = client.get(base).json()["data"]["version"]

    back = client.post(f"{base}/assignments/{placed_id}/unassign", json={"expected_run_version": version})
    assert back.status_code == 200, back.text
    data = back.json()["data"]
    assert data["version"] == version + 1 and all(a["id"] != placed_id for a in data["assignments"])
    waiting = next(c for c in data["candidates"] if c["gitlab_issue_external_id"] == "9401")
    assert (waiting["status"], waiting["member_id"], waiting["proposed_priority"], waiting["requested_hours"]) == ("READY", None, "P1", 4.0)
    assert all(w["assignment_id"] != placed_id for w in data["warnings"]), "warnings of the removed placement go with it"

    again = client.post(f"{base}/assignments/{through_id}/unassign", json={"expected_run_version": data["version"]}).json()["data"]
    restored = next(c for c in again["candidates"] if c["gitlab_issue_external_id"] == "9402")
    assert restored["status"] == "READY" and restored["assignment_id"] is None and restored["member_id"] is None and restored["title"] == "Việc qua danh sách chờ"
    assert len([c for c in again["candidates"] if c["gitlab_issue_external_id"] == "9402"]) == 1, "the candidate it came from is reused, not doubled"

    assert "PLANNING_VERSION_CONFLICT" in client.post(f"{base}/assignments/{through_id}/unassign", json={"expected_run_version": version}).text
    assert client.post(f"{base}/assignments/{placed_id}/unassign", json={"expected_run_version": again["version"]}).status_code == 422
    with get_session() as session:
        assert session.scalar(select(AuditEvent).where(AuditEvent.event_type == "planning.assignment.unassigned", AuditEvent.entity_id == run["id"])) is not None
        for row in session.scalars(select(WorkforceMember).where(WorkforceMember.display_name == "Unassign Test")).all():
            row.status = "INACTIVE"
        session.commit()


def test_new_work_survives_the_plan_changing_while_its_issue_is_requested(monkeypatch) -> None:
    """The plan version moves between approving the Intake and listing it (another Issue finishing, another planner):
    the new work must still land once, not fail after the Intake is already approved."""
    from app.models import PlanningRun
    from app.modules.planning.add_work import add_work_service

    run = client.post("/api/v1/planning/runs", json={"plan_date": "2026-12-30", "project_ids": ["orbit"]}).json()["data"]
    original = add_work_service._start_issue

    def start_then_bump(*args, **kwargs):
        original(*args, **kwargs)
        with get_session() as session:
            row = session.get(PlanningRun, run["id"])
            row.version += 1
            session.commit()

    monkeypatch.setattr(add_work_service, "_start_issue", start_then_bump)
    _delivery_sync("orbit", True)
    try:
        with get_session() as session:
            before = session.scalar(select(func.count()).select_from(IntakeItem))
        response = client.post(f"/api/v1/planning/runs/{run['id']}/work", json={
            "expected_run_version": run["version"], "project_id": "orbit", "source": "NEW", "title": "Việc tạo khi kế hoạch đổi giữa chừng",
            "item_type": "TASK", "priority": "P2", "reason": "Cần làm ngay trong chiều nay",
        })
        assert response.status_code == 201, response.text
        assert response.json()["data"]["state"] == "CREATING_ISSUE"
        with get_session() as session:
            assert session.scalar(select(func.count()).select_from(IntakeItem)) == before + 1
        waiting = [c for c in client.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]["candidates"] if c["title"] == "Việc tạo khi kế hoạch đổi giữa chừng"]
        assert len(waiting) == 1
    finally:
        _delivery_sync("orbit", False)
