"""Password reset email through Mailgun's HTTPS API; the application never uses SMTP credentials."""
from __future__ import annotations

import html
from urllib.parse import quote

import httpx

from app.config import get_settings


class MailgunError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class PasswordResetMailer:
    def configured(self) -> bool:
        settings = get_settings()
        return bool(settings.mailgun_api_key and settings.mailgun_domain and settings.mailgun_from and settings.app_public_url)

    async def send(self, *, email: str, display_name: str, token: str) -> None:
        settings = get_settings()
        if not self.configured():
            raise MailgunError("MAILGUN_NOT_CONFIGURED")
        base = str(settings.app_public_url).rstrip("/")
        reset_url = f"{base}/login#reset={quote(token, safe='')}"
        minutes = max(5, settings.password_reset_ttl_minutes)
        safe_name = html.escape(display_name or "bạn")
        safe_url = html.escape(reset_url, quote=True)
        text = (
            f"Xin chào {display_name or 'bạn'},\n\n"
            f"Mở liên kết sau để đặt lại mật khẩu Private Intake:\n{reset_url}\n\n"
            f"Liên kết chỉ dùng một lần và hết hạn sau {minutes} phút. "
            "Nếu bạn không yêu cầu, hãy bỏ qua email này."
        )
        html_body = (
            f"<p>Xin chào {safe_name},</p>"
            "<p>Bạn vừa yêu cầu đặt lại mật khẩu Private Intake.</p>"
            f'<p><a href="{safe_url}">Đặt lại mật khẩu</a></p>'
            f"<p>Liên kết chỉ dùng một lần và hết hạn sau {minutes} phút. "
            "Nếu bạn không yêu cầu, hãy bỏ qua email này.</p>"
        )
        url = f"{settings.mailgun_api_base_url.rstrip('/')}/v3/{settings.mailgun_domain}/messages"
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                fields = {
                    "from": settings.mailgun_from, "to": email,
                    "subject": "Đặt lại mật khẩu Private Intake", "text": text, "html": html_body,
                    "o:tracking": "no", "o:tracking-clicks": "no", "o:tracking-opens": "no",
                }
                response = await client.post(
                    url, auth=("api", settings.mailgun_api_key),
                    files={name: (None, value) for name, value in fields.items()},
                )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise MailgunError("MAILGUN_UNAVAILABLE") from exc
        if response.status_code == 401:
            raise MailgunError("MAILGUN_AUTH_FAILED")
        if response.status_code == 429 or response.status_code >= 500:
            raise MailgunError("MAILGUN_UNAVAILABLE")
        if response.status_code >= 400:
            raise MailgunError("MAILGUN_REJECTED")


password_reset_mailer = PasswordResetMailer()
