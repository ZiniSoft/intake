"""The morning picture per project with its "enough to review" gate, and one plan per project at 07:00
(FR-PLAN-23, FR-PLAN-24)."""
import hashlib
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_session
from app.main import app
from app.models import DailyCapacity, EmailMessage, IntakeItem, PlanningRun, Project, User, WorkforceMember, WorkforceProjectMembership
from app.workers.planning_tasks import create_daily_planning_run

client = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
DAY = date.today() + timedelta(days=60)
YESTERDAY = DAY - timedelta(days=1)


def _team(project_code: str, names: list[str]) -> list[str]:
    """Members of a project who worked yesterday, each with a report address."""
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == project_code))
        cto = session.scalar(select(User).where(User.auth_subject == "cto"))
        ids = []
        for name in names:
            member = WorkforceMember(id=str(uuid4()), display_name=name, email_reference=f"{name.lower()}.{uuid4().hex[:6]}@example.test", status="ACTIVE", default_weekday_hours=8)
            session.add(member)
            session.flush()
            session.add(WorkforceProjectMembership(id=str(uuid4()), member_id=member.id, project_id=project.id, gitlab_user_external_id=None, active=True))
            session.add(DailyCapacity(id=str(uuid4()), member_id=member.id, work_date=YESTERDAY, base_hours=8, available_hours=8, updated_by=cto.id))
            session.add(DailyCapacity(id=str(uuid4()), member_id=member.id, work_date=DAY, base_hours=8, available_hours=8, updated_by=cto.id))
            ids.append(str(member.id))
        session.commit()
        return ids


def _report(member_id: str, project_code: str) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        member = session.get(WorkforceMember, member_id)
        project = session.scalar(select(Project).where(Project.code == project_code))
        session.add(EmailMessage(
            id=str(uuid4()), project_id=project.id, member_id=member.id, mailbox="reports@example.test", uid_validity="1", uid=uuid4().hex,
            sender_address=member.email_reference, report_date=YESTERDAY, content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
            status="VALID", parse_version="daily-report-v1", parse_errors=[], received_at=now, revision=1, is_current=True, is_late=False,
            purge_after=now + timedelta(days=90), created_at=now,
        ))
        session.commit()


def _cleanup(member_ids: list[str], intake_ids: list[str]) -> None:
    with get_session() as session:
        session.execute(delete(EmailMessage).where(EmailMessage.member_id.in_(member_ids)))
        session.execute(delete(DailyCapacity).where(DailyCapacity.member_id.in_(member_ids)))
        session.execute(delete(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id.in_(member_ids)))
        session.execute(delete(WorkforceMember).where(WorkforceMember.id.in_(member_ids)))
        for intake_id in intake_ids:
            item = session.get(IntakeItem, intake_id)
            if item is not None:
                session.delete(item)
        session.execute(delete(PlanningRun).where(PlanningRun.plan_date == DAY))
        session.commit()


