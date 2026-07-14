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
    tail (`FEATURE_FUSION` -> ... -> `COMPLETED`) then produces the final,
    synthesized report, which reconciles the preliminary assessments rather
    than reasoning over the raw data from scratch.
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
