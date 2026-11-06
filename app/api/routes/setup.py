from fastapi import APIRouter, Depends, Response, status

from app.api.errors import api_exception
from app.api.routes.auth import issue_session
from app.api.security import AuthContext, require_cto
from app.modules.setup.service import SetupError, setup_service
from app.schemas import BootstrapIn, SetupStateOut, SetupStatusOut

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("", response_model=SetupStateOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-01"]})
async def get_setup(context: AuthContext = Depends(require_cto)) -> SetupStateOut:
    return SetupStateOut.model_validate(setup_service.state())


@router.post("/private-sample", response_model=SetupStateOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-02"]})
async def load_private_sample(context: AuthContext = Depends(require_cto)) -> SetupStateOut:
    try:
        setup_service.load_private_sample(context.user_id)
    except SetupError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error
    return SetupStateOut.model_validate(setup_service.state())


@router.post("/demo-project", response_model=SetupStateOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-11"]})
async def load_demo_project(context: AuthContext = Depends(require_cto)) -> SetupStateOut:
    try:
        setup_service.load_demo_project(context.user_id)
    except SetupError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error
    return SetupStateOut.model_validate(setup_service.state())


@router.post("/complete",response_model=SetupStateOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-03"]})
async def complete_setup(context: AuthContext = Depends(require_cto)) -> SetupStateOut:
    try:
        return SetupStateOut.model_validate(setup_service.complete(context.user_id))
    except SetupError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, error.message) from error


@router.get("/status", response_model=SetupStatusOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-05"]})
async def setup_status() -> SetupStatusOut:
    return SetupStatusOut(needs_bootstrap=setup_service.needs_bootstrap())


@router.post("/bootstrap", response_model=SetupStatusOut, openapi_extra={"x-requirement-ids": ["FR-SETUP-06"]})
async def bootstrap(payload: BootstrapIn, response: Response) -> SetupStatusOut:
    try:
        subject = setup_service.bootstrap(payload.cto.model_dump(), payload.owner.model_dump() if payload.owner else None)
    except SetupError as error:
        if error.code == "NOT_FOUND":
            raise api_exception(status.HTTP_404_NOT_FOUND, error.code, error.message) from error
        code = status.HTTP_409_CONFLICT if error.code == "BOOTSTRAP_DONE" else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise api_exception(code, error.code, error.message) from error
    issue_session(response, subject)
    return SetupStatusOut(needs_bootstrap=False)
