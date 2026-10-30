import secrets
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status

from app.api.security import AuthContext, create_access_token, get_current_user_strict, require_account
from app.modules.identity.tokens import TOKEN_PREFIX, api_token_service
from app.modules.identity.mailgun import MailgunError, password_reset_mailer
from app.config import get_settings
from app.modules.identity.service import IdentityError, identity_service
from app.schemas import (
    ApiTokenCreate,
    ApiTokenIssued,
    ApiTokenOut,
    LoginRequest,
    MfaCodeRequest,
    MfaSetupResponse,
    MfaStepUpRequest,
    PasswordChange,
    PasswordResetAccepted,
    PasswordResetConfirm,
    PasswordResetRequestIn,
    RecoveryCodesResponse,
    TokenResponse,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


async def _deliver_password_reset(request_id: str, email: str, display_name: str, token: str) -> None:
    try:
        await password_reset_mailer.send(email=email, display_name=display_name, token=token)
    except MailgunError as error:
        identity_service.mark_password_reset_delivery(request_id, sent=False, error=error.code)
        logger.warning("password reset email delivery failed: %s", error.code)
    else:
        identity_service.mark_password_reset_delivery(request_id, sent=True)


@router.post("/login", response_model=TokenResponse, openapi_extra={"x-requirement-ids": ["FR-ID-01", "FR-ID-05", "FR-ID-09"]})
async def login(payload: LoginRequest, response: Response) -> TokenResponse:
    payload.subject = identity_service.resolve_login(payload.subject)
    try:
        identity_service.get_context(payload.subject)
    except KeyError as exc:
        raise HTTPException(status_code=401, detail="Invalid credentials") from exc
    if not identity_service.verify_password(payload.subject, payload.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if identity_service.mfa_required(payload.subject) and not (
        identity_service.verify_mfa(payload.subject, payload.otp)
        or identity_service.consume_recovery_code(payload.subject, payload.recovery_code)
    ):
        raise HTTPException(status_code=401, detail="A valid MFA code is required")
    return issue_session(response, payload.subject)


def issue_session(response: Response, subject: str) -> TokenResponse:
    """Set the session and CSRF cookies for an account whose credentials were already checked."""
    token, expires_in = create_access_token(subject)
    settings = get_settings()
    csrf_token = secrets.token_urlsafe(32)
    response.set_cookie(
        settings.auth_cookie_name,
        token,
        max_age=expires_in,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=expires_in,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )
    return TokenResponse(access_token=token, expires_in=expires_in)


@router.post(
    "/password-reset/request", response_model=PasswordResetAccepted, status_code=status.HTTP_202_ACCEPTED,
    openapi_extra={"x-requirement-ids": ["FR-ID-06", "NFR-SEC-03"]},
)
async def request_password_reset(payload: PasswordResetRequestIn, background: BackgroundTasks) -> PasswordResetAccepted:
    if not password_reset_mailer.configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "PASSWORD_RESET_UNAVAILABLE",
                "message": "Chức năng gửi email đặt lại mật khẩu chưa được cấu hình.",
                "details": [],
            },
        )
    # The same response is returned for unknown, inactive, throttled and valid accounts: no account enumeration.
    prepared = identity_service.prepare_password_reset(payload.identifier)
    if prepared is not None:
        background.add_task(
            _deliver_password_reset, prepared["request_id"], prepared["email"],
            prepared["display_name"], prepared["token"],
        )
    return PasswordResetAccepted(
        message="Nếu tài khoản tồn tại, email đặt lại mật khẩu sẽ được gửi trong ít phút.",
    )


@router.post(
    "/password-reset/confirm", response_model=dict,
    openapi_extra={"x-requirement-ids": ["FR-ID-06", "NFR-SEC-03"]},
)
async def confirm_password_reset(payload: PasswordResetConfirm, response: Response) -> dict[str, bool]:
    try:
        identity_service.complete_password_reset(payload.token, payload.new_password)
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": error.code, "message": error.message, "details": []},
        ) from error
    settings = get_settings()
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"changed": True}


