"""
routers/deps.py

Shared authentication dependencies.

The token only proves identity (`user_id`); every authorization-relevant
fact -- `is_active`, `is_admin` -- is re-read from the DB on each request.
Tokens live 7 days, so trusting the payload's snapshot would mean a locked
account or a revoked admin keeps working until expiry (Plans.md, "Quyết
định bổ sung từ advisor consult").
"""

from __future__ import annotations

import uuid
from datetime import timezone

from fastapi import Depends, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as DBSession

from db.models import UserORM
from db.session import get_db
from utils.security import AccessTokenError, decode_access_token

# auto_error=False so a missing header is OUR 401 (with a Vietnamese
# message), not FastAPI's default 403.
_bearer = HTTPBearer(auto_error=False)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _authenticate(raw_token: str | None, db: DBSession) -> UserORM:
    """
    The authenticated user for `raw_token`, re-read from the DB.

    Raises 401 for a missing/invalid/expired token, an unknown user id, or
    a locked account (`is_active=false` -- lockout takes effect immediately,
    even for tokens issued before the lock).
    """
    if raw_token is None:
        raise _unauthorized("Chưa đăng nhập.")

    try:
        payload = decode_access_token(raw_token)
        user_id = uuid.UUID(payload["user_id"])
    except (AccessTokenError, KeyError, ValueError) as exc:
        raise _unauthorized("Phiên đăng nhập không hợp lệ hoặc đã hết hạn.") from exc

    user = db.get(UserORM, user_id)
    if user is None:
        raise _unauthorized("Tài khoản không tồn tại.")
    if not user.is_active:
        raise _unauthorized("Tài khoản đã bị khoá.")

    # Tokens minted before the last password change are dead: changing a
    # password is the user's compromise-recovery action, and it must revoke
    # any stolen live session, not just future logins. Both sides are
    # truncated to whole seconds (JWT `iat` is integer seconds), so a token
    # issued within the same second as the change survives -- a deliberate
    # 1-second tolerance, not a bug.
    if user.password_changed_at is not None:
        changed_at = user.password_changed_at
        if changed_at.tzinfo is None:
            # SQLite (tests) returns naive datetimes; values are always
            # written as UTC, so re-attach UTC rather than local time.
            changed_at = changed_at.replace(tzinfo=timezone.utc)
        token_issued_at = int(payload.get("iat", 0))
        if token_issued_at < int(changed_at.timestamp()):
            raise _unauthorized("Phiên đăng nhập đã hết hiệu lực sau khi đổi mật khẩu.")

    return user


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: DBSession = Depends(get_db),
) -> UserORM:
    """The authenticated user for this request, via the `Authorization: Bearer` header."""
    return _authenticate(credentials.credentials if credentials is not None else None, db)


def get_current_user_from_header_or_query(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    token: str | None = Query(
        None, description="Access token, for callers that can't set a header (e.g. <video src>)."
    ),
    db: DBSession = Depends(get_db),
) -> UserORM:
    """
    Same as `get_current_user`, but also accepts the token as a `token`
    query parameter. A plain `<video src>`/`<a href>` is a browser-issued
    GET that never carries a custom `Authorization` header, so
    `routers/self_practice.py`'s video-streaming route -- the one place a
    real `<video>` element points straight at this API -- uses this instead.
    Every other route stays header-only.
    """
    raw_token = credentials.credentials if credentials is not None else token
    return _authenticate(raw_token, db)


def require_admin(current_user: UserORM = Depends(get_current_user)) -> UserORM:
    """
    Admin-only routes. Layers on `get_current_user`, so `is_admin` is the
    same fresh DB read -- an admin flag revoked mid-token-lifetime takes
    effect on the very next request, never waiting for the token to expire.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Yêu cầu quyền quản trị.")
    return current_user
