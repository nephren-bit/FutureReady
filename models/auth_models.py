"""
models/auth_models.py

Pydantic request/response schemas for the Auth API (`routers/auth.py`,
Nhóm B Task 11 / Plans.md B2).

Validation lives here (server-side) AND in the frontend forms (B5) -- the
Pydantic layer is the one that counts; the frontend copy only exists so the
user gets feedback before a round-trip.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from db.models import UserORM

# One number, used by register and change-password alike, and mirrored by
# the frontend form (B5). Length only -- composition rules (digits/symbols)
# push people toward reused short passwords, not stronger ones.
MIN_PASSWORD_LENGTH = 8


class RegisterRequest(BaseModel):
    """Body for `POST /auth/register`."""

    email: EmailStr
    password: str = Field(..., min_length=MIN_PASSWORD_LENGTH)
    full_name: str = Field("", max_length=255)


class LoginRequest(BaseModel):
    """Body for `POST /auth/login`."""

    email: EmailStr
    password: str


class ChangePasswordRequest(BaseModel):
    """Body for `POST /auth/change-password`."""

    old_password: str
    new_password: str = Field(..., min_length=MIN_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    """A user as returned to the client -- never includes the password hash."""

    id: uuid.UUID
    email: str
    full_name: str
    is_admin: bool
    created_at: datetime

    @classmethod
    def from_orm_user(cls, user: UserORM) -> "UserResponse":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_admin=user.is_admin,
            created_at=user.created_at,
        )


class TokenResponse(BaseModel):
    """Response for register and login: a bearer token plus the user it belongs to."""

    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class AdminUserResponse(BaseModel):
    """
    A user as returned by the admin API (`routers/admin.py`, Plans.md B6).
    Unlike `UserResponse`, includes `is_active` -- the only field an admin
    can change, and the reason they're looking at this list at all.
    """

    id: uuid.UUID
    email: str
    full_name: str
    is_admin: bool
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None

    @classmethod
    def from_orm_user(cls, user: UserORM) -> "AdminUserResponse":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            is_admin=user.is_admin,
            is_active=user.is_active,
            created_at=user.created_at,
            last_login_at=user.last_login_at,
        )


class AdminSetUserActiveRequest(BaseModel):
    """
    Body for `PATCH /admin/users/{id}`. `is_active` is the only field an
    admin can change here -- there is no delete; locking is the removal
    mechanism (rows, and the practice-session history they own, are never
    deleted).
    """

    is_active: bool