@router.post("/logout", openapi_extra={"x-requirement-ids": ["FR-ID-03"]})
async def logout(response: Response, _: AuthContext = Depends(get_current_user_strict)) -> dict[str, bool]:
    settings = get_settings()
    response.delete_cookie(settings.auth_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"logged_out": True}


@router.post("/mfa/setup", response_model=MfaSetupResponse, openapi_extra={"x-requirement-ids": ["FR-ID-02"]})
async def setup_mfa(
    payload: MfaStepUpRequest,
    context: AuthContext = Depends(get_current_user_strict),
) -> MfaSetupResponse:
    try:
        secret = identity_service.start_mfa_setup(
            context.subject, current_password=payload.current_password, otp=payload.otp,
        )
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": error.code, "message": error.message},
        ) from error
    return MfaSetupResponse(secret=secret, issuer="Private Feedback Intake", subject=context.subject)


@router.post("/mfa/confirm", openapi_extra={"x-requirement-ids": ["FR-ID-02"]})
async def confirm_mfa(
    payload: MfaCodeRequest,
    response: Response,
    context: AuthContext = Depends(get_current_user_strict),
) -> dict[str, bool]:
    if not identity_service.confirm_mfa_setup(context.subject, payload.code):
        raise HTTPException(status_code=400, detail="Invalid MFA code")
    # The factor change revokes every older auth_version. Keep only this freshly stepped-up browser signed in.
    issue_session(response, context.subject)
    return {"enabled": True}


@router.post("/mfa/recovery-codes", response_model=RecoveryCodesResponse, openapi_extra={"x-requirement-ids": ["FR-ID-02"]})
async def generate_recovery_codes(
    payload: MfaStepUpRequest,
    context: AuthContext = Depends(get_current_user_strict),
) -> RecoveryCodesResponse:
    try:
        codes = identity_service.generate_recovery_codes(
            context.subject, current_password=payload.current_password, otp=payload.otp,
        )
    except KeyError as exc:
        raise HTTPException(status_code=409, detail="MFA must be enabled before generating recovery codes") from exc
    except IdentityError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": error.code, "message": error.message},
        ) from error
    return RecoveryCodesResponse(recovery_codes=codes)


@router.get("/me", response_model=dict, openapi_extra={"x-requirement-ids": ["FR-ID-01", "FR-ID-04"]})
async def get_me(context: AuthContext = Depends(get_current_user_strict)) -> dict:
    from app.config import get_settings
    from app.db import get_session
    from app.models import User

    from sqlalchemy import select

    from app.models import Project, UserProjectAccess, WorkforceProjectMembership
    from app.modules.private_space.service import private_project_ids

    with get_session() as session:
        account = session.get(User, context.user_id)
        member_id = str(account.member_id) if account is not None and account.member_id else None
        # The person's projects with their kind (FR-MKT-03): the web picks its words and its sidebar from these.
        hidden = set(private_project_ids(session))
        if context.role == "CTO":
            query = select(Project).where(Project.status == "ACTIVE")
        elif context.role == "DEVELOPER" and member_id:
            query = select(Project).join(WorkforceProjectMembership, WorkforceProjectMembership.project_id == Project.id).where(
                WorkforceProjectMembership.member_id == member_id, WorkforceProjectMembership.active.is_(True), Project.status == "ACTIVE")
        elif context.role == "PROJECT_OWNER":
            query = select(Project).join(UserProjectAccess, UserProjectAccess.project_id == Project.id).where(UserProjectAccess.user_id == context.user_id, Project.status == "ACTIVE")
        else:
            query = None
        projects = [] if query is None else [
            {"id": str(p.id), "code": p.code, "name": p.name, "kind": p.kind}
            for p in session.scalars(query.order_by(Project.name)).all() if str(p.id) not in hidden and p.code != "other"
        ]
    mode = "MARKETING" if context.role != "CTO" and projects and all(p["kind"] == "NON_CODE" for p in projects) else "FULL"
    return {
        "subject": context.subject,
        # The member this account is, when it is one: the web shows "Việc của tôi" and the Góp ý page from it.
        "member_id": member_id,
        "email": context.email,
        "display_name": context.display_name,
        "role": context.role,
        "can_view_raw": context.can_view_raw,
        "can_approve": context.can_approve,
        "mfa_enabled": identity_service.mfa_required(context.subject),
        # null means every project (the CTO); a list means exactly those projects.
        "project_ids": None if context.project_ids is None else sorted(context.project_ids),
        "must_change_password": context.must_change_password,
        "projects": projects,
        "mode": mode,
        "beta_features_enabled": get_settings().beta_features_enabled,
    }


