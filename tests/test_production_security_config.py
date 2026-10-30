from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, select

from app.config import Settings
from app.db import get_session
from app.models import User
from app.modules.identity import service as identity_module
from app.modules.identity.service import IdentityService, UserContext


VALID_PRODUCTION = {
    "app_env": "production",
    "secret_key": "production-signing-key-with-32-characters",
    "cto_initial_password": "unique-cto-bootstrap-password",
    "project_owner_initial_password": "",
    "cookie_secure": True,
}


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"secret_key": ""}, "SECRET_KEY"),
        ({"secret_key": "dev-secret-key"}, "SECRET_KEY"),
        ({"secret_key": "too-short"}, "SECRET_KEY"),
        ({"secret_key": "x" * 64}, "SECRET_KEY"),
        ({"cto_initial_password": ""}, "CTO_INITIAL_PASSWORD"),
        ({"cto_initial_password": "dev-cto-password"}, "CTO_INITIAL_PASSWORD"),
        ({"cto_initial_password": "too-short"}, "CTO_INITIAL_PASSWORD"),
        ({"cookie_secure": False}, "COOKIE_SECURE"),
        ({"project_owner_initial_password": "dev-owner-password"}, "PROJECT_OWNER_INITIAL_PASSWORD"),
        ({"project_owner_initial_password": "change-me-owner-password"}, "PROJECT_OWNER_INITIAL_PASSWORD"),
    ],
)
def test_deployed_settings_reject_insecure_authentication_defaults(override: dict[str, object], message: str) -> None:
    values = {**VALID_PRODUCTION, **override}
    with pytest.raises(ValidationError, match=message):
        Settings(**values, _env_file=None)


def test_deployed_settings_accept_strong_explicit_authentication_config() -> None:
    settings = Settings(**VALID_PRODUCTION, _env_file=None)

    assert settings.is_deployed_environment is True


def test_unknown_environment_names_fail_closed() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(app_env="prodution", _env_file=None)


def test_local_and_test_environments_keep_development_defaults() -> None:
    for environment in ("development", "local", "test"):
        settings = Settings(app_env=environment, _env_file=None)
        assert settings.is_deployed_environment is False


def test_deployed_seed_account_must_change_initial_password(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(**VALID_PRODUCTION, _env_file=None)
    monkeypatch.setattr(identity_module, "get_settings", lambda: settings)
    service = IdentityService()
    subject = f"seed-{uuid4().hex}"
    user_id = str(uuid4())
    service._users = {
        subject: UserContext(
            user_id=user_id,
            email=f"{subject}@example.test",
            role="CTO",
            can_view_raw=True,
            can_approve=True,
        )
    }
    service._passwords = {subject: service._hash_password(settings.cto_initial_password)}

    try:
        service.ensure_database_users()
        with get_session() as session:
            seeded = session.scalar(select(User).where(User.auth_subject == subject))
            assert seeded is not None and seeded.must_change_password is True
    finally:
        with get_session() as session:
            session.execute(delete(User).where(User.auth_subject == subject))
            session.commit()
