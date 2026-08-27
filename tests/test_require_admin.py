"""
Tests for routers/deps.py::require_admin (Nhóm B, Task 12 / Plans.md B3).

Exercised through a throwaway route mounted on the app's own DB-override
plumbing -- require_admin has no route of its own yet (B6's admin router
adds the first real caller), but the dependency must work standalone.
Written before require_admin exists (TDD Red).
"""

from __future__ import annotations

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.session import get_db
from routers.deps import require_admin

_PROBE_PATH = "/__test-admin-only"


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

    @app_module.app.get(_PROBE_PATH)
    def _admin_only_probe(user=Depends(require_admin)):
        return {"ok": True, "user_id": str(user.id)}

    with TestClient(app_module.app) as test_client:
        yield test_client

    app_module.app.dependency_overrides.clear()
    app_module.app.router.routes = [
        r for r in app_module.app.router.routes if getattr(r, "path", None) != _PROBE_PATH
    ]


def _register(client: TestClient, email="an@example.com", password="matkhau-du-dai", full_name="An"):
    return client.post("/auth/register", json={"email": email, "password": password, "full_name": full_name})


def _set_is_admin(client: TestClient, email: str, is_admin: bool) -> None:
    import app as app_module
    from db.models import UserORM

    override = app_module.app.dependency_overrides[get_db]
    db = next(override())
    user = db.query(UserORM).filter(UserORM.email == email).one()
    user.is_admin = is_admin
    db.commit()


class TestRequireAdmin:
    def test_no_token_is_401(self, client):
        resp = client.get(_PROBE_PATH)
        assert resp.status_code == 401

    def test_non_admin_token_is_403(self, client):
        token = _register(client).json()["access_token"]
        resp = client.get(_PROBE_PATH, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_admin_account_is_200(self, client):
        token = _register(client).json()["access_token"]
        _set_is_admin(client, "an@example.com", True)

        resp = client.get(_PROBE_PATH, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_admin_flag_revoked_mid_token_lifetime_takes_effect_immediately(self, client):
        """
        The token's is_admin claim is only an issue-time snapshot (it was
        False at registration and is never reissued here) -- require_admin
        must re-read is_admin from the DB on every call, not trust it.
        """
        token = _register(client).json()["access_token"]
        _set_is_admin(client, "an@example.com", True)
        assert client.get(_PROBE_PATH, headers={"Authorization": f"Bearer {token}"}).status_code == 200

        _set_is_admin(client, "an@example.com", False)
        resp = client.get(_PROBE_PATH, headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403