@router.post("/password", openapi_extra={"x-requirement-ids": ["FR-ID-01", "FR-ID-06"]})
async def change_password(payload: PasswordChange, context: AuthContext = Depends(get_current_user_strict)) -> dict[str, bool]:
    try:
        identity_service.change_password(context.subject, payload.current_password, payload.new_password)
    except IdentityError as error:
        raise HTTPException(status_code=422, detail={"code": error.code, "message": error.message}) from error
    return {"changed": True}


# ---- Personal tokens for agents (FR-MCP-01) ----------------------------------------------------------------------

def _from_session(request: Request) -> None:
    """Tokens are minted and revoked from a signed-in session only; a token cannot make or unmake tokens."""
    if request.headers.get("Authorization", "").startswith(f"Bearer {TOKEN_PREFIX}"):
        raise HTTPException(status_code=403, detail="Sign in to manage tokens")


@router.get("/tokens", response_model=list[ApiTokenOut], openapi_extra={"x-requirement-ids": ["FR-MCP-01", "FR-ID-04"]})
async def list_tokens(request: Request, context: AuthContext = Depends(require_account)) -> list[ApiTokenOut]:
    _from_session(request)
    return [ApiTokenOut.model_validate(row) for row in api_token_service.list(context.user_id)]


@router.post("/tokens", response_model=ApiTokenIssued, status_code=201, openapi_extra={"x-requirement-ids": ["FR-MCP-01", "FR-ID-04"]})
async def create_token(payload: ApiTokenCreate, request: Request, context: AuthContext = Depends(require_account)) -> ApiTokenIssued:
    _from_session(request)
    try:
        return ApiTokenIssued.model_validate(api_token_service.issue(context.user_id, payload.name))
    except ValueError as error:
        raise HTTPException(status_code=409, detail="Too many tokens; revoke one first") from error


@router.delete("/tokens/{token_id}", status_code=204, openapi_extra={"x-requirement-ids": ["FR-MCP-01", "FR-ID-04"]})
async def revoke_token(token_id: str, request: Request, context: AuthContext = Depends(require_account)) -> Response:
    _from_session(request)
    if not api_token_service.revoke(context.user_id, token_id):
        raise HTTPException(status_code=404, detail="Token not found")
    return Response(status_code=204)


@router.get("/agent-commands", openapi_extra={"x-requirement-ids": ["FR-MCP-07"]})
async def list_agent_commands(request: Request, context: AuthContext = Depends(require_account)) -> dict:
    """The command sheet: what this person can type to their agent and when (FR-MCP-07)."""
    from app.modules.mcp.prompts import MARKETING_COMMANDS, commands_for, install_lines, public_base, tool_lines_for
    return {
        "commands": commands_for(context), "install": install_lines(public_base() or str(request.base_url).rstrip("/")),
        # For a marketing project: the commands that matter there, and one sentence per tool to paste (FR-MCP-09).
        "marketing": {"commands": list(MARKETING_COMMANDS), "tools": tool_lines_for(context)},
    }
