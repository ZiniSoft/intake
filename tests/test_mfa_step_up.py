import base64
import hashlib
import hmac
import struct
import time
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import ApiToken, MFARecoveryCode, User
from app.modules.identity.service import identity_service
from app.modules.identity.tokens import api_token_service
from app.modules.identity.totp import generate_secret, verify_code
from app.services.raw_crypto import decrypt, encrypt


PASSWORD = "correct-horse-battery-staple"


def _totp(secret: str, timestamp: int | None = None) -> str:
    counter = (int(time.time()) if timestamp is None else timestamp) // 30
    digest = hmac.new(
        base64.b32decode(secret + "=" * (-len(secret) % 8)),
        struct.pack(">Q", counter),
        hashlib.sha1,
    ).digest()
    index = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[index : index + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def _invalid_totp(secret: str) -> str:
    candidate = "000000"
    while verify_code(secret, candidate):
        candidate = f"{(int(candidate) + 1) % 1_000_000:06d}"
    return candidate


def _account(*, mfa_secret: str | None = None) -> tuple[str, str]:
    tag = uuid4().hex[:12]
    subject = f"mfa.{tag}"
    user_id = str(uuid4())
    with get_session() as session:
        session.add(User(
            id=user_id,
            auth_subject=subject,
            email=f"{subject}@example.test",
            display_name=f"MFA {tag}",
            role="DEVELOPER",
            password_hash=identity_service.password_hash_value(PASSWORD),
            mfa_secret_ciphertext=encrypt(mfa_secret) if mfa_secret else None,
            mfa_enabled=mfa_secret is not None,
            is_active=True,
        ))
        session.commit()
    return subject, user_id


def _login(client: TestClient, subject: str, secret: str | None = None):
    payload = {"subject": subject, "password": PASSWORD}
    if secret:
        payload["otp"] = _totp(secret)
    return client.post("/api/v1/auth/login", json=payload)


def _post(client: TestClient, path: str, payload: dict):
    return client.post(path, json=payload, headers={"X-CSRF-Token": client.cookies["intake_csrf"]})


def test_stolen_session_cannot_replace_or_disable_an_existing_factor() -> None:
    active_secret = generate_secret()
    subject, _ = _account(mfa_secret=active_secret)
    client = TestClient(app)
    assert _login(client, subject, active_secret).status_code == 200

    missing = _post(client, "/api/v1/auth/mfa/setup", {})
    wrong_password = _post(
        client,
        "/api/v1/auth/mfa/setup",
        {"current_password": "stolen-session-has-no-password", "otp": _totp(active_secret)},
    )
    wrong_otp = _post(
        client,
        "/api/v1/auth/mfa/setup",
        {"current_password": PASSWORD, "otp": _invalid_totp(active_secret)},
    )

    assert missing.status_code == 422
    assert wrong_password.status_code == 403
    assert wrong_otp.status_code == 403
    with get_session() as session:
        user = session.scalar(select(User).where(User.auth_subject == subject))
        assert user is not None
        assert user.mfa_enabled is True
        assert decrypt(user.mfa_secret_ciphertext) == active_secret
        assert user.mfa_pending_secret_ciphertext is None


def test_abandoned_setup_preserves_active_mfa_and_successful_confirmation_is_atomic() -> None:
    active_secret = generate_secret()
    subject, user_id = _account(mfa_secret=active_secret)
    client = TestClient(app)
    login = _login(client, subject, active_secret)
    assert login.status_code == 200
    old_access_token = login.json()["data"]["access_token"]
    issued_token = api_token_service.issue(user_id, "MFA replacement test")["token"]

    setup = _post(
        client,
        "/api/v1/auth/mfa/setup",
        {"current_password": PASSWORD, "otp": _totp(active_secret)},
    )
    assert setup.status_code == 200, setup.text
    pending_secret = setup.json()["data"]["secret"]

    with get_session() as session:
        user = session.scalar(select(User).where(User.auth_subject == subject))
        assert user is not None
        old_auth_version = user.auth_version
        assert user.mfa_enabled is True
        assert decrypt(user.mfa_secret_ciphertext) == active_secret
        assert decrypt(user.mfa_pending_secret_ciphertext) == pending_secret
        assert user.mfa_pending_expires_at is not None

    # Leaving enrollment here must not affect login with the active factor.
    assert _login(TestClient(app), subject, active_secret).status_code == 200

    rejected = _post(
        client, "/api/v1/auth/mfa/confirm", {"code": _invalid_totp(pending_secret)},
    )
    assert rejected.status_code == 400
    with get_session() as session:
        user = session.scalar(select(User).where(User.auth_subject == subject))
        assert user is not None
        assert decrypt(user.mfa_secret_ciphertext) == active_secret
        assert decrypt(user.mfa_pending_secret_ciphertext) == pending_secret
        assert user.auth_version == old_auth_version

    confirmed = _post(
        client, "/api/v1/auth/mfa/confirm", {"code": _totp(pending_secret)},
    )
    assert confirmed.status_code == 200, confirmed.text
    with get_session() as session:
        user = session.scalar(select(User).where(User.auth_subject == subject))
        assert user is not None
        assert user.mfa_enabled is True
        assert decrypt(user.mfa_secret_ciphertext) == pending_secret
        assert user.mfa_pending_secret_ciphertext is None
        assert user.mfa_pending_expires_at is None
        assert user.auth_version == old_auth_version + 1
        token = session.scalar(select(ApiToken).where(ApiToken.user_id == user_id))
        assert token is not None and token.revoked_at is not None

    # Confirmation refreshes the browser that performed step-up, but every older session and personal token is dead.
    assert client.get("/api/v1/auth/me").status_code == 200
    stale = TestClient(app).get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {old_access_token}"},
    )
    assert stale.status_code == 401
    assert api_token_service.resolve(str(issued_token)) is None


