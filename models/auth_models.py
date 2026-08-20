"""
models/auth_models.py

Request/response schemas for authentication and account administration.

Validation lives here rather than in the routers so the same rules apply to
every caller, and so the OpenAPI schema documents them — which is also how
the browser form gets its rules without them being restated in TypeScript
(the report requires email format and password length to be checked "at both
the browser and the server").

No response model in this file ever carries `password_hash`. That is not a
matter of remembering to leave it out: `UserPublic` lists what goes out, so a
field can only be exposed by someone adding it deliberately.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from db.models import UserRole
from utils.security import BCRYPT_MAX_PASSWORD_BYTES

# Short enough not to be theatre, long enough to matter. The report specifies
# only "check password length"; 8 is the common floor.
MIN_PASSWORD_LENGTH = 8


def _validate_password(value: str) -> str:
    """
    Shared password rule: at least `MIN_PASSWORD_LENGTH` characters, and no
    longer than bcrypt can actually hash.

    The upper bound is in *bytes*, not characters, because that is what bcrypt
    counts. Vietnamese text is multi-byte in UTF-8, so a 40-character
    Vietnamese passphrase can exceed 72 bytes while a 40-character ASCII one
    cannot. Rejecting is the honest option: silently truncating would make two
    different passwords open the same account.
    """
    if len(value) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự.")
    encoded = len(value.encode("utf-8"))
    if encoded > BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Mật khẩu dài {encoded} byte, vượt giới hạn {BCRYPT_MAX_PASSWORD_BYTES} byte. "
            "Ký tự tiếng Việt chiếm nhiều byte hơn ký tự thường, hãy rút ngắn mật khẩu."
        )
    return value


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------


class RegisterRequest(BaseModel):
    """
    Sign-up payload.

    `role` is chosen at registration and the user is admitted immediately —
    the report's flow has no approval queue. `role` cannot name an
    administrator: `UserRole` has no such value, so this endpoint structurally
    cannot mint one.
    """

    email: EmailStr
    password: str = Field(..., description=f"At least {MIN_PASSWORD_LENGTH} characters.")
    full_name: str = Field("", max_length=160)
    role: UserRole = Field(UserRole.LEARNER, description="`learner` or `lecturer`.")
    preferred_language: str = Field("vi", pattern="^(vi|en)$")

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)


class LoginRequest(BaseModel):
    """Sign-in payload."""

    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    """
    Password change.

    The current password is required even though the caller is already
    authenticated: a token left behind on a shared machine should not be
    enough to lock the real owner out of their own account.
    """

    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        return _validate_password(value)


class ChangeRoleRequest(BaseModel):
    """
    Self-service role switch (learner <-> lecturer).

    The report requires the role to be changeable in settings without losing
    data, so this only ever updates the `role` column — nothing that hangs off
    the account is touched.
    """

    role: UserRole


class UpdateProfileRequest(BaseModel):
    """Editable profile fields. Email is not among them — it is the login identity."""

    full_name: str | None = Field(None, max_length=160)
    preferred_language: str | None = Field(None, pattern="^(vi|en)$")


class AdminUpdateUserRequest(BaseModel):
    """
    The changes an administrator may make to another account.

    Every field is optional; only those supplied are applied. `is_admin` is
    absent on purpose — admin rights are granted by CLI only, so a compromised
    administrator session cannot mint further administrators.
    """

    role: UserRole | None = None
    is_verified: bool | None = None
    is_active: bool | None = None


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------


class UserPublic(BaseModel):
    """
    An account as any client may see it.

    The allowlist that keeps `password_hash` from ever reaching a response.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_admin: bool
    is_verified: bool
    is_active: bool
    preferred_language: str
    recording_consent_ack_at: datetime | None = None
    created_at: datetime | None = None
    last_login_at: datetime | None = None

    @property
    def effective_role(self) -> str:
        """How the role reads in the UI, with the admin flag taking precedence."""
        return "admin" if self.is_admin else self.role.value


class TokenResponse(BaseModel):
    """What a successful register/login returns."""

    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    user: UserPublic


class UserListResponse(BaseModel):
    """One page of accounts for the admin screen."""

    total: int = Field(..., description="Total matching accounts, before paging.")
    items: list[UserPublic]


class AdminStatsResponse(BaseModel):
    """Headline counts for the admin dashboard."""

    total_users: int
    active_users: int
    inactive_users: int
    verified_users: int
    learners: int
    lecturers: int
    admins: int
    total_sessions: int
