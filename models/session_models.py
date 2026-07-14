"""
models/session_models.py

Pydantic request/response schemas for the Session API
(`routers/sessions.py`, Phase 3). Reuses the existing Layer 3/4/6 models
(`DerivedFeatures`, `ScoreBreakdown`, `ReasoningPayload`) rather than
redefining their fields, so a session's report has exactly the same shape
as the legacy `/evaluate` response plus session/versioning metadata.

`EvaluationMode`, `EvaluationStage`, and `SessionState` are re-exported from
`db.models` (they are plain `str` enums with no SQLAlchemy dependency baked
in) so callers never need to import from both `db.models` and
`models.session_models`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from db.models import (
    AnalysisSession,
    EvaluationMode,
    EvaluationStage,
    PreliminaryEvaluationORM,
    RecommendationORM,
    SessionState,
)
from models.features import DerivedFeatures, ScoreBreakdown
from models.responses import ReasoningPayload
from services.session_state_machine import legal_events

__all__ = [
    "EvaluationMode",
    "EvaluationStage",
    "SessionState",
    "SessionCreateRequest",
    "SessionResponse",
    "SessionReportResponse",
    "PreliminaryEvaluationResponse",
    "RecommendationItemResponse",
    "RecommendationListResponse",
]


class SessionCreateRequest(BaseModel):
    """Request body for `POST /sessions`."""

    mode: EvaluationMode = Field(..., description="Which evaluation workflow this session runs.")
    language: str = Field("vi", min_length=2, max_length=8, description="Report output language.")


class SessionResponse(BaseModel):
    """
    Response for `POST /sessions`, `POST /sessions/{id}/*`, and
    `GET /sessions/{id}`. `legal_next_events` tells the client what it may
    legally do next (e.g. `["upload_video"]` once slides have been
    analyzed), so the frontend does not need to hard-code the state machine.
    """

    id: uuid.UUID
    mode: EvaluationMode
    state: SessionState
    language: str
    has_resume: bool
    has_slide: bool
    has_video: bool
    error_message: str | None = None
    legal_next_events: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_session(cls, session: AnalysisSession) -> "SessionResponse":
        return cls(
            id=session.id,
            mode=session.mode,
            state=session.state,
            language=session.language,
            has_resume=session.resume_file_path is not None,
            has_slide=session.slide_file_path is not None,
            has_video=session.video_file_path is not None,
            error_message=session.error_message,
            legal_next_events=legal_events(session.mode, session.state),
            created_at=session.created_at,
            updated_at=session.updated_at,
        )


class SessionReportResponse(BaseModel):
    """Response for `GET /sessions/{id}/report`. Only available once `state == COMPLETED`."""

    session_id: uuid.UUID
    mode: EvaluationMode
    scores: ScoreBreakdown
    derived_features: DerivedFeatures
    reasoning: ReasoningPayload
    scoring_engine_version: str
    fusion_engine_version: str
    reasoning_engine_name: str
    reasoning_engine_version: str | None = None
    generated_at: datetime


class PreliminaryEvaluationResponse(BaseModel):
    """
    Response for `GET /sessions/{id}/preliminary/{stage}` -- the "quick
    review" score + reasoning for exactly one material (slide/resume/video),
    available as soon as that material finishes analysis, well before the
    rest of the session's materials are uploaded and the final report is
    ready. Same field shape as `SessionReportResponse` minus
    `derived_features` (Feature Fusion only ever runs over the full, final
    feature set) so a frontend can reuse one rendering component for both.
    """

    session_id: uuid.UUID
    stage: EvaluationStage
    scores: ScoreBreakdown
    reasoning: ReasoningPayload
    scoring_engine_version: str
    reasoning_engine_name: str
    reasoning_engine_version: str | None = None
    generated_at: datetime

    @classmethod
    def from_orm_row(cls, row: PreliminaryEvaluationORM) -> "PreliminaryEvaluationResponse":
        return cls(
            session_id=row.session_id,
            stage=row.stage,
            scores=ScoreBreakdown(
                resume_score=row.resume_score,
                slide_score=row.slide_score,
                speech_score=row.speech_score,
                transcript_score=row.transcript_score,
                emotion_score=row.emotion_score,
                eye_contact_score=row.eye_contact_score,
                voice_confidence_score=row.voice_confidence_score,
                presentation_score=row.presentation_score,
                communication_score=row.communication_score,
                overall_score=row.overall_score,
            ),
            reasoning=ReasoningPayload(
                strengths=row.strengths,
                weaknesses=row.weaknesses,
                improvement_plan=row.improvement_plan,
                presentation_feedback=row.presentation_feedback,
                interview_feedback=row.interview_feedback,
                interview_questions=row.interview_questions,
                suggestions=row.suggestions,
            ),
            scoring_engine_version=row.scoring_engine_version,
            reasoning_engine_name=row.reasoning_engine_name,
            reasoning_engine_version=row.reasoning_engine_version,
            generated_at=row.generated_at,
        )


class RecommendationItemResponse(BaseModel):
    """One ranked learning-resource pick within `RecommendationListResponse`."""

    resource_title: str
    resource_url: str
    resource_type: str
    platform: str | None = None
    language: str | None = None
    speaker: str | None = None
    rank: int
    rationale: str
    target_skill_tags: list[str] = Field(default_factory=list)

    @classmethod
    def from_orm_row(cls, row: RecommendationORM) -> "RecommendationItemResponse":
        return cls(
            resource_title=row.resource.title,
            resource_url=row.resource.url,
            resource_type=row.resource.resource_type,
            platform=row.resource.platform,
            language=row.resource.language,
            speaker=row.resource.speaker,
            rank=row.rank,
            rationale=row.rationale,
            target_skill_tags=row.target_skill_tags,
        )


class RecommendationListResponse(BaseModel):
    """
    Response for `GET /sessions/{id}/recommendations` -- the ranked learning
    resources the Recommendation Engine picked for this session, generated
    automatically once the final report exists (see the `RECOMMENDING`
    state in `services/session_state_machine.py` and
    `services/recommendation_engine.py`). `recommendations` may be an empty
    list if the `learning_resources` catalog had not been seeded yet when
    this session completed (see `scripts/seed_learning_resources.py`) --
    that is not an error, just nothing to suggest.
    """

    session_id: uuid.UUID
    recommendations: list[RecommendationItemResponse]
    generated_by: str | None = None

    @classmethod
    def from_orm_rows(cls, session_id: uuid.UUID, rows: list[RecommendationORM]) -> "RecommendationListResponse":
        return cls(
            session_id=session_id,
            recommendations=[RecommendationItemResponse.from_orm_row(row) for row in rows],
            generated_by=rows[0].generated_by if rows else None,
        )
