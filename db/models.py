"""
db/models.py

SQLAlchemy ORM models for the session-centric persistence layer.

These tables mirror the Pydantic feature models in `models/features.py`
field-for-field wherever practical (see the docstring on each class for the
exact Pydantic counterpart), so converting between "what the pipeline
computed" and "what is stored" is a straightforward 1:1 mapping, never a
lossy reinterpretation.

Design notes (see docs/ERD_Design.md for the original, broader-scope ERD
this schema is a focused subset of):

* Every pipeline-stage table hangs directly off `AnalysisSession` via a
  unique `session_id` foreign key (star topology) — see §0.4 of the ERD doc
  for the rationale (partial pipeline states must be representable without
  dangling/order-dependent joins).
* Nested, variable-length, "always read as a whole" data (slide arrays,
  MFCC vectors, emotion timelines, transcript segments) is stored as JSON,
  not normalized into child tables — see §3 of the ERD doc.
* `VideoFeature`/`SpeechFeature`/`TranscriptFeature`/`EmotionFeature`/
  `FaceMeshFeature` are kept as five separate tables rather than one
  flattened "video blob", preserving the ability to re-run a single vision
  analyzer independently. A single unified view is assembled at the
  service layer (`EvaluationWorkflowManager`), not the storage layer.
* `Uuid`/`JSON` are SQLAlchemy's cross-dialect generic types (not
  `postgresql.UUID`/`postgresql.JSONB`) so this module can be smoke-tested
  against SQLite in development; PostgreSQL remains the only supported
  production dialect (see `db/session.py`).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from db.base import Base


def _uuid_pk() -> Mapped[uuid.UUID]:
    """Shared UUID primary-key column definition."""
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Accounts and authorization (Project 1 report, section 3.6 -- the function
# permission matrix, Bang 3.3).
#
# The report describes three authenticated actor groups that inherit upward:
# Nguoi hoc (learner) < Giang vien (lecturer) < Quan tri vien (admin), plus an
# unauthenticated Khach vang lai who may only view the landing page, register,
# and log in.
#
# Those four columns are modelled here as `role` (learner | lecturer) plus a
# SEPARATE `is_admin` flag rather than a three-value `role`, for one specific
# reason: users are allowed to change their own role from the settings screen.
# If administrator were a value of `role`, that same endpoint would be a
# privilege-escalation hole -- any account could promote itself by sending
# `{"role": "admin"}`. With admin as its own flag, no request body reaching a
# self-service endpoint can grant it; it is set only by the CLI in
# `scripts/create_admin.py`. The permission matrix is reproduced exactly
# either way.
# ---------------------------------------------------------------------------


class UserRole(str, enum.Enum):
    """
    The self-selectable roles, matching the report's actor list.

    Administrator is deliberately absent -- it is `UserORM.is_admin`, which no
    self-service endpoint can set. See the section comment above.
    """

    LEARNER = "learner"
    """AC-02 Nguoi hoc: the primary actor -- own sessions, own reports, practice."""

    LECTURER = "lecturer"
    """AC-03 Giang vien: inherits learner, plus other learners' reports and scoring weights."""


class UserORM(Base):
    """
    One account.

    Field notes where the choice is not obvious:

    * `email` is stored lowercased and is unique. Case-preserving storage
      would let `An@x.com` and `an@x.com` register as two accounts that every
      human reader would take for one.
    * `password_hash` is nullable so an account can exist without a password,
      which is what a future SSO-only account needs (ERD section 2.1). A NULL
      hash can never satisfy a login: `verify_password` is not reached.
    * `is_verified` defaults to false and is informational for now -- it marks
      accounts an institution has confirmed. It does NOT gate login, because
      the report's registration flow puts the user straight into the product
      with no approval queue.
    * `is_active` is how an account gets disabled. Deactivating rather than
      deleting keeps the session history that hangs off `analysis_sessions`
      intact and attributable.
    * `recording_consent_ack_at` records when a teacher acknowledged that they
      are responsible for telling people they are being recorded. The
      protection that matters belongs at the recording layer, not the account
      layer -- a role label never stopped anyone from filming another person.
    """

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("email", name="uq_users_email"),)

    id: Mapped[uuid.UUID] = _uuid_pk()

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=UserRole.LEARNER,
    )
    is_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    preferred_language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi")
    recording_consent_ack_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    sessions: Mapped[list["AnalysisSession"]] = relationship(back_populates="owner")

    @property
    def can_view_other_learners(self) -> bool:
        """Row 9 of the permission matrix: lecturers and admins, not learners."""
        return self.is_admin or self.role is UserRole.LECTURER

    @property
    def effective_role_label(self) -> str:
        """How the role reads in the UI, with the admin flag taking precedence."""
        if self.is_admin:
            return "admin"
        return self.role.value


