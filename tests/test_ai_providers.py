from __future__ import annotations

import asyncio

import pytest

from app.config import Settings
from app.services.ai_processor import (
    AIExtraction,
    AIProviderChain,
    AIProviderPermanentError,
    AIProviderTransientError,
    OpenRouterAdapter,
    UModelVerseAdapter,
)


def settings(**overrides) -> Settings:
    values = {
        "ai_provider_primary": "umodelverse",
        "ai_provider_fallback": "openrouter",
        "umodelverse_api_key": "test-primary-key",
        "openrouter_api_key": "test-fallback-key",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def extraction() -> AIExtraction:
    return AIExtraction(
        item_type="BUG",
        suggested_priority="P1",
        proposed_route="GITLAB",
        normalized_title="Login fails",
        normalized_summary="Login returns an error for an existing user.",
    )


def test_umodelverse_payload_is_non_streaming_json_without_openrouter_options() -> None:
    payload = UModelVerseAdapter(settings()).build_payload("không đăng nhập được")

    assert payload["model"] == "deepseek-v4.1-flash"
    assert payload["stream"] is False
    assert payload["response_format"] == {"type": "json_object"}
    assert "provider" not in payload


def test_umodelverse_env_default_models() -> None:
    configured = settings()

    assert configured.umodelverse_model == "deepseek-v4.1-flash"
    assert configured.umodelverse_pro_model == "deepseek-v4-pro-0813"
    assert configured.umodelverse_vision_model == "deepseek-v4-flash-vision-exp"


def test_umodelverse_takes_any_model_name() -> None:
    adapter = UModelVerseAdapter(settings(umodelverse_model="my-own-model"))

    assert adapter.build_payload("test")["model"] == "my-own-model"


def test_openrouter_keeps_zdr_and_disables_internal_fallback() -> None:
    payload = OpenRouterAdapter(settings()).build_payload("test")

    assert payload["provider"] == {
        "zdr": True,
        "data_collection": "deny",
        "allow_fallbacks": False,
    }


class FakeAdapter:
    def __init__(self, provider_name: str, model_name: str, outcome, configured: bool = True) -> None:
        self.provider_name = provider_name
        self.model_name = model_name
        self.outcome = outcome
        self.configured = configured
        self.calls = 0

    def is_configured(self) -> bool:
        return self.configured

    async def extract(self, source_text: str) -> AIExtraction:
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def test_chain_uses_primary_when_it_succeeds() -> None:
    primary = FakeAdapter("UMODELVERSE", "primary-model", extraction())
    fallback = FakeAdapter("OPENROUTER", "fallback-model", extraction())
    chain = AIProviderChain(settings(), {"umodelverse": primary, "openrouter": fallback})

    result = asyncio.run(chain.extract("source"))

    assert result is not None
    assert result.provider == "UMODELVERSE"
    assert result.fallback_used is False
    assert primary.calls == 1
    assert fallback.calls == 0


def test_chain_falls_back_on_transient_primary_failure() -> None:
    primary = FakeAdapter(
        "UMODELVERSE",
        "primary-model",
        AIProviderTransientError("UMODELVERSE", "UMODELVERSE_UNAVAILABLE"),
    )
    fallback = FakeAdapter("OPENROUTER", "fallback-model", extraction())
    chain = AIProviderChain(settings(), {"umodelverse": primary, "openrouter": fallback})

    result = asyncio.run(chain.extract("source"))

    assert result is not None
    assert result.provider == "OPENROUTER"
    assert result.fallback_used is True
    assert result.fallback_reason == "UMODELVERSE_UNAVAILABLE"
    assert fallback.calls == 1


def test_chain_does_not_hide_permanent_primary_failure() -> None:
    primary = FakeAdapter(
        "UMODELVERSE",
        "primary-model",
        AIProviderPermanentError("UMODELVERSE", "UMODELVERSE_REJECTED"),
    )
    fallback = FakeAdapter("OPENROUTER", "fallback-model", extraction())
    chain = AIProviderChain(settings(), {"umodelverse": primary, "openrouter": fallback})

    with pytest.raises(AIProviderPermanentError, match="UMODELVERSE_REJECTED"):
        asyncio.run(chain.extract("source"))

    assert fallback.calls == 0


def test_chain_uses_fallback_when_primary_has_no_key() -> None:
    primary = FakeAdapter("UMODELVERSE", "primary-model", extraction(), configured=False)
    fallback = FakeAdapter("OPENROUTER", "fallback-model", extraction())
    chain = AIProviderChain(settings(), {"umodelverse": primary, "openrouter": fallback})

    result = asyncio.run(chain.extract("source"))

    assert result is not None
    assert result.provider == "OPENROUTER"
    assert result.fallback_reason == "PRIMARY_NOT_CONFIGURED"
    assert primary.calls == 0
    assert fallback.calls == 1
