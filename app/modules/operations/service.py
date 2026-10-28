from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.config import get_settings
from app.db import get_session
from app.models import BackupRun
from app.modules.ai_config.routing import ROUTE_KEYS, resolve_route

# The backup runs once a day; a little slack before it counts as overdue.
BACKUP_OVERDUE_AFTER = timedelta(hours=26)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class OperationsService:
    def backup_status(self) -> dict[str, object]:
        with get_session() as session:
            last = session.scalar(select(BackupRun).order_by(BackupRun.completed_at.desc()))
            last_ok = session.scalar(select(BackupRun).where(BackupRun.status == "DONE").order_by(BackupRun.completed_at.desc()))
            fresh = last_ok is not None and datetime.now(timezone.utc) - _aware(last_ok.completed_at) <= BACKUP_OVERDUE_AFTER
            state = "healthy" if fresh else "never" if last_ok is None else "overdue"
            return {
                "state": state,
                "last_ok_at": last_ok.completed_at if last_ok else None,
                "last_ok_file": last_ok.file_name if last_ok else None,
                "last_ok_size_bytes": last_ok.size_bytes if last_ok else None,
                "last_ok_objects": last_ok.object_count if last_ok else None,
                # Shown only while the newest attempt is a failure.
                "last_error_code": last.error_code if last is not None and last.status == "FAILED" else None,
                "last_error_at": last.completed_at if last is not None and last.status == "FAILED" else None,
            }

    def get_status(self) -> dict[str, object]:
        settings = get_settings()
        configured = {
            "umodelverse": bool(settings.umodelverse_api_key),
            "openrouter": bool(settings.openrouter_api_key),
        }
        backup = self.backup_status()
        ai_route = next((r for r in (resolve_route(key, settings) for key in ROUTE_KEYS) if r is not None), None)
        return {
            "status": "ok",
            "web": "healthy",
            "worker_ai": "healthy",
            "worker_integration": "healthy",
            "backup": backup["state"],
            "backup_detail": backup,
            "storage": "healthy",
            "ai_provider_primary": settings.ai_provider_primary,
            "ai_primary_configured": configured.get(settings.ai_provider_primary.lower(), False),
            "ai_provider_fallback": settings.ai_provider_fallback,
            "ai_fallback_configured": configured.get(settings.ai_provider_fallback.lower(), False),
            "ai_configured": ai_route is not None,
            "ai_source": ai_route.source if ai_route else "none",
        }


operations_service = OperationsService()
