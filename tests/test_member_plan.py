"""One person's plan over a stretch of days, read only (FR-PLAN-40, ADR-0081): who sees whom, what shows as work and
what as hours only, days off, own tasks kept private, internal work placed on its due or closing day."""
from datetime import date, datetime, time, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.db import get_session
from app.main import app
from app.models import (
    ApiToken, DailyCapacity, PersonalTask, PlanningAssignment, PlanningRun, Project, User, UserProjectAccess,
    WorkforceMember, WorkforceProjectMembership, WorkItem,
)
from app.modules.planning.overview import LOCAL_TZ

cto = TestClient(app, headers={"X-User-Subject": "cto"})
DAYS = {name: date(2031, 11, 3 + offset) for offset, name in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}


def _login(subject: str, body: dict) -> tuple[str, TestClient]:
    created = cto.post("/api/v1/users", json={"subject": subject, **body})
    assert created.status_code == 201, created.text
    data = created.json()["data"]
    client = TestClient(app, headers={"X-User-Subject": subject})
    changed = client.post("/api/v1/auth/password", json={"current_password": data["temporary_password"], "new_password": f"{subject}-long-pass-1"})
    assert changed.status_code == 200, changed.text
    return data["account"]["id"], client


def _run(session, cto_id: str, day: date, status: str = "APPROVED") -> PlanningRun:
    run = PlanningRun(
        id=str(uuid4()), plan_date=day, project_scope=[], scope_hash=uuid4().hex, status=status,
        source_snapshot_at=datetime.now(timezone.utc), created_by=cto_id,
    )
    session.add(run)
    session.flush()
    return run


def _assign(session, run: PlanningRun, project_id: str, member_id: str, hours: float, title: str, work_status: str = "PLANNED") -> None:
    session.add(PlanningAssignment(
        id=str(uuid4()), planning_run_id=run.id, project_id=project_id, member_id=member_id, slot="MORNING", work_type="DEVELOPMENT",
        planned_hours=hours, source_type="MANUAL", source_reference=title, work_status=work_status,
    ))


