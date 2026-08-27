"""add users table and self_practice_sessions.user_id

Accounts, Nhóm B Task 10 (specs/in-class-analysis/tasks.md; Plans.md B1).

`users` deliberately has NO `role` column: every account has the same
rights, `is_admin` is the only distinction and is set from the CLI, never
from the UI (plan.md, "Đăng ký, đăng nhập và phân quyền"). Email uniqueness
is a unique index on `lower(email)` so `An@x.vn` and `an@x.vn` cannot both
register; the service layer also lowercases before storing.

`self_practice_sessions.user_id` is nullable: sessions recorded before
accounts existed have no owner and stay reachable only by admins -- they are
never silently claimed. ON DELETE SET NULL rather than CASCADE, because
locking via `is_active` is the product's removal mechanism (rows are never
deleted), and if a user row ever is removed their recordings must survive.

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        # Tokens issued before this instant are rejected (routers/deps.py) --
        # changing a password revokes any stolen live session. NULL = never changed.
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_users_email_lower", "users", [sa.text("lower(email)")], unique=True
    )

    op.add_column(
        "self_practice_sessions",
        sa.Column("user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "self_practice_sessions_user_id_fkey",
        "self_practice_sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_self_practice_sessions_user_id", "self_practice_sessions", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_self_practice_sessions_user_id", table_name="self_practice_sessions")
    op.drop_constraint(
        "self_practice_sessions_user_id_fkey", "self_practice_sessions", type_="foreignkey"
    )
    op.drop_column("self_practice_sessions", "user_id")

    op.drop_index("uq_users_email_lower", table_name="users")
    op.drop_table("users")
