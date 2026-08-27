"""
End-to-end tests for routers/quality.py (Nhom B Task 14 / Nhom C Task 18):
admin-only gating and response shape. The number-crunching itself is
covered by tests/test_quality_tracking.py against the service directly.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker
import pytest

from db.base import Base
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


def _register(client: TestClient, email="an@example.com", password="matkhau-du-dai") -> str:
    resp = client.post("/auth/register", json={"email": email, "password": password, "full_name": "An"})
    assert resp.status_code == 201
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(client: TestClient, email: str) -> None:
    import app as app_module
    from db.models import UserORM

    override = app_module.app.dependency_overrides[get_db]
    db = next(override())
    user = db.query(UserORM).filter(UserORM.email == email).one()
    user.is_admin = True
    db.commit()


class TestQualityReportApi:
    def test_no_token_is_401(self, client):
        resp = client.get("/admin/quality-report")
        assert resp.status_code == 401

    def test_non_admin_is_403(self, client):
        token = _register(client)
        resp = client.get("/admin/quality-report", headers=_auth(token))
        assert resp.status_code == 403

    def test_admin_gets_an_empty_report_with_no_data_yet(self, client):
        token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")

        resp = client.get("/admin/quality-report", headers=_auth(token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["by_event_type"] == []
        assert body["miss_rate"] is None
        assert body["invite_completion_rate"] is None