class EvaluationMode(str, enum.Enum):
    """Which of the two supported workflows a session runs."""

    PRESENTATION = "presentation"
    INTERVIEW = "interview"


class SessionState(str, enum.Enum):
    """
    Unified state machine covering both evaluation modes. `SLIDE_*` states
    are only reachable in `PRESENTATION` mode; `RESUME_*` states only in
    `INTERVIEW` mode. Both modes converge on the shared
    `WAITING_FOR_VIDEO -> ... -> COMPLETED` tail. Kept as a single enum
    (rather than two near-duplicate ones) so `EvaluationWorkflowManager`
    has exactly one transition table to validate against.

    Each material (slide/resume/video) is now scored and given a
    *preliminary* reasoning pass (`*_SCORING` -> `*_REASONING` ->
    `*_EVALUATED`) as soon as it finishes analysis, persisted as a
    `PreliminaryEvaluationORM` row, and shown to the user immediately via
    `GET /sessions/{id}/preliminary/{stage}` — the user does not have to
    wait for the video to see feedback on their slides/resume. The shared
    tail (`FEATURE_FUSION` -> ... -> `REPORT_GENERATED`) then produces the
    final, synthesized report, which reconciles the preliminary assessments
    rather than reasoning over the raw data from scratch. `RECOMMENDING`
    runs once the report exists: an LLM-driven Recommendation Engine picks
    learning resources from `learning_resources` (seeded from curated
    catalogs) targeted at the session's weakest areas, persisted as
    `RecommendationORM` rows and shown via `GET /sessions/{id}/recommendations`.
    """

    EMPTY = "empty"

    SLIDE_UPLOADED = "slide_uploaded"
    SLIDE_ANALYZING = "slide_analyzing"
    SLIDE_ANALYZED = "slide_analyzed"
    SLIDE_SCORING = "slide_scoring"
    SLIDE_REASONING = "slide_reasoning"
    SLIDE_EVALUATED = "slide_evaluated"

    RESUME_UPLOADED = "resume_uploaded"
    RESUME_ANALYZING = "resume_analyzing"
    RESUME_ANALYZED = "resume_analyzed"
    RESUME_SCORING = "resume_scoring"
    RESUME_REASONING = "resume_reasoning"
    RESUME_EVALUATED = "resume_evaluated"

    WAITING_FOR_VIDEO = "waiting_for_video"
    VIDEO_UPLOADED = "video_uploaded"
    VIDEO_ANALYZING = "video_analyzing"
    VIDEO_ANALYZED = "video_analyzed"
    VIDEO_SCORING = "video_scoring"
    VIDEO_REASONING = "video_reasoning"
    VIDEO_EVALUATED = "video_evaluated"

    FEATURE_FUSION = "feature_fusion"
    SCORING = "scoring"
    PROMPT_BUILDING = "prompt_building"
    REASONING = "reasoning"
    REPORT_GENERATED = "report_generated"
    RECOMMENDING = "recommending"
    COMPLETED = "completed"

    FAILED = "failed"
    """Terminal error state. `AnalysisSession.error_message` explains why,
    and `AnalysisSession.failed_state` records which state the retry should
    resume from (see the Error Recovery section of db/models.py's module
    docstring and services/workflow_manager.py)."""


class EvaluationStage(str, enum.Enum):
    """Which material a `PreliminaryEvaluationORM` row's score/reasoning covers."""

    SLIDE = "slide"
    RESUME = "resume"
    VIDEO = "video"


# ---------------------------------------------------------------------------
# Session — the aggregate root
# ---------------------------------------------------------------------------