def test_each_project_has_a_row_with_its_gate_and_the_rows_sort_by_urgency() -> None:
    members = _team("orbit", ["Mai", "Nam"])
    _report(members[0], "orbit")
    created = client.post("/api/v1/intakes", json={"project_id": "ember", "channel": "MANUAL", "raw_text": f"Sập thanh toán toàn bộ cửa hàng {uuid4().hex[:6]}"})
    intake = created.json()["data"]
    reviewed = client.patch(f"/api/v1/intakes/{intake['id']}/review", json={
        "normalized_title": "Sập thanh toán", "normalized_summary": "Mọi cửa hàng không thanh toán được", "suggested_priority": "P0",
        "proposed_route": "GITLAB", "expected_version": intake["version"],
    })
    assert reviewed.status_code == 200, reviewed.text
    try:
        shown = client.get(f"/api/v1/planning/overview/{DAY.isoformat()}")
        assert shown.status_code == 200, shown.text
        data = shown.json()["data"]
        rows = {row["code"]: row for row in data["projects"]}
        assert "orbit" in rows and "ember" in rows and "other" not in rows, "only software projects are planned"

        # Other tests leave members of their own behind in the shared database: count ours, not theirs.
        orbit = rows["orbit"]
        assert orbit["reports"]["expected"] >= 2 and orbit["reports"]["received"] >= 1
        assert "Nam" in orbit["reports"]["missing"] and "Mai" not in orbit["reports"]["missing"]
        assert orbit["readiness"]["state"] == "MISSING" and any("Nam" in reason for reason in orbit["readiness"]["reasons"])
        assert orbit["plan"]["run_id"] is None and orbit["plan"]["available_hours"] >= 16 and orbit["plan"]["people_today"] >= 2

        ember = rows["ember"]
        assert ember["approvals"]["pending"] >= 1 and ember["approvals"]["urgent"] >= 1 and ember["p0"] is True
        order = [(not row["p0"], -row["attention"]) for row in data["projects"]]
        assert order == sorted(order), "projects with a P0 first, then by what waits"
        assert data["missing_projects"] >= 1

        # A plan made for the day shows up on the row, with what waits in it, who made it, and who has hours but no work yet.
        run = client.post("/api/v1/planning/runs", json={"plan_date": DAY.isoformat(), "project_ids": ["orbit"]}).json()["data"]
        after = {row["code"]: row for row in client.get(f"/api/v1/planning/overview/{DAY.isoformat()}").json()["data"]["projects"]}
        assert after["orbit"]["plan"]["run_id"] == run["id"] and after["orbit"]["plan"]["scope"] == "PROJECT" and after["orbit"]["plan"]["status"] == run["status"]
        assert after["orbit"]["plan"]["made_by"] and {"Mai", "Nam"} <= set(after["orbit"]["unassigned"])
        assert "Mai" not in after["orbit"]["people_off"] and isinstance(after["orbit"]["carry_over"], int)

        # The Project Owner may close the plan of a project of theirs: the only refusal left is the plan being empty.
        closing = owner.post(f"/api/v1/planning/runs/{run['id']}/approve", json={"expected_version": run["version"]})
        assert closing.status_code in (404, 422), closing.text
        if closing.status_code == 422:
            assert "PLANNING_EMPTY" in closing.text
        assert owner.get(f"/api/v1/planning/runs/{run['id']}/sync-jobs").status_code in (200, 404)
        assert TestClient(app, headers={"X-User-Subject": "nobody"}).post(f"/api/v1/planning/runs/{run['id']}/approve", json={"expected_version": run["version"]}).status_code in (401, 403)

        # A Project Owner sees only the projects granted to them.
        theirs = owner.get(f"/api/v1/planning/overview/{DAY.isoformat()}")
        assert theirs.status_code == 200
        granted = {row["code"] for row in owner.get("/api/v1/projects").json()["data"]}
        assert {row["code"] for row in theirs.json()["data"]["projects"]} <= granted
        assert len(theirs.json()["data"]["projects"]) < len(data["projects"]), "an owner sees fewer rows than the CTO"
    finally:
        _cleanup(members, [intake["id"]])


def test_the_morning_job_makes_one_plan_per_project_and_keeps_an_existing_one() -> None:
    try:
        first = create_daily_planning_run(DAY.isoformat())
        by_project = {row["project_id"]: row for row in first["runs"]}
        with get_session() as session:
            software = {str(value) for value in session.scalars(select(Project.id).where(Project.status == "ACTIVE", Project.kind == "SOFTWARE")).all()}
        assert set(by_project) == software
        with get_session() as session:
            runs = session.scalars(select(PlanningRun).where(PlanningRun.plan_date == DAY, PlanningRun.status != "SUPERSEDED")).all()
            assert all(len(run.project_scope) == 1 for run in runs), "one project per plan"
        second = create_daily_planning_run(DAY.isoformat())
        assert {row["planning_run_id"] for row in second["runs"]} == {row["planning_run_id"] for row in first["runs"]}, "the same plans, not new ones"
    finally:
        with get_session() as session:
            session.execute(delete(PlanningRun).where(PlanningRun.plan_date == DAY))
            session.commit()


