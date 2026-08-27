"""
Unit tests for utils/security.py (Nhóm B, Task 10): password hashing and JWT
issue/verify. Written before the module exists (TDD Red) -- see Plans.md B1.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


class TestPasswordHashing:
    def test_hashing_the_same_password_twice_gives_different_hashes(self) -> None:
        """Per-password salt (bcrypt.gensalt()), not a single pepper reused everywhere."""
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")
        assert first != second

    def test_the_hash_never_contains_the_plaintext_password(self) -> None:
        password = "correct horse battery staple"
        assert password not in hash_password(password)

    def test_verify_accepts_the_correct_password(self) -> None:
        password = "correct horse battery staple"
        assert verify_password(password, hash_password(password)) is True

    def test_verify_rejects_a_wrong_password(self) -> None:
        assert verify_password("wrong password", hash_password("correct horse battery staple")) is False

    def test_a_password_over_72_utf8_bytes_is_rejected_loudly(self) -> None:
        """
        bcrypt silently truncates input beyond 72 bytes -- two different
        long passwords sharing the first 72 bytes would verify as equal.
        Refusing loudly is correct; truncating silently is a bug.
        """
        with pytest.raises(ValueError):
            hash_password("x" * 73)

    def test_a_multibyte_password_is_measured_in_bytes_not_characters(self) -> None:
        # 25 chars x 3 bytes each = 75 bytes > 72, even though len() is only 25.
        with pytest.raises(ValueError):
            hash_password("ằ" * 25)


class TestJWT:
    def test_a_freshly_issued_token_decodes_back_to_the_same_user(self) -> None:
        token = create_access_token(user_id="u1", is_admin=False)
        payload = decode_access_token(token)
        assert payload["user_id"] == "u1"
        assert payload["is_admin"] is False

    def test_is_admin_is_carried_in_the_token(self) -> None:
        token = create_access_token(user_id="u1", is_admin=True)
        assert decode_access_token(token)["is_admin"] is True

    def test_an_expired_token_is_rejected(self) -> None:
        token = create_access_token(user_id="u1", is_admin=False, expires_delta=timedelta(seconds=-1))
        with pytest.raises(Exception):
            decode_access_token(token)

    def test_a_token_signed_with_a_different_secret_is_rejected(self) -> None:
        import jwt as pyjwt

        forged = pyjwt.encode({"user_id": "u1", "is_admin": True}, "wrong-secret", algorithm="HS256")
        with pytest.raises(Exception):
            decode_access_token(forged)

    def test_a_malformed_token_is_rejected(self) -> None:
        with pytest.raises(Exception):
            decode_access_token("not-a-real-token")

    def test_an_unset_secret_fails_loudly_instead_of_signing_insecurely(self, monkeypatch) -> None:
        from config import settings
        from utils.security import SecurityConfigurationError

        monkeypatch.setattr(settings, "JWT_SECRET_KEY", "")
        with pytest.raises(SecurityConfigurationError):
            create_access_token(user_id="u1", is_admin=False)
        with pytest.raises(SecurityConfigurationError):
            decode_access_token("anything")
