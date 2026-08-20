"""
routers/dependencies.py

The shared authentication and role dependencies every protected route hangs
off. One implementation, so "who may call this?" is answered the same way
everywhere instead of being re-derived per router.

Implements NFR-08 from the Project 1 report — every business route requires a
valid token, **401 when it is missing or invalid, 403 when the role is
wrong** — and gives NFR-09 ("users may only reach their own sessions, checked
in the business layer, not just in the UI") its enforcement point in
`assert_can_access_session`.

The role ladder mirrors the report's actors, each inheriting the one below:

    Khach vang lai   ->  no token at all
    Nguoi hoc        ->  require_user
    Giang vien       ->  require_lecturer
    Quan tri vien    ->  require_admin

Why the database is re-read on every request
--------------------------------------------
The token already carries `role` and `is_admin`, so authorization could be
decided from the token alone with no query. It is not, because a token
outlives the decision that issued it: an administrator who deactivates an
abusive account would otherwise have to wait out that account's token
lifetime, and "banned" that takes twelve hours to mean anything is not
banned. The account is re-read and `is_active` re-checked every time, so
deactivation takes effect on the next request.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession

from db.models import AnalysisSession, UserORM, UserRole
from db.session import get_db
from utils.logger import get_logger
from utils.security import TokenError, decode_access_token

logger = get_logger(__name__)

# auto_error=False so a missing header reaches our own handler and produces
# the report's 401 with a Vietnamese message, rather than FastAPI's default
# 403 for absent credentials -- which would be the wrong code entirely.
_bearer = HTTPBearer(auto_error=False, description="JWT cấp khi đăng nhập.")

CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
DbDep = Annotated[DBSession, Depends(get_db)]


def _unauthorized(detail: str) -> HTTPException:
    """401: caller has not proven who they are."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> HTTPException:
    """403: caller is known, but not allowed."""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def get_current_user(credentials: CredentialsDep, db: DbDep) -> UserORM:
    """
    Resolve the caller from the `Authorization: Bearer` header.

    Returns:
        The `UserORM` for the token's subject.

    Raises:
        HTTPException: 401 if the header is missing, the token does not
            verify, the account no longer exists, or it has been deactivated.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Yêu cầu này cần đăng nhập.")

    try:
        claims = decode_access_token(credentials.credentials)
    except TokenError as exc:
        raise _unauthorized(str(exc)) from exc

    user = db.get(UserORM, uuid.UUID(str(claims["sub"])))
    if user is None:
        # The account was deleted after the token was issued. 401, not 404:
        # the caller has failed to prove they are anyone, and confirming which
        # ids once existed would leak information to an unauthenticated caller.
        raise _unauthorized("Tài khoản trong mã thông báo không còn tồn tại.")

    if not user.is_active:
        # 403, not 401: we know exactly who this is, they simply may not in.
        # Re-issuing a token would not help, so telling them to log in again
        # would be a lie.
        raise _forbidden("Tài khoản đã bị khoá. Liên hệ quản trị viên để mở khoá.")

    return user


CurrentUser = Annotated[UserORM, Depends(get_current_user)]


def require_user(user: CurrentUser) -> UserORM:
    """Any signed-in account (AC-02 Nguoi hoc and upward)."""
    return user


def require_lecturer(user: CurrentUser) -> UserORM:
    """
    Lecturer or administrator (AC-03 and upward).

    Rows 9 and 10 of the permission matrix: viewing other learners' reports
    and adjusting scoring weights.
    """
    if not (user.is_admin or user.role is UserRole.LECTURER):
        raise _forbidden("Chức năng này dành cho giảng viên.")
    return user


def require_admin(user: CurrentUser) -> UserORM:
    """
    Administrator only (AC-04).

    Rows 11 through 15: account management, resource catalog, RAG knowledge
    base, failed sessions, AI provider configuration.
    """
    if not user.is_admin:
        raise _forbidden("Chức năng này dành cho quản trị viên.")
    return user


CurrentLecturer = Annotated[UserORM, Depends(require_lecturer)]
CurrentAdmin = Annotated[UserORM, Depends(require_admin)]


def get_optional_user(credentials: CredentialsDep, db: DbDep) -> UserORM | None:
    """
    The caller if they presented a usable token, otherwise `None`.

    For routes a guest may reach but which behave differently when signed in.
    Never raises: an invalid token is treated as no token, because the point
    of these routes is that not being signed in is allowed.
    """
    if credentials is None or not credentials.credentials:
        return None
    try:
        claims = decode_access_token(credentials.credentials)
    except TokenError:
        return None
    user = db.get(UserORM, uuid.UUID(str(claims["sub"])))
    return user if user is not None and user.is_active else None


OptionalUser = Annotated[UserORM | None, Depends(get_optional_user)]


def assert_can_access_session(session: AnalysisSession, user: UserORM) -> None:
    """
    NFR-09's enforcement point: may `user` read this session?

    Allowed for the owner, for any lecturer (matrix row 9), and for
    administrators. Unowned sessions — those created before accounts existed —
    stay readable, since refusing them would strand existing history behind an
    ownership check it can never satisfy.

    Raises:
        HTTPException: 403 when the session belongs to someone else.
    """
    if session.user_id is None:
        return
    if session.user_id == user.id:
        return
    if user.is_admin or user.role is UserRole.LECTURER:
        return
    logger.warning(
        "User %s was refused access to session %s owned by %s.",
        user.id,
        session.id,
        session.user_id,
    )
    raise _forbidden("Bạn chỉ xem được phiên của chính mình.")
