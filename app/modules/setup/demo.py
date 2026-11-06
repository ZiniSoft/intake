"""The fictional demo project that lets a fresh install show the product without an AI key (FR-SETUP-11, ADR-0073).

Everything it creates is data in Intake's own tables. It never creates a `ProjectIntegration`, never queues
`ai.normalize` or `integration.sync`, and its people have no Telegram or email, so nothing leaves the install.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.db import get_session
from app.models import (
    AuditEvent, DailyCapacity, IntakeItem, PlanningAssignment, PlanningRun, Project, SourceMessage, WorkforceMember,
    WorkforceProjectMembership,
)
from app.services.raw_crypto import encrypt

DEMO_BUNDLE = Path(__file__).resolve().parents[2] / "resources" / "demo_project" / "demo.json"
DEMO_FLAG = "demo"
CHANNELS = {"ZALO", "WHATSAPP", "EMAIL", "MEETING", "MANUAL", "AGENT", "TELEGRAM", "FEEDBACK"}
STATUSES = {"PENDING_APPROVAL", "NEEDS_INFORMATION", "APPROVED"}


class DemoError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_demo(project: Project) -> bool:
    return bool((project.project_settings or {}).get(DEMO_FLAG))


def _read_bundle(path: Path) -> dict:
    if not path.exists():
        raise DemoError("SAMPLE_MISSING", "The demo project is not bundled with this build")
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
        project, members, intakes = bundle["project"], bundle["members"], bundle["intakes"]
        keys = {member["key"] for member in members}
        if bundle["owner"] not in keys or not intakes:
            raise ValueError("owner or intakes missing")
        for row in intakes:
            if row["channel"] not in CHANNELS or row["status"] not in STATUSES or not row["title"] or not row["raw"]:
                raise ValueError(f"intake is not valid: {row.get('title')}")
        for row in bundle.get("plan", []):
            if row["member"] not in keys or not 0 < row["hours"] <= 8:
                raise ValueError("plan row is not valid")
        if not (project["code"] and project["intake_key"] and project["name"] and project["kind"] == "SOFTWARE"):
            raise ValueError("project is not valid")
    except (KeyError, TypeError, ValueError) as error:
        raise DemoError("SAMPLE_INVALID", f"The demo project bundle is not valid: {error}") from error
    return bundle


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_demo_project(actor_id: str, bundle_path: Path = DEMO_BUNDLE) -> dict[str, object]:
    """Create the demo project once. A second call changes nothing and reports `created: false`."""
    from app.services.intake_service import intake_store

    bundle = _read_bundle(bundle_path)
    spec = bundle["project"]
    now = datetime.now(timezone.utc)
    plan_date: date = now.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    with get_session() as session:
        existing = session.scalar(select(Project).where(Project.code == spec["code"]))
        if existing is not None:
            if not is_demo(existing):
                raise DemoError("DEMO_CODE_TAKEN", f"A project with code {spec['code']} already exists and is not the demo")
            return {"created": False, "project_id": str(existing.id), "project_code": existing.code}
        if session.scalar(select(Project.id).where(Project.intake_key == spec["intake_key"])):
            raise DemoError("DEMO_CODE_TAKEN", f"The Intake key {spec['intake_key']} is already used")

        members: dict[str, WorkforceMember] = {}
        for row in bundle["members"]:
            member = WorkforceMember(
                id=str(uuid4()), display_name=row["display_name"], email_reference=None, status="ACTIVE",
                created_at=now, updated_at=now,
            )
            session.add(member)
            members[row["key"]] = member
        session.flush()  # the project's owner FK needs the member row first (PostgreSQL enforces it; SQLite tests do not)
        project = Project(
            id=str(uuid4()), code=spec["code"], intake_key=spec["intake_key"], name=spec["name"], kind="SOFTWARE", status="ACTIVE",
            owner_member_id=members[bundle["owner"]].id,
            project_settings={DEMO_FLAG: True, "demo_repo_url": spec.get("demo_repo_url")}, created_at=now, updated_at=now,
        )
        session.add(project)
        session.flush()
        for row in bundle["members"]:
            session.add(WorkforceProjectMembership(
                id=str(uuid4()), member_id=members[row["key"]].id, project_id=project.id, role=row.get("role"), active=True,
                created_at=now, updated_at=now,
            ))

        public_ids: list[str] = []
        for row in bundle["intakes"]:
            public_id = intake_store._next_public_id(session, project, now)
            public_ids.append(public_id)
            approved = row["status"] == "APPROVED"
            item_id = str(uuid4())
            session.add(IntakeItem(
                id=item_id, public_id=public_id, project_id=project.id, channel=row["channel"], item_type=row["type"],
                status=row["status"], normalized_title=row["title"], normalized_summary=row["summary"],
                normalized_details=row.get("details"), suggested_priority=row["priority"],
                approved_priority=row["priority"] if approved else None, proposed_route=row["route"],
                approved_route=row["route"] if approved else None, version=1, created_by=actor_id, created_at=now, updated_at=now,
            ))
            session.add(SourceMessage(
                id=str(uuid4()), intake_id=item_id, channel=row["channel"], sender_reference_ciphertext=encrypt("Người dùng mẫu"),
                raw_content_ciphertext=encrypt(row["raw"]), received_at=now, purge_after=now + timedelta(days=90), created_at=now,
            ))

        plan = bundle.get("plan", [])
        if plan:
            run = PlanningRun(
                id=str(uuid4()), plan_date=plan_date, timezone="Asia/Ho_Chi_Minh", project_scope=[str(project.id)],
                scope_hash=_canonical_hash([str(project.id)]), status="REVIEW_REQUIRED", version=1, revision=1,
                source_snapshot_at=now, created_by=actor_id, created_at=now, updated_at=now,
            )
            session.add(run)
            session.flush()
            used: dict[str, float] = {}
            for index, row in enumerate(plan):
                member = members[row["member"]]
                used[str(member.id)] = used.get(str(member.id), 0) + row["hours"]
                session.add(PlanningAssignment(
                    id=str(uuid4()), planning_run_id=run.id, project_id=project.id, member_id=member.id, slot=row["slot"],
                    work_type=row["work_type"], is_primary=bool(row.get("primary")), planned_hours=row["hours"],
                    source_type="INTAKE", source_reference=public_ids[min(index, len(public_ids) - 1)],
                    proposed_priority="P2", work_status="PLANNED", created_at=now, updated_at=now,
                ))
            if plan_date.weekday() < 5:
                for member in members.values():
                    session.add(DailyCapacity(
                        id=str(uuid4()), member_id=member.id, work_date=plan_date, base_hours=8, meeting_hours=0, review_hours=0,
                        support_hours=0, fixed_hours=0, available_hours=8, updated_by=actor_id, created_at=now, updated_at=now,
                    ))
        session.add(AuditEvent(
            id=str(uuid4()), project_id=project.id, actor_type="USER", actor_id=actor_id, event_type="setup.demo_project",
            entity_type="project", entity_id=project.id, details={"intakes": len(public_ids)}, created_at=now,
        ))
        session.commit()
        return {"created": True, "project_id": str(project.id), "project_code": project.code}
