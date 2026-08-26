"""add self_practice_sessions / self_notes, re-parent pose_features / presentation_events

In-class analysis, Group A (specs/in-class-analysis/tasks.md, Task 4/7).

`pose_features` and `presentation_events` were created in 0006 hanging off
`analysis_sessions` -- the old upload-and-score session, whose `mode`/`state`
columns describe a slide/resume/scoring workflow that self-practice recordings
never go through. Neither table has any real data yet, so this migration
re-parents both foreign keys onto a new, dedicated `self_practice_sessions`
table instead of carrying the mismatch forward. `teacher_notes` stays put:
that model is legacy (see `specs/in-class-analysis/plan.md`, "Vi sao bo loi
vao giao vien") but the table is untouched, so there is nothing to migrate.

`self_notes` is `teacher_notes`'s much simpler sibling for the self-review
flow: no `visibility`, `category`, or `revision_of` self-reference, because a
session's only viewer is its own owner and edits persist in place rather than
chaining revisions (see `models.notes.SelfNote`).

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-27
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
self_practice_state = postgresql.ENUM(
    "processing",
    "completed",
    "failed",
    name="self_practice_state",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()
    self_practice_state.create(bind, checkfirst=True)

    op.create_table(
        "self_practice_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("profile", sa.String(length=64), nullable=False),
        sa.Column("video_file_path", sa.String(length=1024), nullable=False),
        sa.Column("state", self_practice_state, nullable=False, server_default="processing"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    op.create_table(
        "self_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(),
            sa.ForeignKey("self_practice_sessions.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("mark_sec", sa.Float(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
    )

    # Re-parent: drop the FKs 0006 pointed at analysis_sessions, point them
    # at self_practice_sessions instead. Column name/type are unchanged
    # (both are Uuid), so this is a constraint swap, not a data migration --
    # safe because neither table has any real rows yet.
    op.drop_constraint("pose_features_session_id_fkey", "pose_features", type_="foreignkey")
    op.create_foreign_key(
        "pose_features_session_id_fkey",
        "pose_features",
        "self_practice_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "presentation_events_session_id_fkey", "presentation_events", type_="foreignkey"
    )
    op.create_foreign_key(
        "presentation_events_session_id_fkey",
        "presentation_events",
        "self_practice_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "presentation_events_session_id_fkey", "presentation_events", type_="foreignkey"
    )
    op.create_foreign_key(
        "presentation_events_session_id_fkey",
        "presentation_events",
        "analysis_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint("pose_features_session_id_fkey", "pose_features", type_="foreignkey")
    op.create_foreign_key(
        "pose_features_session_id_fkey",
        "pose_features",
        "analysis_sessions",
        ["session_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_table("self_notes")
    op.drop_table("self_practice_sessions")

    self_practice_state.drop(op.get_bind(), checkfirst=True)
