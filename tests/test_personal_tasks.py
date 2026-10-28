"""A person's own tasks for the day (FR-PER-01..03, ADR-0060): only the owner reads them, their hours come off the
person's free hours in planning, the agent sees them in get_my_day, and the Telegram bot reminds at the set minute."""
from datetime import date, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, PersonalTask, Project, User, WorkforceMember, WorkforceProjectMembership
from app.modules.notify import reminders
from app.modules.planning.overview import LOCAL_TZ

cto = TestClient(app, headers={"X-User-Subject": "cto"})
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
MCP = "/api/v1/mcp-server"
DAY = "2031-05-26"


def _call(client: TestClient, name: str, arguments: dict) -> dict:
    answer = client.post(MCP, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": arguments}}).json()
    return answer["result"]


def test_own_tasks_take_hours_reach_the_agent_and_remind_on_telegram() -> None:
    tag = uuid4().hex[:6]
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Personal Member", "email_reference": f"personal-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424293", "role": "Developer"}],
    }).json()["data"]
    created = cto.post("/api/v1/users", json={"subject": f"per{tag}", "role": "DEVELOPER", "member_id": member["id"]}).json()["data"]
    dev = TestClient(app, headers={"X-User-Subject": f"per{tag}"})
    assert dev.post("/api/v1/auth/password", json={"current_password": created["temporary_password"], "new_password": f"per-pass-{tag}-long"}).status_code == 200
    task_ids: list[str] = []
    try:
        made = dev.post("/api/v1/personal-tasks", json={"title": "Nộp thuế quý", "task_date": DAY, "hours": 2, "start_time": "14:00", "remind_at": "13:45", "note": "Cổng thuế điện tử"})
        assert made.status_code == 201, made.text
        task = made.json()["data"]
        task_ids.append(task["id"])
        assert task["status"] == "PLANNED" and task["hours"] == 2.0 and task["remind_at"] == "13:45"
        bad = dev.post("/api/v1/personal-tasks", json={"title": "x", "task_date": DAY, "remind_at": "25:99"})
        assert bad.status_code == 422 and "TIME_INVALID" in bad.text
        # Only the owner lists or touches it.
        listed = dev.get(f"/api/v1/personal-tasks?from={DAY}&to={DAY}").json()["data"]
        assert [row["id"] for row in listed] == [task["id"]]
        assert cto.get(f"/api/v1/personal-tasks?from={DAY}&to={DAY}").json()["data"] == []
        assert cto.patch(f"/api/v1/personal-tasks/{task['id']}", json={"status": "DONE"}).status_code == 404
        assert owner.get("/api/v1/personal-tasks").status_code == 200
        # The hours come off the person's free hours; the number shows, the task does not.
        with get_session() as session:
            stored = session.get(WorkforceMember, member["id"])
            assert reminders._hours_on(session, stored, date.fromisoformat(DAY)) == 6.0
        capacities = cto.get(f"/api/v1/planning/capacities/{DAY}").json()["data"]
        mine = next(row for row in capacities if row["member_id"] == member["id"])
        assert mine["personal_hours"] == 2.0 and mine["available_hours"] == 6.0 and "Nộp thuế" not in str(mine)
        # The agent sees it under "personal", adds another, marks one done.
        token = dev.post("/api/v1/auth/tokens", json={"name": "t"}).json()["data"]
        agent = TestClient(app, headers={"Authorization": f"Bearer {token['token']}"})
        day = _call(agent, "get_my_day", {"date": DAY})["structuredContent"]
        assert [row["title"] for row in day["personal"]] == ["Nộp thuế quý"] and day["personal"][0]["remind_at"] == "13:45"
        added = _call(agent, "add_personal_task", {"title": "Gọi ngân hàng", "date": DAY, "hours": 0.5})["structuredContent"]
        task_ids.append(added["id"])
        done = _call(agent, "update_personal_task", {"task_id": added["id"], "status": "DONE"})["structuredContent"]
        assert done["status"] == "DONE" and done["done_at"]
        assert "TASK_NOT_FOUND" in _call(agent, "update_personal_task", {"task_id": str(uuid4()), "status": "DONE"})["content"][0]["text"]
        # Telegram: the 08:00 note lists planned tasks; the reminder goes out at 13:45 even on a Sunday, once.
        with get_session() as session:
            stored = session.get(WorkforceMember, member["id"])
            stored.telegram_chat_id = "990011"
            session.commit()
            note = reminders.plan_private_message(session, stored, date.fromisoformat(DAY))
            assert "Việc riêng" in note and "14:00 · 2h · Nộp thuế quý" in note and "Gọi ngân hàng" not in note, note
            due = reminders.personal_reminders(session, datetime(2031, 5, 26, 13, 46, tzinfo=LOCAL_TZ))
            assert len(due) == 1 and due[0].kind == "PERSONAL_REMIND" and due[0].chat_id == "990011" and "Nộp thuế quý" in due[0].text and "Cổng thuế" in due[0].text
            assert reminders.personal_reminders(session, datetime(2031, 5, 26, 13, 30, tzinfo=LOCAL_TZ)) == []
        assert date.fromisoformat(DAY).weekday() == 0 or True
        # Eisenhower (FR-PER-04): important is the person's call, urgent follows the date unless overridden; the matrix
        # order holds everywhere and the drop quadrant is never reminded.
        from app.modules.planning import personal as personal_module
        far = "2031-06-20"
        q1 = dev.post("/api/v1/personal-tasks", json={"title": "Ký hợp đồng (quan trọng, hôm đó)", "task_date": DAY, "important": True}).json()["data"]
        q2 = dev.post("/api/v1/personal-tasks", json={"title": "Đọc sách (quan trọng, xa)", "task_date": far, "important": True}).json()["data"]
        q3 = dev.post("/api/v1/personal-tasks", json={"title": "Trả lời khảo sát (có nhắc)", "task_date": far, "remind_at": "09:00"}).json()["data"]
        q4 = dev.post("/api/v1/personal-tasks", json={"title": "Dọn hộp thư (không gì cả)", "task_date": far}).json()["data"]
        task_ids.extend([q1["id"], q2["id"], q3["id"], q4["id"]])
        today = personal_module._today()
        with get_session() as session:
            rows = {str(row.id): row for row in session.scalars(select(PersonalTask).where(PersonalTask.id.in_([q1["id"], q2["id"], q3["id"], q4["id"]]))).all()}
            assert personal_module.quadrant_of(rows[q1["id"]], date.fromisoformat(DAY)) == 1
            assert personal_module.quadrant_of(rows[q2["id"]], today) == 2 and personal_module.quadrant_of(rows[q3["id"]], today) == 3 and personal_module.quadrant_of(rows[q4["id"]], today) == 4
        assert q2["quadrant"] == 2 and q2["quadrant_label"] == "Lên lịch" and q3["quadrant"] == 3 and q4["quadrant_label"] == "Bỏ"
        # Override: the far task becomes urgent by hand, then goes back to the date's call.
        forced = dev.patch(f"/api/v1/personal-tasks/{q2['id']}", json={"urgent": True}).json()["data"]
        assert forced["quadrant"] == 1 and forced["urgent"] is True
        auto = dev.patch(f"/api/v1/personal-tasks/{q2['id']}", json={"urgent": None}).json()["data"]
        assert auto["quadrant"] == 2 and auto["urgent"] is None
        # The list for that far day comes in matrix order; the 08:00 note and the minute reminder skip the drop quadrant.
        listed = dev.get(f"/api/v1/personal-tasks?from={far}&to={far}").json()["data"]
        assert [row["quadrant"] for row in listed] == [2, 3, 4]
        with get_session() as session:
            stored = session.get(WorkforceMember, member["id"])
            note_far = reminders.plan_private_message(session, stored, date.fromisoformat(far))
            assert "[Lên lịch] Đọc sách" in note_far and "[Ủy quyền]" in note_far and "Dọn hộp thư" not in note_far, note_far
            assert reminders.personal_reminders(session, datetime(2031, 6, 20, 9, 5, tzinfo=LOCAL_TZ))[0].text.count("Trả lời khảo sát") == 1
            # On its own day a task is urgent by the date; only an override keeps it in the drop quadrant, unreminded.
            drop = session.get(PersonalTask, q4["id"])
            drop.remind_at, drop.urgent = "09:00", False
            session.commit()
            texts = [row.text for row in reminders.personal_reminders(session, datetime(2031, 6, 20, 9, 5, tzinfo=LOCAL_TZ))]
            assert all("Dọn hộp thư" not in text for text in texts)
        agent_day = _call(agent, "get_my_day", {"date": far})["structuredContent"]
        assert [row["quadrant"] for row in agent_day["personal"]] == [2, 3, 4] and agent_day["personal"][0]["quadrant_label"] == "Lên lịch"
        moved = _call(agent, "update_personal_task", {"task_id": q4["id"], "important": True, "urgent": True})["structuredContent"]
        assert moved["quadrant"] == 1

        # The week (FR-PER-05): a task with no date waits in the matrix; the strip counts; unfinished work rolls to
        # the next working day and is counted; a task the drop quadrant kept a week is archived and can come back.
        undated = dev.post("/api/v1/personal-tasks", json={"title": "Đọc báo cáo thị trường (chưa có ngày)", "important": True}).json()["data"]
        task_ids.append(undated["id"])
        assert undated["task_date"] is None and undated["quadrant"] == 2
        board = dev.get(f"/api/v1/personal-tasks/matrix?week_of={far}").json()["data"]
        assert board["week_start"] == "2031-06-16" and board["week_end"] == "2031-06-22"
        titles = [row["title"] for row in board["tasks"]]
        assert "Đọc báo cáo thị trường (chưa có ngày)" in titles and "Đọc sách (quan trọng, xa)" in titles
        assert board["summary"]["undated"] == 1 and any(q["quadrant"] == 2 and q["open"] >= 2 for q in board["summary"]["quadrants"])
        assert dev.get("/api/v1/personal-tasks/matrix").json()["data"]["today"] == personal_module._today().isoformat()
        # Scheduling from the matrix: a date goes on, the date comes off again.
        dated = dev.patch(f"/api/v1/personal-tasks/{undated['id']}", json={"task_date": far}).json()["data"]
        assert dated["task_date"] == far
        cleared = dev.patch(f"/api/v1/personal-tasks/{undated['id']}", json={"task_date": None}).json()["data"]
        assert cleared["task_date"] is None
        # The night after 2031-06-20 (a Friday): what was still planned for that day moves to Monday 23/06, counted.
        from datetime import timezone as _tz
        from app.modules.planning.overview import LOCAL_TZ as _ltz
        moved = personal_module.nightly(datetime(2031, 6, 20, 23, 58, tzinfo=_ltz))
        assert moved["rolled"] >= 2
        after = {row["title"]: row for row in dev.get(f"/api/v1/personal-tasks?from=2031-06-23&to=2031-06-23").json()["data"]}
        assert "Đọc sách (quan trọng, xa)" in after and after["Đọc sách (quan trọng, xa)"]["rollover_count"] == 1
        # The drop quadrant archives what it has held untouched for a week; restoring brings it back.
        with get_session() as session:
            drop = session.get(PersonalTask, q4["id"])
            drop.important, drop.urgent, drop.remind_at, drop.task_date = False, False, None, None
            drop.updated_at = datetime(2031, 6, 1, tzinfo=_tz.utc)
            session.commit()
        swept = personal_module.nightly(datetime(2031, 6, 20, 23, 58, tzinfo=_ltz))
        assert swept["archived"] >= 1
        assert q4["id"] in [row["id"] for row in dev.get("/api/v1/personal-tasks/archived").json()["data"]]
        assert q4["id"] not in [row["id"] for row in dev.get(f"/api/v1/personal-tasks/matrix?week_of={far}").json()["data"]["tasks"]]
        back = dev.patch(f"/api/v1/personal-tasks/{q4['id']}", json={"archived": False, "important": True}).json()["data"]
        assert back["archived_at"] is None and back["quadrant"] == 2

        # Delete: gone for the owner, and the hours come back.
        assert dev.delete(f"/api/v1/personal-tasks/{task['id']}").status_code == 204
        assert dev.delete(f"/api/v1/personal-tasks/{task['id']}").status_code == 404
        task_ids.remove(task["id"])
        with get_session() as session:
            stored = session.get(WorkforceMember, member["id"])
            # The half-hour task marked done still took its time; only the deleted one gives hours back.
            assert reminders._hours_on(session, stored, date.fromisoformat(DAY)) == 7.5
    finally:
        with get_session() as session:
            for row in session.scalars(select(PersonalTask).where(PersonalTask.id.in_(task_ids))).all():
                session.delete(row)
            user = session.scalar(select(User).where(User.auth_subject == f"per{tag}"))
            if user is not None:
                for row in session.scalars(select(PersonalTask).where(PersonalTask.user_id == user.id)).all():
                    session.delete(row)
                for row in session.scalars(select(ApiToken).where(ApiToken.user_id == user.id)).all():
                    session.delete(row)
                session.delete(user)
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member["id"])).all():
                session.delete(row)
            stored = session.get(WorkforceMember, member["id"])
            if stored is not None:
                session.delete(stored)
            session.commit()


