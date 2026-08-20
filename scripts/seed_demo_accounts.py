"""
scripts/seed_demo_accounts.py

Creates a set of sample accounts for demos and manual testing: five learners,
two lecturers, and one administrator.

**These accounts have known, shared passwords printed below.** They exist so a
demo has something to show and so the permission matrix can be exercised by
hand. Running this against anything a real person uses would hand every one of
those passwords to whoever reads this file, so the script refuses to do
anything without `--confirm`, and refuses outright when `APP_ENV=production`.

Usage:

    python -m scripts.seed_demo_accounts --confirm
    python -m scripts.seed_demo_accounts --confirm --reset

`--reset` deletes the demo accounts first, so the script can be re-run without
tripping over the email uniqueness constraint. It only ever touches the eight
addresses listed in `DEMO_ACCOUNTS` -- it will not clear a table.

Passwords are per role, not per person, so they are easy to use in a demo:

    Người học    -> sinhvien12345
    Giảng viên   -> giangvien12345
    Quản trị viên -> quantri12345
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import UserORM, UserRole
from db.session import SessionLocal
from utils.security import hash_password

LEARNER_PASSWORD = "sinhvien12345"
LECTURER_PASSWORD = "giangvien12345"
ADMIN_PASSWORD = "quantri12345"


@dataclass(frozen=True)
class DemoAccount:
    """One sample account to create."""

    email: str
    full_name: str
    role: UserRole
    password: str
    is_admin: bool = False
    is_verified: bool = False


DEMO_ACCOUNTS: tuple[DemoAccount, ...] = (
    # Five learners (AC-02 Nguoi hoc).
    DemoAccount("an.nguyen@truong.edu.vn", "Nguyễn Văn An", UserRole.LEARNER, LEARNER_PASSWORD),
    DemoAccount("binh.tran@truong.edu.vn", "Trần Thị Bình", UserRole.LEARNER, LEARNER_PASSWORD),
    DemoAccount("cuong.le@truong.edu.vn", "Lê Minh Cường", UserRole.LEARNER, LEARNER_PASSWORD),
    DemoAccount("dung.pham@truong.edu.vn", "Phạm Thùy Dung", UserRole.LEARNER, LEARNER_PASSWORD),
    DemoAccount("giang.hoang@truong.edu.vn", "Hoàng Trường Giang", UserRole.LEARNER, LEARNER_PASSWORD),
    # Two lecturers (AC-03 Giang vien). Marked verified, since in a real
    # deployment a lecturer account is the kind an institution confirms.
    DemoAccount("thu.vo@truong.edu.vn", "Võ Thị Thu", UserRole.LECTURER, LECTURER_PASSWORD, is_verified=True),
    DemoAccount("nam.dang@truong.edu.vn", "Đặng Hoài Nam", UserRole.LECTURER, LECTURER_PASSWORD, is_verified=True),
    # One administrator (AC-04 Quan tri vien). `is_admin` is a flag, never a
    # role value -- see db/models.py on why. Its base role stays lecturer so
    # that stripping the flag leaves a sensible account behind rather than one
    # with no role at all.
    DemoAccount(
        "admin@truong.edu.vn",
        "Quản trị hệ thống",
        UserRole.LECTURER,
        ADMIN_PASSWORD,
        is_admin=True,
        is_verified=True,
    ),
)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Bắt buộc. Xác nhận bạn hiểu các tài khoản này dùng mật khẩu công khai.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Xoá các tài khoản mẫu cũ trước khi tạo lại. Chỉ chạm vào 8 email trong danh sách.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Seed the demo accounts. Returns a shell exit code."""
    args = parse_args(argv)

    if os.getenv("APP_ENV", "").lower() == "production":
        print(
            "APP_ENV=production. Script này tạo tài khoản có mật khẩu công khai nên "
            "không chạy trên môi trường thật.",
            file=sys.stderr,
        )
        return 2

    if not args.confirm:
        print(
            "Cần cờ --confirm.\n"
            "Các tài khoản này dùng mật khẩu dùng chung, được ghi thẳng trong mã nguồn "
            "(sinhvien12345 / giangvien12345 / quantri12345). Chỉ dùng cho demo và thử tay.",
            file=sys.stderr,
        )
        return 2

    emails = [account.email for account in DEMO_ACCOUNTS]

    with SessionLocal() as db:
        if args.reset:
            removed = 0
            for existing in db.scalars(select(UserORM).where(UserORM.email.in_(emails))).all():
                db.delete(existing)
                removed += 1
            db.commit()
            print(f"Đã xoá {removed} tài khoản mẫu cũ.\n")

        created, skipped = 0, 0
        for account in DEMO_ACCOUNTS:
            if db.scalar(select(UserORM).where(UserORM.email == account.email)) is not None:
                print(f"  bỏ qua (đã tồn tại): {account.email}")
                skipped += 1
                continue

            db.add(
                UserORM(
                    email=account.email,
                    password_hash=hash_password(account.password),
                    full_name=account.full_name,
                    role=account.role,
                    is_admin=account.is_admin,
                    is_verified=account.is_verified,
                    is_active=True,
                    preferred_language="vi",
                    created_at=datetime.now(timezone.utc),
                )
            )
            label = "quản trị viên" if account.is_admin else (
                "giảng viên" if account.role is UserRole.LECTURER else "người học"
            )
            print(f"  tạo {label:<14} {account.email:<28} {account.full_name}")
            created += 1

        db.commit()

    print(f"\nĐã tạo {created} tài khoản, bỏ qua {skipped}.")
    if skipped:
        print("Dùng --reset để tạo lại từ đầu.")
    print("\nMật khẩu:")
    print(f"  người học      {LEARNER_PASSWORD}")
    print(f"  giảng viên     {LECTURER_PASSWORD}")
    print(f"  quản trị viên  {ADMIN_PASSWORD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
