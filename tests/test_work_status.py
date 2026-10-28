"""Where a placed piece of work stands, from the web (FR-PLAN-34): the CTO, a Project Owner or the Developer who has
it sets the status; "done" with an Issue joins the acceptance queue; what is not done comes back on the next day's
plan as a continuation; the Developer reads their day over HTTP."""
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, IssueVerification, PlanningApprovalSnapshot, PlanningAssignment, PlanningCandidate, PlanningRun, PlanningWarning, Project, User, WorkforceMember, WorkforceProjectMembership

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
DAY_ONE, DAY_TWO = "2031-09-02", "2031-09-03"


def _cleanup(project_id: str, member_ids: list[str], user_id: str | None) -> None:
    with get_session() as session:
        for run in session.scalars(select(PlanningRun).where(PlanningRun.plan_date.in_((date.fromisoformat(DAY_ONE), date.fromisoformat(DAY_TWO))))).all():
            for model in (PlanningApprovalSnapshot, PlanningWarning, PlanningAssignment, PlanningCandidate):
                for row in session.scalars(select(model).where(model.planning_run_id == run.id)).all():
                    session.delete(row)
            session.delete(run)
        for row in session.scalars(select(IssueVerification).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id.in_(("811", "812", "812")))).all():
            session.delete(row)
        if user_id:
            for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user_id)).all():
                session.delete(row)
            user = session.get(User, user_id)
            if user is not None:
                session.delete(user)
        for member_id in member_ids:
            for row in session.scalars(select(PlanningWarning).where(PlanningWarning.member_id == member_id)).all():
                session.delete(row)
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
                session.delete(row)
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
        session.commit()


def test_work_status_from_the_web_feeds_acceptance_and_the_next_day() -> None:
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    first = cto.post("/api/v1/planning/members", json={
        "display_name": "Status Dev", "email_reference": f"status-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424311", "role": "Developer"}],
    }).json()["data"]
    second = cto.post("/api/v1/planning/members", json={
        "display_name": "Status Other", "email_reference": f"status-other-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424312", "role": "Developer"}],
    }).json()["data"]
    user_id = None
    try:
        run = cto.post("/api/v1/planning/runs", json={"plan_date": DAY_ONE, "project_ids": [project_id]}).json()["data"]
        place = lambda member, issue, primary, version: cto.post(f"/api/v1/planning/runs/{run['id']}/assignments", json={
            "expected_run_version": version, "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": primary, "planned_hours": 2, "source_type": "GITLAB", "source_reference": f"GL#{issue}",
            "gitlab_issue_external_id": issue, "approved_priority": "P1",
        })
        mine = place(first, "811", True, run["version"])
        assert mine.status_code == 201, mine.text
        theirs = place(second, "812", True, cto.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]["version"])
        assert theirs.status_code == 201, theirs.text
        mine_id, theirs_id = mine.json()["data"]["id"], theirs.json()["data"]["id"]
        status_url = lambda assignment_id: f"/api/v1/planning/runs/{run['id']}/assignments/{assignment_id}/work-status"

        # The CTO says the first piece is under way; a Project Owner outside the project cannot touch it.
        started = cto.patch(status_url(mine_id), json={"status": "IN_PROGRESS"})
        assert started.status_code == 200, started.text
        assert started.json()["data"]["work_status"] == "IN_PROGRESS" and started.json()["data"]["previous"] == "PLANNED"
        assert owner.patch(status_url(mine_id), json={"status": "DONE"}).status_code == 404
        assert cto.patch(status_url(mine_id), json={"status": "FINISHED"}).status_code == 422

        # The Developer who has the work says it is done; the Issue joins acceptance once, from the plan.
        created = cto.post("/api/v1/users", json={"subject": f"status{tag}", "role": "DEVELOPER", "member_id": first["id"]})
        assert created.status_code == 201, created.text
        user_id = created.json()["data"]["account"]["id"]
        dev = TestClient(app, headers={"X-User-Subject": f"status{tag}"})
        assert dev.post("/api/v1/auth/password", json={"current_password": created.json()["data"]["temporary_password"], "new_password": f"status-pass-{tag}-long"}).status_code == 200
        assert dev.patch(status_url(theirs_id), json={"status": "DONE"}).status_code == 404, "not their work"
        done = dev.patch(status_url(mine_id), json={"status": "DONE", "note": "Đã merge"})
        assert done.status_code == 200, done.text
        assert done.json()["data"]["acceptance_queued"] is True
        with get_session() as session:
            rows = session.scalars(select(IssueVerification).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id == "811")).all()
            assert len(rows) == 1 and rows[0].source == "PLAN" and rows[0].decision == "PENDING" and str(rows[0].member_id) == first["id"] and rows[0].reported_on == date.fromisoformat(DAY_ONE)
        queue = cto.get("/api/v1/acceptance")
        assert queue.status_code == 200 and any(row["issue_external_id"] == "811" and row["source"] == "PLAN" and row["reporter_name"] == "Status Dev" for row in queue.json()["data"]["today"] + queue.json()["data"]["more"])
        assert dev.patch(status_url(mine_id), json={"status": "DONE"}).json()["data"]["acceptance_queued"] is False, "offered once"
        # Taking "done" back withdraws the offer nobody has looked at.
        assert dev.patch(status_url(mine_id), json={"status": "IN_PROGRESS"}).status_code == 200
        with get_session() as session:
            assert session.scalar(select(IssueVerification.id).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id == "811")) is None
        assert dev.patch(status_url(mine_id), json={"status": "DONE"}).status_code == 200

        # The Developer's day over HTTP, the same shape the agent gets.
        day = dev.get(f"/api/v1/planning/my-day/{DAY_ONE}")
        assert day.status_code == 200, day.text
        assert [row["issue"] for row in day.json()["data"]["items"]] == ["811"] and day.json()["data"]["items"][0]["work_status"] == "DONE"
        assert dev.get(f"/api/v1/planning/day-plans/{DAY_ONE}").status_code == 403

        # The next day's plan: the piece still open comes back to wait as a continuation, the done one does not.
        second_run = cto.post("/api/v1/planning/runs", json={"plan_date": DAY_TWO, "project_ids": [project_id]}).json()["data"]
        waiting = [row for row in second_run["candidates"] if row["status"] == "READY" and row["gitlab_issue_external_id"] in ("811", "812")]
        assert [row["gitlab_issue_external_id"] for row in waiting] == ["812"], waiting
        carried = waiting[0]
        assert "issue_url" in carried and "intake_public_id" in carried, "every waiting entry carries its links"
        assert carried.get("member_id") == second["id"] and carried["source_reference"] == f"Kế hoạch {DAY_ONE}" and carried["summary"].startswith("Làm tiếp từ 02/09: chưa bắt đầu")
        assert carried["proposed_priority"] == "P1" and carried["requested_hours"] == 2.0
        # Opening the same plan again adds nothing twice.
        again = cto.post("/api/v1/planning/runs", json={"plan_date": DAY_TWO, "project_ids": [project_id]}).json()["data"]
        assert len([row for row in again["candidates"] if row["gitlab_issue_external_id"] == "812"]) == 1
    finally:
        _cleanup(project_id, [first["id"], second["id"]], user_id)


