"""
models/practice_models.py

Pydantic request/response schemas for the Live Practice API
(`routers/practice.py`). Kept separate from `models/session_models.py`
since practice sessions are not part of the `AnalysisSession` state
machine -- see `db.models.PracticeSessionORM`/`PracticeSessionState` and
`services/practice_session_manager.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from db.models import EvaluationMode, PracticeEvaluationORM, PracticeSessionORM, PracticeSessionState
from models.features import ScoreBreakdown
from models.responses import ReasoningPayload

__all__ = [
    "PracticeSessionState",
    "PracticeSessionCreateRequest",
    "PracticeSessionResponse",
    "PracticeEvaluationResponse",
]


class PracticeSessionCreateRequest(BaseModel):
    """
    Request body for `POST /practice` -- create a practice session ahead of
    streaming. Only needed if you want to attach a slide deck/resume before
    recording (via `POST /practice/{id}/slide` or `/resume`); a plain
    audio-only practice can skip this and let `WS /practice/stream` create
    its own session, as before.
    """

    mode: EvaluationMode | None = Field(
        None, description="presentation or interview -- required to later attach a slide/resume."
    )
    language: str = Field("vi", min_length=2, max_length=8, description="Report output language.")


class PracticeSessionResponse(BaseModel):
    """Response for `POST /practice` and `GET /practice/{id}` -- a live-practice session's current status."""

    id: uuid.UUID
    mode: EvaluationMode | None = None
    language: str
    state: PracticeSessionState
    has_slide: bool
    has_resume: bool
    transcript_so_far: str
    error_message: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    created_at: datetime

    @classmethod
    def from_orm_session(cls, session: PracticeSessionORM) -> "PracticeSessionResponse":
        return cls(
            id=session.id,
            mode=session.mode,
            language=session.language,
            state=session.state,
            has_slide=session.slide_file_path is not None,
            has_resume=session.resume_file_path is not None,
            transcript_so_far=session.transcript_so_far,
            error_message=session.error_message,
            started_at=session.started_at,
            ended_at=session.ended_at,
            created_at=session.created_at,
        )


class PracticeEvaluationResponse(BaseModel):
    """
    Response for `GET /practice/{id}/evaluation` -- the final, audio-only
    evaluation of one live-practice session. Only available once
    `state == COMPLETED`. Same field shape as
    `PreliminaryEvaluationResponse` (see `models/session_models.py`) since
    both are produced by the same `build_preliminary_prompt` mechanism, just
    on a `PracticeSessionORM` instead of an `AnalysisSession`.
    """

    practice_session_id: uuid.UUID
    scores: ScoreBreakdown
    reasoning: ReasoningPayload
    scoring_engine_version: str
    reasoning_engine_name: str
    reasoning_engine_version: str | None = None
    generated_at: datetime

    @classmethod
    def from_orm_row(cls, row: PracticeEvaluationORM) -> "PracticeEvaluationResponse":
        return cls(
            practice_session_id=row.practice_session_id,
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