class AnalysisSession(Base):
    """The aggregate root: one row per evaluation run (Presentation or Interview)."""

    __tablename__ = "analysis_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    mode: Mapped[EvaluationMode] = mapped_column(
        Enum(EvaluationMode, name="evaluation_mode", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )
    state: Mapped[SessionState] = mapped_column(
        Enum(SessionState, name="session_state", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=SessionState.EMPTY,
    )
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi")

    # Path to each uploaded file on disk; NULL until that file is uploaded.
    # At most one of each per session (matches the two fixed evaluation modes).
    resume_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    slide_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    video_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_state: Mapped[SessionState | None] = mapped_column(
        Enum(SessionState, name="session_state", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )

    # Both added now although nothing in this milestone writes them. Storing
    # only a free-text student name and wiring accounts up later would mean a
    # migration plus a manual reconciliation pass over thousands of historical
    # rows; two nullable columns today cost nothing.
    # Who owns this session. Nullable because sessions created before accounts
    # existed have no owner, and the teacher-recording flow creates sessions
    # for a student who may have no account at all.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    student_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, nullable=True, doc="Set once a student claims this session into their account."
    )
    claim_token: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, doc="Token behind the no-login student result link."
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    resume_feature: Mapped["ResumeFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    slide_feature: Mapped["SlideFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    video_feature: Mapped["VideoFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    speech_feature: Mapped["SpeechFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    transcript_feature: Mapped["TranscriptFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    emotion_feature: Mapped["EmotionFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    face_mesh_feature: Mapped["FaceMeshFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    unified_feature: Mapped["UnifiedFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    score_result: Mapped["ScoreResultORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    report: Mapped["ReportORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    preliminary_evaluations: Mapped[list["PreliminaryEvaluationORM"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["RecommendationORM"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    owner: Mapped["UserORM | None"] = relationship(back_populates="sessions")
    pose_feature: Mapped["PoseFeatureORM | None"] = relationship(
        back_populates="session", uselist=False, cascade="all, delete-orphan"
    )
    presentation_events: Mapped[list["PresentationEventORM"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    teacher_notes: Mapped[list["TeacherNoteORM"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# Layer 1 / 2 feature tables — one row per session, created once that stage
# of the pipeline completes. Field names mirror models/features.py exactly.
# ---------------------------------------------------------------------------


class ResumeFeatureORM(Base):
    """Mirrors `models.features.ResumeFeature` + `ResumeAnalysisFeature` (merged, see ERD §0.1)."""

    __tablename__ = "resume_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # --- extraction (Layer 1, PyMuPDF) ---
    text: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_words_per_page: Mapped[float] = mapped_column(Float, nullable=False)
    headings: Mapped[list] = mapped_column(JSON, default=list)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    experience: Mapped[list] = mapped_column(JSON, default=list)
    projects: Mapped[list] = mapped_column(JSON, default=list)
    font_size_min: Mapped[float] = mapped_column(Float, default=0.0)
    font_size_max: Mapped[float] = mapped_column(Float, default=0.0)
    font_size_avg: Mapped[float] = mapped_column(Float, default=0.0)
    distinct_fonts: Mapped[list] = mapped_column(JSON, default=list)

    # --- analysis (Layer 2, cv_analyzer.py) ---
    keyword_density: Mapped[float] = mapped_column(Float, default=0.0)
    action_verb_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    quantified_achievement_count: Mapped[int] = mapped_column(Integer, default=0)
    section_completeness: Mapped[float] = mapped_column(Float, default=0.0)
    contact_info_present: Mapped[bool] = mapped_column(Boolean, default=False)
    length_appropriateness: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="resume_feature")


class SlideFeatureORM(Base):
    """Mirrors `models.features.SlideFeature` + `SlideAnalysisFeature` (merged, see ERD §0.1)."""

    __tablename__ = "slide_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # --- extraction (Layer 1, python-pptx) ---
    slide_count: Mapped[int] = mapped_column(Integer, nullable=False)
    slides: Mapped[list] = mapped_column(JSON, default=list)  # array of SlideInfo dicts
    image_count: Mapped[int] = mapped_column(Integer, default=0)
    chart_count: Mapped[int] = mapped_column(Integer, default=0)
    table_count: Mapped[int] = mapped_column(Integer, default=0)
    fonts: Mapped[list] = mapped_column(JSON, default=list)
    colors: Mapped[list] = mapped_column(JSON, default=list)
    average_text_length: Mapped[float] = mapped_column(Float, default=0.0)

    # --- analysis (Layer 2, slide_analyzer.py) ---
    text_density_score: Mapped[float] = mapped_column(Float, default=0.0)
    visual_richness_score: Mapped[float] = mapped_column(Float, default=0.0)
    consistency_score: Mapped[float] = mapped_column(Float, default=0.0)
    notes_usage_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    title_presence_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    structure_balance_score: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="slide_feature")


class VideoFeatureORM(Base):
    """Mirrors `models.features.VideoFeature` — raw OpenCV extraction only (Layer 1)."""

    __tablename__ = "video_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    fps: Mapped[float] = mapped_column(Float, nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_sec: Mapped[float] = mapped_column(Float, nullable=False)
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    sampled_frame_count: Mapped[int] = mapped_column(Integer, nullable=False)
    brightness_mean: Mapped[float] = mapped_column(Float, default=0.0)
    brightness_std: Mapped[float] = mapped_column(Float, default=0.0)
    contrast_mean: Mapped[float] = mapped_column(Float, default=0.0)
    motion_score_mean: Mapped[float] = mapped_column(Float, default=0.0)
    motion_score_std: Mapped[float] = mapped_column(Float, default=0.0)
    scene_cut_count: Mapped[int] = mapped_column(Integer, default=0)
    blur_score_mean: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="video_feature")


class SpeechFeatureORM(Base):
    """
    Mirrors `models.features.AudioFeature` (Librosa) + `SpeechIntelligenceFeature`
    (Whisper) merged — both derive from the video's extracted audio track (see
    ERD §0.2). No standalone audio upload exists anymore; this row is always
    populated as part of the unified video pipeline.
    """

    __tablename__ = "speech_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    # --- acoustic (Librosa) ---
    sample_rate: Mapped[int] = mapped_column(Integer, default=0)
    duration_sec: Mapped[float] = mapped_column(Float, default=0.0)
    pitch_mean_hz: Mapped[float] = mapped_column(Float, default=0.0)
    pitch_std_hz: Mapped[float] = mapped_column(Float, default=0.0)
    pitch_min_hz: Mapped[float] = mapped_column(Float, default=0.0)
    pitch_max_hz: Mapped[float] = mapped_column(Float, default=0.0)
    voiced_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    tempo_bpm: Mapped[float] = mapped_column(Float, default=0.0)
    rms_mean: Mapped[float] = mapped_column(Float, default=0.0)
    rms_std: Mapped[float] = mapped_column(Float, default=0.0)
    mfcc_mean: Mapped[list] = mapped_column(JSON, default=list)
    mfcc_std: Mapped[list] = mapped_column(JSON, default=list)
    chroma_mean: Mapped[list] = mapped_column(JSON, default=list)
    spectral_centroid_mean: Mapped[float] = mapped_column(Float, default=0.0)
    spectral_bandwidth_mean: Mapped[float] = mapped_column(Float, default=0.0)
    spectral_rolloff_mean: Mapped[float] = mapped_column(Float, default=0.0)
    zcr_mean: Mapped[float] = mapped_column(Float, default=0.0)
    zcr_std: Mapped[float] = mapped_column(Float, default=0.0)
    silence_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    total_silence_sec: Mapped[float] = mapped_column(Float, default=0.0)
    silent_region_count: Mapped[int] = mapped_column(Integer, default=0)

    # --- speech intelligence (Whisper) ---
    transcript_text: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(16), default="")
    segments: Mapped[list] = mapped_column(JSON, default=list)  # [{start_sec, end_sec, text, confidence}]
    average_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    words_per_minute: Mapped[float] = mapped_column(Float, default=0.0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="speech_feature")
    transcript_feature: Mapped["TranscriptFeatureORM | None"] = relationship(
        back_populates="speech_feature", uselist=False
    )


class TranscriptFeatureORM(Base):
    """Mirrors `models.features.TranscriptFeature` — deterministic linguistic analysis."""

    __tablename__ = "transcript_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    speech_feature_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("speech_features.id", ondelete="SET NULL"), nullable=True
    )

    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sentence_count: Mapped[int] = mapped_column(Integer, default=0)
    vocabulary_diversity: Mapped[float] = mapped_column(Float, default=0.0)
    repeated_words: Mapped[dict] = mapped_column(JSON, default=dict)
    filler_word_count: Mapped[int] = mapped_column(Integer, default=0)
    filler_word_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    grammar_issue_estimate: Mapped[int] = mapped_column(Integer, default=0)
    has_opening: Mapped[bool] = mapped_column(Boolean, default=False)
    has_body: Mapped[bool] = mapped_column(Boolean, default=False)
    has_conclusion: Mapped[bool] = mapped_column(Boolean, default=False)
    has_call_to_action: Mapped[bool] = mapped_column(Boolean, default=False)
    topic_consistency: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_cefr: Mapped[str] = mapped_column(String(4), default="A1")
    keyword_coverage: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="transcript_feature")
    speech_feature: Mapped["SpeechFeatureORM | None"] = relationship(back_populates="transcript_feature")


class EmotionFeatureORM(Base):
    """Mirrors `models.features.EmotionFeature` (HSEmotion)."""

    __tablename__ = "emotion_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    emotion_timeline: Mapped[list] = mapped_column(JSON, default=list)  # [{timestamp_sec, emotion, confidence}]
    emotion_distribution: Mapped[dict] = mapped_column(JSON, default=dict)
    dominant_emotion: Mapped[str] = mapped_column(String(16), default="neutral")
    emotion_consistency: Mapped[float] = mapped_column(Float, default=0.0)
    emotion_confidence_mean: Mapped[float] = mapped_column(Float, default=0.0)
    positive_emotion_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="emotion_feature")


class FaceMeshFeatureORM(Base):
    """Mirrors `models.features.FaceMeshFeature` (MediaPipe Face Mesh)."""

    __tablename__ = "face_mesh_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    frames_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    faces_detected_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    blink_rate_per_min: Mapped[float] = mapped_column(Float, default=0.0)
    eye_openness_mean: Mapped[float] = mapped_column(Float, default=0.0)
    eye_contact_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    # Nullable on purpose: NULL means no face was found, which must stay
    # distinguishable from a measured 0.0 (head down the whole time).
    head_up_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    head_pose_pitch_std: Mapped[float] = mapped_column(Float, default=0.0)
    head_pose_yaw_std: Mapped[float] = mapped_column(Float, default=0.0)
    head_pose_roll_std: Mapped[float] = mapped_column(Float, default=0.0)
    head_movement_score: Mapped[float] = mapped_column(Float, default=0.0)
    face_stability_ratio: Mapped[float] = mapped_column(Float, default=0.0)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="face_mesh_feature")


# ---------------------------------------------------------------------------
# Layer 3 / 4 / 6 outputs
# ---------------------------------------------------------------------------


class UnifiedFeatureORM(Base):
    """
    Mirrors `models.features.DerivedFeatures`, materialized once at Feature
    Fusion time (Layer 3). `snapshot_json` holds the exact merged payload fed
    into Scoring + Prompt Building, so a historical report remains
    byte-for-byte reproducible even if the underlying feature tables are
    later reprocessed with improved extractors/analyzers (see ERD §0.3).
    """

    __tablename__ = "unified_features"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    professionalism: Mapped[float] = mapped_column(Float, default=0.0)
    presentation_density: Mapped[float] = mapped_column(Float, default=0.0)
    communication_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    visual_engagement: Mapped[float] = mapped_column(Float, default=0.0)
    voice_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    presentation_readiness: Mapped[float] = mapped_column(Float, default=0.0)

    snapshot_json: Mapped[dict] = mapped_column(JSON, default=dict)
    fusion_engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    fused_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="unified_feature")


class ScoreResultORM(Base):
    """
    Mirrors `models.features.ScoreBreakdown` — the ONLY table any numeric
    score is ever written to. No AI/reasoning provider may write here;
    only `services/scoring_engine.py` does.
    """

    __tablename__ = "score_results"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    resume_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speech_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emotion_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eye_contact_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voice_confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    presentation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    communication_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)

    scoring_engine_version: Mapped[str] = mapped_column(String(32), nullable=False)
    scored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="score_result")


class ReportORM(Base):
    """
    Mirrors `models.responses.ReasoningPayload` — the only table any LLM
    reasoning-engine output is written to. Never contains scores (enforced
    by the `BaseReasoningEngine` contract, not by this table's shape alone).
    """

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    strengths: Mapped[list] = mapped_column(JSON, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, default=list)
    improvement_plan: Mapped[list] = mapped_column(JSON, default=list)
    presentation_feedback: Mapped[str] = mapped_column(Text, default="")
    interview_feedback: Mapped[str] = mapped_column(Text, default="")
    interview_questions: Mapped[list] = mapped_column(JSON, default=list)
    suggestions: Mapped[list] = mapped_column(JSON, default=list)

    reasoning_engine_name: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning_engine_version: Mapped[str] = mapped_column(String(64), nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="report")


class PreliminaryEvaluationORM(Base):
    """
    A per-material "quick review" — score + reasoning for exactly one of
    slide / resume / video, produced as soon as that material finishes
    Layer 1/2 analysis, well before the rest of the session's materials are
    uploaded. Lets the user see feedback on their slides immediately after
    uploading them, instead of waiting for the video.

    Distinct from `ScoreResultORM`/`ReportORM`, which remain strictly the
    FINAL, synthesized score/report for the whole session (see their own
    docstrings) — `EvaluationWorkflowManager`'s final synthesis step reads
    these rows as additional context (via `providers.registry`'s reasoning
    engine) rather than reasoning over raw features from scratch, and
    combines their `overall_score` values into the session's final
    `overall_score` (see workflow_manager._combine_preliminary_scores).
    """

    __tablename__ = "preliminary_evaluations"
    __table_args__ = (
        UniqueConstraint("session_id", "stage", name="uq_preliminary_evaluations_session_stage"),
    )

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[EvaluationStage] = mapped_column(
        Enum(EvaluationStage, name="evaluation_stage", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
    )

    # Whichever sub-scores are relevant to this stage; the rest stay NULL.
    # Same shape as ScoreResultORM so the two can share a Pydantic response
    # model (see models/session_models.py) without a bespoke schema.
    resume_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speech_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emotion_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eye_contact_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voice_confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    presentation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    communication_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_engine_version: Mapped[str] = mapped_column(String(32), nullable=False)

    strengths: Mapped[list] = mapped_column(JSON, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, default=list)
    improvement_plan: Mapped[list] = mapped_column(JSON, default=list)
    presentation_feedback: Mapped[str] = mapped_column(Text, default="")
    interview_feedback: Mapped[str] = mapped_column(Text, default="")
    interview_questions: Mapped[list] = mapped_column(JSON, default=list)
    suggestions: Mapped[list] = mapped_column(JSON, default=list)

    reasoning_engine_name: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning_engine_version: Mapped[str] = mapped_column(String(64), nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="preliminary_evaluations")


# ---------------------------------------------------------------------------
# Recommendation Engine (MVP: LLM-driven, see docs/ERD_Design.md §4 for the
# rule_engine -> tfrs upgrade path this schema was designed to absorb without
# a rewrite; `generated_by` already accommodates "llm" as a third strategy).
# ---------------------------------------------------------------------------


class LearningResourceORM(Base):
    """
    The catalog of coachable content (`docs/ERD_Design.md` §2.13) that
    `RecommendationORM` rows point into. Seeded from curated resource lists
    (see `scripts/seed_learning_resources.py`) — a root entity, independent
    of any session, so the catalog can be curated/extended without touching
    evaluation history.
    """

    __tablename__ = "learning_resources"
    __table_args__ = (UniqueConstraint("url", name="uq_learning_resources_url"),)

    id: Mapped[uuid.UUID] = _uuid_pk()

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), default="video")  # video / article / course / exercise
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)  # "Youtube" / "Website"
    language: Mapped[str | None] = mapped_column(String(8), nullable=True)  # "vi" / "en"
    speaker: Mapped[str | None] = mapped_column(String(256), nullable=True)
    source: Mapped[str | None] = mapped_column(String(128), nullable=True)  # catalog/category label, e.g. "TEDx..."
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Normalized skill slugs (e.g. "confidence", "speaking", "presentation",
    # "critical_thinking", "interview", "general") that `RecommendationEngine`
    # matches against a session's weak sub-scores. See
    # `services/recommendation_engine.py::SKILL_TAG_TO_SCORE_FIELDS`.
    skill_tags: Mapped[list] = mapped_column(JSON, default=list)
    category_label: Mapped[str | None] = mapped_column(String(128), nullable=True)  # original catalog category text

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    recommendations: Mapped[list["RecommendationORM"]] = relationship(back_populates="resource")


class RecommendationORM(Base):
    """
    One learning-resource suggestion generated for a session
    (`docs/ERD_Design.md` §2.12), produced once the session's final report
    exists (`RECOMMENDING` state, after `REPORT_GENERATED` and before
    `COMPLETED` — see `services/session_state_machine.py`). MVP generates
    these via the reasoning engine (`generated_by="llm"`), matching resources
    against the session's weakest sub-scores/weaknesses; `generated_by` also
    accommodates `"rule_engine"`/`"tfrs"` per the ERD's documented upgrade
    path without any schema change.
    """

    __tablename__ = "recommendations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("learning_resources.id", ondelete="CASCADE"), nullable=False
    )

    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    target_skill_tags: Mapped[list] = mapped_column(JSON, default=list)  # which weak areas this addresses
    generated_by: Mapped[str] = mapped_column(String(32), default="llm")

    reasoning_engine_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reasoning_engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="recommendations")
    resource: Mapped["LearningResourceORM"] = relationship(back_populates="recommendations")


