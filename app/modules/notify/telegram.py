"""The few Telegram Bot API calls the reminders need (FR-NTF-01). Outbound HTTPS only: the server opens no port.

The bot token lives in the telegram-bot container alone; the API never holds it. Messages are HTML with the tags
Telegram allows (b, i, a, code); every piece of text that came from people goes through `escape`.
"""
from __future__ import annotations

import html
import logging

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
API = "https://api.telegram.org"


class TelegramError(RuntimeError):
    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


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
            raise TelegramError("TELEGRAM_UNAVAILABLE", str(exc)) from exc
        try:
            body = response.json()
        except ValueError as exc:
            raise TelegramError("TELEGRAM_INVALID_RESPONSE") from exc
        if response.status_code == 401:
            raise TelegramError("TELEGRAM_AUTH_FAILED")
        if response.status_code == 429:
            raise TelegramError("TELEGRAM_RATE_LIMITED", str(body.get("parameters", {}).get("retry_after", "")))
        if not isinstance(body, dict) or not body.get("ok"):
            raise TelegramError("TELEGRAM_REJECTED", str((body or {}).get("description", ""))[:200] if isinstance(body, dict) else "")
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
            raise TelegramError("TELEGRAM_UNAVAILABLE", str(exc)) from exc
        if response.status_code != 200:
            raise TelegramError("TELEGRAM_REJECTED", f"file download {response.status_code}")
        return response.content

    def get_updates(self, offset: int | None, timeout: int = 25) -> list[dict]:
        params: dict[str, object] = {"timeout": timeout, "allowed_updates": ["message"]}
        if offset is not None:
            params["offset"] = offset
        result = self._call("getUpdates", **params)
        return [row for row in result if isinstance(row, dict)] if isinstance(result, list) else []
