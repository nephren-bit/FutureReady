"""add practice_sessions / practice_evaluations tables (Live Practice)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Own enum, deliberately not reusing `session_state` -- practice sessions are
# not part of the Presentation/Interview state machine (see db/models.py's
# PracticeSessionState docstring). create_type=False for the same reason as
# 0001's evaluation_mode/session_state: table creation would otherwise also
# try to auto-create this type via SQLAlchemy's before_create hook.
practice_session_state = postgresql.ENUM(
    "connecting",
    "streaming",
    "finalizing",
    "completed",
    "failed",
    name="practice_session_state",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    practice_session_state.create(bind, checkfirst=True)

    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("language", sa.String(length=8), nullable=False, server_default="vi"),
        sa.Column("state", practice_session_state, nullable=False, server_default="connecting"),
        sa.Column("audio_file_path", sa.String(length=1024), nullable=True),
        sa.Column("transcript_so_far", sa.Text(), nullable=False, server_default=""),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "practice_evaluations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "practice_session_id",
            sa.Uuid(),
            sa.ForeignKey("practice_sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
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
        sa.Column("scoring_engine_version", sa.String(length=64), nullable=False),
        sa.Column("strengths", sa.JSON(), nullable=False),
        sa.Column("weaknesses", sa.JSON(), nullable=False),
        sa.Column("improvement_plan", sa.JSON(), nullable=False),
        sa.Column("presentation_feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("interview_feedback", sa.Text(), nullable=False, server_default=""),
        sa.Column("interview_questions", sa.JSON(), nullable=False),
        sa.Column("suggestions", sa.JSON(), nullable=False),
        sa.Column("reasoning_engine_name", sa.String(length=64), nullable=False),
        sa.Column("reasoning_engine_version", sa.String(length=64), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("practice_evaluations")
    op.drop_table("practice_sessions")

    bind = op.get_bind()
    practice_session_state.drop(bind, checkfirst=True)