# ---------------------------------------------------------------------------
# In-class analysis (specs/in-class-analysis). One recording produces one
# `PoseFeatureORM`, many `PresentationEventORM` rows (what the machine found),
# and many `TeacherNoteORM` rows (what the teacher marked).
#
# The machine events and the teacher notes are two tables on purpose, and
# never one table with a `source` column. Both accuracy features (Task 10's
# threshold calibration and Task 15's quality dashboard) work by comparing one
# against the other on a shared time axis; keeping them physically apart makes
# that comparison impossible to get wrong. A single table with a flag works
# right until somebody forgets the filter, and then the verification data is
# quietly worthless.
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
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), unique=True, nullable=False
    )

    profile: Mapped[str] = mapped_column(String(64), nullable=False, default="presentation_class")
    profile_version: Mapped[str] = mapped_column(String(32), nullable=False, default="0.0.0")

    frames_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    pose_detected_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    available_landmark_groups: Mapped[list] = mapped_column(JSON, default=list)
    landmark_group_availability: Mapped[list] = mapped_column(JSON, default=list)
    sampling_rate_hz: Mapped[float] = mapped_column(Float, default=0.0)
    sampling_warning: Mapped[str | None] = mapped_column(Text, nullable=True)

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

    session: Mapped["AnalysisSession"] = relationship(back_populates="pose_feature")


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
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False, index=True
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

    session: Mapped["AnalysisSession"] = relationship(back_populates="presentation_events")


