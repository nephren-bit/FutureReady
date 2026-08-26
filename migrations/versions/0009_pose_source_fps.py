"""add pose_features.source_fps

Events reported by frame number (`report.value: frame`, see events/rules.py
and config/profiles/presentation_solo.yaml) need the source video's real
frame rate to convert a segment's start second into a frame number --
`pose_features.sampling_rate_hz` is the *sampling* rate (how many of the
video's frames were actually analyzed), a different and much sparser number
that would produce a meaningless frame index.

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("pose_features", sa.Column("source_fps", sa.Float(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("pose_features", "source_fps")
