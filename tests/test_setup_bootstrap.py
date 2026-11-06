"""First-run wizard: public status, one-shot bootstrap and the mandatory AI key (FR-SETUP-05..08, ADR-0071).

The shared SQLite database is restored after each test: the seeded CTO row, the markers and anything created here."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from app.config import get_settings
from app.db import get_session
from app.main import app
from app.models import AiProvider, AiRoute, AppSetting, AuditEvent, User

MARKERS = ("bootstrap_completed", "setup_completed")
CTO_FIELDS = ("email", "display_name", "password_hash", "must_change_password", "auth_version")


@pytest.fixture()
def wizard(monkeypatch):
    monkeypatch.setattr(get_settings(), "first_run_wizard", True)
    with get_session() as session:
        cto = session.scalar(select(User).where(User.auth_subject == "cto"))
        saved = {name: getattr(cto, name) for name in CTO_FIELDS}
        markers = {row.key: row.value for row in session.scalars(select(AppSetting).where(AppSetting.key.in_(MARKERS)))}
        before_ids = set(session.scalars(select(User.id)).all())
        session.execute(delete(AppSetting).where(AppSetting.key.in_(MARKERS)))
        session.commit()
    yield
    with get_session() as session:
        session.execute(delete(AiRoute))
        session.execute(delete(AiProvider).where(AiProvider.name.like("wizard-test-%")))
        session.execute(delete(AuditEvent).where(AuditEvent.event_type == "setup.bootstrap"))
        session.execute(delete(AppSetting).where(AppSetting.key.in_(MARKERS)))
        session.execute(delete(User).where(User.id.notin_(before_ids)))
        cto = session.scalar(select(User).where(User.auth_subject == "cto"))
        for name, value in saved.items():
            setattr(cto, name, value)
        for key, value in markers.items():
            session.add(AppSetting(key=key, value=value))
        session.commit()


def _body(tag: str, owner: bool = True) -> dict:
    body = {"cto": {"email": f"Boss.{tag}@Example.com", "display_name": f"Boss {tag}", "password": f"boss-password-{tag}"}}
    body["owner"] = {"email": f"owner.{tag}@example.com", "display_name": f"Owner {tag}", "password": f"owner-password-{tag}"} if owner else None
    return body


def _post(body: dict, client: TestClient | None = None):
    return (client or TestClient(app)).post("/api/v1/setup/bootstrap", json=body)


def test_status_is_false_when_the_flag_is_off() -> None:
    assert get_settings().first_run_wizard is False
    status = TestClient(app).get("/api/v1/setup/status")
    assert status.status_code == 200 and status.json()["data"] == {"needs_bootstrap": False}
    assert _post(_body(uuid4().hex[:8])).status_code == 404


def test_bootstrap_creates_both_accounts_signs_in_and_closes(wizard) -> None:
    tag = uuid4().hex[:8]
    assert TestClient(app).get("/api/v1/setup/status").json()["data"] == {"needs_bootstrap": True}
    client = TestClient(app)
    created = _post(_body(tag), client)
    assert created.status_code == 200, created.text
    assert created.json()["data"] == {"needs_bootstrap": False}

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["data"]["role"] == "CTO" and me.json()["data"]["email"] == f"boss.{tag}@example.com"

    # The seeded password is gone; the chosen one works with the email and with the account name.
    assert TestClient(app).post("/api/v1/auth/login", json={"subject": "cto", "password": get_settings().cto_initial_password}).status_code == 401
    assert TestClient(app).post("/api/v1/auth/login", json={"subject": f"Boss.{tag}@example.com", "password": f"boss-password-{tag}"}).status_code == 200
    owner = TestClient(app).post("/api/v1/auth/login", json={"subject": f"owner.{tag}@example.com", "password": f"owner-password-{tag}"})
    assert owner.status_code == 200

    assert TestClient(app).get("/api/v1/setup/status").json()["data"] == {"needs_bootstrap": False}
    again = _post(_body(uuid4().hex[:8]))
    assert again.status_code == 409 and again.json()["error"] == "BOOTSTRAP_DONE"


def test_owner_is_optional(wizard) -> None:
    tag = uuid4().hex[:8]
    with get_session() as session:
        users_before = len(session.scalars(select(User.id)).all())
    assert _post(_body(tag, owner=False)).status_code == 200
    with get_session() as session:
        assert len(session.scalars(select(User.id)).all()) == users_before


def test_invalid_input_is_rejected_and_leaves_the_door_open(wizard) -> None:
    tag = uuid4().hex[:8]
    short = _body(tag)
    short["cto"]["password"] = "short"
    assert _post(short).json()["error"] == "PASSWORD_TOO_SHORT"
    short["cto"]["password"] = "1234567"  # 7 characters: still too short; 8 is the minimum
    assert _post(short).json()["error"] == "PASSWORD_TOO_SHORT"
    bad_email = _body(tag)
    bad_email["cto"]["email"] = "not-an-email"
    assert _post(bad_email).json()["error"] == "EMAIL_INVALID"
    same = _body(tag)
    same["owner"]["email"] = same["cto"]["email"].upper()
    assert _post(same).json()["error"] == "EMAIL_DUPLICATE"
    taken = f"taken.{tag}@example.com"
    with get_session() as session:
        session.add(User(
            id=str(uuid4()), auth_subject=f"taken.{tag}", email=taken, display_name="Existing",
            role="PROJECT_OWNER", password_hash="", mfa_enabled=False, is_active=True,
        ))
        session.commit()
    clash = _body(tag)
    clash["owner"]["email"] = taken
    assert _post(clash).status_code == 422
    assert TestClient(app).get("/api/v1/setup/status").json()["data"] == {"needs_bootstrap": True}
    assert _post(_body(tag)).status_code == 200


def test_owner_account_name_gets_a_suffix_when_taken(wizard) -> None:
    tag = uuid4().hex[:8]
    with get_session() as session:
        session.add(User(
            id=str(uuid4()), auth_subject=f"owner.{tag}", email=f"someone.{tag}@example.com", display_name="Existing",
            role="PROJECT_OWNER", password_hash="", mfa_enabled=False, is_active=True,
        ))
        session.commit()
    assert _post(_body(tag)).status_code == 200
    with get_session() as session:
        subject = session.scalar(select(User.auth_subject).where(User.email == f"owner.{tag}@example.com"))
    assert subject == f"owner.{tag}2"


def test_complete_needs_an_ai_route_while_the_wizard_is_on(wizard) -> None:
    tag = uuid4().hex[:8]
    client = TestClient(app)
    assert _post(_body(tag), client).status_code == 200

    def call(method: str, path: str, body: dict | None = None):
        return client.request(method, path, json=body, headers={"X-CSRF-Token": client.cookies.get(get_settings().csrf_cookie_name, "")})

    state = call("GET", "/api/v1/setup").json()["data"]
    assert state["wizard"] is True and state["ai_ready"] is False
    blocked = call("POST", "/api/v1/setup/complete")
    assert blocked.status_code == 422 and blocked.json()["error"] == "AI_KEY_REQUIRED"

    provider = call("POST", "/api/v1/ai/providers", {"name": f"wizard-test-{tag}", "base_url": "http://127.0.0.1:9/v1", "api_key": "fixture-ai-key-0000"})
    assert provider.status_code in (200, 201), provider.text
    assert call("POST", "/api/v1/setup/complete").status_code == 422
    assert call("PUT", "/api/v1/ai/routes/default", {"provider_id": provider.json()["data"]["id"], "model": "test-model"}).status_code == 200
    assert call("GET", "/api/v1/setup").json()["data"]["ai_ready"] is True
    done = call("POST", "/api/v1/setup/complete")
    assert done.status_code == 200 and done.json()["data"]["completed"] is True


def test_complete_ignores_the_ai_requirement_when_the_flag_is_off() -> None:
    response = TestClient(app).post("/api/v1/setup/complete", headers={"X-User-Subject": "cto"})
    assert response.status_code == 200
    state = response.json()["data"]
    assert state["wizard"] is False
    with get_session() as session:
        flag = session.get(AppSetting, "setup_completed")
        if flag is not None:
            session.delete(flag)
            session.commit()
