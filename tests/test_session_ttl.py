"""The web session lasts a working week for every user (FR-ID-09, Intake INT-26W42-012, GitLab #14)."""
from fastapi.testclient import TestClient

from app.main import app

SEVEN_DAYS = 7 * 24 * 60 * 60

client = TestClient(app)


def _max_age(response, cookie_name: str) -> int:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{cookie_name}="):
            attributes = {part.strip().split("=", 1)[0].lower(): part.strip().split("=", 1)[-1] for part in header.split(";")}
            return int(attributes["max-age"])
    raise AssertionError(f"cookie {cookie_name} was not set")


def test_login_session_lasts_seven_days_for_every_user() -> None:
    for subject, password in (("cto", "dev-cto-password"), ("project-owner", "dev-owner-password")):
        response = client.post("/api/v1/auth/login", json={"subject": subject, "password": password})
        assert response.status_code == 200, response.text
        expires_in = response.json()["data"]["expires_in"]
        assert expires_in >= SEVEN_DAYS, f"{subject}: session expires after {expires_in}s"
        # Both cookies live exactly as long as the token they carry, so the browser drops them together.
        assert _max_age(response, "intake_session") == expires_in
        assert _max_age(response, "intake_csrf") == expires_in
