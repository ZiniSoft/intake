from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


_LOCAL_ENVIRONMENTS = frozenset({"dev", "development", "local", "test", "testing"})
_KNOWN_SECRET_KEYS = frozenset({"", "dev-secret-key", "change-me-in-production"})
_KNOWN_INITIAL_PASSWORDS = frozenset({
    "",
    "dev-cto-password",
    "change-me-cto-password",
    "dev-owner-password",
    "change-me-owner-password",
})


class Settings(BaseSettings):
    app_name: str = "Private Feedback Intake"
    app_env: str = "development"
    project_name: str = ""
    database_url: str = "postgresql+psycopg://intake:intake@localhost:5432/intake"
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/1"
    outbox_poll_seconds: float = 1.0
    outbox_batch_size: int = 20
    outbox_lease_seconds: int = 60
    outbox_max_attempts: int = 8
    pipeline_run_lease_seconds: int = 600
    redis_required: bool = False
    storage_backend: str = "local"
    attachment_root: str = "data/attachments"
    s3_endpoint_url: str = "http://seaweed-s3:8333"
    s3_bucket: str = "intake-attachments"
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    secret_key: str = "dev-secret-key"
    # The web session for every user, CTO and Project Owner alike: a working week (FR-ID-09, Intake INT-26W42-012).
    # Logging in again means the password and MFA; the cookie is HttpOnly, Secure and SameSite=Strict.
    access_token_ttl_minutes: int = 7 * 24 * 60
    auth_cookie_name: str = "intake_session"
    csrf_cookie_name: str = "intake_csrf"
    cookie_secure: bool = False
    allow_subject_header_auth: bool = False
    cto_initial_password: str = "dev-cto-password"
    project_owner_initial_password: str = ""
    # Set by the one-command installer only: opens the one-shot first-account route and requires an AI key (ADR-0071).
    first_run_wizard: bool = False
    ai_provider_primary: str = "umodelverse"
    ai_provider_fallback: str = "openrouter"
    ai_request_timeout_seconds: float = 45.0
    ai_report_timeout_seconds: float = 120.0
    report_ai_batch_size: int = 5
    report_late_cutoff: str = "23:30"
    # The build that is running, shown under "what's new"; set by the deploy command (FR-UI-14).
    git_sha: str = "dev"
    build_time: str | None = None
    umodelverse_api_key: str | None = None
    umodelverse_model: str = "deepseek-v4.1-flash"
    umodelverse_pro_model: str = "deepseek-v4-pro-0813"
    umodelverse_vision_model: str = "deepseek-v4-flash-vision-exp"
    umodelverse_base_url: str = "https://api-sg.umodelverse.ai/v1"
    openrouter_api_key: str | None = None
    openrouter_model: str = "openai/gpt-4o-mini"
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    ai_task_max_retries: int = 3
    # Attachments read by the vision model (ADR-0061): on by default, a PDF gives at most this many pages, one call may take this long.
    attachment_vision_enabled: bool = True
    attachment_pdf_max_pages: int = 8
    ai_vision_timeout_seconds: float = 90.0
    # The posting flow outside Intake (ADR-0038). Unset or short means its routes answer 404.
    publish_api_key: str | None = None
    publish_webhook_secret: str | None = None
    # The scanning flow outside Intake (ADR-0039): one key to read what to scan, one secret to sign what it found.
    watch_api_key: str | None = None
    watch_webhook_secret: str | None = None
    # The short domain that redirects to posts' landing pages (FR-MKT-12), e.g. https://go.example.com; empty shows a relative link.
    short_link_base: str = ""
    raw_retention_days: int = 90
    gitlab_base_url: str = "https://gitlab.com"
    # The HTML comment prefix written into Issue bodies to find them again; a deployment that already created Issues must keep its old prefix.
    integration_marker_prefix: str = "intake"
    # Marketing posts and watch sources are still changing; false hides them from the menu and routes.
    beta_features_enabled: bool = False
    gitlab_integration_enabled: bool = False
    gitlab_token: str | None = None
    # Read-only token of the repo-reader worker (ADR-0063): reads docs/agent/CONTEXT.md, never writes.
    gitlab_repo_read_token: str | None = None
    # Reminders over Telegram (ADR-0057): the token lives in the telegram-bot container only; the username builds invite links.
    telegram_bot_token: str | None = None
    telegram_bot_username: str | None = None
    # Where the app is reached from outside, for links in messages (no trailing slash).
    app_public_url: str | None = None
    # Self-service password recovery. Mailgun is called over HTTPS; no SMTP credential enters the app.
    mailgun_api_key: str | None = None
    mailgun_domain: str | None = None
    mailgun_from: str | None = None
    mailgun_api_base_url: str = "https://api.mailgun.net"
    password_reset_ttl_minutes: int = 30
    password_reset_resend_seconds: int = 60
    sync_job_max_attempts: int = 5
    sync_job_lease_seconds: int = 120
    meeting_capture_enabled: bool = False
    elevenlabs_api_key: str | None = None
    elevenlabs_base_url: str = "https://api.elevenlabs.io"
    elevenlabs_realtime_model: str = "scribe_v2_realtime"
    elevenlabs_batch_model: str = "scribe_v2"
    elevenlabs_delete_after_meeting: bool = True
    meeting_language: str = "vi"
    meeting_max_minutes: int = 60
    meeting_max_speakers: int = 8
    meeting_max_audio_mb: int = 200
    meeting_background_enabled: bool = True
    report_imap_enabled: bool = False
    report_imap_host: str = ""
    report_imap_port: int = 993
    report_imap_username: str = ""
    report_imap_password: str | None = None
    report_imap_folder: str = "INBOX"
    report_imap_poll_seconds: int = 1800
    report_imap_fetch_limit: int = 200

    @property
    def is_deployed_environment(self) -> bool:
        """Unknown environment names fail closed instead of silently behaving like development."""
        return self.app_env.strip().lower() not in _LOCAL_ENVIRONMENTS

    @model_validator(mode="after")
    def validate_deployed_security(self) -> "Settings":
        if not self.is_deployed_environment:
            return self

        errors: list[str] = []
        secret_key = self.secret_key.strip()
        initial_password = self.cto_initial_password.strip()
        owner_password = self.project_owner_initial_password.strip()
        if secret_key.lower() in _KNOWN_SECRET_KEYS or len(secret_key) < 32 or len(set(secret_key)) < 8:
            errors.append("SECRET_KEY must be at least 32 characters, have sufficient character diversity, and not use a repository default")
        if initial_password.lower() in _KNOWN_INITIAL_PASSWORDS or len(initial_password) < 12:
            errors.append("CTO_INITIAL_PASSWORD must be at least 12 characters and must not use a repository default")
        if owner_password and (owner_password.lower() in _KNOWN_INITIAL_PASSWORDS or len(owner_password) < 12):
            errors.append("PROJECT_OWNER_INITIAL_PASSWORD must be at least 12 characters and must not use a repository default")
        if not self.cookie_secure:
            errors.append("COOKIE_SECURE must be true outside local and test environments")
        if errors:
            raise ValueError("Unsafe deployed configuration: " + "; ".join(errors))
        return self

    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
