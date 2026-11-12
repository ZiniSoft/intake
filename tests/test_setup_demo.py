"""FR-SETUP-11, FR-SETUP-12: the fictional demo project that lets a fresh install finish setup without an AI key."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import (
    AppSetting, DailyCapacity, IntakeItem, PlanningAssignment, PlanningRun, PlanningSyncJob, Project, ProjectIntegration,
    SyncJob, WorkforceMember, WorkforceProjectMembership,
)
from app.modules.projects.service import OTHER_PROJECT_CODE
from app.modules.setup import demo as demo_module
from app.modules.setup.service import SETUP_KEY, SetupService

cto = TestClient(app, headers={"X-User-Subject": "cto"})


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def _remove_demo() -> None:
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "demo"))
        if project is None:
            return
        pid = project.id
        member_ids = [m for (m,) in session.execute(
            select(WorkforceProjectMembership.member_id).where(WorkforceProjectMembership.project_id == pid)).all()]
        run_ids = [r for (r,) in session.execute(select(PlanningAssignment.planning_run_id).where(PlanningAssignment.project_id == pid)).all()]
        for model in (PlanningAssignment,):
            for row in session.scalars(select(model).where(model.project_id == pid)).all():
                session.delete(row)
        for run in session.scalars(select(PlanningRun).where(PlanningRun.id.in_(set(run_ids)))).all():
            session.delete(run)
        for item in session.scalars(select(IntakeItem).where(IntakeItem.project_id == pid)).all():
            session.delete(item)
        for row in session.scalars(select(WorkforceProjectMembership).where(WorkforceProjectMembership.project_id == pid)).all():
            session.delete(row)
        for row in session.scalars(select(DailyCapacity).where(DailyCapacity.member_id.in_(member_ids))).all():
            session.delete(row)
        session.flush()
        for row in session.scalars(select(Project).where(Project.id == pid)).all():
            session.delete(row)
        session.flush()
        for row in session.scalars(select(WorkforceMember).where(WorkforceMember.id.in_(member_ids))).all():
            session.delete(row)
        session.commit()


@pytest.fixture()
def fresh(monkeypatch):
    """A fresh install: wizard flag on, no real project, setup not yet completed; the demo is removed afterwards."""
    monkeypatch.setattr(get_settings(), "first_run_wizard", True)
    monkeypatch.setattr(SetupService, "_real_projects", staticmethod(lambda session: 0))
    other_state = None
    with get_session() as session:
        other = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
        other_state = (other.name, other.updated_at) if other is not None else None
        row = session.get(AppSetting, SETUP_KEY)
        if row:
            session.delete(row)
            session.commit()
    _remove_demo()
    yield
    _remove_demo()
    with get_session() as session:
        other = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
        if other is not None and other_state is not None:
            other.name, other.updated_at = other_state
        row = session.get(AppSetting, SETUP_KEY)
        if row:
            session.delete(row)
            session.commit()


def test_demo_is_offered_and_loads_once(fresh):
    state = cto.get("/api/v1/setup").json()["data"]
    assert state["demo_available"] is True and state["has_demo"] is False
    first = cto.post("/api/v1/setup/demo-project")
    assert first.status_code == 200, first.text
    assert first.json()["data"]["has_demo"] is True
    with get_session() as session:
        before = (_count(session, IntakeItem), _count(session, WorkforceMember))
    assert cto.post("/api/v1/setup/demo-project").status_code == 200  # asking twice is harmless
    with get_session() as session:
        assert (_count(session, IntakeItem), _count(session, WorkforceMember)) == before


def test_demo_project_content(fresh):
    assert cto.post("/api/v1/setup/demo-project").status_code == 200
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "demo"))
        assert project.name == "Sample project"
        assert project.kind == "SOFTWARE" and project.project_settings["demo"] is True
        assert project.project_settings["demo_repo_url"] == "https://github.com/ZiniSoft/minigames"
        members = session.scalars(select(WorkforceMember).join(WorkforceProjectMembership).where(
            WorkforceProjectMembership.project_id == project.id
        )).all()
        assert {member.display_name for member in members} == {"Maya Sample", "Noah Sample", "Avery Sample"}
        other = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
        assert other is not None and other.name == "Other project"
        items = session.scalars(select(IntakeItem).where(IntakeItem.project_id == project.id)).all()
        assert len(items) == 4 and all(i.public_id.startswith("DEM-") for i in items)
        assert {i.status for i in items} == {"PENDING_APPROVAL", "NEEDS_INFORMATION", "APPROVED"}
        approved = [i for i in items if i.status == "APPROVED"]
        assert approved and all(i.approved_route and i.approved_priority for i in approved)
        run = session.scalar(select(PlanningRun).where(PlanningRun.project_scope == [str(project.id)]))
        assert run is not None
        assert session.scalars(select(PlanningAssignment).where(PlanningAssignment.planning_run_id == run.id)).all()


def test_demo_project_uses_the_requested_browser_locale(fresh):
    assert cto.post("/api/v1/setup/demo-project?locale=vi").status_code == 200
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "demo"))
        assert project.name == "Dự án mẫu"
        members = session.scalars(select(WorkforceMember).join(WorkforceProjectMembership).where(
            WorkforceProjectMembership.project_id == project.id
        )).all()
        assert {member.display_name for member in members} == {"Linh Mẫu", "Bình Mẫu", "Châu Mẫu"}
        other = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
        assert other is not None and other.name == "Dự án khác"
        titles = [row.normalized_title for row in session.scalars(
            select(IntakeItem).where(IntakeItem.project_id == project.id)
        ).all()]
        assert "Thêm nút tắt tiếng nhạc nền" in titles


def test_demo_project_rejects_an_unknown_locale(fresh):
    response = cto.post("/api/v1/setup/demo-project?locale=fr")
    assert response.status_code == 422


def test_demo_sends_nothing_outside(fresh):
    with get_session() as session:
        before = (_count(session, ProjectIntegration), _count(session, SyncJob), _count(session, PlanningSyncJob))
    assert cto.post("/api/v1/setup/demo-project").status_code == 200
    with get_session() as session:
        assert (_count(session, ProjectIntegration), _count(session, SyncJob), _count(session, PlanningSyncJob)) == before
        project = session.scalar(select(Project).where(Project.code == "demo"))
        assert project.telegram_chat_id is None
        member_ids = [m for (m,) in session.execute(
            select(WorkforceProjectMembership.member_id).where(WorkforceProjectMembership.project_id == project.id)).all()]
        members = session.scalars(select(WorkforceMember).where(WorkforceMember.id.in_(member_ids))).all()
        assert len(members) == 3
        assert all(m.email_reference is None and m.telegram_chat_id is None and m.telegram_username is None for m in members)


def test_demo_does_not_touch_other_projects(fresh):
    with get_session() as session:
        before = {p.code: (p.name, p.owner_member_id, p.updated_at) for p in session.scalars(select(Project)).all() if p.code != OTHER_PROJECT_CODE}
        items_before = _count(session, IntakeItem)
    assert cto.post("/api/v1/setup/demo-project").status_code == 200
    with get_session() as session:
        after = {p.code: (p.name, p.owner_member_id, p.updated_at) for p in session.scalars(select(Project)).all() if p.code not in {"demo", OTHER_PROJECT_CODE}}
        other = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
        assert other is not None and other.name == "Other project"
        assert {k: v for k, v in after.items() if k != "demo"} == before
        assert _count(session, IntakeItem) == items_before + 4


def test_finishing_without_a_key_needs_the_demo(fresh):
    blocked = cto.post("/api/v1/setup/complete")
    assert blocked.status_code == 422 and blocked.json()["error"] == "AI_KEY_REQUIRED"
    assert cto.post("/api/v1/setup/demo-project").status_code == 200
    state = cto.get("/api/v1/setup").json()["data"]
    # Loading the demo finishes setup (so the app's guard lets the person in), yet it is not the install's own project.
    assert state["completed"] is True and state["has_project"] is False
    done = cto.post("/api/v1/setup/complete")
    assert done.status_code == 200, done.text
    assert done.json()["data"]["completed"] is True and done.json()["data"]["has_demo"] is True


def test_demo_is_closed_when_the_wizard_is_off(fresh, monkeypatch):
    monkeypatch.setattr(get_settings(), "first_run_wizard", False)
    assert cto.post("/api/v1/setup/demo-project").status_code == 422
    with get_session() as session:
        assert session.scalar(select(Project).where(Project.code == "demo")) is None


def test_demo_needs_the_cto(fresh):
    assert TestClient(app, headers={"X-User-Subject": "nobody"}).post("/api/v1/setup/demo-project").status_code in (401, 403)


def test_missing_and_broken_bundles_are_refused(fresh, monkeypatch, tmp_path):
    with pytest.raises(demo_module.DemoError) as missing:
        demo_module.load_demo_project("x", tmp_path / "none.json")
    assert missing.value.code == "SAMPLE_MISSING"
    broken = tmp_path / "demo.json"
    broken.write_text(json.dumps({"project": {}}), encoding="utf-8")
    with pytest.raises(demo_module.DemoError) as invalid:
        demo_module.load_demo_project("x", broken)
    assert invalid.value.code == "SAMPLE_INVALID"
    with get_session() as session:
        assert session.scalar(select(Project).where(Project.code == "demo")) is None
