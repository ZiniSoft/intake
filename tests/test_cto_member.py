"""The CTO is staff too when they take work themselves (FR-PLAN-37).

One click gives the CTO's login a staff record with no daily hours and no Daily Report expected; mapped onto a
software project it is planned like anyone else; a project the CTO runs can name the CTO as its Project Owner
without a second login.
"""
import hashlib
import random
import string
from datetime import date, datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import (
    AuditEvent, DailyCapacity, GitLabIssueSnapshot, PlanningApprovalSnapshot, PlanningAssignment, PlanningCandidate,
    PlanningRun, PlanningWarning, Project, ProjectIntegration, User, UserProjectAccess, WorkforceMember, WorkforceProjectMembership,
)
from app.modules.notify import reminders
from app.modules.planning.day_plans import day_plans
from app.modules.planning.overview import LOCAL_TZ
from app.modules.planning.service import planning_service

cto = TestClient(app, headers={"X-User-Subject": "cto"})
DAYS = (date(2031, 10, 6), date(2031, 10, 7))  # a Monday and the Tuesday after it
ISSUE = "9931"


def _issue(project_id: str) -> None:
    now = datetime.now(timezone.utc)
    with get_session() as session:
        session.add(GitLabIssueSnapshot(
            id=str(uuid4()), project_id=project_id, issue_external_id=ISSUE, title="Việc CTO tự làm", state="opened",
            labels=["priority:p2"], assignee_external_ids=[], milestone_external_id=None, milestone_title=None, due_date=None,
            web_url=None, payload_hash=hashlib.sha256(f"cto-member:{ISSUE}".encode()).hexdigest(),
            is_current=True, fetched_at=now, last_seen_at=now,
        ))
        session.commit()


def _cleanup(member_id: str | None, project_code: str) -> None:
    with get_session() as session:
        for run in session.scalars(select(PlanningRun).where(PlanningRun.plan_date.in_(list(DAYS)))).all():
            for model in (PlanningApprovalSnapshot, PlanningWarning, PlanningAssignment, PlanningCandidate):
                for row in session.scalars(select(model).where(model.planning_run_id == run.id)).all():
                    session.delete(row)
            session.delete(run)
        for row in session.scalars(select(GitLabIssueSnapshot).where(GitLabIssueSnapshot.issue_external_id == ISSUE)).all():
            session.delete(row)
        for user in session.scalars(select(User).where(User.role == "CTO")).all():
            user.member_id = None
        if member_id:
            for model in (DailyCapacity, PlanningWarning, WorkforceProjectMembership):
                for row in session.scalars(select(model).where(model.member_id == member_id)).all():
                    session.delete(row)
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
        project = session.scalar(select(Project).where(Project.code == project_code))
        if project is not None:
            for row in session.scalars(select(UserProjectAccess).where(UserProjectAccess.project_id == project.id)).all():
                session.delete(row)
            for row in session.scalars(select(ProjectIntegration).where(ProjectIntegration.project_id == project.id)).all():
                session.delete(row)
            for row in session.scalars(select(AuditEvent).where(AuditEvent.project_id == project.id)).all():
                session.delete(row)
            session.delete(project)
        session.commit()


