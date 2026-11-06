"""First-run setup: tells the app whether a fresh install still needs its first project, and loads the sample voice."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import get_session
from app.models import AiProvider, AiRoute, AppSetting, AuditEvent, Project, User
from app.modules.identity.service import identity_service
from app.modules.private_space.service import private_project_ids, private_space_service
from app.modules.projects.service import OTHER_PROJECT_CODE
from app.modules.setup.demo import DEMO_BUNDLE, DEMO_FLAG, DemoError, load_demo_project

SETUP_KEY = "setup_completed"
BOOTSTRAP_KEY = "bootstrap_completed"
MIN_PASSWORD_LENGTH = 8
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SAMPLE_BUNDLE = Path(__file__).resolve().parents[2] / "resources" / "private_space_sample" / "setup.json"


class SetupError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class SetupService:
    @staticmethod
    def _real_projects(session) -> int:
        private = set(private_project_ids(session))
        rows = session.execute(select(Project.id, Project.code, Project.project_settings)).all()
        # The fictional demo project never counts as the install's own work (FR-SETUP-11).
        return sum(
            1 for pid, code, settings in rows
            if code != OTHER_PROJECT_CODE and str(pid) not in private
            and not (settings or {}).get(DEMO_FLAG) and not (settings or {}).get("showcase")
        )

    @staticmethod
    def _has_demo(session) -> bool:
        return any((settings or {}).get(DEMO_FLAG) for (settings,) in session.execute(select(Project.project_settings)).all())

    def state(self) -> dict[str, object]:
        """An install that already has a real project counts as set up, so a pilot never meets the wizard."""
        with get_session() as session:
            flag = session.get(AppSetting, SETUP_KEY)
            marked = bool(flag and flag.value)
            real = self._real_projects(session)
            has_demo = self._has_demo(session)
            has_space = bool(private_project_ids(session))
            ai_ready = session.scalar(
                select(AiRoute.task).join(AiProvider, AiProvider.id == AiRoute.provider_id).where(AiProvider.enabled.is_(True), AiRoute.task != "stt").limit(1)
            ) is not None
        return {
            "completed": marked or real > 0, "has_project": real > 0, "has_private_space": has_space,
            "sample_available": SAMPLE_BUNDLE.exists(), "wizard": get_settings().first_run_wizard, "ai_ready": ai_ready,
            "has_demo": has_demo, "demo_available": DEMO_BUNDLE.exists(),
        }

    def needs_bootstrap(self) -> bool:
        if not get_settings().first_run_wizard:
            return False
        with get_session() as session:
            return session.get(AppSetting, BOOTSTRAP_KEY) is None

    @staticmethod
    def _clean_account(label: str, account: dict[str, str]) -> dict[str, str]:
        email = (account.get("email") or "").strip().lower()
        name = " ".join((account.get("display_name") or "").split())[:255]
        password = account.get("password") or ""
        if not EMAIL_PATTERN.match(email) or len(email) > 255:
            raise SetupError("EMAIL_INVALID", f"{label}: email is not valid")
        if not name:
            raise SetupError("NAME_REQUIRED", f"{label}: a display name is required")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise SetupError("PASSWORD_TOO_SHORT", f"{label}: the password needs at least {MIN_PASSWORD_LENGTH} characters")
        return {"email": email, "display_name": name, "password": password}

    def bootstrap(self, cto: dict[str, str], owner: dict[str, str] | None) -> str:
        """Create the first CTO (and optionally a Project Owner) on a fresh install; returns the CTO's auth subject.
        Open only while the installer's flag is on and nobody has done it yet (FR-SETUP-06, ADR-0071)."""
        if not get_settings().first_run_wizard:
            raise SetupError("NOT_FOUND", "Not found")
        cto = self._clean_account("CTO", cto)
        owner = self._clean_account("Project Owner", owner) if owner else None
        if owner and owner["email"] == cto["email"]:
            raise SetupError("EMAIL_DUPLICATE", "The CTO and the Project Owner need different emails")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            # The marker row is the lock: its primary key lets exactly one of two concurrent requests through.
            session.add(AppSetting(key=BOOTSTRAP_KEY, value=1, updated_by=None, updated_at=now))
            try:
                session.flush()
            except IntegrityError as error:
                session.rollback()
                raise SetupError("BOOTSTRAP_DONE", "The first account has already been created") from error
            user = session.scalar(select(User).where(User.role == "CTO").order_by(User.created_at).limit(1))
            if user is None:
                raise SetupError("CTO_MISSING", "The installed CTO account is missing")
            user.email, user.display_name = cto["email"], cto["display_name"]
            user.password_hash = identity_service.password_hash_value(cto["password"])
            user.must_change_password = False
            user.auth_version = (user.auth_version or 0) + 1
            user.updated_at = now
            subject, cto_id = user.auth_subject, user.id
            owner_id = None
            if owner:
                base = re.sub(r"[^a-z0-9._-]", "", owner["email"].split("@", 1)[0]).lstrip("._-")[:60] or "owner"
                if len(base) < 3:
                    base = f"{base}-owner"
                owner_subject, suffix = base, 1
                while session.scalar(select(User.id).where(User.auth_subject == owner_subject)):
                    suffix += 1
                    owner_subject = f"{base}{suffix}"
                owner_id = str(uuid4())
                session.add(User(
                    id=owner_id, auth_subject=owner_subject, email=owner["email"], display_name=owner["display_name"],
                    role="PROJECT_OWNER", password_hash=identity_service.password_hash_value(owner["password"]),
                    mfa_enabled=False, is_active=True, created_at=now, updated_at=now,
                ))
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="SYSTEM", actor_id="bootstrap", event_type="setup.bootstrap", entity_type="user",
                entity_id=cto_id, details={"owner_created": owner_id is not None}, created_at=now,
            ))
            try:
                session.commit()
            except IntegrityError as error:
                session.rollback()
                raise SetupError("EMAIL_TAKEN", "An account already uses one of these emails") from error
        return subject

    def load_private_sample(self, actor_id: str) -> dict[str, object]:
        from app.tools.setup_private_voice import load_bundle

        if not SAMPLE_BUNDLE.exists():
            raise SetupError("SAMPLE_MISSING", "The sample voice is not bundled with this build")
        try:
            return load_bundle(SAMPLE_BUNDLE, actor_id)
        except SystemExit as error:
            raise SetupError("SAMPLE_INVALID", str(error)) from error

    def load_demo_project(self, actor_id: str) -> dict[str, object]:
        if not get_settings().first_run_wizard:
            raise SetupError("NOT_FOUND", "Not found")
        try:
            result = load_demo_project(actor_id)
        except DemoError as error:
            raise SetupError(error.code, error.message) from error
        # Trying the demo is a way of finishing setup; without this the app's guard would bounce the person back to /setup.
        self._mark_done(actor_id)
        return result

    @staticmethod
    def _mark_done(actor_id: str) -> None:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            row = session.get(AppSetting, SETUP_KEY)
            if row is None:
                session.add(AppSetting(key=SETUP_KEY, value=1, updated_by=actor_id, updated_at=now))
            else:
                row.value, row.updated_by, row.updated_at = 1, actor_id, now
            session.commit()

    def complete(self, actor_id: str) -> dict[str, object]:
        state = self.state()
        # Someone who tried the demo project may finish without a key; the UI keeps reminding them (FR-SETUP-12).
        if get_settings().first_run_wizard and not state["ai_ready"] and not state["has_demo"]:
            raise SetupError("AI_KEY_REQUIRED", "Add an AI provider and choose a model before finishing setup")
        self._mark_done(actor_id)
        return self.state()


setup_service = SetupService()
