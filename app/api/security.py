from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings
from app.modules.identity.service import identity_service
from app.modules.identity.tokens import TOKEN_PREFIX, api_token_service


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    subject: str
    email: str
    role: str
    can_view_raw: bool
    can_approve: bool
    display_name: str = ""
    # None means every project (the CTO); otherwise the projects granted to a Project Owner.
    project_ids: frozenset[str] | None = None
    must_change_password: bool = False

    def allows(self, project_id: object) -> bool:
        return self.project_ids is None or str(project_id) in self.project_ids


bearer_scheme = HTTPBearer(auto_error=False)


def _encode_token(subject: str, auth_version: int) -> str:
    settings = get_settings()
    payload = {"sub": subject, "ver": auth_version, "exp": int(time.time()) + settings.access_token_ttl_minutes * 60}
    encoded_payload = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).rstrip(b"=")
    signature = hmac.new(settings.secret_key.encode(), encoded_payload, hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=")
    return f"{encoded_payload.decode()}.{encoded_signature.decode()}"


def create_access_token(subject: str) -> tuple[str, int]:
    settings = get_settings()
    context = identity_service.get_context(subject)
    return _encode_token(subject, context.auth_version), settings.access_token_ttl_minutes * 60


def _decode_token(token: str) -> tuple[str, int]:
    settings = get_settings()
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected_signature = hmac.new(settings.secret_key.encode(), encoded_payload.encode(), hashlib.sha256).digest()
        actual_signature = base64.urlsafe_b64decode(encoded_signature + "==")
        if not hmac.compare_digest(actual_signature, expected_signature):
            raise ValueError
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload + "=="))
        if not isinstance(payload.get("sub"), str) or int(payload["exp"]) <= int(time.time()):
            raise ValueError
        return payload["sub"], int(payload.get("ver", 0))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired access token")


def get_current_user(
    request: Request,
    x_user_subject: str | None = Header(default=None, alias="X-User-Subject"),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthContext:
    settings = get_settings()
    auth_version: int | None = None
    if credentials is not None and credentials.credentials.startswith(TOKEN_PREFIX):
        # A personal token: an agent acting as the person who issued it.
        subject = api_token_service.resolve(credentials.credentials)
        if subject is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid, expired or revoked token")
    elif credentials is not None:
        subject, auth_version = _decode_token(credentials.credentials)
    elif x_user_subject and settings.allow_subject_header_auth:
        subject = x_user_subject
    elif request.cookies.get(settings.auth_cookie_name):
        subject, auth_version = _decode_token(request.cookies[settings.auth_cookie_name])
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication is required",
        )

    try:
        user = identity_service.get_context(subject)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unknown user subject",
        ) from exc
    if auth_version is not None and auth_version != user.auth_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session was revoked after a credential change")

    return AuthContext(
        user_id=user.user_id,
        subject=subject,
        email=user.email,
        role=user.role,
        can_view_raw=user.can_view_raw,
        can_approve=user.can_approve,
        display_name=user.display_name,
        project_ids=user.project_ids,
        must_change_password=user.must_change_password,
    )


def get_current_user_strict(
    request: Request,
    x_user_subject: str | None = Header(default=None, alias="X-User-Subject"),
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
) -> AuthContext:
    return get_current_user(request=request, x_user_subject=x_user_subject, credentials=credentials)


def _password_is_settled(context: AuthContext) -> None:
    if context.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "PASSWORD_CHANGE_REQUIRED", "message": "Choose your own password before continuing"},
        )


def require_cto(context: AuthContext = Depends(get_current_user_strict)) -> AuthContext:
    if context.role != "CTO":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only CTO may access this resource",
        )
    _password_is_settled(context)
    return context


def require_member(context: AuthContext = Depends(get_current_user_strict)) -> AuthContext:
    """The CTO, or a Project Owner. Routes that use this must also check the project of what they touch."""
    if context.role not in ("CTO", "PROJECT_OWNER"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this action")
    _password_is_settled(context)
    return context


def require_account(context: AuthContext = Depends(get_current_user_strict)) -> AuthContext:
    """Any person with a login, a Developer included: their own tokens, password and MFA."""
    if context.role not in ("CTO", "PROJECT_OWNER", "DEVELOPER"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions for this action")
    _password_is_settled(context)
    return context


def ensure_project(context: AuthContext, project_id: object, what: str = "Resource") -> None:
    """Outside the caller's projects a resource looks exactly like one that does not exist."""
    if project_id is None or not context.allows(project_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{what} not found")
