"""FR-INTG-21: GitHub tokens stored encrypted; DB first, environment as fallback; no read-back."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import get_session
from app.main import app
from app.models import GithubToken
from app.modules.integrations import github

cto = TestClient(app, headers={"X-User-Subject": "cto"})
URL = "/api/v1/integrations/github-tokens"
VALUE = "ghp_" + "a1b2c3d4e5f6g7h8i9j0" + "WXYZ"


def _clean():
    with get_session() as session:
        for row in session.scalars(select(GithubToken).where(GithubToken.name.like("GITHUB_TOKEN_ZTEST%"))).all():
            session.delete(row)
        session.commit()


@pytest.fixture(autouse=True)
def clean():
    _clean()
    yield
    _clean()


def test_round_trip_hides_value_and_stores_encrypted():
    response = cto.put(URL, json={"label": "ztest khách", "token": VALUE})
    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["name"] == "GITHUB_TOKEN_ZTEST_KHACH" and data["key_hint"] == "WXYZ"
    assert VALUE not in response.text
    listed = cto.get(URL)
    assert VALUE not in listed.text and any(row["name"] == data["name"] for row in listed.json()["data"])
    with get_session() as session:
        assert VALUE not in session.get(GithubToken, data["name"]).token_enc
    assert github._stored_token(data["name"]) == VALUE


def test_database_wins_over_environment_and_names_are_merged(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN_ZTEST_A", "from-env-value-0123456789")
    monkeypatch.setenv("GITHUB_TOKEN_ZTEST_B", "only-env-value-0123456789")
    assert cto.put(URL, json={"label": "GITHUB_TOKEN_ZTEST_A", "token": VALUE}).status_code == 200
    assert github._headers("GITHUB_TOKEN_ZTEST_A")["Authorization"] == f"Bearer {VALUE}"
    assert github._headers("GITHUB_TOKEN_ZTEST_B")["Authorization"] == "Bearer only-env-value-0123456789"
    names = github.token_names()
    assert "GITHUB_TOKEN_ZTEST_A" in names and "GITHUB_TOKEN_ZTEST_B" in names


def test_delete_and_validation():
    assert cto.put(URL, json={"label": "ztest", "token": "short"}).status_code == 422
    assert cto.put(URL, json={"label": "!!!", "token": VALUE}).status_code == 422
    assert cto.put(URL, json={"label": "ztest", "token": VALUE}).status_code == 200
    assert cto.delete(f"{URL}/GITHUB_TOKEN_ZTEST").status_code == 204
    assert cto.delete(f"{URL}/GITHUB_TOKEN_ZTEST").status_code == 404


def test_only_cto():
    other = TestClient(app, headers={"X-User-Subject": "owner"})
    assert other.get(URL).status_code in (401, 403)
    assert other.put(URL, json={"label": "ztest", "token": VALUE}).status_code in (401, 403)