def test_the_cto_becomes_staff_in_one_click_takes_work_and_owes_no_report() -> None:
    me = cto.get("/api/v1/auth/me").json()["data"]
    assert me["member_id"] is None, "another test left the CTO linked to a staff record"
    tag = uuid4().hex[:6]
    code = f"cto-{tag}"
    key = "C" + "".join(random.choices(string.ascii_uppercase, k=4))
    member_id = None
    try:
        with get_session() as session:
            orbit = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
        # --- one click: a staff record with no hours by default, linked to the login; a second click changes nothing
        added = cto.post("/api/v1/planning/members/me")
        assert added.status_code == 200, added.text
        member = added.json()["data"]
        member_id = member["id"]
        assert member["is_cto"] is True and member["default_weekday_hours"] == 0 and member["email_reference"] == me["email"]
        assert cto.get("/api/v1/auth/me").json()["data"]["member_id"] == member_id
        assert cto.post("/api/v1/planning/members/me").json()["data"]["id"] == member_id
        listed = {row["id"]: row for row in cto.get("/api/v1/planning/members").json()["data"]}
        assert listed[member_id]["is_cto"] is True and not any(row["is_cto"] for key_, row in listed.items() if key_ != member_id)

        # --- mapped onto a software project with a tracker user, the CTO is planned like anyone else
        mapped = cto.put(f"/api/v1/planning/members/{member_id}", json={
            "display_name": member["display_name"], "email_reference": member["email_reference"], "default_weekday_hours": 0,
            "project_mappings": [{"project_id": orbit, "gitlab_user_external_id": "424399", "role": "CTO"}],
        })
        assert mapped.status_code == 200, mapped.text
        _issue(orbit)
        hours = cto.put(f"/api/v1/planning/capacities/{DAYS[0].isoformat()}/{member_id}", json={"override_hours": 4, "reason": "CTO nhận việc hôm nay"})
        assert hours.status_code == 200, hours.text
        first = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[0].isoformat(), "project_ids": [orbit]}).json()["data"]
        placed = cto.post(f"/api/v1/planning/runs/{first['id']}/assignments", json={
            "expected_run_version": first["version"], "project_id": orbit, "member_id": member_id, "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 2, "source_type": "GITLAB", "source_reference": f"GL#{ISSUE}",
            "gitlab_issue_external_id": ISSUE, "approved_priority": "P2",
        })
        assert placed.status_code == 201, placed.text
        block = next(row for row in day_plans(DAYS[0], None)["projects"] if row["id"] == orbit)
        assert any(person["member_id"] == member_id for person in block["people"]), "the CTO's work shows on the day's board"

        # --- no Daily Report is expected from the CTO: no warning on the next plan, no nag from the bot
        with get_session() as session:
            staff = session.get(WorkforceMember, member_id)
            assert planning_service._expected_report_date(session, staff, DAYS[1]) is None
            staff.telegram_chat_id = f"cto-chat-{tag}"
            session.commit()
        second = cto.post("/api/v1/planning/runs", json={"plan_date": DAYS[1].isoformat(), "project_ids": [orbit]}).json()["data"]
        assert not [row for row in second["warnings"] if row["member_id"] == member_id], second["warnings"]
        tonight = reminders.build_messages(datetime(2031, 10, 6, 17, 30, tzinfo=LOCAL_TZ))
        morning = reminders.build_messages(datetime(2031, 10, 7, 8, 0, tzinfo=LOCAL_TZ))
        assert not [m for m in tonight + morning if m.member_id == member_id and m.kind in ("REPORT_TONIGHT", "REPORT_MISSING")]
        # With no hours on a day and nothing planned, the CTO is not listed as off duty either.
        block = next(row for row in day_plans(DAYS[1], None)["projects"] if row["id"] == orbit)
        assert member["display_name"] not in block["off"] and all(person["member_id"] != member_id for person in block["people"] + block["free"])

        # --- a project the CTO runs names the CTO as its Project Owner: no second login, no temporary password
        made = cto.post("/api/v1/projects", json={"name": f"Dự án CTO tự quản {tag}", "code": code, "intake_key": key, "kind": "NON_CODE"})
        assert made.status_code == 201, made.text
        team = cto.put(f"/api/v1/projects/{code}/team", json={"owner_member_id": member_id, "member_ids": []})
        assert team.status_code == 200, team.text
        assert team.json()["data"]["issued"] is None and team.json()["data"]["owner_member_id"] == member_id
        with get_session() as session:
            assert len(session.scalars(select(User).where(User.email == me["email"])).all()) == 1
        listed_project = next(row for row in cto.get("/api/v1/projects").json()["data"] if row["code"] == code)
        assert listed_project["owner_name"] == member["display_name"]
        released = cto.put(f"/api/v1/projects/{code}/team", json={"owner_member_id": None, "member_ids": []})
        assert released.status_code == 200, released.text
        assert cto.get("/api/v1/auth/me").status_code == 200, "giving the project up never locks the CTO out"
    finally:
        _cleanup(member_id, code)
