from fastapi import APIRouter, Depends

from app.api.security import AuthContext, require_cto
from app.modules.operations.service import operations_service

router = APIRouter(prefix="/operations", tags=["operations"])


@router.get("/status", openapi_extra={"x-requirement-ids": ["NFR-OBS-01", "NFR-REL-02"]})
async def get_operations_status(_: AuthContext = Depends(require_cto)) -> dict[str, object]:
    return operations_service.get_status()
