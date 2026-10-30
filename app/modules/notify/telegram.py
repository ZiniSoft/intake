"""The few Telegram Bot API calls the reminders need (FR-NTF-01). Outbound HTTPS only: the server opens no port.

The bot token lives in the telegram-bot container alone; the API never holds it. Messages are HTML with the tags
Telegram allows (b, i, a, code); every piece of text that came from people goes through `escape`.
"""
from __future__ import annotations

import html
import logging
import re

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
API = "https://api.telegram.org"
REDACTED_TELEGRAM_TOKEN = "[REDACTED_TELEGRAM_TOKEN]"
_TELEGRAM_URL_TOKEN = re.compile(r"(?i)(https?://api\.telegram\.org/(?:file/)?bot)([^/\s\"']+)")
_TELEGRAM_TOKEN = re.compile(r"(?<![\w-])\d{6,12}:[A-Za-z0-9_-]{20,}(?![\w-])")


def redact_telegram_secrets(value: object) -> str:
    """Remove bot credentials from text before it reaches an operational log or surfaced error."""
    text = str(value)
    text = _TELEGRAM_URL_TOKEN.sub(rf"\1{REDACTED_TELEGRAM_TOKEN}", text)
    return _TELEGRAM_TOKEN.sub(REDACTED_TELEGRAM_TOKEN, text)


class TelegramRedactingFormatter(logging.Formatter):
    """Redact after standard formatting so arguments and exception tracebacks are covered too."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = redact_telegram_secrets(super().format(record))
        if record.exc_text:
            record.exc_text = redact_telegram_secrets(record.exc_text)
        return rendered


def configure_telegram_logging(level: int = logging.INFO) -> None:
    """Configure the token-holding process with safe logs and quiet HTTP client internals."""
    log_format = "%(asctime)s %(name)s %(levelname)s %(message)s"
    logging.basicConfig(level=level, format=log_format)
    formatter = TelegramRedactingFormatter(log_format)
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class TelegramError(RuntimeError):
    def __init__(self, code: str, *, error_type: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.error_type = error_type

    @property
    def safe_summary(self) -> str:
        summary = f"{self.code}: {self.error_type}" if self.error_type else self.code
        return redact_telegram_secrets(summary)


def escape(text: object) -> str:
    return html.escape(str(text or ""), quote=False)


def mention(chat_id: str | None, name: str, username: str | None = None) -> str:
    """A tag that notifies the person: by user id when the bot knows them, by @username otherwise, else the name."""
    if chat_id:
        return f'<a href="tg://user?id={escape(chat_id)}">{escape(name)}</a>'
    if username:
        return f"@{escape(username.lstrip('@'))}"
    return f"<b>{escape(name)}</b>"


class TelegramClient:
    def __init__(self, token: str | None = None, timeout: float = 35.0) -> None:
        settings = get_settings()
        self.token = token or settings.telegram_bot_token
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.token)

    def _call(self, method: str, **params: object) -> object:
        if not self.token:
            raise TelegramError("TELEGRAM_NOT_CONFIGURED")
        try:
            response = httpx.post(f"{API}/bot{self.token}/{method}", json=params, timeout=self.timeout)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TelegramError("TELEGRAM_UNAVAILABLE", error_type=type(exc).__name__) from None
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramError("TELEGRAM_INVALID_RESPONSE", error_type=type(exc).__name__) from None
        if response.status_code == 401:
            raise TelegramError("TELEGRAM_AUTH_FAILED")
        if response.status_code == 429:
            raise TelegramError("TELEGRAM_RATE_LIMITED", error_type="TelegramAPIError")
        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramError("TELEGRAM_REJECTED", error_type="TelegramAPIError")
        return body.get("result")

    def get_me(self) -> dict:
        result = self._call("getMe")
        return result if isinstance(result, dict) else {}

    def send_message(self, chat_id: str, text: str, *, thread_id: int | None = None) -> dict:
        params: dict[str, object] = {"chat_id": chat_id, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        if thread_id:
            params["message_thread_id"] = thread_id
        result = self._call("sendMessage", **params)
        return result if isinstance(result, dict) else {}

    def get_file(self, file_id: str) -> dict:
        """Where Telegram keeps a file the bot was sent; the path is good for about an hour."""
        result = self._call("getFile", file_id=file_id)
        return result if isinstance(result, dict) else {}

    def download(self, file_path: str) -> bytes:
        """The bytes of a file the bot was sent (FR-AI-14): at most the upload limit, read in one go."""
        if not self.token:
            raise TelegramError("TELEGRAM_NOT_CONFIGURED")
        try:
            response = httpx.get(f"{API}/file/bot{self.token}/{file_path}", timeout=self.timeout)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise TelegramError("TELEGRAM_UNAVAILABLE", error_type=type(exc).__name__) from None
        if response.status_code != 200:
            raise TelegramError("TELEGRAM_REJECTED", error_type="TelegramAPIError")
        return response.content

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        params: dict[str, object] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        result = self._call("getUpdates", **params)
        return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []
