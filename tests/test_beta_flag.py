"""BETA_FEATURES_ENABLED: /auth/me tells the web whether the Beta areas are on."""
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app

cto = TestClient(app, headers={"X-User-Subject": "cto"})


def test_me_reports_the_beta_flag(monkeypatch):
    assert cto.get("/api/v1/auth/me").json()["data"]["beta_features_enabled"] is False
    monkeypatch.setattr(get_settings(), "beta_features_enabled", True)
    assert cto.get("/api/v1/auth/me").json()["data"]["beta_features_enabled"] is True
