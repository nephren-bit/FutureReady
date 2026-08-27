"""add peer_review_invites and peer_notes

Nhom C (specs/in-class-analysis/tasks.md, Task 15): "nhờ bạn chấm hộ" --
the plan's only independent-judgment data source for calibrating event
thresholds (Task 9/14). See models/peer_review.py for the full design
rationale, in particular why `peer_notes` is a table of its own rather than
sharing `self_notes` or `presentation_events`.

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False for the same reason as every other enum in this repo:
# table creation's before_create hook would otherwise also try to
# auto-create the type.
peer_review_status = postgresql.ENUM(
    "pending", "completed", "expired", "revoked", name="peer_review_status", create_type=False
)


def upgrade() -> None:
    bind = op.get_bind()
    peer_review_status.create(bind, checkfirst=True)

    op.create_table(
        "peer_review_invites",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("self_practice_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "inviter_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("status", peer_review_status, nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_peer_review_invites_token", "peer_review_invites", ["token"], unique=True)

    op.create_table(
        "peer_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("self_practice_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "rater_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "invite_id",
            sa.Uuid(),
            sa.ForeignKey("peer_review_invites.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("mark_sec", sa.Float(), nullable=True),
        sa.Column("created_before_reveal", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rubric_scores", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("peer_notes")
    op.drop_index("ix_peer_review_invites_token", table_name="peer_review_invites")
    op.drop_table("peer_review_invites")
    peer_review_status.drop(op.get_bind(), checkfirst=True)
