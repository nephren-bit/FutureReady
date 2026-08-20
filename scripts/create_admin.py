"""
scripts/create_admin.py

The only way to grant administrator rights.

Deliberately a command run at the machine rather than a screen in the app.
Nothing reachable over HTTP can set `is_admin`: not registration, not the
self-service role switch, not the admin panel itself. So an attacker who
takes over an administrator's session can do what that one account could do,
and cannot quietly create more administrators to keep the access after the
original account is locked.

Usage:

    python -m scripts.create_admin --email admin@truong.edu.vn --name "Quản trị"
    python -m scripts.create_admin --email admin@truong.edu.vn --password '...'
    python -m scripts.create_admin --email an@truong.edu.vn --promote

Without `--password` the script prompts for one without echoing it, which
keeps the password out of the shell history file.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import datetime, timezone

from sqlalchemy import select

from db.models import UserORM, UserRole
from db.session import SessionLocal
from models.auth_models import MIN_PASSWORD_LENGTH, _validate_password
from utils.security import hash_password


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--email", required=True, help="Email của quản trị viên.")
    parser.add_argument("--name", default="", help="Họ tên hiển thị.")
    parser.add_argument(
        "--password",
        default=None,
        help="Mật khẩu. Bỏ trống để nhập ẩn, tránh lưu vào lịch sử dòng lệnh.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="Nâng một tài khoản đã có lên quản trị viên thay vì tạo mới.",
    )
    parser.add_argument(
        "--role",
        choices=[r.value for r in UserRole],
        default=UserRole.LECTURER.value,
        help="Vai trò nền của tài khoản (mặc định: lecturer).",
    )
    return parser.parse_args(argv)


def prompt_password() -> str:
    """Ask for a password twice, without echoing it."""
    while True:
        first = getpass.getpass("Mật khẩu quản trị viên: ")
        second = getpass.getpass("Nhập lại mật khẩu: ")
        if first != second:
            print("  Hai lần nhập không khớp, thử lại.\n", file=sys.stderr)
            continue
        try:
            return _validate_password(first)
        except ValueError as exc:
            print(f"  {exc}\n", file=sys.stderr)


def main(argv: list[str]) -> int:
    """Create or promote an administrator. Returns a shell exit code."""
    args = parse_args(argv)
    email = args.email.strip().lower()

    with SessionLocal() as db:
        existing = db.scalar(select(UserORM).where(UserORM.email == email))

        if args.promote:
            if existing is None:
                print(f"Không tìm thấy tài khoản {email}. Bỏ --promote để tạo mới.", file=sys.stderr)
                return 1
            if existing.is_admin:
                print(f"Tài khoản {email} đã là quản trị viên.")
                return 0
            existing.is_admin = True
            existing.is_verified = True
            existing.is_active = True
            db.commit()
            print(f"Đã nâng {email} lên quản trị viên.")
            return 0

        if existing is not None:
            print(
                f"Email {email} đã tồn tại. Dùng --promote để nâng tài khoản này lên quản trị viên.",
                file=sys.stderr,
            )
            return 1

        password = args.password
        if password is None:
            password = prompt_password()
        else:
            try:
                _validate_password(password)
            except ValueError as exc:
                print(f"{exc}", file=sys.stderr)
                return 1

        admin = UserORM(
            email=email,
            password_hash=hash_password(password),
            full_name=args.name.strip(),
            role=UserRole(args.role),
            is_admin=True,
            # An account created at the machine by someone with database
            # access is as verified as this system can make anything.
            is_verified=True,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)

        print(f"Đã tạo quản trị viên {email} (id {admin.id}).")
        print(f"Mật khẩu tối thiểu {MIN_PASSWORD_LENGTH} ký tự; đăng nhập tại /dang-nhap.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
