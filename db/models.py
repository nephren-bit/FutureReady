"""
db/models.py

SQLAlchemy ORM models for the self-practice pipeline (specs/in-class-analysis).

One `self_practice_sessions` row per recording, with two child tables:
`pose_features` (what the analyzer measured, one row per session) and
`presentation_events` (what the machine detected, many rows per session).
`self_notes` holds what the person marked themselves while reviewing.

`Uuid`/`JSON` are SQLAlchemy's cross-dialect generic types (not
`postgresql.UUID`/`postgresql.JSONB`) so this module can be smoke-tested
against SQLite in development; PostgreSQL remains the only supported
production dialect (see `db/session.py`).

This module used to also hold the schema for a much larger evaluation
pipeline (`AnalysisSession` and its dozen feature/score/report tables,
`PracticeSessionORM`, `TeacherNoteORM`, `LearningResourceORM`,
`RecommendationORM`) — removed along with that pipeline's routers/services.
See git history before the removal commit if any of that is needed again.
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    """Shared UUID primary-key column definition."""
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


# ---------------------------------------------------------------------------
# Accounts (Nhóm B)
# ---------------------------------------------------------------------------


class UserORM(Base):
    """
    One account. Every account has the same rights; `is_admin` is the only
    distinction, set from the CLI (`scripts/create_admin.py`), never from
    the UI. Deliberately NO `role` column -- see
    `specs/in-class-analysis/plan.md`, "Đăng ký, đăng nhập và phân quyền".

    Email uniqueness is case-insensitive: the unique index is on
    `lower(email)`, and the service layer normalizes to lowercase before
    storing/matching, so `An@x.vn` and `an@x.vn` are the same account.

    Locking an account flips `is_active` -- rows are never deleted, so a
    locked user's practice-session history stays intact.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Set on every password change; tokens whose `iat` predates it are
    # rejected (routers/deps.py). This is what makes changing a password
    # actually revoke a stolen session instead of leaving old tokens live
    # for their remaining 7-day lifetime. NULL = never changed.
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[list["SelfPracticeSessionORM"]] = relationship(back_populates="owner")


# Case-insensitive uniqueness: an expression index can't go in
# `__table_args__` before the column exists, so it's declared here against
# the mapped column. The service layer also lowercases before storing, so
# this index is the backstop, not the primary mechanism.
Index("uq_users_email_lower", func.lower(UserORM.email), unique=True)


# ---------------------------------------------------------------------------
# Self-practice sessions and their notes
# ---------------------------------------------------------------------------


class SelfPracticeState(str, enum.Enum):
    """Where a self-practice recording is in the pipeline."""

    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SelfPracticeSessionORM(Base):
    """
    One self-recorded practice session (specs/in-class-analysis).

    `profile` is a free-text name matching a `config/profiles/*.yaml` file
    rather than an enum, so a new context is added as a YAML file, not a
    schema migration.
    """

    __tablename__ = "self_practice_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    video_file_path: Mapped[str] = mapped_column(String(1024), nullable=False)

    # Nullable: sessions recorded before accounts existed have no owner.
    # Those are reachable only by admins (see routers/self_practice.py's
    # ownership rule), never silently claimed by whoever finds the id.
    # ON DELETE SET NULL rather than CASCADE: locking (is_active) is the
    # product's removal mechanism -- rows are never deleted -- but if a user
    # row ever is removed, their recordings must not vanish with it.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    state: Mapped[SelfPracticeState] = mapped_column(
        Enum(SelfPracticeState, name="self_practice_state", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=SelfPracticeState.PROCESSING,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    pose_feature: Mapped["PoseFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    presentation_events: Mapped[list["PresentationEventORM"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    self_notes: Mapped[list["SelfNoteORM"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    owner: Mapped["UserORM | None"] = relationship(back_populates="sessions")


class SelfNoteORM(Base):
    """
    Mirrors `models.notes.SelfNote`.

    No `visibility`/`category`/`revision_of`: the owner is the only viewer,
    and edits persist over the same row (see `SelfNote.edited()`), so there
    is no immutability chain to store.
    """

    __tablename__ = "self_notes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("self_practice_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    mark_sec: Mapped[float] = mapped_column(Float, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped["SelfPracticeSessionORM"] = relationship(back_populates="self_notes")


# ---------------------------------------------------------------------------
# Pose measurements and detected events
# ---------------------------------------------------------------------------


class PoseFeatureORM(Base):
    """
    Mirrors `models.features.PoseFeature` (MediaPipe Pose body movement).

    Each of the seven metrics is stored as a value/measured/reason triple
    rather than a bare float. A NULL value with a reason means the landmarks
    were not there -- deliberately distinguishable from a real measurement of
    zero, which is the whole point of `analyzers/landmark_availability.py`.

    `series_json` holds the per-frame time series `events/detector.py` runs
    over, so events can be re-detected against new thresholds without
    re-decoding the video.
    """

    __tablename__ = "pose_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("self_practice_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    profile: Mapped[str] = mapped_column(String(64), nullable=False, default="presentation_class")
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.0.0")

    frames_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    pose_detected_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    available_landmark_groups: Mapped[list] = mapped_column(JSON, default=list)
    landmark_group_availability: Mapped[list] = mapped_column(JSON, default=list)
    sampling_rate_hz: Mapped[float] = mapped_column(Float, default=0.0)
    sampling_warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_fps: Mapped[float] = mapped_column(Float, default=0.0)

    head_up_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    head_up_ratio_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    head_up_ratio_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    postural_sway: Mapped[float | None] = mapped_column(Float, nullable=True)
    postural_sway_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    postural_sway_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    movement_range: Mapped[float | None] = mapped_column(Float, nullable=True)
    movement_range_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    movement_range_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    gesture_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    gesture_rate_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    gesture_rate_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    closed_posture_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    closed_posture_ratio_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_posture_ratio_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    shoulder_tilt: Mapped[float | None] = mapped_column(Float, nullable=True)
    shoulder_tilt_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    shoulder_tilt_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    turned_away_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    turned_away_ratio_measured: Mapped[bool] = mapped_column(Boolean, default=False)
    turned_away_ratio_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    series_json: Mapped[list] = mapped_column(JSON, default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["SelfPracticeSessionORM"] = relationship(back_populates="pose_feature")


class PresentationEventORM(Base):
    """
    Mirrors `models.events.PresentationEvent`: one machine-detected moment.

    `rule_version` is stored per row, not per session: after thresholds are
    recalibrated and the profile's version bumps, historical events stay
    attributable to the rules that actually produced them.
    """

    __tablename__ = "presentation_events"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("self_practice_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    profile: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)

    measured_value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    rule_version: Mapped[str] = mapped_column(String(32), nullable=False)

    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["SelfPracticeSessionORM"] = relationship(back_populates="presentation_events")