def test_the_day_across_projects_is_read_only_and_grouped_by_project() -> None:
    """FR-PLAN-33: one block per software project with its plan, people with work, free people and waiting work;
    reading it never opens a plan; a Project Owner only sees their projects."""
    from app.models import PlanningAssignment, PlanningCandidate, PlanningWarning
    day = "2031-08-04"
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
        before = session.scalar(select(PlanningRun.id).where(PlanningRun.plan_date == date.fromisoformat(day)))
    assert before is None
    member = client.post("/api/v1/planning/members", json={
        "display_name": "Overview Person", "email_reference": f"overview-{uuid4().hex[:6]}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424291", "role": "Developer"}],
    }).json()["data"]
    run_id = None
    try:
        empty = client.get(f"/api/v1/planning/day-plans/{day}")
        assert empty.status_code == 200, empty.text
        block = next(row for row in empty.json()["data"]["projects"] if row["code"] == "orbit")
        assert block["run"] is None and any(row["name"] == "Overview Person" for row in block["free"]) and block["people"] == []
        with get_session() as session:
            assert session.scalar(select(PlanningRun.id).where(PlanningRun.plan_date == date.fromisoformat(day))) is None, "reading opens nothing"
        run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": [project_id]}).json()["data"]
        run_id = run["id"]
        placed = client.post(f"/api/v1/planning/runs/{run_id}/assignments", json={
            "expected_run_version": run["version"], "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 3, "source_type": "GITLAB", "source_reference": "GL#790",
            "gitlab_issue_external_id": "790", "approved_priority": "P1",
        })
        assert placed.status_code == 201, placed.text
        shown = client.get(f"/api/v1/planning/day-plans/{day}").json()["data"]
        block = next(row for row in shown["projects"] if row["code"] == "orbit")
        assert block["run"]["open"] and block["run"]["assignments"] == 1 and block["run"]["assigned_hours"] == 3.0
        person = next(row for row in block["people"] if row["name"] == "Overview Person")
        assert person["assignments"][0]["issue"] == "790" and person["assignments"][0]["slot"] == "MORNING" and person["planned"] == 3.0
        assert "issue_url" in person["assignments"][0] and "intake_public_id" in person["assignments"][0], "links for the Project Owner"
        assert all(row["name"] != "Overview Person" for row in block["free"])
        assert shown["totals"]["projects"] >= 1 and shown["totals"]["unclosed"] >= 1
        assert owner.get(f"/api/v1/planning/day-plans/{day}").json()["data"]["projects"] == []
    finally:
        with get_session() as session:
            if run_id:
                for model in (PlanningWarning, PlanningCandidate, PlanningAssignment):
                    for row in session.scalars(select(model).where(model.planning_run_id == run_id)).all():
                        session.delete(row)
                run = session.get(PlanningRun, run_id)
                if run is not None:
                    session.delete(run)
            for row in session.scalars(select(PlanningWarning).where(PlanningWarning.member_id == member["id"])).all():
                session.delete(row)
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member["id"])).all():
                session.delete(row)
            stored = session.get(WorkforceMember, member["id"])
            if stored is not None:
                session.delete(stored)
            session.commit()


