from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import re
import secrets
from uuid import uuid4

from sqlalchemy import func, select

from app.db import get_session
from app.config import get_settings
from app.models import ApiToken, AuditEvent, MFARecoveryCode, PasswordResetRequest, Project, User, UserProjectAccess, WorkforceMember, WorkforceProjectMembership
from app.modules.identity.totp import generate_secret, verify_code
from app.services.raw_crypto import decrypt, encrypt


MFA_SETUP_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class UserContext:
    user_id: str
    email: str
    role: str
    can_view_raw: bool = False
    can_approve: bool = False
    display_name: str = ""
    # None means every project (the CTO). A Project Owner has exactly the projects granted to them.
    project_ids: frozenset[str] | None = None
    must_change_password: bool = False
    auth_version: int = 0


SUBJECT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")


class IdentityError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class IdentityService:
    def __init__(self) -> None:
        settings = get_settings()
        self._users = {
            "cto": UserContext(
                user_id="00000000-0000-4000-8000-000000000001",
                email="cto@company.local",
                role="CTO",
                can_view_raw=True,
                can_approve=True,
            ),
            "project-owner": UserContext(
                user_id="00000000-0000-4000-8000-000000000002",
                email="owner@company.local",
                role="PROJECT_OWNER",
                can_view_raw=False,
                can_approve=False,
                project_ids=frozenset(),
            ),
        }
        self._passwords = {
            "cto": self._hash_password(settings.cto_initial_password),
            "project-owner": self._hash_password(settings.project_owner_initial_password),
        }
        if not settings.project_owner_initial_password or settings.first_run_wizard:
            # The sample Project Owner exists only when a deployment sets its password; owners are otherwise
            # invited by the CTO from Settings.
            del self._users["project-owner"], self._passwords["project-owner"]

    @staticmethod
    def _hash_password(password: str) -> tuple[str, str]:
        salt = secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
        return salt, digest

    @classmethod
    def password_hash_value(cls, password: str) -> str:
        salt, digest = cls._hash_password(password)
        return f"{salt}:{digest}"

    @staticmethod
    def resolve_login(identifier: str) -> str:
        """Map what a person typed at sign-in (account name or email) to the account's auth subject."""
        identifier = identifier.strip()
        with get_session() as session:
            if session.scalar(select(User.id).where(User.auth_subject == identifier)) is not None:
                return identifier
            if "@" in identifier:
                subject = session.scalar(select(User.auth_subject).where(func.lower(User.email) == identifier.lower()))
                if subject is not None:
                    return subject
        return identifier

    def get_context(self, subject: str) -> UserContext:
        with get_session() as session:
            user = session.scalar(select(User).where(User.auth_subject == subject))
            if user is not None:
                if not user.is_active:
                    # A deactivated account must not fall back to the built-in seed accounts.
                    raise KeyError(subject)
                granted = None
                if user.role == "DEVELOPER":
                    # A developer's projects are the ones their staff record is on; nothing is granted by hand.
                    granted = self._member_projects(session, user)
                elif user.role != "CTO":
                    granted = frozenset(str(value) for value in session.scalars(
                        select(UserProjectAccess.project_id).join(Project, Project.id == UserProjectAccess.project_id)
                        .where(UserProjectAccess.user_id == user.id, Project.status == "ACTIVE")
                    ).all())
                return self._context_from_user(user, granted)
        return self._users[subject]

    def can_access_raw(self, subject: str) -> bool:
        return self.get_context(subject).can_view_raw

    def verify_password(self, subject: str, password: str) -> bool:
        with get_session() as session:
            user = session.scalar(select(User).where(User.auth_subject == subject, User.is_active.is_(True)))
            if user is not None and user.password_hash:
                salt, expected_hash = user.password_hash.split(":", 1)
                actual_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
                return hmac.compare_digest(actual_hash, expected_hash)
        credentials = self._passwords.get(subject)
        if credentials is None:
            return False
        salt, expected_hash = credentials
        actual_hash = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
        return hmac.compare_digest(actual_hash, expected_hash)

    def mfa_required(self, subject: str) -> bool:
        with get_session() as session:
            user = session.scalar(select(User).where(User.auth_subject == subject, User.is_active.is_(True)))
            return bool(user and user.mfa_enabled)

    def verify_mfa(self, subject: str, code: str | None) -> bool:
        with get_session() as session:
            user = session.scalar(select(User).where(User.auth_subject == subject, User.is_active.is_(True)))
            secret = decrypt(user.mfa_secret_ciphertext) if user and user.mfa_secret_ciphertext else None
            return bool(secret and code and verify_code(secret, code))

    def _require_mfa_step_up(self, user: User, current_password: str, otp: str | None) -> None:
        try:
            salt, expected_hash = user.password_hash.split(":", 1)
        except ValueError as error:
            raise IdentityError("STEP_UP_FAILED", "The current credentials are not valid") from error
        actual_hash = hashlib.pbkdf2_hmac("sha256", current_password.encode(), salt.encode(), 120000).hex()
        if not hmac.compare_digest(actual_hash, expected_hash):
            raise IdentityError("STEP_UP_FAILED", "The current credentials are not valid")
        if user.mfa_enabled:
            secret = decrypt(user.mfa_secret_ciphertext) if user.mfa_secret_ciphertext else None
            if not secret or not otp or not verify_code(secret, otp):
                raise IdentityError("STEP_UP_FAILED", "The current credentials are not valid")

    def generate_recovery_codes(
        self, subject: str, *, current_password: str, otp: str | None,
    ) -> list[str]:
        codes = [f"{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}" for _ in range(8)]
        hashed_codes = [self._hash_recovery_code(code) for code in codes]
        with get_session() as session:
            user = session.scalar(
                select(User).where(User.auth_subject == subject, User.is_active.is_(True)).with_for_update()
            )
            if user is None or not user.mfa_enabled:
                raise KeyError(subject)
            self._require_mfa_step_up(user, current_password, otp)
            existing = session.scalars(
                select(MFARecoveryCode).where(MFARecoveryCode.user_id == user.id)
            ).all()
            for recovery_code in existing:
                session.delete(recovery_code)
            for code_hash in hashed_codes:
                session.add(
                    MFARecoveryCode(
                        id=str(uuid4()),
                        user_id=user.id,
                        code_hash=code_hash,
                    )
                )
            session.commit()
        return codes

    def consume_recovery_code(self, subject: str, code: str | None) -> bool:
        if not code:
            return False
        with get_session() as session:
            user = session.scalar(select(User).where(User.auth_subject == subject, User.is_active.is_(True)))
            if user is None:
                return False
            recovery_codes = session.scalars(
                select(MFARecoveryCode).where(
                    MFARecoveryCode.user_id == user.id,
                    MFARecoveryCode.used_at.is_(None),
                )
            ).all()
            for recovery_code in recovery_codes:
                stored_hash = recovery_code.code_hash
                if hmac.compare_digest(self._hash_recovery_code(code, stored_hash.split(":", 1)[0]), stored_hash):
                    recovery_code.used_at = datetime.now(timezone.utc)
                    session.commit()
                    return True
        return False

    @staticmethod
    def _hash_recovery_code(code: str, salt: str | None = None) -> str:
        salt = salt or secrets.token_hex(16)
        digest = hashlib.pbkdf2_hmac("sha256", code.encode(), salt.encode(), 120000).hex()
        return f"{salt}:{digest}"

    def start_mfa_setup(
        self, subject: str, *, current_password: str, otp: str | None,
    ) -> str:
        secret = generate_secret()
        now = datetime.now(timezone.utc)
        with get_session() as session:
            user = session.scalar(
                select(User).where(User.auth_subject == subject, User.is_active.is_(True)).with_for_update()
            )
            if user is None:
                raise KeyError(subject)
            self._require_mfa_step_up(user, current_password, otp)
            user.mfa_pending_secret_ciphertext = encrypt(secret)
            user.mfa_pending_expires_at = now + MFA_SETUP_TTL
            user.updated_at = now
            session.commit()
        return secret

    def confirm_mfa_setup(self, subject: str, code: str) -> bool:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            user = session.scalar(
                select(User).where(User.auth_subject == subject, User.is_active.is_(True)).with_for_update()
            )
            expires_at = user.mfa_pending_expires_at if user else None
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            secret = decrypt(user.mfa_pending_secret_ciphertext) if user and user.mfa_pending_secret_ciphertext else None
            if user is None or not secret or expires_at is None or expires_at <= now or not verify_code(secret, code):
                return False
            user.mfa_secret_ciphertext = user.mfa_pending_secret_ciphertext
            user.mfa_pending_secret_ciphertext = None
            user.mfa_pending_expires_at = None
            user.mfa_enabled = True
            user.auth_version = int(user.auth_version or 0) + 1
            user.updated_at = now
            for token in session.scalars(
                select(ApiToken).where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None))
            ).all():
                token.revoked_at = now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=user.id, event_type="user.mfa_changed",
                entity_type="user", entity_id=user.id, details=None, created_at=now,
            ))
            session.commit()
            return True

    def ensure_database_users(self) -> None:
        settings = get_settings()
        with get_session() as session:
            for subject, context in self._users.items():
                salt, password_hash = self._passwords[subject]
                user = session.scalar(select(User).where(User.auth_subject == subject))
                if user is None:
                    user = User(
                        id=context.user_id,
                        auth_subject=subject,
                        email=context.email,
                        display_name=context.email.split("@", 1)[0],
                        role=context.role,
                        password_hash=f"{salt}:{password_hash}",
                        mfa_enabled=False,
                        must_change_password=settings.is_deployed_environment and not settings.first_run_wizard,
                    )
                    session.add(user)
                else:
                    user.role = context.role
                    if not user.password_hash:
                        user.password_hash = f"{salt}:{password_hash}"
                        user.must_change_password = settings.is_deployed_environment and not settings.first_run_wizard
            session.commit()

    @staticmethod
    def _member_projects(session, user: User) -> frozenset[str]:
        if not user.member_id:
            return frozenset()
        return frozenset(str(value) for value in session.scalars(
            select(WorkforceProjectMembership.project_id).join(Project, Project.id == WorkforceProjectMembership.project_id)
            .where(WorkforceProjectMembership.member_id == user.member_id, WorkforceProjectMembership.active.is_(True), Project.status == "ACTIVE")
        ).all())

    @staticmethod
    def _context_from_user(user: User, project_ids: frozenset[str] | None = None) -> UserContext:
        is_cto = user.role == "CTO"
        decides = is_cto or (user.role == "PROJECT_OWNER" and bool(project_ids))
        return UserContext(
            user_id=user.id,
            email=user.email,
            role=user.role,
            # A Project Owner reads raw content and approves, but only inside the granted projects;
            # every route checks the project as well. A Developer decides nothing and never reads raw content.
            can_view_raw=decides,
            can_approve=decides,
            display_name=user.display_name,
            project_ids=None if is_cto else (project_ids or frozenset()),
            must_change_password=bool(user.must_change_password),
            auth_version=int(user.auth_version),
        )

    # --- accounts managed by the CTO --------------------------------------------------------------

    @staticmethod
    def _account(session, user: User) -> dict[str, object]:
        if user.role == "DEVELOPER" and user.member_id:
            rows = session.execute(
                select(Project.id, Project.code, Project.name).join(WorkforceProjectMembership, WorkforceProjectMembership.project_id == Project.id)
                .where(WorkforceProjectMembership.member_id == user.member_id, WorkforceProjectMembership.active.is_(True)).order_by(Project.name)
            ).all()
        else:
            rows = session.execute(
                select(Project.id, Project.code, Project.name).join(UserProjectAccess, UserProjectAccess.project_id == Project.id)
                .where(UserProjectAccess.user_id == user.id).order_by(Project.name)
            ).all()
        member = session.get(WorkforceMember, user.member_id) if user.member_id else None
        agent_last = session.scalar(select(func.max(ApiToken.last_used_at)).where(ApiToken.user_id == user.id, ApiToken.revoked_at.is_(None)))
        return {
            "id": str(user.id), "subject": user.auth_subject, "email": user.email, "display_name": user.display_name,
            "agent_last_used_at": agent_last,
            "role": user.role, "is_active": user.is_active, "mfa_enabled": user.mfa_enabled,
            "must_change_password": user.must_change_password,
            "member_id": str(user.member_id) if user.member_id else None, "member_name": member.display_name if member is not None else None,
            "projects": [{"id": str(row.id), "code": row.code, "name": row.name} for row in rows],
        }

    def list_accounts(self) -> list[dict[str, object]]:
        with get_session() as session:
            users = session.scalars(select(User).order_by(User.role, User.display_name)).all()
            return [self._account(session, user) for user in users]

    @staticmethod
    def _projects(session, refs: list[str]) -> list[Project]:
        projects = []
        for ref in refs:
            project = session.scalar(select(Project).where(Project.code == ref))
            if project is None and len(ref) == 36:
                project = session.get(Project, ref)
            if project is None:
                raise IdentityError("PROJECT_NOT_FOUND", f"Project '{ref}' does not exist")
            projects.append(project)
        return projects

    def _grant(self, session, user: User, refs: list[str], actor_id: str) -> None:
        wanted = {str(project.id) for project in self._projects(session, refs)}
        existing = {str(row.project_id): row for row in session.scalars(
            select(UserProjectAccess).where(UserProjectAccess.user_id == user.id)
        ).all()}
        for project_id in wanted - set(existing):
            session.add(UserProjectAccess(user_id=user.id, project_id=project_id, granted_by=actor_id))
        for project_id in set(existing) - wanted:
            session.delete(existing[project_id])

    def _temporary_password(self, user: User) -> str:
        password = secrets.token_urlsafe(12)
        salt, digest = self._hash_password(password)
        user.password_hash = f"{salt}:{digest}"
        user.must_change_password = True
        user.auth_version = int(user.auth_version or 0) + 1
        return password

    @staticmethod
    def _reset_token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    def _revoke_api_tokens(session, user_id: str, revoked_at: datetime) -> None:
        """Revoke every personal token in the caller's credential-change transaction."""
        for token in session.scalars(select(ApiToken).where(
            ApiToken.user_id == user_id, ApiToken.revoked_at.is_(None)
        )).all():
            token.revoked_at = revoked_at

    def prepare_password_reset(self, identifier: str) -> dict[str, str] | None:
        """Create a one-time reset token without revealing whether the identifier exists.

        The route always returns the same response. This method returns delivery details only to the server.
        """
        settings = get_settings()
        value = identifier.strip().lower()
        now = datetime.now(timezone.utc)
        with get_session() as session:
            user = session.scalar(select(User).where(
                User.is_active.is_(True),
                (func.lower(User.auth_subject) == value) | (func.lower(User.email) == value),
            ))
            if user is None:
                return None
            recent = session.scalar(select(PasswordResetRequest.id).where(
                PasswordResetRequest.user_id == user.id,
                PasswordResetRequest.created_at >= now - timedelta(seconds=max(1, settings.password_reset_resend_seconds)),
                PasswordResetRequest.used_at.is_(None),
                PasswordResetRequest.send_error.is_(None),
            ).limit(1))
            if recent is not None:
                return None
            for old in session.scalars(select(PasswordResetRequest).where(
                PasswordResetRequest.user_id == user.id, PasswordResetRequest.used_at.is_(None)
            )).all():
                old.used_at = now
            token = secrets.token_urlsafe(32)
            row = PasswordResetRequest(
                id=str(uuid4()), user_id=user.id, token_hash=self._reset_token_hash(token),
                expires_at=now + timedelta(minutes=max(5, settings.password_reset_ttl_minutes)), created_at=now,
            )
            session.add(row)
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="ANONYMOUS", actor_id="password-reset",
                event_type="user.password_reset_requested", entity_type="user", entity_id=user.id,
                details=None, created_at=now,
            ))
            session.commit()
            return {
                "request_id": str(row.id), "token": token, "email": user.email,
                "display_name": user.display_name, "subject": user.auth_subject,
            }

    def mark_password_reset_delivery(self, request_id: str, *, sent: bool, error: str | None = None) -> None:
        with get_session() as session:
            row = session.get(PasswordResetRequest, request_id)
            if row is None:
                return
            row.sent_at = datetime.now(timezone.utc) if sent else None
            row.send_error = None if sent else (error or "MAILGUN_ERROR")[:80]
            session.commit()

    def complete_password_reset(self, token: str, new_password: str) -> None:
        if len(new_password) < 12:
            raise IdentityError("PASSWORD_TOO_SHORT", "Mật khẩu mới phải có ít nhất 12 ký tự")
        now = datetime.now(timezone.utc)
        token_hash = self._reset_token_hash(token)
        with get_session() as session:
            row = session.scalar(select(PasswordResetRequest).where(
                PasswordResetRequest.token_hash == token_hash,
                PasswordResetRequest.used_at.is_(None),
                PasswordResetRequest.expires_at > now,
            ).with_for_update())
            user = session.get(User, row.user_id) if row is not None else None
            if row is None or user is None or not user.is_active:
                raise IdentityError("RESET_TOKEN_INVALID", "Link đặt lại mật khẩu không hợp lệ hoặc đã hết hạn")
            salt, digest = self._hash_password(new_password)
            user.password_hash = f"{salt}:{digest}"
            user.must_change_password = False
            user.auth_version = int(user.auth_version or 0) + 1
            user.updated_at = now
            self._revoke_api_tokens(session, user.id, now)
            for pending in session.scalars(select(PasswordResetRequest).where(
                PasswordResetRequest.user_id == user.id, PasswordResetRequest.used_at.is_(None)
            )).all():
                pending.used_at = now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=user.id,
                event_type="user.password_reset_completed", entity_type="user", entity_id=user.id,
                details=None, created_at=now,
            ))
            session.commit()

    def create_account(
        self, *, subject: str, email: str | None, display_name: str | None, project_refs: list[str], actor_id: str,
        role: str = "PROJECT_OWNER", member_id: str | None = None,
    ) -> tuple[dict[str, object], str]:
        """Create a Project Owner, or a Developer tied to a staff member (FR-MCP-05). Returns the account and a
        temporary password that is shown once."""
        if project_refs:
            raise IdentityError("PROJECTS_ASSIGNED_ON_PROJECT", "Choose the Project Owner on the project's own page")
        if role not in ("PROJECT_OWNER", "DEVELOPER"):
            raise IdentityError("ROLE_INVALID", "Role must be PROJECT_OWNER or DEVELOPER")
        subject = subject.strip().lower()
        if not SUBJECT_PATTERN.match(subject):
            raise IdentityError("USERNAME_INVALID", "Username must be 3-64 lowercase letters, digits, dots, hyphens or underscores")
        now = datetime.now(timezone.utc)
        with get_session() as session:
            member = None
            if role == "DEVELOPER":
                member = session.get(WorkforceMember, member_id) if member_id else None
                if member is None or member.status != "ACTIVE":
                    raise IdentityError("MEMBER_REQUIRED", "A Developer login belongs to an active staff member")
                if session.scalar(select(User.id).where(User.member_id == member.id)):
                    raise IdentityError("MEMBER_HAS_ACCOUNT", "This staff member already has a login")
                email = (member.email_reference or "").strip().lower()
                if not email:
                    raise IdentityError("MEMBER_EMAIL_REQUIRED", "This staff member needs an email before getting a login")
                display_name = member.display_name
            email = (email or "").strip().lower()
            display_name = " ".join((display_name or "").split())[:255]
            if not email or not display_name:
                raise IdentityError("ACCOUNT_FIELDS_REQUIRED", "Email and display name are required")
            if session.scalar(select(User.id).where((User.auth_subject == subject) | (User.email == email))):
                raise IdentityError("ACCOUNT_EXISTS", "Another account already uses this username or email")
            user = User(
                id=str(uuid4()), auth_subject=subject, email=email, display_name=display_name,
                role=role, password_hash="", mfa_enabled=False, is_active=True, member_id=member.id if member is not None else None,
                created_at=now, updated_at=now,
            )
            password = self._temporary_password(user)
            session.add(user)
            session.flush()
            self._grant(session, user, project_refs, actor_id)
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="user.created",
                entity_type="user", entity_id=user.id, details={"role": user.role, "projects": sorted(project_refs), "member_id": str(member.id) if member else None}, created_at=now,
            ))
            session.commit()
            return self._account(session, user), password

    def update_account(
        self, user_id: str, *, display_name: str | None, is_active: bool | None, project_refs: list[str] | None, actor_id: str,
        member_id: str | None = None,
    ) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                raise KeyError(user_id)
            if project_refs is not None:
                # One Project Owner per project is guaranteed by assigning it on the project, never here.
                raise IdentityError("PROJECTS_ASSIGNED_ON_PROJECT", "Choose the Project Owner on the project's own page")
            if user.role == "CTO" and is_active is False:
                raise IdentityError("CTO_ACCOUNT_PROTECTED", "The CTO account cannot be deactivated")
            if member_id is not None:
                # The staff record behind a login: the CTO links their own so free hours and Telegram reach them.
                if member_id == "":
                    if user.role == "DEVELOPER":
                        raise IdentityError("MEMBER_REQUIRED", "A Developer login belongs to an active staff member")
                    user.member_id = None
                else:
                    member = session.get(WorkforceMember, member_id)
                    if member is None or member.status != "ACTIVE":
                        raise IdentityError("MEMBER_REQUIRED", "Choose an active staff member")
                    taken = session.scalar(select(User.id).where(User.member_id == member.id, User.id != user.id))
                    if taken:
                        raise IdentityError("MEMBER_HAS_ACCOUNT", "This staff member already has a login")
                    user.member_id = member.id
            if display_name is not None:
                user.display_name = " ".join(display_name.split())[:255] or user.display_name
            if is_active is not None:
                user.is_active = is_active
            if project_refs is not None:
                self._grant(session, user, project_refs, actor_id)
            user.updated_at = now
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="user.updated",
                entity_type="user", entity_id=user.id,
                details={"is_active": user.is_active, "projects": sorted(project_refs) if project_refs is not None else None, "member_id": str(user.member_id) if user.member_id else None}, created_at=now,
            ))
            session.commit()
            return self._account(session, user)

    def owner_account(self, session, member, actor_id: str) -> tuple[User, str | None]:
        """The login of a staff member who becomes a Project Owner, created or unlocked as needed.

        Returns a temporary password only when one was just issued. The caller commits.
        """
        now = datetime.now(timezone.utc)
        email = (member.email_reference or "").strip().lower()
        if not email:
            raise IdentityError("OWNER_EMAIL_REQUIRED", "This staff member needs an email before becoming a Project Owner")
        user = session.scalar(select(User).where(User.member_id == member.id))
        if user is None:
            user = session.scalar(select(User).where(User.email == email))
            if user is not None and user.member_id is None:
                user.member_id = member.id
        if user is not None and user.role == "CTO":
            # The CTO runs this project themself (FR-PLAN-37): their login already decides everywhere, so
            # nothing is created, unlocked or granted.
            return user, None
        if user is not None:
            if user.role == "DEVELOPER":
                # The developer's login becomes the Project Owner's; the token they already hold gains the role.
                user.role = "PROJECT_OWNER"
                user.updated_at = now
            if user.is_active:
                return user, None
            user.is_active = True
            user.updated_at = now
            return user, self._temporary_password(user)
        base = re.sub(r"[^a-z0-9._-]", "", email.split("@", 1)[0].lower()).lstrip("._-")[:60] or "owner"
        if len(base) < 3:
            base = f"{base}-owner"
        subject, suffix = base, 1
        while session.scalar(select(User.id).where(User.auth_subject == subject)):
            suffix += 1
            subject = f"{base}{suffix}"
        user = User(
            id=str(uuid4()), auth_subject=subject, email=email, display_name=member.display_name[:255], role="PROJECT_OWNER",
            password_hash="", mfa_enabled=False, is_active=True, member_id=member.id, created_at=now, updated_at=now,
        )
        password = self._temporary_password(user)
        session.add(user)
        session.flush()
        session.add(AuditEvent(
            id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="user.created",
            entity_type="user", entity_id=user.id, details={"role": user.role, "member_id": str(member.id)}, created_at=now,
        ))
        return user, password

    def reset_password(self, user_id: str, actor_id: str) -> tuple[dict[str, object], str]:
        now = datetime.now(timezone.utc)
        with get_session() as session:
            user = session.get(User, user_id)
            if user is None:
                raise KeyError(user_id)
            if user.role == "CTO":
                raise IdentityError("CTO_ACCOUNT_PROTECTED", "The CTO password is not reset from here")
            password = self._temporary_password(user)
            user.updated_at = now
            self._revoke_api_tokens(session, user.id, now)
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=actor_id, event_type="user.password_reset",
                entity_type="user", entity_id=user.id, details=None, created_at=now,
            ))
            session.commit()
            return self._account(session, user), password

    def change_password(self, subject: str, current_password: str, new_password: str) -> None:
        if len(new_password) < 12:
            raise IdentityError("PASSWORD_TOO_SHORT", "The new password needs at least 12 characters")
        if new_password == current_password:
            raise IdentityError("PASSWORD_UNCHANGED", "The new password must differ from the current one")
        if not self.verify_password(subject, current_password):
            raise IdentityError("PASSWORD_INCORRECT", "The current password is not correct")
        with get_session() as session:
            user = session.scalar(select(User).where(User.auth_subject == subject, User.is_active.is_(True)))
            if user is None:
                raise KeyError(subject)
            salt, digest = self._hash_password(new_password)
            now = datetime.now(timezone.utc)
            user.password_hash = f"{salt}:{digest}"
            user.must_change_password = False
            user.auth_version = int(user.auth_version or 0) + 1
            user.updated_at = now
            self._revoke_api_tokens(session, user.id, now)
            session.add(AuditEvent(
                id=str(uuid4()), actor_type="USER", actor_id=user.id, event_type="user.password_changed",
                entity_type="user", entity_id=user.id, details=None, created_at=now,
            ))
            session.commit()


identity_service = IdentityService()
