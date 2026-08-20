"""
utils/security.py

Password hashing and JWT issuing/verification — the two primitives every
authenticated route depends on.

Implements two non-functional requirements from the Project 1 report:

* **NFR-07** — passwords are never stored as plaintext: 100% hashed with
  bcrypt using a per-password random salt.
* **NFR-08** — every business API route requires a valid token: 401 when it
  is missing or invalid, 403 when the role is wrong.

On the bcrypt library choice
----------------------------
The report names `passlib[bcrypt]`. passlib 1.7.4 (its last release, 2020)
crashes against bcrypt 5.x — it reads `bcrypt.__about__`, removed in bcrypt
4.1 — so it cannot hash a password at all in this environment. Pinning
bcrypt back below 4.1 to keep an unmaintained wrapper alive is the wrong
trade for the one component whose job is security, so this module calls the
maintained `bcrypt` package directly. The requirement (NFR-07: bcrypt,
random per-password salt) is met exactly; only the wrapper differs.

The 72-byte limit
-----------------
bcrypt hashes at most 72 bytes and, since 5.0, raises rather than silently
truncating. A silent truncation would mean two different long passwords
hashing identically, so passwords are validated against this limit at the
schema layer (`models/auth_models.py`) and re-checked here. Note the limit
is in *bytes*, not characters: Vietnamese text is multi-byte in UTF-8, so
"mật khẩu rất dài" runs out of budget sooner than an ASCII password of the
same length.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Final

import bcrypt
from jose import JWTError, jwt

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# bcrypt ignores everything past this many bytes of the password.
BCRYPT_MAX_PASSWORD_BYTES: Final[int] = 72

# Work factor. 12 is the current common default: roughly a quarter second per
# hash on ordinary hardware, which is slow enough to make offline guessing
# expensive and fast enough not to be felt on login.
BCRYPT_ROUNDS: Final[int] = 12

# `sub` carries the user id; `typ` distinguishes token kinds so an access
# token can never be replayed where another kind is expected.
TOKEN_TYPE_ACCESS: Final[str] = "access"


class TokenError(Exception):
    """Raised when a token is missing, malformed, expired, or of the wrong type."""


class PasswordTooLongError(ValueError):
    """Raised when a password exceeds what bcrypt can actually hash."""


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """
    Hash a plaintext password with bcrypt and a fresh random salt.

    Args:
        password: The plaintext password.

    Returns:
        The bcrypt hash, salt included, as stored in `users.password_hash`.

    Raises:
        PasswordTooLongError: If the password exceeds 72 bytes in UTF-8.
    """
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
        raise PasswordTooLongError(
            f"Mật khẩu dài {len(encoded)} byte, vượt giới hạn {BCRYPT_MAX_PASSWORD_BYTES} byte của bcrypt."
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """
    Check a plaintext password against a stored hash.

    Never raises on bad input — a malformed hash in the database is a failed
    login, not a 500. Returns False for every failure mode so callers cannot
    accidentally treat "the hash was corrupt" as "the password was right".
    """
    try:
        encoded = password.encode("utf-8")
        if len(encoded) > BCRYPT_MAX_PASSWORD_BYTES:
            return False
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        logger.warning("Password verification failed against a malformed hash: %s", exc)
        return False


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: uuid.UUID | str,
    *,
    role: str,
    is_admin: bool,
    expires_minutes: int | None = None,
) -> str:
    """
    Issue a signed access token.

    `role` and `is_admin` ride along so an authorization check costs no
    database round trip. The trade is that a role change does not take effect
    until the token is re-issued; `expires_minutes` bounds that staleness,
    and anything irreversible (deactivating an account) is re-checked against
    the database on every request — see `routers/dependencies.py`.

    Args:
        user_id: The account the token identifies.
        role: `learner` or `lecturer`.
        is_admin: Whether the account carries the separate admin flag.
        expires_minutes: Lifetime override; defaults to `JWT_EXPIRE_MINUTES`.

    Returns:
        The encoded JWT.
    """
    lifetime = expires_minutes if expires_minutes is not None else settings.JWT_EXPIRE_MINUTES
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "role": role,
        "is_admin": is_admin,
        "typ": TOKEN_TYPE_ACCESS,
        "iat": now,
        "exp": now + timedelta(minutes=lifetime),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Verify a token's signature and expiry and return its claims.

    Args:
        token: The raw JWT from the `Authorization: Bearer` header.

    Returns:
        The decoded claims.

    Raises:
        TokenError: If the signature is invalid, the token has expired, it is
            not an access token, or `sub` is not a usable user id.
    """
    try:
        claims = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise TokenError(f"Mã thông báo không hợp lệ hoặc đã hết hạn: {exc}") from exc

    if claims.get("typ") != TOKEN_TYPE_ACCESS:
        raise TokenError("Mã thông báo không phải loại access.")

    subject = claims.get("sub")
    if not subject:
        raise TokenError("Mã thông báo thiếu trường `sub`.")
    try:
        uuid.UUID(str(subject))
    except ValueError as exc:
        raise TokenError("Trường `sub` trong mã thông báo không phải UUID hợp lệ.") from exc

    return claims


def token_subject(token: str) -> uuid.UUID:
    """The user id a token identifies, after full verification."""
    return uuid.UUID(str(decode_access_token(token)["sub"]))
