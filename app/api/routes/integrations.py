from fastapi import APIRouter, Depends, HTTPException, status

from app.api.errors import api_exception
from app.api.routes.intakes import intake_member
from app.api.security import AuthContext, ensure_project, require_member
from app.modules.integrations.service import SyncValidationError, integration_service
from app.schemas import SyncJobOut, SyncStatusOut


router = APIRouter(tags=["integrations"])


@router.get(
    "/intakes/{intake_id}/sync-status",
    response_model=SyncStatusOut,
    openapi_extra={"x-requirement-ids": ["FR-SYNC-01", "FR-UI-03"]},
)
async def get_sync_status(
    intake_id: str,
    _: AuthContext = Depends(intake_member),
) -> SyncStatusOut:
    try:
        return SyncStatusOut.model_validate(integration_service.status_for_intake(intake_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Intake not found") from exc


@router.post(
    "/approval-snapshots/{snapshot_id}/sync",
    response_model=SyncJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-SYNC-01", "FR-SYNC-02", "FR-SYNC-03"]},
)
async def queue_snapshot_sync(
    snapshot_id: str,
    context: AuthContext = Depends(require_member),
) -> SyncJobOut:
    project_id = integration_service.snapshot_project(snapshot_id)
    if project_id is not None:
        ensure_project(context, project_id, "Approval snapshot")
    try:
        return SyncJobOut.model_validate(integration_service.queue_snapshot(snapshot_id, context.user_id))
    except KeyError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval snapshot not found") from exc
    except SyncValidationError as exc:
        status_code = (
            status.HTTP_409_CONFLICT
            if exc.code == "SNAPSHOT_INVALIDATED"
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise api_exception(status_code, exc.code, str(exc)) from exc