def test_a_persons_plan_shows_shared_work_and_only_hours_of_the_rest() -> None:
    tag = uuid4().hex[:6]
    ids: dict[str, str] = {}
    users: list[str] = []
    with get_session() as session:
        cto_id = str(session.scalar(select(User).where(User.auth_subject == "cto")).id)
        for key in ("p1", "p2"):
            project = Project(id=str(uuid4()), code=f"zt{key}{tag}", intake_key=f"Z{key[-1]}{tag[:4]}".upper()[:8], name=f"ZTEST {key.upper()} {tag}")
            session.add(project)
            ids[key] = project.id
        for key in ("a", "b", "c", "d", "e"):
            member = WorkforceMember(id=str(uuid4()), display_name=f"ZTEST Người {key.upper()} {tag}", email_reference=f"zt-{key}-{tag}@example.test")
            session.add(member)
            ids[key] = member.id
        session.flush()
        for member, project in (("a", "p1"), ("b", "p1"), ("b", "p2"), ("c", "p2")):
            session.add(WorkforceProjectMembership(id=str(uuid4()), member_id=ids[member], project_id=ids[project], role="Developer"))
        session.commit()
    try:
        user_a, dev_a = _login(f"ztmpa{tag}", {"role": "DEVELOPER", "member_id": ids["a"]})
        user_b, dev_b = _login(f"ztmpb{tag}", {"role": "DEVELOPER", "member_id": ids["b"]})
        users += [user_a, user_b]
        # The Project Owner of P2 is chosen on the project's team page, which issues the login.
        team = cto.put(f"/api/v1/projects/ztp2{tag}/team", json={"owner_member_id": ids["e"], "member_ids": [ids["b"], ids["c"]]})
        assert team.status_code == 200, team.text
        issued = team.json()["data"]["issued"]
        users.append(next(row for row in cto.get("/api/v1/users").json()["data"] if row["subject"] == issued["subject"])["id"])
        po = TestClient(app, headers={"X-User-Subject": issued["subject"]})
        assert po.post("/api/v1/auth/password", json={"current_password": issued["temporary_password"], "new_password": f"ztpo-pass-{tag}-long"}).status_code == 200

        with get_session() as session:
            monday = _run(session, cto_id, DAYS["mon"])
            _assign(session, monday, ids["p1"], ids["b"], 3, "ZTEST việc P1 thứ hai")
            _assign(session, monday, ids["p2"], ids["b"], 2, "ZTEST việc P2 thứ hai")
            replaced = _run(session, cto_id, DAYS["mon"], status="SUPERSEDED")
            _assign(session, replaced, ids["p1"], ids["b"], 6, "ZTEST bản cũ")
            tuesday = _run(session, cto_id, DAYS["tue"])
            _assign(session, tuesday, ids["p1"], ids["b"], 4, "ZTEST việc xong", work_status="DONE")
            session.add(DailyCapacity(id=str(uuid4()), member_id=ids["b"], work_date=DAYS["wed"], base_hours=8, override_hours=0, available_hours=0,
                                      override_reason="ZTEST nghỉ phép", updated_by=cto_id))
            session.add(PersonalTask(id=str(uuid4()), user_id=user_b, member_id=ids["b"], task_date=DAYS["mon"], title="ZTEST đi khám", hours=1))
            session.add(WorkItem(id=str(uuid4()), project_id=ids["p2"], seq=1, code=f"ZT2-W-{tag}", title="ZTEST bài đăng", status="READY",
                                 member_id=ids["b"], due_date=DAYS["thu"]))
            closed = datetime.combine(DAYS["fri"], time(15, 0), tzinfo=LOCAL_TZ)
            session.add(WorkItem(id=str(uuid4()), project_id=ids["p1"], seq=1, code=f"ZT1-W-{tag}", title="ZTEST việc nội bộ", status="DONE",
                                 member_id=ids["b"], due_date=DAYS["mon"], closed_at=closed))
            session.commit()

        week = f"from={DAYS['mon']}&to={DAYS['sun']}"

        # A Developer sees themselves and the people who share a project with them, never anyone else.
        listed = dev_a.get("/api/v1/planning/people")
        assert listed.status_code == 200, listed.text
        names = {row["member_id"] for row in listed.json()["data"]["members"]}
        assert listed.json()["data"]["me"] == ids["a"] and listed.json()["data"]["members"][0]["is_me"]
        assert ids["a"] in names and ids["b"] in names and ids["c"] not in names and ids["d"] not in names
        assert dev_a.get(f"/api/v1/planning/people/{ids['c']}/plan?{week}").status_code == 404
        assert dev_a.get(f"/api/v1/planning/people/{ids['d']}/plan?{week}").status_code == 404

        shown = dev_a.get(f"/api/v1/planning/people/{ids['b']}/plan?{week}")
        assert shown.status_code == 200, shown.text
        plan = shown.json()["data"]
        assert plan["member"]["is_me"] is False and len(plan["days"]) == 7
        day = {row["date"]: row for row in plan["days"]}
        mon = day[DAYS["mon"].isoformat()]
        assert [row["title"] for row in mon["items"]] == ["ZTEST việc P1 thứ hai"], "shared project work only, no own task title"
        assert mon["hidden_projects"] == [{"name": f"ZTEST P2 {tag}", "hours": 2.0}]
        assert mon["planned_hours"] == 5.0 and mon["personal_hours"] == 1.0 and mon["available_hours"] == 7.0, "the replaced plan does not count"
        assert day[DAYS["wed"].isoformat()]["off"] is True and day[DAYS["sat"].isoformat()]["off"] is True
        assert day[DAYS["thu"].isoformat()]["items"] == [], "a post in a project the viewer is not in stays hidden"
        fri = day[DAYS["fri"].isoformat()]["items"]
        assert [(row["kind"], row["code"], row["closed"]) for row in fri] == [("WORK_ITEM", f"ZT1-W-{tag}", True)], "closed work sits on its closing day"
        totals = plan["totals"]
        assert totals["planned_hours"] == 9.0 and totals["work_status"]["DONE"] == 1 and totals["work_status"]["PLANNED"] == 1
        assert totals["off_days"] == 1 and totals["personal_hours"] == 1.0
        assert {(row["name"], row["visible"]) for row in totals["by_project"]} == {(f"ZTEST P1 {tag}", True), (f"ZTEST P2 {tag}", False)}
        assert "ZTEST đi khám" not in shown.text

        # A Project Owner sees the people of their projects and the work in those projects.
        theirs = {row["member_id"] for row in po.get("/api/v1/planning/people").json()["data"]["members"]}
        assert {ids["b"], ids["c"]} <= theirs and ids["a"] not in theirs
        seen = {row["date"]: row for row in po.get(f"/api/v1/planning/people/{ids['b']}/plan?{week}").json()["data"]["days"]}
        assert [row["title"] for row in seen[DAYS["mon"].isoformat()]["items"]] == ["ZTEST việc P2 thứ hai"]
        assert seen[DAYS["mon"].isoformat()]["hidden_projects"] == [{"name": f"ZTEST P1 {tag}", "hours": 3.0}]
        assert [row["code"] for row in seen[DAYS["thu"].isoformat()]["items"]] == [f"ZT2-W-{tag}"], "an open post sits on its due day"
        assert po.get(f"/api/v1/planning/people/{ids['a']}/plan?{week}").status_code == 404

        # The person themselves sees everything, their own tasks with titles.
        mine = {row["date"]: row for row in dev_b.get(f"/api/v1/planning/people/{ids['b']}/plan?{week}").json()["data"]["days"]}
        monday_items = mine[DAYS["mon"].isoformat()]["items"]
        assert [row["kind"] for row in monday_items] == ["ASSIGNMENT", "ASSIGNMENT", "PERSONAL"] and monday_items[-1]["title"] == "ZTEST đi khám"
        assert mine[DAYS["mon"].isoformat()]["hidden_projects"] == []

        # The CTO sees everyone; the range is bounded.
        assert ids["d"] in {row["member_id"] for row in cto.get("/api/v1/planning/people").json()["data"]["members"]}
        assert cto.get(f"/api/v1/planning/people/{ids['d']}/plan?{week}").status_code == 200
        too_long = cto.get(f"/api/v1/planning/people/{ids['b']}/plan?from=2031-01-01&to=2031-03-15")
        assert too_long.status_code == 422 and too_long.json()["error"] == "RANGE_TOO_LONG"
        backwards = cto.get(f"/api/v1/planning/people/{ids['b']}/plan?from={DAYS['sun']}&to={DAYS['mon']}")
        assert backwards.status_code == 422 and backwards.json()["error"] == "RANGE_INVALID"
    finally:
        with get_session() as session:
            members = [ids[key] for key in ("a", "b", "c", "d", "e") if key in ids]
            projects = [ids[key] for key in ("p1", "p2") if key in ids]
            for project_id in projects:
                project = session.get(Project, project_id)
                if project is not None:
                    project.owner_member_id = None
            runs = list(session.scalars(select(PlanningAssignment.planning_run_id).where(PlanningAssignment.member_id.in_(members))))
            session.execute(delete(PlanningAssignment).where(PlanningAssignment.planning_run_id.in_(runs)))
            session.execute(delete(PlanningRun).where(PlanningRun.id.in_(runs)))
            session.execute(delete(PersonalTask).where(PersonalTask.member_id.in_(members)))
            session.execute(delete(WorkItem).where(WorkItem.project_id.in_(projects)))
            session.execute(delete(DailyCapacity).where(DailyCapacity.member_id.in_(members)))
            session.execute(delete(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id.in_(members)))
            session.execute(delete(UserProjectAccess).where(UserProjectAccess.user_id.in_(users)))
            session.execute(delete(ApiToken).where(ApiToken.user_id.in_(users)))
            for user_id in users:
                user = session.get(User, user_id)
                if user is not None:
                    session.delete(user)
            session.flush()
            session.execute(delete(WorkforceMember).where(WorkforceMember.id.in_(members)))
            session.execute(delete(Project).where(Project.id.in_(projects)))
            session.commit()
