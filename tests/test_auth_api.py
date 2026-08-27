"""
End-to-end tests for routers/auth.py (Nhóm B, Task 11 / Plans.md B2), via
FastAPI's TestClient against in-memory SQLite -- same DB-override pattern as
tests/test_self_practice_api.py. Written before the router exists (TDD Red).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.session import get_db
from utils.security import decode_access_token


@pytest.fixture()
def client():
    import app as app_module

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=pool.StaticPool
    )
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app_module.app.dependency_overrides[get_db] = override_get_db
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def _register(client: TestClient, email="an@example.com", password="matkhau-du-dai", full_name="An"):
    return client.post(
        "/auth/register", json={"email": email, "password": password, "full_name": full_name}
    )


class TestRegister:
    def test_register_returns_a_usable_token_immediately(self, client):
        """No approval queue, no verification step -- the token works right away."""
        resp = _register(client)
        assert resp.status_code == 201
        body = resp.json()
        payload = decode_access_token(body["access_token"])
        assert payload["user_id"] == body["user"]["id"]
        assert body["user"]["email"] == "an@example.com"
        assert body["user"]["is_admin"] is False

    def test_duplicate_email_is_409(self, client):
        assert _register(client).status_code == 201
        assert _register(client).status_code == 409

    def test_duplicate_email_check_is_case_insensitive(self, client):
        assert _register(client, email="An@Example.com").status_code == 201
        assert _register(client, email="an@example.com").status_code == 409

    def test_email_is_stored_lowercased(self, client):
        resp = _register(client, email="An@Example.Com")
        assert resp.json()["user"]["email"] == "an@example.com"

    def test_invalid_email_format_is_422(self, client):
        assert _register(client, email="khong-phai-email").status_code == 422

    def test_password_shorter_than_8_chars_is_422(self, client):
        assert _register(client, password="ngan").status_code == 422


class TestLogin:
    def test_login_with_correct_credentials_returns_token(self, client):
        _register(client)
        resp = client.post("/auth/login", json={"email": "an@example.com", "password": "matkhau-du-dai"})
        assert resp.status_code == 200
        assert decode_access_token(resp.json()["access_token"])["user_id"]

    def test_login_email_match_is_case_insensitive(self, client):
        _register(client, email="an@example.com")
        resp = client.post("/auth/login", json={"email": "AN@EXAMPLE.COM", "password": "matkhau-du-dai"})
        assert resp.status_code == 200

    def test_wrong_password_is_401(self, client):
        _register(client)
        resp = client.post("/auth/login", json={"email": "an@example.com", "password": "sai-mat-khau"})
        assert resp.status_code == 401

    def test_unknown_email_is_401_not_404(self, client):
        """404 would leak which emails have accounts."""
        resp = client.post("/auth/login", json={"email": "ma@example.com", "password": "matkhau-du-dai"})
        assert resp.status_code == 401

    def test_login_updates_last_login_at(self, client):
        _register(client)
        client.post("/auth/login", json={"email": "an@example.com", "password": "matkhau-du-dai"})
        # Read back through the app's own DB session override.
        import app as app_module
        from db.models import UserORM
        from db.session import get_db as real_get_db

        override = app_module.app.dependency_overrides[real_get_db]
        db = next(override())
        user = db.query(UserORM).filter(UserORM.email == "an@example.com").one()
        assert user.last_login_at is not None


class TestChangePassword:
    def _token(self, client) -> str:
        return _register(client).json()["access_token"]

    def test_requires_authentication(self, client):
        resp = client.post(
            "/auth/change-password",
            json={"old_password": "matkhau-du-dai", "new_password": "mat-khau-moi-dai"},
        )
        assert resp.status_code == 401

    def test_wrong_old_password_is_401(self, client):
        token = self._token(client)
        resp = client.post(
            "/auth/change-password",
            json={"old_password": "sai-mat-khau", "new_password": "mat-khau-moi-dai"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 401

    def test_correct_old_password_changes_it_for_real(self, client):
        token = self._token(client)
        resp = client.post(
            "/auth/change-password",
            json={"old_password": "matkhau-du-dai", "new_password": "mat-khau-moi-dai"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200

        # The old password no longer logs in; the new one does.
        old = client.post("/auth/login", json={"email": "an@example.com", "password": "matkhau-du-dai"})
        assert old.status_code == 401
        new = client.post("/auth/login", json={"email": "an@example.com", "password": "mat-khau-moi-dai"})
        assert new.status_code == 200

    def test_new_password_shorter_than_8_chars_is_422(self, client):
        token = self._token(client)
        resp = client.post(
            "/auth/change-password",
            json={"old_password": "matkhau-du-dai", "new_password": "ngan"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422

    def test_a_garbage_token_is_401(self, client):
        resp = client.post(
            "/auth/change-password",
            json={"old_password": "matkhau-du-dai", "new_password": "mat-khau-moi-dai"},
            headers={"Authorization": "Bearer khong-phai-token"},
        )
        assert resp.status_code == 401


class TestPasswordChangeRevokesOldTokens:
    """
    Changing a password is the compromise-recovery action: any token minted
    before the change (i.e. one an attacker may hold) must stop working
    immediately, not at its 7-day expiry.
    """

    def test_a_token_issued_before_the_change_is_rejected_after_it(self, client):
        old_token = _register(client).json()["access_token"]

        # Mint the pre-change token 10 minutes in the past, so the whole-second
        # comparison in routers/deps.py unambiguously sees iat < changed_at.
        import utils.security as security
        from datetime import datetime, timedelta, timezone

        real_now = datetime.now(timezone.utc)
        stolen_payload_time = real_now - timedelta(minutes=10)
        stolen_token = security.jwt.encode(
            {
                "user_id": security.decode_access_token(old_token)["user_id"],
                "is_admin": False,
                "iat": stolen_payload_time,
                "exp": real_now + timedelta(days=7),
            },
            __import__("config").settings.JWT_SECRET_KEY,
            algorithm="HS256",
        )

        change = client.post(
            "/auth/change-password",
            json={"old_password": "matkhau-du-dai", "new_password": "mat-khau-moi-dai"},
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert change.status_code == 200

        # The stolen (pre-change) token is dead on an authenticated endpoint.
        reuse = client.post(
            "/auth/change-password",
            json={"old_password": "mat-khau-moi-dai", "new_password": "mat-khau-moi-hon"},
            headers={"Authorization": f"Bearer {stolen_token}"},
        )
        assert reuse.status_code == 401

    def test_change_password_returns_a_fresh_token_that_works_immediately(self, client):
        old_token = _register(client).json()["access_token"]
        change = client.post(
            "/auth/change-password",
            json={"old_password": "matkhau-du-dai", "new_password": "mat-khau-moi-dai"},
            headers={"Authorization": f"Bearer {old_token}"},
        )
        assert change.status_code == 200
        fresh = change.json()["access_token"]

        # The fresh token authenticates right away -- the legitimate user is
        # not logged out by their own password change.
        again = client.post(
            "/auth/change-password",
            json={"old_password": "mat-khau-moi-dai", "new_password": "mat-khau-moi-hon"},
            headers={"Authorization": f"Bearer {fresh}"},
        )
        assert again.status_code == 200
