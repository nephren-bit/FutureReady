"""add recommending session state + learning_resources / recommendations tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New session_state value: REPORT_GENERATED -> RECOMMENDING -> COMPLETED
    # (see db/models.py SessionState + services/session_state_machine.py).
    op.execute("ALTER TYPE session_state ADD VALUE IF NOT EXISTS 'recommending'")

    op.create_table(
        "learning_resources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("resource_type", sa.String(length=32), nullable=False, server_default="video"),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("speaker", sa.String(length=256), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("skill_tags", sa.JSON(), nullable=False),
        sa.Column("category_label", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("url", name="uq_learning_resources_url"),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "resource_id",
            sa.Uuid(),
            sa.ForeignKey("learning_resources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("target_skill_tags", sa.JSON(), nullable=False),
        sa.Column("generated_by", sa.String(length=32), nullable=False, server_default="llm"),
        sa.Column("reasoning_engine_name", sa.String(length=64), nullable=True),
        sa.Column("reasoning_engine_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_recommendations_session_id", "recommendations", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_recommendations_session_id", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_table("learning_resources")

    # Postgres has no ALTER TYPE ... DROP VALUE; removing 'recommending' on
    # downgrade would require rebuilding the type. Not implemented: this is
    # a dev-schema migration and the added value is harmless to leave in
    # place on downgrade (matches the precedent set in 0002's downgrade()).
