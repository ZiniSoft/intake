from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import app


def _create_account() -> tuple[str, str, str]:
    tag = uuid4().hex[:10]
    subject = f"mail.{tag}"
    email = f"Mail.{tag}@Example.com"
    response = TestClient(app).post(
        "/api/v1/users",
        headers={"X-User-Subject": "cto"},
        json={"subject": subject, "email": email, "display_name": f"Mail {tag}", "project_ids": []},
    )
    assert response.status_code == 201, response.text
    return subject, email, response.json()["data"]["temporary_password"]


def _login(identifier: str, password: str):
    return TestClient(app).post("/api/v1/auth/login", json={"subject": identifier, "password": password})


def test_login_accepts_account_name_or_email_in_any_case() -> None:
    subject, email, password = _create_account()
    assert _login(subject, password).status_code == 200
    assert _login(email.lower(), password).status_code == 200
    assert _login(email.upper(), password).status_code == 200
    assert _login(f"  {email}  ", password).status_code == 200


def test_login_failure_is_generic_for_unknown_email_and_wrong_password() -> None:
    subject, email, password = _create_account()
    unknown = _login(f"nobody.{uuid4().hex[:8]}@example.com", password)
    wrong = _login(email, "not-the-password-0000")
    assert unknown.status_code == 401 and wrong.status_code == 401
    assert {**unknown.json(), "request_id": ""} == {**wrong.json(), "request_id": ""}


def test_session_from_email_login_belongs_to_the_account() -> None:
    subject, email, password = _create_account()
    client = TestClient(app)
    assert client.post("/api/v1/auth/login", json={"subject": email, "password": password}).status_code == 200
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200 and me.json()["data"]["email"] == email.lower()
