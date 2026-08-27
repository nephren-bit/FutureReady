"""
routers/auth.py

The Auth API (Nhóm B Task 11 / Plans.md B2): register, login, change
password.

Registration is immediate -- no approval queue, no verification step, no
role selection (specs/in-class-analysis/plan.md, "Đăng ký, đăng nhập và
phân quyền"). Emails are lowercased before storing and matching, with the
`lower(email)` unique index as the DB-level backstop.

Login failures for a wrong password and an unknown email are the same 401
with the same message, so the endpoint doesn't leak which emails have
accounts. A locked account (`is_active=false`) gets a DIFFERENT message --
the user should know they're locked out, not think they mistyped.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession

from db.models import UserORM
from db.session import get_db
from models.auth_models import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from models.responses import ErrorResponse
from routers.deps import get_current_user
from utils.security import create_access_token, hash_password, verify_password
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

_ERROR_RESPONSES = {401: {"model": ErrorResponse}, 409: {"model": ErrorResponse}}

_BAD_CREDENTIALS = "Email hoặc mật khẩu không đúng."

# Burned on login attempts against unknown emails, so the "no such account"
# path pays the same bcrypt cost as "wrong password" -- without this, the
# response-time difference would leak which emails have accounts even though
# the 401 message is identical. Computed once at import.
_TIMING_EQUALIZER_HASH = hash_password("timing-equalizer-not-a-real-account")


def _find_by_email(db: DBSession, email: str) -> UserORM | None:
    """Case-insensitive lookup; `email` may arrive in any casing."""
    return db.query(UserORM).filter(func.lower(UserORM.email) == email.lower()).one_or_none()


def _token_response(user: UserORM) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id=str(user.id), is_admin=user.is_admin),
        user=UserResponse.from_orm_user(user),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
    summary="Register a new account. Usable immediately -- no approval queue.",
)
async def register(body: RegisterRequest, db: DBSession = Depends(get_db)) -> TokenResponse:
    email = body.email.lower()
    if _find_by_email(db, email) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email này đã được đăng ký.")

    user = UserORM(
        email=email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        last_login_at=datetime.now(timezone.utc),  # registering IS the first login
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Two concurrent registrations of the same email: the find-then-insert
        # pre-check above can't see the other transaction, but the
        # lower(email) unique index can. Same 409 as the pre-check path.
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email này đã được đăng ký.")
    db.refresh(user)
    logger.info("New account registered: user_id=%s", user.id)
    return _token_response(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    responses=_ERROR_RESPONSES,
    summary="Log in with email and password.",
)
async def login(body: LoginRequest, db: DBSession = Depends(get_db)) -> TokenResponse:
    user = _find_by_email(db, body.email)
    if user is None:
        # Same 401 AND the same bcrypt cost as the wrong-password path --
        # see _TIMING_EQUALIZER_HASH.
        verify_password(body.password, _TIMING_EQUALIZER_HASH)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_BAD_CREDENTIALS)
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=_BAD_CREDENTIALS)
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Tài khoản đã bị khoá.")

    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(user)
    return _token_response(user)


@router.post(
    "/change-password",
    response_model=TokenResponse,
    responses=_ERROR_RESPONSES,
    summary=(
        "Change the current user's password (requires the old one). Revokes every "
        "previously-issued token and returns a fresh one."
    ),
)
async def change_password(
    body: ChangePasswordRequest,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> TokenResponse:
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Mật khẩu cũ không đúng.")

    current_user.password_hash = hash_password(body.new_password)
    # Kills every token issued before this instant (routers/deps.py checks
    # iat against it) -- changing a password is the compromise-recovery
    # action, so a stolen live session must die with the old password. The
    # fresh token below is what keeps the LEGITIMATE user logged in.
    current_user.password_changed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(current_user)
    logger.info("Password changed: user_id=%s", current_user.id)
    return _token_response(current_user)