class NoteVisibilityDB(str, enum.Enum):
    """Storage-level mirror of `models.notes.NoteVisibility`."""

    PRIVATE = "private"
    SHARED_WITH_STUDENT = "shared_with_student"


class TeacherNoteORM(Base):
    """
    Mirrors `models.notes.TeacherNote`: one mark the teacher made by pressing
    a single key mid-presentation.

    Two invariants this table carries, both load-bearing:

    * **Originals are never updated.** An edit inserts a new row whose
      `revision_of` points at the original. Only rows with
      `created_during_recording = TRUE AND revision_of IS NULL` may be used as
      ground truth, because those are the only ones written before the teacher
      could see the machine's output.
    * **`visibility` defaults to `private`.** Sharing a note with the student
      takes an explicit per-note action; linking a session to a student
      account never reveals notes on its own.
    """

    __tablename__ = "teacher_notes"

    id: Mapped[uuid.UUID] = _uuid_pk()
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )

    mark_sec: Mapped[float] = mapped_column(Float, nullable=False)
    created_during_recording: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    visibility: Mapped[NoteVisibilityDB] = mapped_column(
        Enum(NoteVisibilityDB, name="note_visibility", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=NoteVisibilityDB.PRIVATE,
    )

    revision_of: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("teacher_notes.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["AnalysisSession"] = relationship(back_populates="teacher_notes")
    original: Mapped["TeacherNoteORM | None"] = relationship(remote_side=[id])


# ---------------------------------------------------------------------------
# Live Practice (WebSocket audio streaming). Deliberately NOT built on
# `AnalysisSession`/`SessionState` -- practice sessions are single-material
# (audio only), ephemeral, and repeatable, so routing them through the full
# Presentation/Interview state machine would add complexity with no benefit.
# See `services/practice_session_manager.py` for the orchestration logic and
# `routers/practice.py` for the WebSocket protocol.
# ---------------------------------------------------------------------------


class PracticeSessionState(str, enum.Enum):
    """Lifecycle of a single live-practice WebSocket connection."""

    CONNECTING = "connecting"
    STREAMING = "streaming"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class PracticeSessionORM(Base):
    """
    One live speaking-practice attempt: the client streams audio chunks over
    a WebSocket while practicing, then signals end-of-session, at which
    point the full recording is analyzed and a `PracticeEvaluationORM` is
    produced (see `PracticeSessionManager.finalize`).
    """

    __tablename__ = "practice_sessions"

    id: Mapped[uuid.UUID] = _uuid_pk()
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="vi")
    state: Mapped[PracticeSessionState] = mapped_column(
        Enum(PracticeSessionState, name="practice_session_state", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=PracticeSessionState.CONNECTING,
    )
    # NULL means a plain audio-only practice session (no slide/resume
    # attached) -- the original Live Practice behavior. Set either at
    # creation or inferred from whichever of attach_slide/attach_resume is
    # called first (see PracticeSessionManager).
    mode: Mapped[EvaluationMode | None] = mapped_column(
        Enum(EvaluationMode, name="evaluation_mode", values_callable=lambda obj: [e.value for e in obj]),
        nullable=True,
    )

    audio_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Optional material attached before streaming starts, analyzed alongside
    # the recorded audio at finalize time (see
    # `PracticeSessionManager.finalize` -> `AIOrchestrator.build_unified_features`).
    # At most one of the two is ever set, matching `mode`.
    slide_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    resume_file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    transcript_so_far: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    evaluation: Mapped["PracticeEvaluationORM | None"] = relationship(
        back_populates="practice_session", uselist=False, cascade="all, delete-orphan"
    )


class PracticeEvaluationORM(Base):
    """
    The final, audio-only evaluation of one `PracticeSessionORM`. Mirrors
    `PreliminaryEvaluationORM`'s shape (same sub-score columns + the same
    `ReasoningPayload` fields) so the two can share persistence/response
    conversion patterns, even though a practice session only ever populates
    the speech/transcript-relevant subset.
    """

    __tablename__ = "practice_evaluations"

    id: Mapped[uuid.UUID] = _uuid_pk()
    practice_session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("practice_sessions.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    resume_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    slide_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    speech_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    emotion_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eye_contact_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voice_confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    presentation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    communication_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overall_score: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_engine_version: Mapped[str] = mapped_column(String(64), nullable=False)

    strengths: Mapped[list] = mapped_column(JSON, default=list)
    weaknesses: Mapped[list] = mapped_column(JSON, default=list)
    improvement_plan: Mapped[list] = mapped_column(JSON, default=list)
    presentation_feedback: Mapped[str] = mapped_column(Text, default="")
    interview_feedback: Mapped[str] = mapped_column(Text, default="")
    interview_questions: Mapped[list] = mapped_column(JSON, default=list)
    suggestions: Mapped[list] = mapped_column(JSON, default=list)

    reasoning_engine_name: Mapped[str] = mapped_column(String(64), nullable=False)
    reasoning_engine_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    practice_session: Mapped["PracticeSessionORM"] = relationship(back_populates="evaluation")
