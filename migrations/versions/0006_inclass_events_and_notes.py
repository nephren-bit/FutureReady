"""add pose_features / presentation_events / teacher_notes, and session claim columns

In-class analysis, Group A (specs/in-class-analysis/tasks.md, Task 4).

`presentation_events` (what the machine found) and `teacher_notes` (what the
teacher marked) are deliberately two tables rather than one with a `source`
flag: every accuracy figure in this product is table A compared against table
B on a shared time axis, and separate tables make that comparison impossible
to get wrong.

`analysis_sessions.student_user_id` / `claim_token` are added now even though
nothing writes them yet -- retrofitting them after thousands of sessions have
stored only a free-text student name would mean a migration plus manual
reconciliation.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# create_type=False for the same reason as 0001/0004: table creation would
# otherwise also try to auto-create the type via SQLAlchemy's before_create hook.
note_visibility = postgresql.ENUM(
    "private",
    "shared_with_student",
    name="note_visibility",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    note_visibility.create(bind, checkfirst=True)

    # Fallback head-up signal for PoseFeature.head_up_ratio. Nullable: NULL
    # means no face was found, distinct from a measured 0.0.
    op.add_column("face_mesh_features", sa.Column("head_up_ratio", sa.Float(), nullable=True))

    op.add_column("analysis_sessions", sa.Column("student_user_id", sa.Uuid(), nullable=True))
    op.add_column("analysis_sessions", sa.Column("claim_token", sa.String(length=64), nullable=True))
    op.create_unique_constraint(
        "uq_analysis_sessions_claim_token", "analysis_sessions", ["claim_token"]
    )

    # Each metric is value + measured + reason. A NULL value with a reason
    # means "the landmarks were not there", which must stay distinguishable
    # from a genuine measurement of zero.
    metric_columns: list[sa.Column] = []
    for metric in (
        "head_up_ratio",
        "postural_sway",
        "movement_range",
        "gesture_rate",
        "closed_posture_ratio",
        "shoulder_tilt",
        "turned_away_ratio",
    ):
        metric_columns.extend(
            [
                sa.Column(metric, sa.Float(), nullable=True),
                sa.Column(f"{metric}_measured", sa.Boolean(), nullable=False, server_default=sa.false()),
                sa.Column(f"{metric}_reason", sa.Text(), nullable=True),
            ]
        )

    op.create_table(
        "pose_features",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("profile", sa.String(length=64), nullable=False, server_default="presentation_class"),
        sa.Column("profile_version", sa.String(length=32), nullable=False, server_default="0.0.0"),
        sa.Column("frames_analyzed", sa.Integer(), server_default="0"),
        sa.Column("pose_detected_ratio", sa.Float(), server_default="0"),
        sa.Column("available_landmark_groups", sa.JSON(), nullable=True),
        sa.Column("landmark_group_availability", sa.JSON(), nullable=True),
        sa.Column("sampling_rate_hz", sa.Float(), server_default="0"),
        sa.Column("sampling_warning", sa.Text(), nullable=True),
        *metric_columns,
        sa.Column("series_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "presentation_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False, index=True),
        sa.Column("start_sec", sa.Float(), nullable=False),
        sa.Column("duration_sec", sa.Float(), nullable=False),
        sa.Column("measured_value", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("rule_version", sa.String(length=32), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "teacher_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("analysis_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("mark_sec", sa.Float(), nullable=False),
        sa.Column(
            "created_during_recording", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=64), nullable=True),
        sa.Column("visibility", note_visibility, nullable=False, server_default="private"),
        # Self-reference: an edit inserts a new row pointing back at the
        # original, which is never updated in place.
        sa.Column(
            "revision_of",
            sa.Uuid(),
            sa.ForeignKey("teacher_notes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("teacher_notes")
    op.drop_table("presentation_events")
    op.drop_table("pose_features")

    op.drop_column("face_mesh_features", "head_up_ratio")

    op.drop_constraint("uq_analysis_sessions_claim_token", "analysis_sessions", type_="unique")
    op.drop_column("analysis_sessions", "claim_token")
    op.drop_column("analysis_sessions", "student_user_id")

    note_visibility.drop(op.get_bind(), checkfirst=True)
