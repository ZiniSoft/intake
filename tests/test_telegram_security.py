"""Telegram credentials stay out of transport errors, surfaced diagnostics, and operational logs (FR-NTF-01)."""
from __future__ import annotations

import logging
import sys

import httpx
import pytest

from app.modules.notify import telegram
from app.modules.notify.telegram import TelegramClient, TelegramError, TelegramRedactingFormatter, redact_telegram_secrets


TOKEN = "123456789:SYNTHETIC_SECRET_ABCDEFGHIJKLMNOPQRSTUVWXYZ"
URL = f"https://api.telegram.org/bot{TOKEN}/getMe"


@pytest.mark.parametrize(
    ("failure", "error_type"),
    [
        (httpx.ConnectError(f"DNS lookup failed for {URL}"), "ConnectError"),
        (httpx.ConnectError(f"connection refused for {URL}"), "ConnectError"),
        (httpx.ReadTimeout(f"timed out requesting {URL}"), "ReadTimeout"),
        (httpx.ConnectError(f"TLS certificate failure for {URL}"), "ConnectError"),
    ],
    ids=["dns", "connect", "timeout", "tls"],
)
def test_transport_failures_surface_only_stable_diagnostics(monkeypatch, failure, error_type) -> None:
    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr(telegram.httpx, "post", fail)
    with pytest.raises(TelegramError) as caught:
        TelegramClient(token=TOKEN).get_me()

    assert caught.value.code == "TELEGRAM_UNAVAILABLE"
    assert caught.value.error_type == error_type
    assert caught.value.safe_summary == f"TELEGRAM_UNAVAILABLE: {error_type}"
    assert TOKEN not in str(caught.value)
    assert TOKEN not in repr(caught.value)
    assert TOKEN not in caught.value.safe_summary
    assert caught.value.__cause__ is None


def test_download_transport_failure_uses_the_same_safe_boundary(monkeypatch) -> None:
    def fail(*args, **kwargs):
        raise httpx.ReadTimeout(f"timed out requesting https://api.telegram.org/file/bot{TOKEN}/photo.jpg")

    monkeypatch.setattr(telegram.httpx, "get", fail)
    with pytest.raises(TelegramError) as caught:
        TelegramClient(token=TOKEN).download("photo.jpg")
    assert caught.value.safe_summary == "TELEGRAM_UNAVAILABLE: ReadTimeout"
    assert TOKEN not in repr(caught.value)


def test_redaction_covers_api_urls_standalone_tokens_and_tracebacks() -> None:
    file_url = f"https://api.telegram.org/file/bot{TOKEN}/photo.jpg"
    redacted = redact_telegram_secrets(f"request={URL} download={file_url} token={TOKEN}")
    assert TOKEN not in redacted
    assert redacted.count(telegram.REDACTED_TELEGRAM_TOKEN) == 3

    formatter = TelegramRedactingFormatter("%(name)s %(levelname)s %(message)s")
    record = logging.LogRecord("httpx", logging.INFO, __file__, 1, "HTTP Request: POST %s", (URL,), None)
    assert TOKEN not in formatter.format(record)

    try:
        raise RuntimeError(f"request failed at {file_url}")
    except RuntimeError:
        traceback_record = logging.LogRecord("telegram-bot", logging.ERROR, __file__, 1, "polling failed", (), sys.exc_info())
    formatted = formatter.format(traceback_record)
    assert TOKEN not in formatted
    assert telegram.REDACTED_TELEGRAM_TOKEN in formatted

    surfaced = TelegramError("TELEGRAM_UNAVAILABLE", error_type=f"ConnectError {TOKEN}").safe_summary
    assert TOKEN not in surfaced
    assert telegram.REDACTED_TELEGRAM_TOKEN in surfaced


def test_logging_configuration_suppresses_http_client_info_logs() -> None:
    telegram.configure_telegram_logging(logging.INFO)
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
    assert all(isinstance(handler.formatter, TelegramRedactingFormatter) for handler in logging.getLogger().handlers)
