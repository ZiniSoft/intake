import asyncio
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import PasswordResetRequest, User
from app.config import get_settings
from app.modules.identity.mailgun import PasswordResetMailer, password_reset_mailer


def _create_account() -> tuple[str, str, str]:
    tag = uuid4().hex[:10]
    subject = f"reset.{tag}"
    email = f"reset.{tag}@example.com"
    response = TestClient(app).post(
        "/api/v1/users",
        headers={"X-User-Subject": "cto"},
        json={"subject": subject, "email": email, "display_name": f"Reset {tag}", "project_ids": []},
    )
    assert response.status_code == 201, response.text
    return subject, email, response.json()["data"]["temporary_password"]


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get(get_settings().csrf_cookie_name, "")}


def _ready_account() -> tuple[str, str, str, TestClient]:
    subject, email, temporary_password = _create_account()
    bootstrap = TestClient(app)
    assert bootstrap.post("/api/v1/auth/login", json={"subject": subject, "password": temporary_password}).status_code == 200
    current_password = f"current-password-{uuid4().hex}"
    changed = bootstrap.post(
        "/api/v1/auth/password",
        json={"current_password": temporary_password, "new_password": current_password},
        headers=_csrf(bootstrap),
    )
    assert changed.status_code == 200, changed.text
    signed_in = TestClient(app)
    assert signed_in.post("/api/v1/auth/login", json={"subject": subject, "password": current_password}).status_code == 200
    return subject, email, current_password, signed_in


def test_password_change_revokes_old_sessions_and_personal_tokens() -> None:
    subject, _, current_password, signed_in = _ready_account()
    issued = signed_in.post("/api/v1/auth/tokens", json={"name": "old agent token"}, headers=_csrf(signed_in))
    assert issued.status_code == 201, issued.text
    old_agent = TestClient(app, headers={"Authorization": f"Bearer {issued.json()['data']['token']}"})
    assert old_agent.get("/api/v1/auth/me").status_code == 200

    new_password = f"changed-password-{uuid4().hex}"
    changed = signed_in.post(
        "/api/v1/auth/password",
        json={"current_password": current_password, "new_password": new_password},
        headers=_csrf(signed_in),
    )
    assert changed.status_code == 200, changed.text

    assert signed_in.get("/api/v1/auth/me").status_code == 401
    assert old_agent.get("/api/v1/auth/me").status_code == 401
    fresh = TestClient(app)
    assert fresh.post("/api/v1/auth/login", json={"subject": subject, "password": new_password}).status_code == 200
    assert fresh.get("/api/v1/auth/tokens").json()["data"] == []
    new_token = fresh.post("/api/v1/auth/tokens", json={"name": "new agent token"}, headers=_csrf(fresh))
    assert new_token.status_code == 201, new_token.text
    new_agent = TestClient(app, headers={"Authorization": f"Bearer {new_token.json()['data']['token']}"})
    assert new_agent.get("/api/v1/auth/me").status_code == 200


def test_password_reset_email_is_private_single_use_and_revokes_old_session(monkeypatch) -> None:
    subject, email, old_password, signed_in = _ready_account()
    delivered: list[dict[str, str]] = []

    async def fake_send(**message: str) -> None:
        delivered.append(message)

    monkeypatch.setattr(password_reset_mailer, "send", fake_send)
    assert signed_in.get("/api/v1/auth/me").status_code == 200
    issued = signed_in.post("/api/v1/auth/tokens", json={"name": "old reset token"}, headers=_csrf(signed_in))
    assert issued.status_code == 201, issued.text
    old_agent = TestClient(app, headers={"Authorization": f"Bearer {issued.json()['data']['token']}"})
    assert old_agent.get("/api/v1/auth/me").status_code == 200

    public = TestClient(app)
    requested = public.post("/api/v1/auth/password-reset/request", json={"identifier": email.upper()})
    assert requested.status_code == 202
    generic = requested.json()["data"]
    assert generic["accepted"] is True and "Nếu tài khoản tồn tại" in generic["message"]
    assert len(delivered) == 1 and delivered[0]["email"] == email
    token = delivered[0]["token"]

    with get_session() as session:
        user = session.scalar(select(User).where(User.auth_subject == subject))
        row = session.scalar(select(PasswordResetRequest).where(PasswordResetRequest.user_id == user.id))
        assert row is not None and row.token_hash != token and len(row.token_hash) == 64 and row.sent_at is not None

    # Repeating immediately gives exactly the same public answer and does not mail-bomb the account.
    repeated = public.post("/api/v1/auth/password-reset/request", json={"identifier": subject})
    assert repeated.status_code == 202 and repeated.json()["data"] == generic
    assert len(delivered) == 1

    too_short = public.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": "short"})
    assert too_short.status_code == 422 and too_short.json()["error"] == "PASSWORD_TOO_SHORT"
    new_password = f"new-reset-password-{uuid4().hex}"
    changed = public.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": new_password})
    assert changed.status_code == 200 and changed.json()["data"] == {"changed": True}

    # The old cookie and password are both invalid; the reset link cannot be replayed.
    assert signed_in.get("/api/v1/auth/me").status_code == 401
    assert old_agent.get("/api/v1/auth/me").status_code == 401
    assert TestClient(app).post("/api/v1/auth/login", json={"subject": subject, "password": old_password}).status_code == 401
    fresh = TestClient(app)
    assert fresh.post("/api/v1/auth/login", json={"subject": subject, "password": new_password}).status_code == 200
    assert fresh.get("/api/v1/auth/tokens").json()["data"] == []
    new_token = fresh.post("/api/v1/auth/tokens", json={"name": "new reset token"}, headers=_csrf(fresh))
    assert new_token.status_code == 201, new_token.text
    new_agent = TestClient(app, headers={"Authorization": f"Bearer {new_token.json()['data']['token']}"})
    assert new_agent.get("/api/v1/auth/me").status_code == 200
    replay = public.post("/api/v1/auth/password-reset/confirm", json={"token": token, "new_password": f"other-{uuid4().hex}"})
    assert replay.status_code == 422 and replay.json()["error"] == "RESET_TOKEN_INVALID"


