"""drop the old upload-and-score pipeline's tables

The Session API (`routers/sessions.py`), Live Practice
(`routers/practice.py`), and everything under them (`AnalysisSession` and
its feature/score/report tables, `PracticeSessionORM`/`PracticeEvaluationORM`,
`TeacherNoteORM`, `LearningResourceORM`/`RecommendationORM`,
`preliminary_evaluations`) were removed from the codebase: this product's
entry point is now self-practice only (`self_practice_sessions`), which
never computes a total score and does not need any of this. See
specs/in-class-analysis/plan.md and tasks.md for the product rationale.

This migration is one-way. `downgrade()` deliberately does not attempt to
reconstruct 17 tables' worth of columns added incrementally across 0001-0006
-- that code still exists in git history (this repo's commits before this
migration was added) if the old pipeline is ever needed again; copy the
`upgrade()` bodies of 0001-0006 back out of history rather than trusting a
best-effort reversal written after the fact.

`self_practice_sessions`, `self_notes`, `pose_features`,
`presentation_events`, and the `self_practice_state` enum (all from 0007)
are untouched.

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Same enums 0001/0002/0004/0005/0006 created for the tables this migration
# drops. create_type=False for the usual reason: table creation's
# before_create hook would otherwise also try to create these.
_evaluation_mode = postgresql.ENUM("presentation", "interview", name="evaluation_mode", create_type=False)
_session_state = postgresql.ENUM(
    "empty", "slide_uploaded", "slide_analyzing", "slide_analyzed", "resume_uploaded", "resume_analyzing",
    "resume_analyzed", "waiting_for_video", "video_uploaded", "video_analyzing", "video_analyzed",
    "feature_fusion", "scoring", "prompt_building", "reasoning", "report_generated", "recommending",
    "completed", "failed",
    name="session_state", create_type=False,
)
_evaluation_stage = postgresql.ENUM("slide", "resume", "video", name="evaluation_stage", create_type=False)
_note_visibility = postgresql.ENUM("private", "shared_with_student", name="note_visibility", create_type=False)
_practice_session_state = postgresql.ENUM(
    "connecting", "streaming", "finalizing", "completed", "failed", name="practice_session_state", create_type=False,
)

# Drop order satisfies every FK in 0001-0006: children before the parent
# they reference. `recommendations` references both `analysis_sessions` and
# `learning_resources`; `transcript_features` references `speech_features`
# in addition to `analysis_sessions`; `practice_evaluations` references
# `practice_sessions`.
_TABLES_IN_DROP_ORDER = (
    "recommendations",
    "preliminary_evaluations",
    "teacher_notes",
    "reports",
    "score_results",
    "unified_features",
    "face_mesh_features",
    "emotion_features",
    "transcript_features",
    "speech_features",
    "video_features",
    "slide_features",
    "resume_features",
    "analysis_sessions",
    "learning_resources",
    "practice_evaluations",
    "practice_sessions",
)


def upgrade() -> None:
    for table in _TABLES_IN_DROP_ORDER:
        op.drop_table(table)

    bind = op.get_bind()
    _evaluation_stage.drop(bind, checkfirst=True)
    _note_visibility.drop(bind, checkfirst=True)
    _practice_session_state.drop(bind, checkfirst=True)
    _session_state.drop(bind, checkfirst=True)
    _evaluation_mode.drop(bind, checkfirst=True)


def downgrade() -> None:
    raise NotImplementedError(
        "0008 removes the old upload-and-score pipeline's tables and does not "
        "reconstruct them -- restore by checking out this repo's history from "
        "before the removal commit and re-running 0001-0007 against a fresh "
        "database instead of downgrading this one."
    )
