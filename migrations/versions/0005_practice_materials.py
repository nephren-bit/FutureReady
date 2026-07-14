"""add mode/slide_file_path/resume_file_path to practice_sessions

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-15
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reuses the `evaluation_mode` enum type created in 0001 (create_type=False --
# it already exists). A practice session's mode is optional: NULL means a
# plain audio-only practice session with no slide/resume attached, which
# remains fully supported (see db/models.py's PracticeSessionORM docstring).
evaluation_mode = postgresql.ENUM("presentation", "interview", name="evaluation_mode", create_type=False)


def upgrade() -> None:
    op.add_column("practice_sessions", sa.Column("mode", evaluation_mode, nullable=True))
    op.add_column("practice_sessions", sa.Column("slide_file_path", sa.String(length=1024), nullable=True))
    op.add_column("practice_sessions", sa.Column("resume_file_path", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("practice_sessions", "resume_file_path")
    op.drop_column("practice_sessions", "slide_file_path")
    op.drop_column("practice_sessions", "mode")
