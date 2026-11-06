"""FR-INTG-20: the pre-filled GitHub issue link carries normalized content only."""
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import IntakeItem, Project
from app.modules.integrations.issue_link import MAX_URL_LENGTH, build_new_issue_url
from app.services.intake_service import intake_store

cto = TestClient(app, headers={"X-User-Subject": "cto"})
CODE = "ghlink-test"


def _clean():
    with get_session() as session:
        project = session.scalar(select(Project).where(Project.code == CODE))
        if project is not None:
            for item in session.scalars(select(IntakeItem).where(IntakeItem.project_id == project.id)).all():
                session.delete(item)
            session.delete(project)
            session.commit()


@pytest.fixture
def made():
    _clean()
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    with get_session() as session:
        project = Project(id=str(uuid4()), code=CODE, intake_key="GHL", name="Link thử", kind="SOFTWARE", status="ACTIVE",
                          project_settings={"repo_url": "https://github.com/example/demo.git"}, created_at=now, updated_at=now)
        session.add(project)
        session.flush()
        ids = []
        for title, summary in (("[GHL-W43-1] Sửa nút lưu", "Nút lưu không phản hồi."), (None, None)):
            item_id = str(uuid4())
            session.add(IntakeItem(
                id=item_id, public_id=f"GHL-{len(ids)}", project_id=project.id, channel="MANUAL", item_type="BUG", status="PENDING_APPROVAL",
                normalized_title=title, normalized_summary=summary, normalized_details={"steps": ["Mở form", "Bấm Lưu"]},
                suggested_priority="P2", proposed_route="GITHUB", version=1, created_at=now, updated_at=now,
            ))
            ids.append(item_id)
        session.commit()
    yield ids
    _clean()


def test_link_is_prefilled_from_normalized_content(made):
    response = cto.get(f"/api/v1/intakes/{made[0]}/github-issue-link")
    assert response.status_code == 200, response.text
    data = response.json()["data"] if "data" in response.json() else response.json()
    parts = urlsplit(data["url"])
    assert parts.path == "/example/demo/issues/new"
    query = parse_qs(parts.query)
    assert query["title"] == ["Sửa nút lưu"]
    assert "Nút lưu không phản hồi." in query["body"][0] and "Bấm Lưu" in query["body"][0]
    assert data["repository"] == "example/demo" and data["shortened"] is False


def test_not_normalized_is_rejected(made):
    response = cto.get(f"/api/v1/intakes/{made[1]}/github-issue-link")
    assert response.status_code == 422
    assert "NOT_NORMALIZED" in response.text


def test_long_body_is_shortened_below_the_url_limit():
    url, shortened = build_new_issue_url("https://github.com/a/b", "T", "Việc dài " * 3000)
    assert shortened is True and len(url) <= MAX_URL_LENGTH


def test_project_without_repository_is_rejected(made):
    with get_session() as session:
        session.scalar(select(Project).where(Project.code == CODE)).project_settings = {}
        session.commit()
    assert cto.get(f"/api/v1/intakes/{made[0]}/github-issue-link").status_code == 422
