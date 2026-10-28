import os
from pathlib import Path

import pytest


# Tests use an isolated SQLite file; production configuration defaults to PostgreSQL.
TEST_DATABASE = Path(__file__).resolve().parent.parent / "intake_test.db"
test_database_url = os.environ.get("INTAKE_TEST_DATABASE_URL")
if test_database_url:
    os.environ["DATABASE_URL"] = test_database_url
else:
    TEST_DATABASE.unlink(missing_ok=True)
    os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DATABASE.as_posix()}"
os.environ["ALLOW_SUBJECT_HEADER_AUTH"] = "true"
os.environ["CTO_INITIAL_PASSWORD"] = "dev-cto-password"
os.environ["PROJECT_OWNER_INITIAL_PASSWORD"] = "dev-owner-password"
os.environ["UMODELVERSE_API_KEY"] = ""
os.environ["OPENROUTER_API_KEY"] = ""
os.environ["GITLAB_TOKEN"] = ""
os.environ["GITLAB_INTEGRATION_ENABLED"] = "false"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["ATTACHMENT_ROOT"] = "/tmp/intake-test-attachments"
os.environ["REDIS_REQUIRED"] = "false"
os.environ["REPORT_IMAP_ENABLED"] = "false"
os.environ["MEETING_CAPTURE_ENABLED"] = "false"
os.environ["MEETING_BACKGROUND_ENABLED"] = "false"
os.environ["ELEVENLABS_API_KEY"] = ""
os.environ["APP_PUBLIC_URL"] = "https://intake.test"
os.environ["MAILGUN_API_KEY"] = "test-mailgun-key"
os.environ["MAILGUN_DOMAIN"] = "mg.intake.test"
os.environ["MAILGUN_FROM"] = "Private Intake <no-reply@mg.intake.test>"


# Fictional projects the suite runs on. The application seeds only the catch-all project, so the suite adds
# these two, each with a disabled GitLab mapping, the way a CTO would after first-run setup.
TEST_PROJECTS = (
    ("10000000-0000-4000-8000-000000000001", "orbit", "ORB", "Orbit", "2026/orbit-platform", "https://gitlab.example.test/2026/orbit-platform/"),
    ("10000000-0000-4000-8000-000000000002", "ember", "EMB", "Ember", "2026/ember-platform", "https://gitlab.example.test/2026/ember-platform"),
)


def _seed_test_projects() -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db import get_session
    from app.models import Project, ProjectIntegration
    from app.modules.projects.service import _mapping_id

    now = datetime.now(timezone.utc)
    with get_session() as session:
        for project_id, code, intake_key, name, path, url in TEST_PROJECTS:
            if session.scalar(select(Project).where(Project.code == code)) is None:
                session.add(Project(
                    id=project_id, code=code, intake_key=intake_key, name=name, kind="SOFTWARE", status="ACTIVE",
                    project_settings={}, created_at=now, updated_at=now,
                ))
                session.flush()
                session.add(ProjectIntegration(
                    id=_mapping_id(project_id, "GITLAB"), project_id=project_id, system="GITLAB",
                    base_url="https://gitlab.example.test", project_external_id=path, credential_ref="GITLAB_TOKEN",
                    enabled=False, config={"project_url": url}, created_at=now, updated_at=now,
                ))
        session.commit()


@pytest.fixture(scope="session", autouse=True)
def seed_database() -> None:
    from app.db import init_db
    from app.modules.identity.service import identity_service
    from app.modules.projects.service import project_catalog_service

    init_db()
    identity_service.ensure_database_users()
    project_catalog_service.ensure_database_projects()
    _seed_test_projects()
