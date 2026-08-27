"""
utils/security.py

Password hashing and access tokens for the account system (Nhóm B).

Password hashing is bcrypt with a per-password salt (`bcrypt.gensalt()` on
every call) -- hashing the same password twice yields two different strings,
and verification reads the salt back out of the stored hash. Inputs longer
than bcrypt's hard 72-byte limit are REJECTED, not silently truncated:
truncation would make two different long passwords verify as equal, which is
strictly worse than telling the user to pick a shorter password.

Access tokens are JWTs signed HS256 with `settings.JWT_SECRET_KEY`. The
secret has no default: the first call to issue or verify a token with the
secret unset raises, rather than signing with a guessable value. Decoding
pins `algorithms=["HS256"]` explicitly -- never trust the token's own header
to choose the algorithm.

The token payload carries `user_id` and `is_admin`, but `is_admin` is only a
snapshot from issue time (tokens live 7 days). Authorization decisions --
admin checks, `is_active` lockout -- must re-read the user row from the DB
by `user_id` on every request; the token only proves identity. See Plans.md,
"Quyết định bổ sung từ advisor consult".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from config import settings

# bcrypt ignores every byte past this hard limit; see module docstring for
# why exceeding it is an error rather than a truncation.
_BCRYPT_MAX_PASSWORD_BYTES = 72

_JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_LIFETIME = timedelta(days=7)


class SecurityConfigurationError(RuntimeError):
    """Raised when token operations are attempted with no JWT secret configured."""


class AccessTokenError(ValueError):
    """
    Raised when a token is expired, malformed, or signed with the wrong key.

    Named distinctly from `jwt.exceptions.InvalidTokenError` on purpose --
    the two would otherwise be easy to confuse in a module that imports
    `jwt` alongside this one.
    """


def _require_secret() -> str:
    secret = settings.JWT_SECRET_KEY
    if not secret:
        raise SecurityConfigurationError(
            "JWT_SECRET_KEY is not set. Add it to .env (see .env.example) -- refusing "
            "to sign or verify tokens with an empty secret."
        )
    return secret


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """
    Hash a password with bcrypt and a fresh per-password salt.

    Raises:
        ValueError: If the password exceeds bcrypt's 72-byte limit (measured
            in UTF-8 bytes, not characters -- Vietnamese text can hit the
            limit well under 72 characters).
    """
    encoded = password.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_PASSWORD_BYTES:
        raise ValueError(
            f"Mật khẩu dài quá {_BCRYPT_MAX_PASSWORD_BYTES} byte (giới hạn của bcrypt); "
            "vui lòng dùng mật khẩu ngắn hơn."
        )
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Whether `password` matches `password_hash`. Never raises on a wrong password."""
    encoded = password.encode("utf-8")
    if len(encoded) > _BCRYPT_MAX_PASSWORD_BYTES:
        # A password this long could never have been stored by hash_password,
        # so it cannot match anything.
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("utf-8"))
    except ValueError:
        # Malformed stored hash (e.g. corrupted row) -- treat as no match.
        return False


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


def create_access_token(
    user_id: str, is_admin: bool, expires_delta: timedelta | None = None
) -> str:
    """
    Issue a signed access token for a user.

    Args:
        user_id: The user's id, as a string.
        is_admin: Snapshot of the admin flag at issue time (informational --
            see module docstring; never authorize from this alone).
        expires_delta: Override the default 7-day lifetime (tests use a
            negative delta to mint an already-expired token).
    """
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user_id,
        "is_admin": is_admin,
        "iat": now,
        "exp": now + (expires_delta if expires_delta is not None else ACCESS_TOKEN_LIFETIME),
    }
    return jwt.encode(payload, _require_secret(), algorithm=_JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """
    Verify a token's signature and expiry, returning its payload.

    Raises:
        AccessTokenError: If the token is expired, malformed, or not signed
            with this server's secret.
        SecurityConfigurationError: If no JWT secret is configured.
    """
    try:
        return jwt.decode(token, _require_secret(), algorithms=[_JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise AccessTokenError(f"Token không hợp lệ: {exc}") from exc
