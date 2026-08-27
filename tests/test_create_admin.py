"""
Tests for scripts/create_admin.py (Nhóm B, Task 12 / Plans.md B3).

`set_admin` only ever promotes an account that already registered itself --
there is no admin self-registration from the UI (specs/in-class-analysis/
plan.md, "Đăng ký, đăng nhập và phân quyền"), so this CLI must fail loudly,
never silently create a phantom account, when the email isn't registered.
Written before scripts/create_admin.py exists (TDD Red).
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import UserORM
from scripts.create_admin import set_admin
from utils.security import hash_password


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=pool.StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    yield session
    session.close()


def _make_user(db, email="an@example.com") -> UserORM:
    user = UserORM(email=email, password_hash=hash_password("matkhau-du-dai"), full_name="An")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TestSetAdmin:
    def test_promotes_an_existing_account(self, db):
        user = _make_user(db)
        assert user.is_admin is False

        promoted = set_admin(db, "an@example.com")
        assert promoted.is_admin is True

    def test_is_case_insensitive(self, db):
        _make_user(db, email="an@example.com")
        promoted = set_admin(db, "AN@EXAMPLE.COM")
        assert promoted.is_admin is True

    def test_unknown_email_raises_instead_of_creating_an_account(self, db):
        with pytest.raises(ValueError):
            set_admin(db, "khong-ton-tai@example.com")
        assert db.query(UserORM).count() == 0
