"""
Tests for accounts, authorization, and the admin API.

Covers the Project 1 report's stated guarantees rather than only the happy
path:

* **NFR-07** — passwords are never stored in plaintext; the row holds a
  bcrypt hash with a per-password salt.
* **NFR-08** — 401 when a token is missing or bad, 403 when the role is wrong.
* **Bang 3.3** — the function permission matrix, checked per role.
* The registration flow admits the user immediately, with no approval queue.
* Role changes lose no data, and switching back restores the previous view.
* Locking an account blocks sign-in but keeps its session history.
* No HTTP route anywhere can grant `is_admin`.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as app_module
import db.models as dbm
from db.base import Base
from db.session import get_db
from utils.security import create_access_token, verify_password


@pytest.fixture()
def db_session():
    """An isolated in-memory database per test."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with maker() as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    """A TestClient whose requests share the test's database session."""
    app_module.app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def register(client: TestClient, email: str, password: str = "matkhau123", **kwargs) -> dict:
    """Register an account and return the parsed token response."""
    payload = {"email": email, "password": password, **kwargs}
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def auth_header(token: str) -> dict[str, str]:
    """Bearer header for a token."""
    return {"Authorization": f"Bearer {token}"}


def make_admin(db_session: DBSession, email: str = "admin@truong.edu.vn") -> dbm.UserORM:
    """
    Create an administrator the only way the system allows: directly, the way
    `scripts/create_admin.py` does. There is deliberately no HTTP route for it.
    """
    from utils.security import hash_password

    admin = dbm.UserORM(
        email=email,
        password_hash=hash_password("matkhau123"),
        full_name="Quan tri",
        role=dbm.UserRole.LECTURER,
        is_admin=True,
        is_verified=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


def admin_token(admin: dbm.UserORM) -> str:
    """A signed token for an administrator account."""
    return create_access_token(admin.id, role=admin.role.value, is_admin=True)


class TestRegistration:
    def test_registration_signs_the_user_straight_in(self, client) -> None:
        """The report's flow: no approval queue, usable immediately."""
        body = register(client, "an@truong.edu.vn", full_name="Nguyen An", role="lecturer")
        assert body["token_type"] == "bearer"
        assert body["access_token"]
        assert body["user"]["role"] == "lecturer"
        assert body["user"]["is_active"] is True
        # Not verified, but that does not stand between them and the product.
        assert body["user"]["is_verified"] is False

        me = client.get("/auth/me", headers=auth_header(body["access_token"]))
        assert me.status_code == 200
        assert me.json()["email"] == "an@truong.edu.vn"

    def test_password_is_stored_only_as_a_bcrypt_hash(self, client, db_session) -> None:
        """NFR-07, read straight out of the row."""
        register(client, "an@truong.edu.vn", password="matkhau123")
        user = db_session.scalar(select(dbm.UserORM).where(dbm.UserORM.email == "an@truong.edu.vn"))

        assert user.password_hash != "matkhau123"
        assert user.password_hash.startswith("$2b$")
        assert verify_password("matkhau123", user.password_hash)

    def test_each_password_gets_its_own_salt(self, client, db_session) -> None:
        """Two accounts with the same password must not share a hash."""
        register(client, "a@truong.edu.vn", password="matkhau123")
        register(client, "b@truong.edu.vn", password="matkhau123")
        hashes = db_session.scalars(select(dbm.UserORM.password_hash)).all()
        assert len(set(hashes)) == 2

    def test_duplicate_email_is_rejected(self, client) -> None:
        register(client, "an@truong.edu.vn")
        again = client.post(
            "/auth/register", json={"email": "an@truong.edu.vn", "password": "matkhau123"}
        )
        assert again.status_code == 409

    def test_email_case_does_not_create_a_second_account(self, client) -> None:
        register(client, "an@truong.edu.vn")
        again = client.post(
            "/auth/register", json={"email": "AN@Truong.Edu.VN", "password": "matkhau123"}
        )
        assert again.status_code == 409

    def test_malformed_email_and_short_password_are_refused(self, client) -> None:
        assert client.post("/auth/register", json={"email": "khong-phai-email", "password": "matkhau123"}).status_code == 422
        assert client.post("/auth/register", json={"email": "a@b.com", "password": "ngan"}).status_code == 422

    def test_registration_cannot_mint_an_administrator(self, client, db_session) -> None:
        """
        The escalation this design exists to prevent. `admin` is not a value
        of `role`, so the request fails validation before any handler runs.
        """
        response = client.post(
            "/auth/register",
            json={"email": "ke@xau.com", "password": "matkhau123", "role": "admin"},
        )
        assert response.status_code == 422
        assert db_session.scalar(select(dbm.UserORM).where(dbm.UserORM.is_admin.is_(True))) is None


class TestLogin:
    def test_correct_credentials_return_a_token(self, client) -> None:
        register(client, "an@truong.edu.vn", password="matkhau123")
        response = client.post(
            "/auth/login", json={"email": "an@truong.edu.vn", "password": "matkhau123"}
        )
        assert response.status_code == 200
        assert response.json()["access_token"]

    def test_login_is_case_insensitive_on_email(self, client) -> None:
        register(client, "an@truong.edu.vn", password="matkhau123")
        response = client.post(
            "/auth/login", json={"email": "AN@TRUONG.EDU.VN", "password": "matkhau123"}
        )
        assert response.status_code == 200

    def test_wrong_password_and_unknown_email_are_indistinguishable(self, client) -> None:
        """Otherwise this endpoint becomes a way to enumerate who has an account."""
        register(client, "an@truong.edu.vn", password="matkhau123")
        wrong = client.post("/auth/login", json={"email": "an@truong.edu.vn", "password": "saibet"})
        unknown = client.post("/auth/login", json={"email": "khong-co@truong.edu.vn", "password": "matkhau123"})

        assert wrong.status_code == unknown.status_code == 401
        assert wrong.json()["detail"] == unknown.json()["detail"]

    def test_login_records_the_time(self, client, db_session) -> None:
        register(client, "an@truong.edu.vn")
        client.post("/auth/login", json={"email": "an@truong.edu.vn", "password": "matkhau123"})
        user = db_session.scalar(select(dbm.UserORM).where(dbm.UserORM.email == "an@truong.edu.vn"))
        assert user.last_login_at is not None


class TestTokenEnforcement:
    """NFR-08: 401 when the token is missing or bad, 403 when the role is wrong."""

    def test_no_token_is_401(self, client) -> None:
        assert client.get("/auth/me").status_code == 401

    def test_garbage_token_is_401(self, client) -> None:
        assert client.get("/auth/me", headers=auth_header("khong-phai-jwt")).status_code == 401

    def test_token_signed_with_another_key_is_401(self, client) -> None:
        from jose import jwt

        forged = jwt.encode(
            {"sub": str(uuid.uuid4()), "role": "learner", "is_admin": True, "typ": "access"},
            "khoa-cua-ke-tan-cong",
            algorithm="HS256",
        )
        assert client.get("/auth/me", headers=auth_header(forged)).status_code == 401

    def test_token_for_a_deleted_account_is_401(self, client) -> None:
        token = create_access_token(uuid.uuid4(), role="learner", is_admin=False)
        assert client.get("/auth/me", headers=auth_header(token)).status_code == 401

    def test_expired_token_is_401(self, client, db_session) -> None:
        admin = make_admin(db_session)
        expired = create_access_token(
            admin.id, role="lecturer", is_admin=True, expires_minutes=-1
        )
        assert client.get("/auth/me", headers=auth_header(expired)).status_code == 401


class TestPermissionMatrix:
    """Bảng 3.3 — who may call what."""

    def test_learner_is_refused_the_admin_api(self, client) -> None:
        """Row 11 belongs to administrators alone."""
        body = register(client, "hoc@truong.edu.vn", role="learner")
        response = client.get("/admin/users", headers=auth_header(body["access_token"]))
        assert response.status_code == 403

    def test_lecturer_is_also_refused_the_admin_api(self, client) -> None:
        """A lecturer inherits learner rights, not administrator rights."""
        body = register(client, "giangvien@truong.edu.vn", role="lecturer")
        response = client.get("/admin/users", headers=auth_header(body["access_token"]))
        assert response.status_code == 403

    def test_admin_reaches_the_admin_api(self, client, db_session) -> None:
        admin = make_admin(db_session)
        response = client.get("/admin/users", headers=auth_header(admin_token(admin)))
        assert response.status_code == 200

    def test_admin_api_without_a_token_is_401_not_403(self, client) -> None:
        """The distinction the report draws: unidentified vs. identified-but-refused."""
        assert client.get("/admin/users").status_code == 401


class TestRoleSwitching:
    def test_switching_role_keeps_session_history(self, client, db_session) -> None:
        """The report requires the role to change without losing data."""
        body = register(client, "an@truong.edu.vn", role="learner")
        token, user_id = body["access_token"], uuid.UUID(body["user"]["id"])

        db_session.add(dbm.AnalysisSession(mode=dbm.EvaluationMode.PRESENTATION, user_id=user_id))
        db_session.commit()

        def session_count() -> int:
            return len(
                db_session.scalars(
                    select(dbm.AnalysisSession).where(dbm.AnalysisSession.user_id == user_id)
                ).all()
            )

        assert session_count() == 1

        to_lecturer = client.patch("/auth/me/role", json={"role": "lecturer"}, headers=auth_header(token))
        assert to_lecturer.status_code == 200
        assert to_lecturer.json()["role"] == "lecturer"
        assert session_count() == 1

        back = client.patch("/auth/me/role", json={"role": "learner"}, headers=auth_header(token))
        assert back.status_code == 200
        assert back.json()["role"] == "learner"
        assert session_count() == 1

    def test_self_service_role_change_cannot_grant_admin(self, client, db_session) -> None:
        """The second half of the escalation guard."""
        body = register(client, "an@truong.edu.vn")
        response = client.patch(
            "/auth/me/role", json={"role": "admin"}, headers=auth_header(body["access_token"])
        )
        assert response.status_code == 422
        assert db_session.scalar(select(dbm.UserORM).where(dbm.UserORM.is_admin.is_(True))) is None


class TestPasswordChange:
    def test_changing_password_requires_the_current_one(self, client) -> None:
        body = register(client, "an@truong.edu.vn", password="matkhau123")
        response = client.patch(
            "/auth/me/password",
            json={"current_password": "doan-mo", "new_password": "matkhaumoi456"},
            headers=auth_header(body["access_token"]),
        )
        assert response.status_code == 403

    def test_password_change_takes_effect(self, client) -> None:
        body = register(client, "an@truong.edu.vn", password="matkhau123")
        changed = client.patch(
            "/auth/me/password",
            json={"current_password": "matkhau123", "new_password": "matkhaumoi456"},
            headers=auth_header(body["access_token"]),
        )
        assert changed.status_code == 204

        assert client.post("/auth/login", json={"email": "an@truong.edu.vn", "password": "matkhau123"}).status_code == 401
        assert client.post("/auth/login", json={"email": "an@truong.edu.vn", "password": "matkhaumoi456"}).status_code == 200


class TestAdminUserManagement:
    def test_search_and_filter(self, client, db_session) -> None:
        admin = make_admin(db_session)
        register(client, "an.nguyen@truong.edu.vn", full_name="Nguyen Van An", role="learner")
        register(client, "binh@truong.edu.vn", full_name="Tran Binh", role="lecturer")
        headers = auth_header(admin_token(admin))

        everyone = client.get("/admin/users", headers=headers).json()
        assert everyone["total"] == 3

        by_name = client.get("/admin/users", params={"search": "nguyen"}, headers=headers).json()
        assert by_name["total"] == 1
        assert by_name["items"][0]["email"] == "an.nguyen@truong.edu.vn"

        lecturers = client.get("/admin/users", params={"role": "lecturer"}, headers=headers).json()
        # The administrator's own base role is lecturer, so two match.
        assert lecturers["total"] == 2

    def test_admin_can_change_a_role_and_mark_verified(self, client, db_session) -> None:
        admin = make_admin(db_session)
        body = register(client, "an@truong.edu.vn", role="learner")
        headers = auth_header(admin_token(admin))

        response = client.patch(
            f"/admin/users/{body['user']['id']}",
            json={"role": "lecturer", "is_verified": True},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["role"] == "lecturer"
        assert response.json()["is_verified"] is True

    def test_locking_blocks_sign_in_but_keeps_history(self, client, db_session) -> None:
        """Row 14's rule: disable, never delete."""
        admin = make_admin(db_session)
        body = register(client, "an@truong.edu.vn", password="matkhau123")
        user_id = uuid.UUID(body["user"]["id"])

        db_session.add(dbm.AnalysisSession(mode=dbm.EvaluationMode.PRESENTATION, user_id=user_id))
        db_session.commit()

        locked = client.patch(
            f"/admin/users/{user_id}", json={"is_active": False}, headers=auth_header(admin_token(admin))
        )
        assert locked.status_code == 200
        assert locked.json()["is_active"] is False

        denied = client.post("/auth/login", json={"email": "an@truong.edu.vn", "password": "matkhau123"})
        assert denied.status_code == 403

        # The row survives, and so does its session history.
        assert db_session.get(dbm.UserORM, user_id) is not None
        assert db_session.scalars(
            select(dbm.AnalysisSession).where(dbm.AnalysisSession.user_id == user_id)
        ).all()

    def test_an_existing_token_stops_working_the_moment_the_account_is_locked(
        self, client, db_session
    ) -> None:
        """Why the account is re-read on every request instead of trusting the token."""
        admin = make_admin(db_session)
        body = register(client, "an@truong.edu.vn")
        token = body["access_token"]

        assert client.get("/auth/me", headers=auth_header(token)).status_code == 200

        client.patch(
            f"/admin/users/{body['user']['id']}",
            json={"is_active": False},
            headers=auth_header(admin_token(admin)),
        )
        assert client.get("/auth/me", headers=auth_header(token)).status_code == 403

    def test_admin_cannot_lock_itself(self, client, db_session) -> None:
        admin = make_admin(db_session)
        response = client.patch(
            f"/admin/users/{admin.id}", json={"is_active": False}, headers=auth_header(admin_token(admin))
        )
        assert response.status_code == 400

    def test_admin_cannot_lock_another_admin(self, client, db_session) -> None:
        first = make_admin(db_session, "admin1@truong.edu.vn")
        second = make_admin(db_session, "admin2@truong.edu.vn")
        response = client.patch(
            f"/admin/users/{second.id}", json={"is_active": False}, headers=auth_header(admin_token(first))
        )
        assert response.status_code == 403

    def test_admin_api_has_no_way_to_grant_admin(self, client, db_session) -> None:
        """`is_admin` is not a field of the request schema, so it is silently ignored."""
        admin = make_admin(db_session)
        body = register(client, "an@truong.edu.vn")

        response = client.patch(
            f"/admin/users/{body['user']['id']}",
            json={"is_admin": True},
            headers=auth_header(admin_token(admin)),
        )
        assert response.status_code == 200
        assert response.json()["is_admin"] is False

    def test_unknown_user_is_404(self, client, db_session) -> None:
        admin = make_admin(db_session)
        response = client.get(f"/admin/users/{uuid.uuid4()}", headers=auth_header(admin_token(admin)))
        assert response.status_code == 404

    def test_stats_partition_the_user_base(self, client, db_session) -> None:
        admin = make_admin(db_session)
        register(client, "a@truong.edu.vn", role="learner")
        register(client, "b@truong.edu.vn", role="lecturer")

        stats = client.get("/admin/stats", headers=auth_header(admin_token(admin))).json()
        assert stats["total_users"] == 3
        # An administrator is counted once, as an admin -- not also as a lecturer.
        assert stats["learners"] + stats["lecturers"] + stats["admins"] == stats["total_users"]
        assert stats["admins"] == 1


class TestSessionOwnership:
    """NFR-09, at its enforcement point."""

    def test_owner_may_read_their_own_session(self, client, db_session) -> None:
        from routers.dependencies import assert_can_access_session

        body = register(client, "an@truong.edu.vn")
        user = db_session.get(dbm.UserORM, uuid.UUID(body["user"]["id"]))
        session = dbm.AnalysisSession(mode=dbm.EvaluationMode.PRESENTATION, user_id=user.id)
        db_session.add(session)
        db_session.commit()

        assert_can_access_session(session, user)  # does not raise

    def test_a_learner_may_not_read_someone_elses_session(self, client, db_session) -> None:
        from fastapi import HTTPException

        from routers.dependencies import assert_can_access_session

        owner = register(client, "chu@truong.edu.vn")
        intruder = register(client, "nguoila@truong.edu.vn", role="learner")
        session = dbm.AnalysisSession(
            mode=dbm.EvaluationMode.PRESENTATION, user_id=uuid.UUID(owner["user"]["id"])
        )
        db_session.add(session)
        db_session.commit()

        intruder_user = db_session.get(dbm.UserORM, uuid.UUID(intruder["user"]["id"]))
        with pytest.raises(HTTPException) as exc:
            assert_can_access_session(session, intruder_user)
        assert exc.value.status_code == 403

    def test_a_lecturer_may_read_a_learners_session(self, client, db_session) -> None:
        """Row 9 of the permission matrix."""
        from routers.dependencies import assert_can_access_session

        owner = register(client, "hocvien@truong.edu.vn")
        lecturer = register(client, "giangvien@truong.edu.vn", role="lecturer")
        session = dbm.AnalysisSession(
            mode=dbm.EvaluationMode.PRESENTATION, user_id=uuid.UUID(owner["user"]["id"])
        )
        db_session.add(session)
        db_session.commit()

        lecturer_user = db_session.get(dbm.UserORM, uuid.UUID(lecturer["user"]["id"]))
        assert_can_access_session(session, lecturer_user)  # does not raise

    def test_sessions_with_no_owner_stay_readable(self, client, db_session) -> None:
        """History predating accounts must not be stranded behind an ownership check."""
        from routers.dependencies import assert_can_access_session

        body = register(client, "an@truong.edu.vn", role="learner")
        user = db_session.get(dbm.UserORM, uuid.UUID(body["user"]["id"]))
        legacy = dbm.AnalysisSession(mode=dbm.EvaluationMode.PRESENTATION, user_id=None)
        db_session.add(legacy)
        db_session.commit()

        assert_can_access_session(legacy, user)  # does not raise