def test_waiting_work_done_elsewhere_leaves_the_list_with_a_note_and_goes_to_acceptance() -> None:
    """FR-PLAN-34: "Hủy" on a waiting entry that was already done: a note is required, the entry is taken off,
    the Issue waits for the CTO's acceptance, and the next day's plan does not offer it again."""
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Done Elsewhere", "email_reference": f"done-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424321", "role": "Developer"}],
    }).json()["data"]
    try:
        run = cto.post("/api/v1/planning/runs", json={"plan_date": DAY_ONE, "project_ids": [project_id]}).json()["data"]
        placed = cto.post(f"/api/v1/planning/runs/{run['id']}/assignments", json={
            "expected_run_version": run["version"], "project_id": project_id, "member_id": member["id"], "slot": "MORNING",
            "work_type": "DEVELOPMENT", "is_primary": True, "planned_hours": 2, "source_type": "GITLAB", "source_reference": "GL#812",
            "gitlab_issue_external_id": "812", "approved_priority": "P2",
        })
        assert placed.status_code == 201, placed.text
        version = cto.get(f"/api/v1/planning/runs/{run['id']}").json()["data"]["version"]
        back = cto.post(f"/api/v1/planning/runs/{run['id']}/assignments/{placed.json()['data']['id']}/unassign", json={"expected_run_version": version})
        assert back.status_code == 200, back.text
        candidate = next(row for row in back.json()["data"]["candidates"] if row["gitlab_issue_external_id"] == "812")
        url = f"/api/v1/planning/runs/{run['id']}/candidates/{candidate['id']}/done"
        assert cto.post(url, json={"note": ""}).status_code == 422
        assert owner.post(url, json={"note": "Nam làm hôm qua"}).status_code == 404
        done = cto.post(url, json={"note": "Nam đã làm hôm qua, chưa kịp báo"})
        assert done.status_code == 200, done.text
        data = done.json()["data"]
        assert data["status"] == "DONE_ELSEWHERE" and data["summary"].startswith("Đã làm xong ngoài kế hoạch: Nam đã làm") and data["acceptance_queued"] is True
        assert cto.post(url, json={"note": "lần nữa"}).json()["data"]["acceptance_queued"] is False, "offered once while it waits"
        with get_session() as session:
            rows = session.scalars(select(IssueVerification).where(IssueVerification.project_id == project_id, IssueVerification.issue_external_id == "812")).all()
            assert len(rows) == 1 and rows[0].source == "PLAN" and rows[0].decision == "PENDING" and rows[0].reported_on == date.fromisoformat(DAY_ONE)
            assert rows[0].source_note and rows[0].source_note.startswith("Nam đã làm hôm qua, chưa kịp báo (") and "/" in rows[0].source_note
            verification_id = str(rows[0].id)
        queue_item = next(row for row in cto.get("/api/v1/acceptance").json()["data"]["today"] + cto.get("/api/v1/acceptance").json()["data"]["more"] if row["id"] == verification_id)
        assert queue_item["source_note"].startswith("Nam đã làm hôm qua")
        # The CTO accepts: the note the tracker gets carries what was written at "Hủy".
        from app.modules.planning import acceptance as acceptance_queue
        accepted = cto.post(f"/api/v1/acceptance/{verification_id}/accept", json={"evidence_missing_reason": "kiểm tay trên máy thử"})
        assert accepted.status_code == 200, accepted.text
        with get_session() as session:
            row = session.get(IssueVerification, verification_id)
            row.sync_status = "PENDING"
            session.commit()
        target = acceptance_queue.sync_target(verification_id)
        if target is not None:
            assert "Đã làm xong ngoài kế hoạch: Nam đã làm hôm qua" in str(target["note"])
        # Tomorrow's plan does not bring it back as a continuation or as waiting work.
        tomorrow = cto.post("/api/v1/planning/runs", json={"plan_date": DAY_TWO, "project_ids": [project_id]}).json()["data"]
        assert all(row["gitlab_issue_external_id"] != "812" for row in tomorrow["candidates"]), tomorrow["candidates"]
    finally:
        _cleanup(project_id, [member["id"]], None)
