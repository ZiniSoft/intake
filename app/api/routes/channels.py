"""Channel rules (FR-MKT-02): read by everyone with a login, edited by the CTO."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.api.errors import api_exception
from app.api.security import AuthContext, require_account, require_cto
from app.modules.work.channels import ChannelRuleError, list_rules, update_rule
from app.schemas import ChannelRuleOut, ChannelRuleUpdate

router = APIRouter(prefix="/channel-rules", tags=["channels"])


@router.get("", response_model=list[ChannelRuleOut], openapi_extra={"x-requirement-ids": ["FR-MKT-02"]})
async def list_channel_rules(_: AuthContext = Depends(require_account)) -> list[dict]:
    return [ChannelRuleOut.model_validate(row).model_dump() for row in list_rules()]


@router.put("/{code}", response_model=ChannelRuleOut, openapi_extra={"x-requirement-ids": ["FR-MKT-02"]})
async def put_channel_rule(code: str, payload: ChannelRuleUpdate, context: AuthContext = Depends(require_cto)) -> dict:
    try:
        row = update_rule(code.upper(), payload.model_dump(exclude_unset=True), actor_id=context.user_id)
    except KeyError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Channel not found")
    except ChannelRuleError as error:
        raise api_exception(status.HTTP_422_UNPROCESSABLE_ENTITY, error.code, str(error))
    return ChannelRuleOut.model_validate(row).model_dump()
