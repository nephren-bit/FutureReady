"""
models/responses.py

Pydantic models describing API response payloads.

`EvaluationReport` is the final shape returned by both evaluation modes
(`/evaluate` and `/evaluate/from-features`). It always contains:

* the full deterministic `ScoreBreakdown` (Layer 4 — never touched by Gemini)
* the `DerivedFeatures` computed by Feature Fusion (Layer 3)
* the Gemini reasoning payload (Layer 6 — strengths/weaknesses/feedback/etc.)

Feature-extraction endpoints (`/extract/*`) and standalone analyzer
endpoints (`/analyze/*`) return the relevant model from `models.features`
directly and therefore do not need dedicated response wrappers.

`RecommendationPayload` is the Recommendation Engine's LLM output shape
(see `services/recommendation_engine.py`) — a ranked list of picks from a
candidate resource list, never a freeform resource description, so the
reasoning engine can only select from what it was actually given.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.features import (
    DerivedFeatures,
    EmotionFeature,
    FaceMeshFeature,
    ScoreBreakdown,
    UnifiedFeatureModel,
    VideoFeature,
)


class VideoVisionResponse(BaseModel):
    """Combined response for the standalone `/analyze/video` vision endpoint."""

    video: VideoFeature
    emotion: EmotionFeature
    facemesh: FaceMeshFeature


class ReasoningPayload(BaseModel):
    """The reasoning-only output produced by Gemini (Layer 6). No scores here."""

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_plan: list[str] = Field(default_factory=list)
    presentation_feedback: str = ""
    interview_feedback: str = ""
    interview_questions: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


class EvaluationReport(BaseModel):
    """Full evaluation report returned by `POST /evaluate*`."""

    resume_score: int | None = Field(None, ge=0, le=100)
    slide_score: int | None = Field(None, ge=0, le=100)
    speech_score: int | None = Field(None, ge=0, le=100)
    transcript_score: int | None = Field(None, ge=0, le=100)
    emotion_score: int | None = Field(None, ge=0, le=100)
    eye_contact_score: int | None = Field(None, ge=0, le=100)
    communication_score: int | None = Field(None, ge=0, le=100)
    presentation_score: int | None = Field(None, ge=0, le=100)
    overall_score: int = Field(..., ge=0, le=100)

    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    improvement_plan: list[str] = Field(default_factory=list)
    presentation_feedback: str = ""
    interview_feedback: str = ""
    interview_questions: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)

    derived_features: DerivedFeatures = Field(
        ..., description="Cross-modal derived signals from the Feature Fusion Engine."
    )
    features: UnifiedFeatureModel = Field(
        ..., description="Full unified feature set that produced this report (for transparency/debugging)."
    )

    @classmethod
    def from_parts(
        cls,
        scores: ScoreBreakdown,
        derived: DerivedFeatures,
        reasoning: ReasoningPayload,
        features: UnifiedFeatureModel,
    ) -> "EvaluationReport":
        """Assemble a report from the deterministic and reasoning halves of the pipeline."""
        return cls(
            resume_score=scores.resume_score,
            slide_score=scores.slide_score,
            speech_score=scores.speech_score,
            transcript_score=scores.transcript_score,
            emotion_score=scores.emotion_score,
            eye_contact_score=scores.eye_contact_score,
            communication_score=scores.communication_score,
            presentation_score=scores.presentation_score,
            overall_score=scores.overall_score,
            strengths=reasoning.strengths,
            weaknesses=reasoning.weaknesses,
            improvement_plan=reasoning.improvement_plan,
            presentation_feedback=reasoning.presentation_feedback,
            interview_feedback=reasoning.interview_feedback,
            interview_questions=reasoning.interview_questions,
            suggestions=reasoning.suggestions,
            derived_features=derived,
            features=features,
        )


class RecommendationItem(BaseModel):
    """One LLM-selected learning-resource pick, referencing a candidate resource by id."""

    resource_id: str = Field(..., description="id of the chosen resource, copied verbatim from the candidate list.")
    rationale: str = Field(..., description="1-2 sentence explanation grounded in the candidate's weak areas.")
    target_skill_tags: list[str] = Field(default_factory=list)


class RecommendationPayload(BaseModel):
    """
    The Recommendation Engine's LLM output (see `services/recommendation_engine.py`):
    a ranked list of resource picks, each referencing a resource_id from the
    candidate list the prompt supplied. The reasoning engine never invents a
    resource — `RecommendationEngine.validate_picks` drops any pick whose
    `resource_id` doesn't match a candidate it was actually given.
    """

    picks: list[RecommendationItem] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    """Standard error payload returned on failures."""

    detail: str = Field(..., description="Human-readable error message.")
