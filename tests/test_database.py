from datetime import datetime, timezone

from sqlalchemy import inspect, select, update

from app.db import get_engine, init_db
from app.models import SourceMessage
from app.services.intake_service import intake_store
from app.schemas import IntakeCreate
from app.services.retention_service import purge_expired_raw


def test_database_initializes_required_tables() -> None:
    init_db()
    engine = get_engine()
    inspector = inspect(engine)

    tables = inspector.get_table_names()
    expected = {
        "users",
        "mfa_recovery_codes",
        "user_sessions",
        "customers",
        "projects",
        "project_integrations",
        "gitlab_issue_snapshots",
        "intake_items",
        "source_messages",
        "attachments",
        "processing_runs",
        "evidence_fragments",
        "ai_extractions",
        "duplicate_candidates",
        "approval_actions",
        "approval_snapshots",
        "external_links",
        "sync_jobs",
        "outbox_events",
        "email_messages",
        "report_runs",
        "report_items",
        "audit_events",
        "workforce_members",
        "workforce_project_memberships",
        "daily_capacities",
        "planning_runs",
        "planning_assignments",
        "planning_warnings",
        "planning_approval_snapshots",
        "planning_sync_jobs",
    }

    missing = expected - set(tables)
    assert not missing, f"Missing database tables: {sorted(missing)}"
    assignment_indexes = {row["name"]: row for row in inspector.get_indexes("planning_assignments")}
    assert bool(assignment_indexes["uq_planning_assignment_run_project_issue"]["unique"])


def test_intake_raw_content_is_persisted_encrypted() -> None:
    raw_text = "Sensitive customer source content."
    item = intake_store.create(
        IntakeCreate(project_id="orbit", channel="MANUAL", raw_text=raw_text)
    )

    with get_engine().begin() as connection:
        stored = connection.execute(
            select(SourceMessage.raw_content_ciphertext).where(SourceMessage.intake_id == item.id)
        ).scalar_one()

    assert stored != raw_text
    assert intake_store.raw_text(item.id) == raw_text


def test_retention_purges_expired_raw_content() -> None:
    raw_text = "Expired source content."
    item = intake_store.create(
        IntakeCreate(project_id="orbit", channel="MANUAL", raw_text=raw_text)
    )
    with get_engine().begin() as connection:
        connection.execute(
            update(SourceMessage)
            .where(SourceMessage.intake_id == item.id)
            .values(purge_after=datetime(2020, 1, 1, tzinfo=timezone.utc))
        )

    assert purge_expired_raw(now=__import__("datetime").datetime(2026, 9, 26, tzinfo=__import__("datetime").timezone.utc)) == 1
    assert intake_store.raw_text(item.id) is None