def test_waiting_work_from_reports_is_one_line_per_person_and_name() -> None:
    """FR-PLAN-24: two report items with the same name for one person give one waiting entry; a second line
    already waiting is set aside with a note; an entry from a report read again goes the same way."""
    import hashlib

    from app.models import PlanningCandidate, PlanningWarning, ReportItem
    tag = uuid4().hex[:6]
    members = _team("orbit", [f"Trùng {tag}"])
    day = "2031-10-07"
    run_id = None
    try:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            member = session.get(WorkforceMember, members[0])
            project = session.scalar(select(Project).where(Project.code == "orbit"))
            email = EmailMessage(
                id=str(uuid4()), project_id=project.id, member_id=member.id, mailbox="reports@example.test", uid_validity="1", uid=uuid4().hex,
                sender_address=member.email_reference, report_date=date.fromisoformat("2031-10-06"), content_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                status="VALID", parse_version="daily-report-v1", parse_errors=[], received_at=now, revision=1, is_current=True, is_late=False,
                purge_after=now + timedelta(days=90), created_at=now,
            )
            session.add(email)
            session.flush()
            for position, (status, title, hours) in enumerate((("IN_PROGRESS", "Kích hoạt giấy phép Envato", 1.5), ("PLANNED", "kích hoạt giấy phép envato.", 2.0), ("PLANNED", "Viết hướng dẫn", 1.0))):
                session.add(ReportItem(
                    id=str(uuid4()), email_message_id=email.id, project_id=project.id, member_id=member.id, source_type="EMAIL", source_reference="t",
                    category="PLAN" if status == "PLANNED" else "DELIVERY", work_status=status, title=title, summary=title, planned_hours=hours if status == "PLANNED" else None,
                    worked_hours=hours if status != "PLANNED" else None, blocker=False, revision=1, is_current=True, created_at=now + timedelta(microseconds=position),
                ))
            session.commit()
            project_id = str(project.id)
        run = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": [project_id]}).json()["data"]
        run_id = run["id"]
        waiting = [row for row in run["candidates"] if row["source_type"] == "REPORT" and row["status"] in ("READY", "PENDING_TRIAGE")]
        assert sorted(row["title"] for row in waiting) == ["Kích hoạt giấy phép Envato", "Viết hướng dẫn"], waiting
        # A stray second line (as older plans carry) is set aside the next time the plan is opened.
        with get_session() as session:
            session.add(PlanningCandidate(
                id=str(uuid4()), planning_run_id=run_id, project_id=project_id, member_id=members[0], intake_id=None, assignment_id=None,
                source_type="REPORT", source_reference="Daily Report 2031-10-06", gitlab_issue_external_id=None,
                title="Kích hoạt giấy phép Envato", summary="Trạng thái báo cáo: PLANNED", status="PENDING_TRIAGE", proposed_priority=None,
                requested_hours=2, target_slot=None, idempotency_key_hash=hashlib.sha256(f"stray:{tag}".encode()).hexdigest(), request_hash=None,
                created_by=str(uuid4()), created_at=now, updated_at=now,
            ))
            session.commit()
        again = client.post("/api/v1/planning/runs", json={"plan_date": day, "project_ids": [project_id]}).json()["data"]
        envato = [row for row in again["candidates"] if row["title"].lower().startswith("kích hoạt")]
        assert len(envato) == 2 and sorted(row["status"] for row in envato) == ["PENDING_TRIAGE", "REJECTED"]
        set_aside = next(row for row in envato if row["status"] == "REJECTED")
        assert set_aside["summary"].startswith("Bỏ vì báo cáo đã được đọc lại") or set_aside["summary"].startswith("Trùng với dòng cùng tên")
        assert sum(1 for row in again["candidates"] if row["status"] in ("READY", "PENDING_TRIAGE") and row["title"].lower().startswith("kích hoạt")) == 1
    finally:
        with get_session() as session:
            if run_id:
                for row in session.scalars(select(PlanningCandidate).where(PlanningCandidate.planning_run_id == run_id)).all():
                    session.delete(row)
                for model in (PlanningWarning,):
                    for row in session.scalars(select(model).where(model.planning_run_id == run_id)).all():
                        session.delete(row)
                run = session.get(PlanningRun, run_id)
                if run is not None:
                    session.delete(run)
            session.commit()
        _cleanup(members, [])
