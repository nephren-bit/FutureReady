"""
scripts/assign_orphan_sessions.py

Gives an owner to every `analysis_sessions` row that has none.

Sessions created before accounts existed carry `user_id = NULL`. Once
`GET /sessions` became owner-scoped (see `EvaluationWorkflowManager.list_sessions`)
those rows stopped appearing on anyone's dashboard: they belong to nobody, so
they match nobody's query. They are not lost -- every feature, score, report,
and recommendation row still hangs off them -- but they are unreachable from
the UI until someone owns them.

This script hands them out round-robin across accounts, oldest session first,
so a demo has several accounts with a plausible history each instead of one
account holding everything and the rest looking broken.

Usage:

    python -m scripts.assign_orphan_sessions                  # dry run, prints the plan
    python -m scripts.assign_orphan_sessions --confirm        # actually writes
    python -m scripts.assign_orphan_sessions --confirm --to an.nguyen@truong.edu.vn,binh.tran@truong.edu.vn
    python -m scripts.assign_orphan_sessions --confirm --reset  # unown everything first, then redistribute

Without `--to`, the recipients are every active account whose role is
`learner`, ordered by email so two runs on the same database produce the same
assignment. `--reset` exists because the first distribution is a judgement
call you may want to redo; it only ever clears `user_id`, never a session.

This touches ownership and nothing else. No session, feature, score, report,
or recommendation row is created, modified, or deleted.
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from sqlalchemy import select

from db.models import AnalysisSession, UserORM, UserRole
from db.session import SessionLocal

# A Windows console defaults to a legacy codepage (cp1258, cp932, ...) that
# cannot encode the Vietnamese text this script prints, and the resulting
# UnicodeEncodeError would abort the run *after* the assignment had been
# decided. Force UTF-8 so the output survives whatever locale the machine has.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Ghi thay đổi. Không có cờ này thì chỉ in ra kế hoạch chia (dry run).",
    )
    parser.add_argument(
        "--to",
        default="",
        help=(
            "Danh sách email nhận phiên, phân tách bằng dấu phẩy. "
            "Mặc định: mọi tài khoản người học đang hoạt động."
        ),
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Gỡ chủ sở hữu của mọi phiên trước, rồi chia lại từ đầu.",
    )
    return parser.parse_args(argv)


def _recipients(db, emails: list[str]) -> list[UserORM]:
    """
    The accounts that will receive sessions.

    Explicit emails must all resolve: silently skipping one that was typed
    wrong would produce a distribution that looks correct and quietly leaves
    an account out.
    """
    if emails:
        users: list[UserORM] = []
        for email in emails:
            user = db.execute(
                select(UserORM).where(UserORM.email == email.strip().lower())
            ).scalar_one_or_none()
            if user is None:
                raise SystemExit(f"Không tìm thấy tài khoản: {email}")
            users.append(user)
        return users

    return list(
        db.execute(
            select(UserORM)
            .where(UserORM.role == UserRole.LEARNER, UserORM.is_active.is_(True))
            .order_by(UserORM.email)
        ).scalars()
    )


def main(argv: list[str]) -> int:
    """Assign unowned sessions. Returns a shell exit code."""
    args = parse_args(argv)
    emails = [e for e in args.to.split(",") if e.strip()]

    db = SessionLocal()
    try:
        recipients = _recipients(db, emails)
        if not recipients:
            print(
                "Không có tài khoản nào để nhận phiên. Chạy "
                "`python -m scripts.seed_demo_accounts --confirm` trước.",
                file=sys.stderr,
            )
            return 1

        if args.reset:
            owned = list(
                db.execute(
                    select(AnalysisSession).where(AnalysisSession.user_id.is_not(None))
                ).scalars()
            )
            print(f"--reset: gỡ chủ sở hữu của {len(owned)} phiên.")
            if args.confirm:
                for session in owned:
                    session.user_id = None
                db.flush()

        orphans = list(
            db.execute(
                select(AnalysisSession)
                .where(AnalysisSession.user_id.is_(None))
                .order_by(AnalysisSession.created_at)
            ).scalars()
        )

        if not orphans:
            print("Không còn phiên nào chưa có chủ. Không cần làm gì.")
            db.rollback()
            return 0

        # Round-robin, oldest first. Deterministic: same database, same result.
        plan: dict[str, list[AnalysisSession]] = defaultdict(list)
        for index, session in enumerate(orphans):
            owner = recipients[index % len(recipients)]
            plan[owner.email].append(session)
            if args.confirm:
                session.user_id = owner.id

        print(f"{len(orphans)} phiên chưa có chủ -> {len(recipients)} tài khoản:\n")
        for email in sorted(plan):
            sessions = plan[email]
            print(f"  {email}  ({len(sessions)} phiên)")
            for session in sessions:
                created = session.created_at.strftime("%Y-%m-%d %H:%M")
                print(f"      {session.id}  {session.mode.value:<12} {session.state.value:<22} {created}")
            print()

        if not args.confirm:
            db.rollback()
            print("Đây mới là bản xem trước. Thêm --confirm để ghi vào cơ sở dữ liệu.")
            return 0

        db.commit()
        print("Đã ghi. Mỗi tài khoản giờ chỉ thấy phiên của chính mình.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
