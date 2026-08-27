"""
scripts/create_admin.py

CLI that grants admin rights to an existing account. There is no admin
self-registration from the UI (specs/in-class-analysis/plan.md, "Đăng ký,
đăng nhập và phân quyền") -- this script is the only way to create an admin,
and it only ever *promotes* an account that already registered itself; it
never creates a new one.

Usage:
    python -m scripts.create_admin --email an@example.com
"""

from __future__ import annotations

import argparse
import sys

from sqlalchemy import func
from sqlalchemy.orm import Session as DBSession

from db.models import UserORM
from db.session import SessionLocal
from utils.logger import get_logger

logger = get_logger(__name__)


def set_admin(db: DBSession, email: str) -> UserORM:
    """
    Promotes the account matching `email` (case-insensitive, matching the
    `lower(email)` uniqueness rule) to admin. Raises `ValueError` -- instead
    of creating the account -- if no such email is registered yet.
    """
    user = db.query(UserORM).filter(func.lower(UserORM.email) == email.strip().lower()).one_or_none()
    if user is None:
        raise ValueError(f"Không tìm thấy tài khoản với email: {email}")
    user.is_admin = True
    db.commit()
    db.refresh(user)
    return user


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--email", required=True, help="Email của tài khoản đã đăng ký, sẽ được cấp quyền admin."
    )
    args = parser.parse_args()

    db = SessionLocal()
    try:
        user = set_admin(db, args.email)
        logger.info("Account promoted to admin: user_id=%s", user.id)
        print(f"Đã cấp quyền admin cho: {user.email}")
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