def test_recovery_code_rotation_requires_password_and_current_otp() -> None:
    active_secret = generate_secret()
    subject, user_id = _account(mfa_secret=active_secret)
    client = TestClient(app)
    assert _login(client, subject, active_secret).status_code == 200
    with get_session() as session:
        session.add(MFARecoveryCode(
            id=str(uuid4()), user_id=user_id,
            code_hash=identity_service._hash_recovery_code("OLD-CODE-00000000"),
        ))
        session.commit()

    denied = _post(
        client,
        "/api/v1/auth/mfa/recovery-codes",
        {"current_password": PASSWORD, "otp": _invalid_totp(active_secret)},
    )
    assert denied.status_code == 403
    with get_session() as session:
        assert len(session.scalars(select(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id)).all()) == 1

    rotated = _post(
        client,
        "/api/v1/auth/mfa/recovery-codes",
        {"current_password": PASSWORD, "otp": _totp(active_secret)},
    )
    assert rotated.status_code == 200, rotated.text
    assert len(rotated.json()["data"]["recovery_codes"]) == 8
    with get_session() as session:
        rows = session.scalars(select(MFARecoveryCode).where(MFARecoveryCode.user_id == user_id)).all()
        assert len(rows) == 8


def test_first_mfa_enrollment_requires_current_password_but_not_an_otp() -> None:
    subject, _ = _account()
    client = TestClient(app)
    assert _login(client, subject).status_code == 200
    assert _post(
        client, "/api/v1/auth/mfa/setup", {"current_password": "wrong-password", "otp": None},
    ).status_code == 403

    setup = _post(
        client, "/api/v1/auth/mfa/setup", {"current_password": PASSWORD, "otp": None},
    )
    assert setup.status_code == 200, setup.text
    pending_secret = setup.json()["data"]["secret"]
    assert _post(
        client, "/api/v1/auth/mfa/confirm", {"code": _totp(pending_secret)},
    ).status_code == 200
