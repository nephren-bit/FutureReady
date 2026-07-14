"""add per-material preliminary evaluation states + preliminary_evaluations table

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# New session_state values added by this migration (see db/models.py SessionState).
_NEW_SESSION_STATES = [
    "slide_scoring",
    "slide_reasoning",
    "slide_evaluated",
    "resume_scoring",
    "resume_reasoning",
    "resume_evaluated",
    "video_scoring",
    "video_reasoning",
    "video_evaluated",
]

evaluation_stage = postgresql.ENUM("slide", "resume", "video", name="evaluation_stage", create_type=False)


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE is safe outside of being used in the same
    # transaction (fine on PG12+); each call is its own autocommit-safe
    # statement, so this runs cleanly inside Alembic's wrapping transaction
    # as long as we never reference the new values later in this same
    # migration (we don't insert any data here).
    for value in _NEW_SESSION_STATES:
        op.execute(f"ALTER TYPE session_state ADD VALUE IF NOT EXISTS '{value}'")

    bind = op.get_bind()
    evaluation_stage.create(bind, checkfirst=True)

    op.create_table(
        "preliminary_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stage", evaluation_stage, nullable=False),
        sa.Column("resume_score", sa.Integer(), nullable=True),
        sa.Column("slide_score", sa.Integer(), nullable=True),
        sa.Column("speech_score", sa.Integer(), nullable=True),
        sa.Column("transcript_score", sa.Integer(), nullable=True),
        sa.Column("emotion_score", sa.Integer(), nullable=True),
        sa.Column("eye_contact_score", sa.Integer(), nullable=True),
        sa.Column("voice_confidence_score", sa.Integer(), nullable=True),
        sa.Column("presentation_score", sa.Integer(), nullable=True),
        sa.Column("communication_score", sa.Integer(), nullable=True),
        sa.Column("overall_score", sa.Integer(), nullable=False),
        sa.Column("scoring_engine_version", sa.String(length=32), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("weaknesses", sa.JSON(), nullable=False),
        sa.Column("improvement_plan", sa.JSON(), nullable=False),
        sa.Column("presentation_feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("interview_feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("interview_questions", sa.JSON(), nullable=False),
        sa.Column("suggestions", sa.JSON(), nullable=False),
        sa.Column("reasoning_engine_name", sa.String(length=64), nullable=False),
        sa.Column("reasoning_engine_version", sa.String(length=64), nullable=True),
        sa.Column("prompt_text", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "stage", name="uq_preliminary_evaluations_session_stage"),
    )


def downgrade() -> None:
    op.drop_table("preliminary_evaluations")

    bind = op.get_bind()
    evaluation_stage.drop(bind, checkfirst=True)

    # Postgres has no ALTER TYPE ... DROP VALUE; removing the added
    # session_state values on downgrade would require rebuilding the type
    # (drop dependent columns' default, create a new type, swap, drop old).
    # Not implemented: this is a dev-schema migration and the added values
    # are harmless to leave in place on downgrade.
