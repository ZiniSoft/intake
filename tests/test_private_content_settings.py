"""The personal-brand Beta settings stay inside the CTO's private project."""
from copy import deepcopy

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import Project
from tests.test_private_space import _space, cto


BASE = "/api/v1/private-space/content-settings"
owner = TestClient(app, headers={"X-User-Subject": "project-owner"})


def _restore(project_id: str, settings: dict) -> None:
    with get_session() as session:
        project = session.get(Project, project_id)
        project.project_settings = settings
        session.commit()


def test_private_channel_and_scanner_settings_do_not_change_global_settings() -> None:
    project = _space()["project"]
    with get_session() as session:
        row = session.get(Project, project["id"])
        before = deepcopy(row.project_settings)

    global_channel = next(row for row in cto.get("/api/v1/channel-rules").json()["data"] if row["code"] == "X")
    global_platform = next(row for row in cto.get("/api/v1/settings/watch-platforms").json()["data"] if row["code"] == "YOUTUBE")
    try:
        assert owner.get(f"{BASE}/channels").status_code == 403
        changed_channel = cto.put(f"{BASE}/channels/X", json={"max_chars": global_channel["max_chars"] + 1, "auto_publish": True}).json()["data"]
        assert changed_channel["max_chars"] == global_channel["max_chars"] + 1
        assert changed_channel["auto_publish"] is False
        assert next(row for row in cto.get("/api/v1/channel-rules").json()["data"] if row["code"] == "X")["max_chars"] == global_channel["max_chars"]

        changed_platform = cto.put(f"{BASE}/watch-platforms/YOUTUBE", json={"enabled": not global_platform["enabled"]}).json()["data"]
        assert changed_platform["enabled"] is (not global_platform["enabled"])
        assert next(row for row in cto.get("/api/v1/settings/watch-platforms").json()["data"] if row["code"] == "YOUTUBE")["enabled"] is global_platform["enabled"]

        assert cto.put(f"{BASE}/watch-limits", json={"max_ai_runs_per_day": 2}).json()["data"] == {"max_ai_runs_per_day": 2}
        with get_session() as session:
            saved = session.get(Project, project["id"]).project_settings["private_content_settings"]
            assert saved["max_ai_runs_per_day"] == 2
    finally:
        _restore(project["id"], before)


def test_private_connector_cannot_escape_the_private_project() -> None:
    project = _space()["project"]
    made = cto.post(f"{BASE}/connectors", json={"project": "ignored-external-project", "name": "Private scanner", "kind": "N8N", "via": "api"})
    assert made.status_code == 201, made.text
    connector = made.json()["data"]
    try:
        with get_session() as session:
            private_id = session.scalar(select(Project.id).where(Project.code == project["code"]))
        listed = cto.get(f"{BASE}/connectors").json()["data"]
        assert connector["id"] in {row["id"] for row in listed}
        assert connector["project_id"] == str(private_id)
        assert owner.get(f"{BASE}/connectors").status_code == 403
    finally:
        assert cto.delete(f"{BASE}/connectors/{connector['id']}").status_code == 204
