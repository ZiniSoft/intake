"""FR-SETUP-15, FR-SETUP-16: the showcase catalogue switches sample and author projects on and off."""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import AuditEvent, IntakeItem, Project, ShowcaseEnabled, SourceMessage
from app.modules.showcase import service

cto = TestClient(app, headers={"X-User-Subject": "cto"})
KEY = "test-showcase-item"


def _catalog(samples=None):
    return {
        "version": 1, "groups": {"g": "Nhóm thử"}, "groups_en": {"g": "Test group"},
        "items": [{
            "key": KEY, "kind": "real", "group": "g", "name": "Showcase thử", "summary": "Mục thử", "project_code": "showcase-test",
            "name_en": "Sample showcase", "summary_en": "Sample item",
            "intake_key": "SCT", "repo_url": "https://github.com/example/example", "languages": ["Python"], "license": "MIT",
            "license_en": "MIT",
            "default_enabled": False, "sample_requests": samples or [],
        }],
    }


def _purge():
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "showcase-test"))
        if project is None:
            return
        for item in session.scalars(select(IntakeItem).where(IntakeItem.project_id == project.id)).all():
            for message in session.scalars(select(SourceMessage).where(SourceMessage.intake_id == item.id)).all():
                session.delete(message)
            session.delete(item)
        for row in session.scalars(select(ShowcaseEnabled).where(ShowcaseEnabled.project_id == project.id)).all():
            session.delete(row)
        for row in session.scalars(select(AuditEvent).where(AuditEvent.project_id == project.id)).all():
            session.delete(row)
        session.flush()
        session.delete(project)
        session.commit()


@pytest.fixture()
def catalog(tmp_path, monkeypatch):
    path = tmp_path / "showcase.json"

    def write(samples=None):
        path.write_text(json.dumps(_catalog(samples)), encoding="utf-8")

    write()
    monkeypatch.setattr(service, "CATALOG", path)
    _purge()
    yield write
    _purge()


def _item():
    items = cto.get("/api/v1/showcase").json()["data"]["items"]
    return next(item for item in items if item["key"] == KEY)


def test_item_starts_off_and_toggle_creates_then_restores_the_same_project(catalog):
    assert _item()["state"] == "off"
    on = cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": True})
    assert on.status_code == 200
    first = _item()
    assert first["state"] == "on" and first["project_code"] == "showcase-test"
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "showcase-test"))
        project_id = project.id
        assert project.kind == "SOFTWARE" and (project.project_settings or {})["repo_url"].startswith("https://")
    cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": False})
    assert _item()["state"] == "archived"
    cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": True})
    assert _item()["state"] == "on"
    with get_session() as session:
        rows = session.scalars(select(Project).where(Project.code == "showcase-test")).all()
        assert [row.id for row in rows] == [project_id]


def test_catalog_text_follows_requested_locale(catalog):
    english = cto.get("/api/v1/showcase?locale=en")
    assert english.status_code == 200
    assert english.json()["data"]["groups"]["g"] == "Test group"
    assert english.json()["data"]["items"][0]["name"] == "Sample showcase"
    vietnamese = cto.get("/api/v1/showcase?locale=vi")
    assert vietnamese.json()["data"]["groups"]["g"] == "Nhóm thử"
    assert vietnamese.json()["data"]["items"][0]["name"] == "Showcase thử"
    assert cto.get("/api/v1/showcase?locale=fr").status_code == 422


def test_samples_are_created_once_marked_and_removable(catalog):
    catalog([{"title": "Yêu cầu thử", "body": "Nội dung thử"}, {"title": "Yêu cầu thử 2", "body": "Nội dung thử 2"}])
    cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": True})
    cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": False})
    cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": True})
    assert _item()["sample_requests"] == 2
    removed = cto.delete(f"/api/v1/showcase/{KEY}/samples")
    assert removed.status_code == 200 and removed.json()["data"]["removed"] == 2
    assert _item()["sample_requests"] == 0


def test_unknown_item_and_non_cto_are_refused(catalog):
    assert cto.put("/api/v1/showcase/no-such-item", json={"enabled": True}).status_code == 404
    assert cto.delete("/api/v1/showcase/no-such-item/samples").status_code == 404
    other = TestClient(app, headers={"X-User-Subject": "project-owner"})
    assert other.get("/api/v1/showcase").status_code == 403
    assert other.put(f"/api/v1/showcase/{KEY}", json={"enabled": True}).status_code == 403


def test_item_dropped_from_the_catalogue_stays_listed_while_on(catalog, tmp_path, monkeypatch):
    cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": True})
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"version": 2, "groups": {}, "items": []}), encoding="utf-8")
    monkeypatch.setattr(service, "CATALOG", empty)
    items = cto.get("/api/v1/showcase").json()["data"]["items"]
    gone = next(item for item in items if item["key"] == KEY)
    assert gone["in_catalog"] is False and gone["state"] == "on"
    assert cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": False}).status_code == 200


def test_showcase_project_does_not_count_as_a_real_project(catalog):
    from app.modules.setup.service import SetupService

    cto.put(f"/api/v1/showcase/{KEY}", json={"enabled": True})
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == "showcase-test"))
        before = SetupService._real_projects(session)
        project.project_settings = {}
        session.flush()
        assert SetupService._real_projects(session) == before + 1
        session.rollback()
