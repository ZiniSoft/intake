"""FR-SETUP-01..03: first-run setup state, the fictional sample voice, and the seed that ships with a fresh install."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AppSetting, Project
from app.modules.private_space.service import MASTER_DNA_KEY, TRACKS, private_space_service, voices_of
from app.modules.projects.service import OTHER_PROJECT_CODE, project_catalog_service
from app.modules.setup.service import SAMPLE_BUNDLE, SETUP_KEY, SetupService

cto = TestClient(app, headers={"X-User-Subject": "cto"})


@pytest.fixture()
def private_space_restored():
    """The private space is shared by many tests: put its settings back after the sample overwrote them."""
    before = None
    with get_session() as session:
        ids = [p for p in session.scalars(select(Project)).all() if (p.project_settings or {}).get("private")]
        before = (ids[0].id, dict(ids[0].project_settings)) if ids else None
    yield
    with get_session() as session:
        if before:
            session.get(Project, before[0]).project_settings = before[1]
            session.commit()


@pytest.fixture()
def no_flag():
    with get_session() as session:
        row = session.get(AppSetting, SETUP_KEY)
        if row:
            session.delete(row)
            session.commit()
    yield
    with get_session() as session:
        row = session.get(AppSetting, SETUP_KEY)
        if row:
            session.delete(row)
            session.commit()


def test_setup_needs_the_cto():
    assert TestClient(app, headers={"X-User-Subject": "nobody"}).get("/api/v1/setup").status_code in (401, 403)


def test_install_with_a_real_project_is_already_set_up(no_flag):
    state = cto.get("/api/v1/setup").json()["data"]
    assert state["completed"] is True and state["has_project"] is True and state["sample_available"] is True


def test_fresh_install_waits_for_setup_until_completed(no_flag, monkeypatch):
    monkeypatch.setattr(SetupService, "_real_projects", staticmethod(lambda session: 0))
    assert cto.get("/api/v1/setup").json()["data"]["completed"] is False
    done = cto.post("/api/v1/setup/complete").json()["data"]
    assert done["completed"] is True and done["has_project"] is False
    assert cto.post("/api/v1/setup/complete").status_code == 200  # asking twice is harmless


def test_sample_voice_loads_fictional_brand(private_space_restored):
    state = cto.post("/api/v1/setup/private-sample")
    assert state.status_code == 200, state.text
    assert state.json()["data"]["has_private_space"] is True
    with get_session() as session:
        project = private_space_service._project(session)
        settings = project.project_settings
    assert "Nova Labs" in settings[MASTER_DNA_KEY]
    voices = voices_of(settings)
    assert set(voices) == set(TRACKS) and voices["business"]["samples"] and voices["technical"]["pillars"]


def test_sample_bundle_is_fictional_and_self_contained():
    bundle = json.loads(SAMPLE_BUNDLE.read_text(encoding="utf-8"))
    base = Path(SAMPLE_BUNDLE).parent
    text = "".join(path.read_text(encoding="utf-8") for path in base.rglob("*") if path.is_file())
    assert "Nova Labs" in text
    assert set(bundle["tracks"]) == set(TRACKS)


def test_fresh_catalog_seeds_only_the_catch_all_project():
    project_catalog_service.ensure_database_projects()
    with get_session() as session:
        other = session.scalar(select(Project).where(Project.code == OTHER_PROJECT_CODE))
    assert other is not None and other.intake_key == "OTH"
