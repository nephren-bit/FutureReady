"""add users table and session ownership

Accounts and authorization, per the Project 1 report section 3.6 (function
permission matrix, Bang 3.3).

The report's four actor columns -- Khach vang lai / Nguoi hoc / Giang vien /
Quan tri vien -- map to `role` (learner | lecturer) plus a separate `is_admin`
flag, not to a three-value role. Users may change their own role from the
settings screen; if administrator were a role value, that endpoint would let
any account promote itself. `is_admin` is reachable only from the CLI in
scripts/create_admin.py.

`analysis_sessions.user_id` is the ownership anchor NFR-09 needs ("users may
only access their own sessions, checked in the business layer"). Nullable:
sessions created before accounts existed have no owner, and a teacher
recording a student creates a session for someone who may have no account.

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False for the same reason as 0001/0004/0006: table creation
# would otherwise also try to auto-create the type via SQLAlchemy's
# before_create hook.
user_role = postgresql.ENUM("learner", "lecturer", name="user_role", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    user_role.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        # 320 = the maximum length of an email address per RFC 5321
        # (64-char local part + "@" + 255-char domain).
        sa.Column("email", sa.String(length=320), nullable=False),
        # Nullable so an account can exist without a password, which is what a
        # future SSO-only account needs (ERD 2.1). A NULL hash can never
        # satisfy a login.
        sa.Column("password_hash", sa.String(length=128), nullable=True),
        sa.Column("full_name", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("role", user_role, nullable=False, server_default="learner"),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("preferred_language", sa.String(length=8), nullable=False, server_default="vi"),
        sa.Column("recording_consent_ack_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Uniqueness is enforced by the database, not only by an application check:
    # two concurrent registrations of the same address would otherwise both
    # pass a "does this email exist?" query and both insert.
    op.create_unique_constraint("uq_users_email", "users", ["email"])

    op.add_column("analysis_sessions", sa.Column("user_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_analysis_sessions_user_id",
        "analysis_sessions",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_analysis_sessions_user_id", "analysis_sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_analysis_sessions_user_id", table_name="analysis_sessions")
    op.drop_constraint("fk_analysis_sessions_user_id", "analysis_sessions", type_="foreignkey")
    op.drop_column("analysis_sessions", "user_id")

    op.drop_constraint("uq_users_email", "users", type_="unique")
    op.drop_table("users")

    user_role.drop(op.get_bind(), checkfirst=True)
