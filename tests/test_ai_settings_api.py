"""FR-AI-15..19 over HTTP: CTO only, the key never comes back, routes resolve before .env."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app
from app.models import AiProvider, AiRoute
from app.modules.ai_config.service import ai_config_service

cto = TestClient(app, headers={"X-User-Subject": "cto"})
SECRET = "fixture-ai-key-7777"


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        with get_session() as session:
            for model in (AiRoute, AiProvider):
                for row in session.query(model).all():
                    session.delete(row)
                session.flush()
            session.commit()

    wipe()
    ai_config_service.transport = None
    yield
    wipe()
    ai_config_service.transport = None


def body(name="trial-api"):
    return {"name": name, "base_url": "http://llm.test/v1", "api_key": SECRET}


def test_only_the_cto_reaches_ai_settings():
    for subject in ("nobody", "po-someone"):
        other = TestClient(app, headers={"X-User-Subject": subject})
        assert other.get("/api/v1/ai/providers").status_code in (401, 403)
        assert other.post("/api/v1/ai/providers", json=body()).status_code in (401, 403)
        assert other.get("/api/v1/ai/routes").status_code in (401, 403)


def test_create_list_and_never_return_the_key():
    created = cto.post("/api/v1/ai/providers", json=body())
    assert created.status_code == 201 and created.json()["data"]["key_hint"] == "7777"
    listed = cto.get("/api/v1/ai/providers")
    assert SECRET not in created.text and SECRET not in listed.text and "api_key" not in listed.text


def test_errors_use_stable_codes():
    assert cto.post("/api/v1/ai/providers", json={**body(), "base_url": "http://169.254.169.254"}).status_code == 422
    assert cto.post("/api/v1/ai/providers", json=body()).status_code == 201
    taken = cto.post("/api/v1/ai/providers", json=body())
    assert taken.status_code == 409 and "AI_PROVIDER_NAME_TAKEN" in taken.text


def test_route_delete_guard_and_status():
    provider = cto.post("/api/v1/ai/providers", json=body()).json()["data"]
    routes = cto.put("/api/v1/ai/routes/default", json={"provider_id": provider["id"], "model": "m-1"})
    assert routes.status_code == 200
    assert {r["task"]: r["source"] for r in routes.json()["data"]}["report"] == "default"
    assert cto.put("/api/v1/ai/routes/pro", json={"provider_id": provider["id"], "model": "m"}).status_code == 404
    blocked = cto.delete(f"/api/v1/ai/providers/{provider['id']}")
    assert blocked.status_code == 409 and "PROVIDER_IN_USE" in blocked.text
    status = cto.get("/api/v1/operations/status").json()["data"]
    assert status["ai_configured"] is True and status["ai_source"] == "route"
    cto.put("/api/v1/ai/routes/default", json={"provider_id": None})
    assert cto.delete(f"/api/v1/ai/providers/{provider['id']}").status_code == 204


def test_test_endpoint_returns_models_without_the_key():
    provider = cto.post("/api/v1/ai/providers", json=body()).json()["data"]
    ai_config_service.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": [{"id": "m-a"}]}))
    result = cto.post(f"/api/v1/ai/providers/{provider['id']}/test")
    assert result.status_code == 200 and result.json()["data"] == {"ok": True, "error": None, "models": ["m-a"]}
    assert SECRET not in result.text
