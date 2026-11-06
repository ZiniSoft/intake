"""Showcase catalogue (FR-SETUP-15, FR-SETUP-16): sample and author-owned projects the CTO can switch on or off.

Switching on creates an ordinary Intake project (or the demo project) once. Switching off only archives it
(`status = INACTIVE`), so switching on again restores the same project and never recreates its data.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete, select

from app.db import get_session
from app.models import AuditEvent, IntakeItem, Project, ShowcaseEnabled, SourceMessage
from app.modules.setup.demo import DEMO_FLAG, DemoError, is_demo, load_demo_project
from app.services.raw_crypto import encrypt

CATALOG = Path(__file__).resolve().parents[2] / "resources" / "showcase.json"
TEST_DATA_FLAG = "test_data"


class ShowcaseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_showcase(project: Project) -> bool:
    settings = project.project_settings or {}
    return bool(settings.get(DEMO_FLAG) or settings.get("showcase"))


def read_catalog() -> dict:
    try:
        return json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 0, "groups": {}, "items": []}


def _item_view(item: dict, row: ShowcaseEnabled | None, project: Project | None, samples: int) -> dict[str, object]:
    state = "off"
    if project is not None:
        state = "on" if project.status == "ACTIVE" else "archived"
    return {
        "key": item["key"], "kind": item["kind"], "group": item["group"], "name": item["name"], "summary": item["summary"],
        "repo_url": item["repo_url"], "languages": item["languages"], "license": item["license"],
        "state": state, "project_code": project.code if project is not None else None, "sample_requests": samples,
        "in_catalog": True,
    }


def _project_of(session, key: str) -> tuple[ShowcaseEnabled | None, Project | None]:
    row = session.get(ShowcaseEnabled, key)
    if row is not None:
        return row, session.get(Project, row.project_id)
    # The demo project may have been loaded by the older setup button, before the catalogue recorded it.
    if any(item["key"] == key and item["kind"] == "demo" for item in read_catalog()["items"]):
        for project in session.scalars(select(Project)).all():
            if is_demo(project):
                return None, project
    return None, None


def _count_samples(session, project: Project | None) -> int:
    if project is None:
        return 0
    rows = session.scalars(select(IntakeItem.normalized_details).where(IntakeItem.project_id == project.id)).all()
    return sum(1 for details in rows if isinstance(details, dict) and details.get(TEST_DATA_FLAG))


def list_items() -> dict[str, object]:
    catalog = read_catalog()
    keys = {item["key"] for item in catalog["items"]}
    with get_session() as session:
        views = []
        for item in catalog["items"]:
            row, project = _project_of(session, item["key"])
            views.append(_item_view(item, row, project, _count_samples(session, project)))
        # An item switched on that a later release dropped from the catalogue stays listed so it can still be archived.
        for row in session.scalars(select(ShowcaseEnabled).where(ShowcaseEnabled.item_key.not_in(keys) if keys else True)).all():
            project = session.get(Project, row.project_id)
            if project is None:
                continue
            views.append({
                "key": row.item_key, "kind": "real", "group": "", "name": project.name, "summary": "", "repo_url": "",
                "languages": [], "license": "", "state": "on" if project.status == "ACTIVE" else "archived",
                "project_code": project.code, "sample_requests": _count_samples(session, project), "in_catalog": False,
            })
    return {"version": catalog["version"], "groups": catalog["groups"], "items": views}


def _find_item(key: str) -> dict:
    for item in read_catalog()["items"]:
        if item["key"] == key:
            return item
    raise ShowcaseError("NOT_FOUND", "This item is not in the catalogue")


def set_enabled(key: str, enabled: bool, actor_id: str) -> dict[str, object]:
    catalog = read_catalog()
    now = datetime.now(timezone.utc)
    with get_session() as session:
        row, project = _project_of(session, key)
        if row is None and project is None and not enabled:
            return list_items()
        if project is None:
            project = _create_project(session, _find_item(key), actor_id, now)
        project.status = "ACTIVE" if enabled else "INACTIVE"
        project.updated_at = now
        if row is None:
            session.add(ShowcaseEnabled(
                item_key=key, project_id=project.id, catalog_version=int(catalog["version"]), enabled_by=actor_id, enabled_at=now,
            ))
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project.id if project is not None else None, actor_type="USER", actor_id=actor_id,
            event_type="showcase.enabled" if enabled else "showcase.archived", entity_type="project",
            entity_id=project.id if project is not None else key, details={"item": key}, created_at=now,
        ))
        session.commit()
    return list_items()


def _create_project(session, item: dict, actor_id: str, now: datetime) -> Project:
    if item["kind"] == "demo":
        session.commit()  # the demo loader opens its own session
        try:
            result = load_demo_project(actor_id)
        except DemoError as error:
            raise ShowcaseError(error.code, error.message) from error
        project = session.get(Project, result["project_id"])
        if project is None or not is_demo(project):
            raise ShowcaseError("DEMO_CODE_TAKEN", "A project with the demo code already exists")
        project.status = "ACTIVE"
        return project
    code, intake_key = item.get("project_code"), item.get("intake_key")
    if not code or not intake_key:
        raise ShowcaseError("CATALOG_INVALID", "The catalogue item has no project code")
    if session.scalar(select(Project.id).where(Project.code == code)) or session.scalar(select(Project.id).where(Project.intake_key == intake_key)):
        raise ShowcaseError("PROJECT_CODE_TAKEN", f"A project with code {code} or key {intake_key} already exists")
    from app.services.intake_service import intake_store

    project = Project(
        id=str(uuid4()), code=code, intake_key=intake_key, name=item["name"], kind="SOFTWARE", status="ACTIVE",
        project_settings={"showcase": item["key"], "repo_url": item["repo_url"]}, created_at=now, updated_at=now,
    )
    session.add(project)
    session.flush()
    for sample in item.get("sample_requests", []):
        public_id = intake_store._next_public_id(session, project, now)
        item_id = str(uuid4())
        session.add(IntakeItem(
            id=item_id, public_id=public_id, project_id=project.id, channel="MANUAL", item_type=sample.get("type", "FEATURE"),
            status="PENDING_APPROVAL", normalized_title=sample["title"], normalized_summary=sample["body"],
            normalized_details={TEST_DATA_FLAG: True}, suggested_priority=sample.get("priority", "P2"), proposed_route="GITHUB",
            version=1, created_by=actor_id, created_at=now, updated_at=now,
        ))
        session.add(SourceMessage(
            id=str(uuid4()), intake_id=item_id, channel="MANUAL", sender_reference_ciphertext=encrypt("Dữ liệu thử"),
            raw_content_ciphertext=encrypt(sample["body"]), received_at=now, purge_after=now + timedelta(days=90), created_at=now,
        ))
    return project


def remove_samples(key: str, actor_id: str) -> int:
    """Delete the sample requests of one item. Only rows still flagged as test data and still pending are removed."""
    with get_session() as session:
        _row, project = _project_of(session, key)
        if project is None:
            raise ShowcaseError("NOT_FOUND", "This item has not been switched on")
        ids = [
            str(item.id) for item in session.scalars(select(IntakeItem).where(IntakeItem.project_id == project.id, IntakeItem.status == "PENDING_APPROVAL")).all()
            if isinstance(item.normalized_details, dict) and item.normalized_details.get(TEST_DATA_FLAG)
        ]
        if ids:
            session.execute(delete(SourceMessage).where(SourceMessage.intake_id.in_(ids)))
            session.execute(delete(IntakeItem).where(IntakeItem.id.in_(ids)))
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id, event_type="showcase.samples_removed",
            entity_type="project", entity_id=project.id, details={"item": key, "removed": len(ids)}, created_at=datetime.now(timezone.utc),
        ))
        session.commit()
        return len(ids)
