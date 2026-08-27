"""
End-to-end tests for routers/admin.py (Nhóm B, Task 13 / Plans.md B6):
list users, lock/unlock via `is_active`. There is no delete -- locking is
the removal mechanism, so a locked account's practice-session history must
survive. Written before routers/admin.py exists (TDD Red).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import SelfPracticeSessionORM, SelfPracticeState, UserORM
from db.session import get_db


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


def _register(client: TestClient, email="an@example.com", password="matkhau-du-dai", full_name="An") -> str:
    resp = client.post("/auth/register", json={"email": email, "password": password, "full_name": full_name})
    assert resp.status_code == 201
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _db_session(client: TestClient):
    import app as app_module

    override = app_module.app.dependency_overrides[get_db]
    return next(override())


def _make_admin(client: TestClient, email: str) -> None:
    db = _db_session(client)
    user = db.query(UserORM).filter(UserORM.email == email).one()
    user.is_admin = True
    db.commit()


def _user_id(client: TestClient, email: str) -> str:
    db = _db_session(client)
    return str(db.query(UserORM).filter(UserORM.email == email).one().id)


class TestListUsers:
    def test_non_admin_is_403(self, client):
        token = _register(client)
        resp = client.get("/admin/users", headers=_auth(token))
        assert resp.status_code == 403

    def test_no_token_is_401(self, client):
        resp = client.get("/admin/users")
        assert resp.status_code == 401

    def test_admin_sees_every_account_with_is_active(self, client):
        _register(client, email="a@example.com")
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")

        resp = client.get("/admin/users", headers=_auth(admin_token))
        assert resp.status_code == 200
        emails = {row["email"]: row["is_active"] for row in resp.json()}
        assert emails == {"a@example.com": True, "admin@example.com": True}


class TestLockUnlockUser:
    def test_non_admin_cannot_lock_anyone(self, client):
        _register(client, email="a@example.com")
        other_token = _register(client, email="b@example.com")
        target_id = _user_id(client, "a@example.com")

        resp = client.patch(
            f"/admin/users/{target_id}", json={"is_active": False}, headers=_auth(other_token)
        )
        assert resp.status_code == 403

    def test_locking_an_unknown_user_is_404(self, client):
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")

        resp = client.patch(
            "/admin/users/00000000-0000-0000-0000-000000000000",
            json={"is_active": False},
            headers=_auth(admin_token),
        )
        assert resp.status_code == 404

    def test_locked_account_cannot_log_in(self, client):
        _register(client, email="a@example.com", password="matkhau-du-dai")
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")
        target_id = _user_id(client, "a@example.com")

        lock_resp = client.patch(
            f"/admin/users/{target_id}", json={"is_active": False}, headers=_auth(admin_token)
        )
        assert lock_resp.status_code == 200
        assert lock_resp.json()["is_active"] is False

        login_resp = client.post(
            "/auth/login", json={"email": "a@example.com", "password": "matkhau-du-dai"}
        )
        assert login_resp.status_code == 401
        assert "khoá" in login_resp.json()["detail"]

    def test_a_token_issued_before_the_lock_is_rejected_immediately(self, client):
        """
        The lock must take effect on the very next request, not wait for the
        7-day token to expire -- get_current_user re-reads is_active from
        the DB every time (routers/deps.py), so this must already hold; this
        test proves the admin endpoint doesn't accidentally bypass it.
        """
        stolen_token = _register(client, email="a@example.com")
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")
        target_id = _user_id(client, "a@example.com")

        client.patch(f"/admin/users/{target_id}", json={"is_active": False}, headers=_auth(admin_token))

        resp = client.get("/self-practice", headers=_auth(stolen_token))
        assert resp.status_code == 401

    def test_unlocking_restores_login(self, client):
        _register(client, email="a@example.com", password="matkhau-du-dai")
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")
        target_id = _user_id(client, "a@example.com")

        client.patch(f"/admin/users/{target_id}", json={"is_active": False}, headers=_auth(admin_token))
        unlock_resp = client.patch(
            f"/admin/users/{target_id}", json={"is_active": True}, headers=_auth(admin_token)
        )
        assert unlock_resp.status_code == 200
        assert unlock_resp.json()["is_active"] is True

        login_resp = client.post(
            "/auth/login", json={"email": "a@example.com", "password": "matkhau-du-dai"}
        )
        assert login_resp.status_code == 200

    def test_locking_never_deletes_the_account_s_session_history(self, client):
        import uuid as uuid_module

        _register(client, email="a@example.com")
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")
        target_id = _user_id(client, "a@example.com")

        db = _db_session(client)
        db.add(
            SelfPracticeSessionORM(
                profile="presentation_solo",
                video_file_path="/tmp/does-not-matter.mp4",
                state=SelfPracticeState.COMPLETED,
                user_id=uuid_module.UUID(target_id),
            )
        )
        db.commit()

        client.patch(f"/admin/users/{target_id}", json={"is_active": False}, headers=_auth(admin_token))

        remaining = _db_session(client).query(SelfPracticeSessionORM).count()
        assert remaining == 1