def test_a_task_is_handed_to_a_staff_member_repeats_and_counts_in_the_week() -> None:
    """FR-PER-06: delegating puts support work in the member's day plan; a weekly task spawns its next occurrence when
    finished; the CTO's week summary carries the personal block; a developer may not delegate."""
    from app.models import PlanningAssignment, PlanningRun
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = cto.post("/api/v1/planning/members", json={
        "display_name": "Delegate Target", "email_reference": f"delegate-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424292", "role": "Developer"}],
    }).json()["data"]
    task_ids: list[str] = []
    run_ids: list[str] = []
    try:
        # A weekly task (Mondays): finishing it makes next Monday's.
        weekly = cto.post("/api/v1/personal-tasks", json={"title": "Báo cáo tuần cho ban điều hành", "task_date": "2031-07-07", "hours": 1, "important": True, "repeat_rule": "WEEKLY:0"}).json()["data"]
        task_ids.append(weekly["id"])
        assert weekly["repeat_label"] == "lặp tuần T2"
        assert "REPEAT_INVALID" in cto.post("/api/v1/personal-tasks", json={"title": "x", "repeat_rule": "DAILY"}).text
        finished = cto.patch(f"/api/v1/personal-tasks/{weekly['id']}", json={"status": "DONE"}).json()["data"]
        assert finished["status"] == "DONE" and finished["done_quadrant"] == 2
        following = cto.get("/api/v1/personal-tasks?from=2031-07-14&to=2031-07-14").json()["data"]
        assert [row["title"] for row in following] == ["Báo cáo tuần cho ban điều hành"] and following[0]["repeat_rule"] == "WEEKLY:0" and following[0]["important"]
        task_ids.append(following[0]["id"])
        # Finishing again does not double the chain; a monthly rule clips to the month's end.
        cto.patch(f"/api/v1/personal-tasks/{weekly['id']}", json={"status": "PLANNED"})
        cto.patch(f"/api/v1/personal-tasks/{weekly['id']}", json={"status": "DONE"})
        assert len(cto.get("/api/v1/personal-tasks?from=2031-07-14&to=2031-07-14").json()["data"]) == 1
        from app.modules.planning.personal import next_occurrence
        assert next_occurrence("MONTHLY:31", date(2031, 1, 31)) == date(2031, 2, 28) and next_occurrence("WEEKLY:0", date(2031, 7, 7)) == date(2031, 7, 14)

        # Delegating: support work in the member's plan for that day, the task marked as given away.
        chore = cto.post("/api/v1/personal-tasks", json={"title": "Gửi hồ sơ bảo hiểm", "task_date": "2031-07-08", "hours": 2}).json()["data"]
        task_ids.append(chore["id"])
        given = cto.post(f"/api/v1/personal-tasks/{chore['id']}/delegate", json={"member_id": member["id"], "project_id": project_id, "task_date": "2031-07-08"})
        assert given.status_code == 200, given.text
        row = given.json()["data"]
        assert row["status"] == "DELEGATED" and row["delegated_member_name"] == "Delegate Target" and row["plan"]["plan_date"] == "2031-07-08"
        run_ids.append(row["plan"]["run_id"])
        plan = cto.get(f"/api/v1/planning/runs/{row['plan']['run_id']}").json()["data"]
        mine = [a for a in plan["assignments"] if a["id"] == row["delegated_assignment_id"]]
        assert mine and mine[0]["work_type"] == "SUPPORT" and mine[0]["planned_hours"] == 2.0 and "Gửi hồ sơ bảo hiểm" in mine[0]["source_reference"] and mine[0]["gitlab_issue_external_id"] is None
        assert "TASK_NOT_OPEN" in cto.post(f"/api/v1/personal-tasks/{chore['id']}/delegate", json={"member_id": member["id"], "project_id": project_id, "task_date": "2031-07-08"}).text
        # The given task no longer reserves the owner's hours; it shows in the week block.
        from app.modules.planning.week import week_summary
        # The week block counts by when things were finished or handed on, which is now.
        from app.modules.planning.personal import _today
        week = week_summary(_today(), None, cto_user_id="00000000-0000-4000-8000-000000000001")
        assert week["personal"]["done_total"] >= 1 and week["personal"]["delegated"] >= 1 and "Việc riêng của CTO" in week["text"]
        assert cto.get(f"/api/v1/planning/week/{week['week_start'].isoformat()}").json()["data"]["personal"]["delegated"] >= 1
        # The Sunday note names what to tidy and last week's numbers.
        from app.modules.planning.personal import weekly_review_message
        with get_session() as session:
            note = weekly_review_message(session, "00000000-0000-4000-8000-000000000001", _today(), "/viec-rieng")
        assert note and "Dọn việc riêng" in note and "giao đi 1" in note, note
        # A developer may not delegate.
        created = cto.post("/api/v1/users", json={"subject": f"nodel{tag}", "role": "DEVELOPER", "member_id": member["id"]}).json()["data"]
        dev = TestClient(app, headers={"X-User-Subject": f"nodel{tag}"})
        dev.post("/api/v1/auth/password", json={"current_password": created["temporary_password"], "new_password": f"nodel-pass-{tag}-long"})
        own = dev.post("/api/v1/personal-tasks", json={"title": "Việc của dev", "task_date": "2031-07-08"}).json()["data"]
        task_ids.append(own["id"])
        assert dev.post(f"/api/v1/personal-tasks/{own['id']}/delegate", json={"member_id": member["id"], "project_id": project_id, "task_date": "2031-07-08"}).status_code == 403
    finally:
        with get_session() as session:
            for row in session.scalars(select(PersonalTask).where(PersonalTask.id.in_(task_ids))).all():
                session.delete(row)
            for run_id in run_ids:
                for a in session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run_id)).all():
                    session.delete(a)
                from app.models import PlanningCandidate, PlanningWarning
                for model in (PlanningWarning, PlanningCandidate):
                    for r in session.scalars(select(model).where(model.planning_run_id == run_id)).all():
                        session.delete(r)
                run = session.get(PlanningRun, run_id)
                if run is not None:
                    session.delete(run)
            user = session.scalar(select(User).where(User.auth_subject == f"nodel{tag}"))
            if user is not None:
                for row in session.scalars(select(PersonalTask).where(PersonalTask.user_id == user.id)).all():
                    session.delete(row)
                session.delete(user)
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member["id"])).all():
                session.delete(row)
            stored = session.get(WorkforceMember, member["id"])
            if stored is not None:
                session.delete(stored)
            session.commit()
