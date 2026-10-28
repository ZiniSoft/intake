from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text
from redis import Redis

from app.config import get_settings
from app.db import get_engine
from app.services.object_storage import get_object_storage
from app.schemas import HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse, openapi_extra={"x-requirement-ids": ["NFR-OBS-01"]})
async def get_health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        app_name=settings.app_name,
        project_name=settings.project_name,
        environment=settings.app_env,
    )


@router.get("/live", openapi_extra={"x-requirement-ids": ["NFR-OBS-01"]})
async def get_liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready", openapi_extra={"x-requirement-ids": ["NFR-OBS-01"]})
async def get_readiness() -> dict[str, object]:
    settings = get_settings()
    dependencies: dict[str, str] = {}
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not ready") from exc
    dependencies["database"] = "ok"
    if settings.redis_required:
        try:
            Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Redis is not ready") from exc
        dependencies["redis"] = "ok"
    try:
        get_object_storage().healthcheck()
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Object storage is not ready") from exc
    dependencies["object_storage"] = "ok"
    return {"status": "ok", "dependencies": dependencies}
