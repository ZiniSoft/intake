from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID

import pytest
from sqlalchemy import inspect, select

from app.db import get_engine, get_session
from app.models import ApprovalSnapshot, IntakeItem, OutboxEvent, Project, ProjectIntegration
from app.schemas import IntakeCreate, IntakeDecision, IntakeReview
from app.services.intake_service import intake_store
from app.services.outbox_dispatcher import outbox_dispatcher
from app.services.processing_repository import processing_repository


def test_seeded_projects_and_ember_mapping_are_isolated() -> None:
    with get_session() as session:
        projects = {project.code: project for project in session.scalars(select(Project)).all()}
        assert set(projects) == {"ember", "other", "orbit"}
        assert projects["ember"].id != projects["orbit"].id
        mapping = session.scalar(
            select(ProjectIntegration).where(
                ProjectIntegration.project_id == projects["ember"].id,
                ProjectIntegration.system == "GITLAB",
            )
        )
        assert mapping is not None
        assert mapping.project_external_id == "2026/ember-platform"
        assert mapping.config["project_url"] == "https://gitlab.example.test/2026/ember-platform"
        assert mapping.enabled is False


def test_new_business_ids_are_uuid_and_project_filter_does_not_leak() -> None:
    orbit = intake_store.create(IntakeCreate(project_id="orbit", channel="MANUAL", raw_text="Orbit item"))
    ember = intake_store.create(IntakeCreate(project_id="ember", channel="MANUAL", raw_text="Ember item"))

    UUID(orbit.id)
    UUID(ember.id)
    assert {item.id for item in intake_store.list("orbit")} >= {orbit.id}
    assert ember.id not in {item.id for item in intake_store.list("orbit")}


def test_json_documents_round_trip_as_objects() -> None:
    item = intake_store.create(IntakeCreate(project_id="orbit", channel="MANUAL", raw_text="JSON contract"))
    reviewed = intake_store.review(
        item.id,
        IntakeReview(
            normalized_title="Reviewed JSON contract",
            normalized_summary="Sanitized JSON contract summary",
            suggested_priority="P2",
            proposed_route="GITLAB",
            expected_version=item.version,
        ),
        actor_id="00000000-0000-4000-8000-000000000001",
    )
    approved = intake_store.approve(
        item.id,
        IntakeDecision(
            approved_route="GITLAB",
            approved_priority="P2",
            expected_version=reviewed.version,
        ),
        actor_id="00000000-0000-4000-8000-000000000001",
    )
    with get_session() as session:
        snapshot = session.scalar(select(ApprovalSnapshot).where(ApprovalSnapshot.intake_id == approved.id))
        event = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == approved.id,
                OutboxEvent.event_type == "intake.approved",
            )
        )
        assert isinstance(snapshot.payload, dict)
        assert isinstance(event.payload, dict)
        assert len(snapshot.payload_hash) == 64


def test_postgresql_uses_native_types_when_contract_database_is_enabled() -> None:
    engine = get_engine()
    if engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL contract assertion runs in the Gate A database job")
    columns = {column["name"]: column for column in inspect(engine).get_columns("ai_extractions")}
    assert str(columns["result"]["type"]).upper() == "JSONB"
    assert "DOUBLE PRECISION" in str(columns["confidence"]["type"]).upper()
    source_columns = {column["name"]: column for column in inspect(engine).get_columns("source_messages")}
    assert "TIMESTAMP" in str(source_columns["purge_after"]["type"]).upper()
    with get_session() as session:
        item = session.scalar(select(IntakeItem).order_by(IntakeItem.created_at.desc()))
        if item is not None:
            assert isinstance(item.created_at, datetime)
            assert item.created_at.tzinfo is not None
            assert item.created_at.utcoffset() == timezone.utc.utcoffset(item.created_at)


def test_postgresql_outbox_claim_is_exclusive() -> None:
    if get_engine().dialect.name != "postgresql":
        pytest.skip("SKIP LOCKED concurrency assertion runs in the Gate A database job")
    item = intake_store.create(IntakeCreate(project_id="ember", channel="MANUAL", raw_text="Concurrent claim"))
    result = processing_repository.enqueue_normalization(item.id)
    assert result is not None
    with get_session() as session:
        event = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == item.id,
                OutboxEvent.event_type == "intake.normalization.requested.v1",
            )
        )
        assert event is not None
        event_id = event.id

    with ThreadPoolExecutor(max_workers=2) as executor:
        claimed_batches = list(executor.map(lambda _: outbox_dispatcher.claim(), range(2)))

    matching_claims = [claim for batch in claimed_batches for claim in batch if claim.id == event_id]
    assert len(matching_claims) == 1
