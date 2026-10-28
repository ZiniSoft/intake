from fastapi import APIRouter, Depends, HTTPException, status

from app.api.security import AuthContext, require_cto
from app.modules.identity.service import IdentityError, identity_service
from app.schemas import AccountCreate, AccountOut, AccountUpdate, AccountWithPassword

router = APIRouter(prefix="/users", tags=["users"])
REQUIREMENTS = {"x-requirement-ids": ["FR-ID-06", "FR-ID-07", "FR-MCP-05", "NFR-SEC-03"]}


def _raise(error: IdentityError) -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT if error.code == "ACCOUNT_EXISTS" else status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={"code": error.code, "message": error.message},
    ) from error


@router.get("", response_model=list[AccountOut], openapi_extra=REQUIREMENTS)
async def list_accounts(_: AuthContext = Depends(require_cto)) -> list[AccountOut]:
    return [AccountOut.model_validate(row) for row in identity_service.list_accounts()]


@router.post("", response_model=AccountWithPassword, status_code=status.HTTP_201_CREATED, openapi_extra=REQUIREMENTS)
async def create_account(payload: AccountCreate, context: AuthContext = Depends(require_cto)) -> AccountWithPassword:
    try:
        account, password = identity_service.create_account(
            subject=payload.subject, email=payload.email, display_name=payload.display_name,
            project_refs=payload.project_ids, actor_id=context.user_id, role=payload.role, member_id=payload.member_id,
        )
    except IdentityError as error:
        _raise(error)
    return AccountWithPassword(account=AccountOut.model_validate(account), temporary_password=password)


@router.patch("/{user_id}", response_model=AccountOut, openapi_extra=REQUIREMENTS)
async def update_account(user_id: str, payload: AccountUpdate, context: AuthContext = Depends(require_cto)) -> AccountOut:
    try:
        return AccountOut.model_validate(identity_service.update_account(
            user_id, display_name=payload.display_name, is_active=payload.is_active,
            project_refs=payload.project_ids, actor_id=context.user_id, member_id=payload.member_id,
        ))
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found") from error
    except IdentityError as error:
        _raise(error)


@router.post("/{user_id}/reset-password", response_model=AccountWithPassword, openapi_extra=REQUIREMENTS)
async def reset_account_password(user_id: str, context: AuthContext = Depends(require_cto)) -> AccountWithPassword:
    try:
        account, password = identity_service.reset_password(user_id, context.user_id)
    except KeyError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found") from error
    except IdentityError as error:
        _raise(error)
    return AccountWithPassword(account=AccountOut.model_validate(account), temporary_password=password)
