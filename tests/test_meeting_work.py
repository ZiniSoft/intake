"""From the meeting straight to the board (FR-REC-19): an action item becomes work in one step, approved from the
meeting without an AI pass, carrying the person and the date settled on the line; a decision stays in the note."""
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApprovalAction, AuditEvent, IntakeItem, Meeting, ProcessingRun, Project, WorkComment, WorkforceMember, WorkforceProjectMembership, WorkItem, WorkLink
from tests.test_meeting_notes import _note, _transcribed, storage  # noqa: F401  (the storage fixture)

client = TestClient(app, headers={"X-User-Subject": "cto"})


def _cleanup(work_ids: list[str], member_id: str | None) -> None:
    with get_session() as session:
        for work_id in work_ids:
            for model in (WorkComment, WorkLink):
                for row in session.scalars(select(model).where(model.work_id == work_id)).all():
                    session.delete(row)
            for row in session.scalars(select(AuditEvent).where(AuditEvent.entity_type == "work", AuditEvent.entity_id == work_id)).all():
                session.delete(row)
            row = session.get(WorkItem, work_id)
            if row is not None:
                session.delete(row)
        if member_id:
            for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.member_id == member_id)).all():
                session.delete(row)
            member = session.get(WorkforceMember, member_id)
            if member is not None:
                session.delete(member)
        session.commit()


def test_an_action_item_goes_straight_to_the_board_with_its_person_and_date(monkeypatch, storage) -> None:  # noqa: F811
    from app.services import ai_processor
    from app.workers import ai_tasks

    # Earlier test files leave recordings waiting for transcription; the gateway takes the oldest first, so they
    # are settled before this meeting is recorded.
    with get_session() as session:
        for stale in session.scalars(select(Meeting).where(Meeting.transcript_status == "PENDING")).all():
            stale.transcript_status = "FAILED"
        session.commit()
    meeting = _transcribed(monkeypatch, storage)

    async def fake_note(source_text: str):
        return _note()

    monkeypatch.setattr(ai_processor.umodelverse_adapter, "is_configured", lambda *a, **k: True)
    monkeypatch.setattr(ai_processor.umodelverse_adapter, "extract_meeting_note", fake_note)
    assert ai_tasks.generate_meeting_note(meeting["id"]) == "SUCCEEDED"
    detail = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
    by_kind = {item["kind"]: item for item in detail["note_items"]}
    assert by_kind["ACTION"]["can_become_work"] is True and by_kind["QUESTION"]["can_become_work"] is True and by_kind["DECISION"]["can_become_work"] is False
    with get_session() as session:
        project_id = str(session.scalar(select(Project).where(Project.code == "orbit")).id)
    tag = uuid4().hex[:6]
    member = client.post("/api/v1/planning/members", json={
        "display_name": "Người Họp", "email_reference": f"hop-{tag}@example.test",
        "project_mappings": [{"project_id": project_id, "gitlab_user_external_id": "424364", "role": "Developer"}],
    }).json()["data"]
    work_ids: list[str] = []
    try:
        base = f"/api/v1/meetings/{meeting['id']}/note/items/work"
        # The action item is on the meeting's project already; the question has a project too (the meeting's).
        made = client.post(base, json={"items": [
            {"item_id": by_kind["ACTION"]["id"], "member_id": member["id"], "due_date": "2026-10-24"},
            {"item_id": by_kind["QUESTION"]["id"]},
            {"item_id": by_kind["DECISION"]["id"]},
        ]})
        assert made.status_code == 201, made.text
        results = {row["item_id"]: row for row in made.json()["data"]["results"]}
        action, question, decision = results[by_kind["ACTION"]["id"]], results[by_kind["QUESTION"]["id"]], results[by_kind["DECISION"]["id"]]
        assert action["work_id"] and action["code"].startswith("ORB-W-") and question["work_id"] and decision["error"] == "NOTE_ITEM_NOT_ACTIONABLE"
        work_ids += [action["work_id"], question["work_id"]]

        work = client.get(f"/api/v1/work/{action['work_id']}").json()["data"]
        assert work["title"] == "Hỏi khách dữ liệu mẫu" and work["status"] == "READY" and work["member_id"] == member["id"] and work["due_date"] == "2026-10-24"
        assert work["intake_public_id"] and work["meeting_id"] == meeting["id"] and work["meeting_title"]
        asked = client.get(f"/api/v1/work/{question['work_id']}").json()["data"]
        assert asked["status"] == "DISCUSS" and asked["title"] == "Khi nào có dữ liệu mẫu?"

        # The Intake behind it: channel MEETING, approved for WORK from the meeting, never read by the AI.
        with get_session() as session:
            intake = session.get(IntakeItem, action["intake_id"])
            assert intake.channel == "MEETING" and intake.status == "APPROVED" and intake.approved_route == "WORK" and intake.item_type == "TASK"
            assert intake.normalized_title == "Hỏi khách dữ liệu mẫu"
            actions = session.scalars(select(ApprovalAction).where(ApprovalAction.intake_id == intake.id)).all()
            assert [(a.action, a.source) for a in actions] == [("APPROVE", "MEETING")] and actions[0].reason.startswith("Từ cuộc họp:")
            assert session.scalars(select(ProcessingRun).where(ProcessingRun.intake_id == intake.id)).all() == []
        after = client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]
        row = next(item for item in after["note_items"] if item["id"] == by_kind["ACTION"]["id"])
        assert row["work_code"] == action["code"] and row["work_id"] == action["work_id"] and row["can_become_work"] is False and row["can_become_intake"] is False
        # Twice is refused; a person off the project is refused before anything is made.
        again = client.post(base, json={"items": [{"item_id": by_kind["ACTION"]["id"]}]}).json()["data"]["results"][0]
        assert again["error"] == "NOTE_ITEM_HAS_INTAKE"
        with get_session() as session:
            ember = str(session.scalar(select(Project).where(Project.code == "ember")).id)
        other = client.post("/api/v1/planning/members", json={"display_name": "Người Khác", "email_reference": f"khac-{tag}@example.test", "project_mappings": [{"project_id": ember, "gitlab_user_external_id": "424365", "role": "Developer"}]}).json()["data"]
        try:
            wrong = client.post(base, json={"items": [{"item_id": by_kind["RISK"]["id"], "member_id": other["id"]}]}).json()["data"]["results"][0]
            assert wrong["error"] == "MEMBER_NOT_IN_PROJECT"
            assert next(item for item in client.get(f"/api/v1/meetings/{meeting['id']}").json()["data"]["note_items"] if item["id"] == by_kind["RISK"]["id"])["intake_id"] is None
        finally:
            _cleanup([], other["id"])
        # The owner of another project cannot reach this meeting.
        owner = TestClient(app, headers={"X-User-Subject": "project-owner"})
        assert owner.post(base, json={"items": [{"item_id": by_kind["RISK"]["id"]}]}).status_code == 404
    finally:
        _cleanup(work_ids, member["id"])