def test_password_reset_request_does_not_reveal_unknown_or_inactive_accounts(monkeypatch) -> None:
    subject, _, _ = _create_account()
    sent: list[str] = []

    async def fake_send(**message: str) -> None:
        sent.append(message["email"])

    monkeypatch.setattr(password_reset_mailer, "send", fake_send)
    with get_session() as session:
        user = session.scalar(select(User).where(User.auth_subject == subject))
        user.is_active = False
        session.commit()

    client = TestClient(app)
    unknown = client.post("/api/v1/auth/password-reset/request", json={"identifier": f"missing.{uuid4().hex}@example.com"})
    inactive = client.post("/api/v1/auth/password-reset/request", json={"identifier": subject})
    assert unknown.status_code == inactive.status_code == 202
    assert unknown.json()["data"] == inactive.json()["data"]
    assert sent == []


def test_invalid_password_reset_token_is_rejected() -> None:
    response = TestClient(app).post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-reset-token-that-is-long-enough", "new_password": f"valid-{uuid4().hex}"},
    )
    assert response.status_code == 422
    assert response.json()["error"] == "RESET_TOKEN_INVALID"


def test_password_reset_request_reports_when_mailgun_is_not_configured(monkeypatch) -> None:
    monkeypatch.setattr(password_reset_mailer, "configured", lambda: False)
    response = TestClient(app).post(
        "/api/v1/auth/password-reset/request", json={"identifier": "anyone@example.com"},
    )
    assert response.status_code == 503
    assert response.json()["error"] == "PASSWORD_RESET_UNAVAILABLE"


def test_mailgun_sender_uses_https_api_basic_auth_and_disables_tracking(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "mailgun_api_key", "test-mailgun-key")
    monkeypatch.setattr(settings, "mailgun_domain", "mg.example.com")
    monkeypatch.setattr(settings, "mailgun_from", "Private Intake <no-reply@mg.example.com>")
    monkeypatch.setattr(settings, "mailgun_api_base_url", "https://api.eu.mailgun.net")
    monkeypatch.setattr(settings, "app_public_url", "https://intake.example.com")
    captured: dict[str, object] = {}

    class FakeClient:
        def __init__(self, **kwargs) -> None:
            captured["client"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            return None

        async def post(self, url: str, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return httpx.Response(200, json={"id": "mailgun-message", "message": "Queued"})

    monkeypatch.setattr("app.modules.identity.mailgun.httpx.AsyncClient", FakeClient)
    asyncio.run(PasswordResetMailer().send(
        email="person@example.com", display_name="Person", token="opaque-reset-token",
    ))

    assert captured["url"] == "https://api.eu.mailgun.net/v3/mg.example.com/messages"
    assert captured["auth"] == ("api", "test-mailgun-key")
    fields = captured["files"]
    assert fields["to"] == (None, "person@example.com")
    assert fields["o:tracking"] == fields["o:tracking-clicks"] == fields["o:tracking-opens"] == (None, "no")
    assert "https://intake.example.com/login#reset=opaque-reset-token" in fields["text"][1]
