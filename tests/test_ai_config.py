"""FR-AI-15..19: LLM providers and per-task routes kept in the database, encrypted, resolved before the old .env."""
import asyncio

import httpx
import pytest

from app.config import get_settings
from app.db import get_session
from app.models import AiProvider, AiRoute
from app.modules.ai_config.routing import db_route, resolve_route
from app.modules.ai_config.service import AiConfigError, ai_config_service, clean_base_url

SECRET = "fixture-ai-key-1234"  # gitleaks:allow - synthetic test credential


@pytest.fixture(autouse=True)
def clean():
    def wipe():
        with get_session() as session:
            for row in session.query(AiRoute).all():
                session.delete(row)
            session.flush()
            for row in session.query(AiProvider).all():
                session.delete(row)
            session.commit()

    wipe()
    ai_config_service.transport = None
    yield
    wipe()
    ai_config_service.transport = None


def make(name="trial-one", **kw):
    return ai_config_service.create_provider(None, name=name, base_url=kw.pop("base_url", "http://llm.test/v1/"), api_key=kw.pop("api_key", SECRET), **kw)


def test_key_is_encrypted_and_never_returned():
    view = make()
    assert view["key_hint"] == "1234" and view["key_ok"] is True and SECRET not in repr(view)
    assert SECRET not in repr(ai_config_service.list_providers())
    with get_session() as session:
        stored = session.query(AiProvider).one().api_key_enc
    assert stored and SECRET not in stored
    assert view["base_url"] == "http://llm.test/v1"


def test_resolved_route_never_prints_the_key():
    provider = make()
    ai_config_service.set_route(None, "default", provider["id"], "m-default")
    assert SECRET not in repr(resolve_route("normalize"))


@pytest.mark.parametrize("url", ["ftp://x.test", "llm.test/v1", "http://169.254.169.254/latest", "http://metadata.google.internal/x", ""])
def test_bad_base_urls_are_refused(url):
    with pytest.raises(AiConfigError) as error:
        clean_base_url(url)
    assert error.value.code == "AI_BASE_URL_INVALID"


def test_private_addresses_are_allowed_for_local_models():
    assert clean_base_url("http://host.docker.internal:11434/v1") == "http://host.docker.internal:11434/v1"
    assert clean_base_url("http://192.168.1.20:8000/v1/") == "http://192.168.1.20:8000/v1"  # export-gate: allow (private-address fixture)


def test_name_must_be_unique_and_short():
    make()
    with pytest.raises(AiConfigError) as error:
        make()
    assert error.value.code == "AI_PROVIDER_NAME_TAKEN" and error.value.status == 409
    with pytest.raises(AiConfigError):
        make(name="x" * 33)


def test_resolution_order_route_then_default_then_env_then_none(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "umodelverse_api_key", None)
    assert resolve_route("report", settings) is None

    monkeypatch.setattr(settings, "umodelverse_api_key", "env-key")
    env = resolve_route("vision", settings)
    assert env.source == "env" and env.model == settings.umodelverse_vision_model and db_route("vision") is None

    a, b = make("trial-a"), make("trial-b", base_url="http://b.test/v1")
    ai_config_service.set_route(None, "default", a["id"], "m-default")
    assert (resolve_route("report", settings).source, resolve_route("report", settings).model) == ("default", "m-default")

    ai_config_service.set_route(None, "report", b["id"], "m-report")
    own = resolve_route("report", settings)
    assert (own.source, own.provider, own.model, own.base_url) == ("route", "trial-b", "m-report", "http://b.test/v1")
    assert resolve_route("meeting", settings).provider == "trial-a"


def test_disabled_provider_is_skipped(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "umodelverse_api_key", None)
    provider = make()
    ai_config_service.set_route(None, "normalize", provider["id"], "m")
    assert resolve_route("normalize", settings) is not None
    ai_config_service.update_provider(None, provider["id"], {"enabled": False})
    assert resolve_route("normalize", settings) is None


def test_unreadable_key_is_skipped_and_flagged(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "umodelverse_api_key", None)
    provider = make()
    ai_config_service.set_route(None, "normalize", provider["id"], "m")
    with get_session() as session:
        session.get(AiProvider, provider["id"]).api_key_enc = "not-a-fernet-token"
        session.commit()
    assert resolve_route("normalize", settings) is None
    assert ai_config_service.list_providers()[0]["key_ok"] is False


def test_provider_in_use_cannot_be_deleted():
    provider = make()
    ai_config_service.set_route(None, "content", provider["id"], "m")
    with pytest.raises(AiConfigError) as error:
        ai_config_service.delete_provider(provider["id"])
    assert error.value.code == "PROVIDER_IN_USE" and error.value.status == 409
    ai_config_service.set_route(None, "content", None, None)
    ai_config_service.delete_provider(provider["id"])
    assert ai_config_service.list_providers() == []


def test_update_keeps_the_key_when_left_blank():
    provider = make()
    ai_config_service.update_provider(None, provider["id"], {"api_key": "", "base_url": "https://new.test/v1"})
    view = ai_config_service.list_providers()[0]
    assert view["key_hint"] == "1234" and view["base_url"] == "https://new.test/v1"
    ai_config_service.update_provider(None, provider["id"], {"api_key": "fixture-ai-key-9999"})
    assert ai_config_service.list_providers()[0]["key_hint"] == "9999"


def test_route_validation():
    provider = make()
    with pytest.raises(AiConfigError) as error:
        ai_config_service.set_route(None, "pro", provider["id"], "m")
    assert error.value.code == "AI_TASK_UNKNOWN"
    with pytest.raises(AiConfigError):
        ai_config_service.set_route(None, "report", provider["id"], "  ")
    with pytest.raises(AiConfigError):
        ai_config_service.set_route(None, "report", "00000000-0000-4000-8000-000000000000", "m")
    assert [r["task"] for r in ai_config_service.list_routes()] == ["default", "normalize", "report", "meeting", "vision", "content"]


def run_test(handler):
    provider = make()
    ai_config_service.transport = httpx.MockTransport(handler)
    return provider, asyncio.run(ai_config_service.test_provider(provider["id"]))


def test_connection_success_lists_models_and_is_remembered():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("authorization")
        seen["path"] = request.url.path
        return httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}]})

    _, result = run_test(handler)
    assert result == {"ok": True, "error": None, "models": ["a-model", "b-model"]}
    assert seen == {"auth": f"Bearer {SECRET}", "path": "/v1/models"}
    saved = ai_config_service.list_providers()[0]
    assert saved["last_test_ok"] is True and saved["last_test_error"] is None


@pytest.mark.parametrize("status,code", [(401, "AUTH"), (403, "AUTH"), (500, "HTTP_500")])
def test_connection_failures_are_codes(status, code):
    _, result = run_test(lambda request: httpx.Response(status, text="secret provider message"))
    assert result["ok"] is False and result["error"] == code and "secret" not in repr(result)
    assert ai_config_service.list_providers()[0]["last_test_error"] == code


def test_connection_timeout_and_network():
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    def down(request):
        raise httpx.ConnectError("refused")

    assert run_test(timeout)[1]["error"] == "TIMEOUT"
    ai_config_service.delete_provider(ai_config_service.list_providers()[0]["id"])
    assert run_test(down)[1]["error"] == "NETWORK"
