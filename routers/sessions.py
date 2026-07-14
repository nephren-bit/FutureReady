"""
routers/sessions.py

The Session API -- the only router the session-centric platform exposes for
running an evaluation. Routers never call `AIOrchestrator`,
`FeatureFusionEngine`, `ScoringEngine`, `PromptBuilder`, `RecommendationEngine`,
or any reasoning engine directly; every request here goes through
`EvaluationWorkflowManager`.

Upload endpoints (`/slide`, `/resume`, `/video`) follow the same two-phase
pattern:

    1. Synchronous, fast: validate the state-machine transition, save the
       file to disk, and move the session into its `*_ANALYZING` state.
    2. Asynchronous, slow: schedule the actual Layer 1/2 AI analysis (and,
       for video, the shared tail through to `COMPLETED`) as a
       `BackgroundTasks` job and return immediately with the session's
       current state. The frontend polls `GET /sessions/{id}` to observe
       progress; heavy analysis never blocks the HTTP response.

Each material's analysis also chains into its own preliminary score +
reasoning pass (see `services/workflow_manager.py`), visible immediately via
`GET /sessions/{id}/preliminary/{stage}` -- the candidate does not have to
wait for the video to see feedback on their slides/resume. Once the final
report is generated, a Recommendation Engine pass automatically picks
learning resources targeted at the session's weakest areas, visible via
`GET /sessions/{id}/recommendations`.

Background jobs open their own DB session (`db.session.SessionLocal`)
rather than reusing the request-scoped one from `Depends(get_db)`, since
the request's session is torn down once the response is sent.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session as DBSession

from config import settings
from db.models import EvaluationStage
from db.session import SessionLocal, get_db
from models.responses import ErrorResponse
from models.session_models import (
    PreliminaryEvaluationResponse,
    RecommendationListResponse,
    SessionCreateRequest,
    SessionReportResponse,
    SessionResponse,
)
from services.session_state_machine import InvalidTransitionError
from services.workflow_manager import (
    PreliminaryEvaluationNotReadyError,
    ReportNotReadyError,
    SessionNotFoundError,
    workflow_manager,
)
from utils.file_utils import save_upload_file, validate_extension
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/sessions", tags=["Sessions"])

_ERROR_RESPONSES = {
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    400: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
}


def _not_found(exc: SessionNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _conflict(exc: InvalidTransitionError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


# ---------------------------------------------------------------------------
# Background job wrappers -- each opens its own DB session and never raises;
# failures are recorded on the session itself (state=FAILED) rather than
# propagating, since there is no HTTP response left to report them to.
# ---------------------------------------------------------------------------


async def _background_run_slide_analysis(session_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        await workflow_manager.run_slide_analysis(db, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Background slide analysis crashed for session %s", session_id)
    finally:
        db.close()


async def _background_run_resume_analysis(session_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        await workflow_manager.run_resume_analysis(db, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Background resume analysis crashed for session %s", session_id)
    finally:
        db.close()


async def _background_run_video_analysis(session_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        await workflow_manager.run_video_analysis(db, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Background video analysis crashed for session %s", session_id)
    finally:
        db.close()


async def _background_retry(session_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        await workflow_manager.retry(db, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Background retry crashed for session %s", session_id)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new evaluation session (Presentation or Interview).",
)
async def create_session(
    payload: SessionCreateRequest, db: DBSession = Depends(get_db)
) -> SessionResponse:
    session = workflow_manager.create_session(db, payload.mode, payload.language)
    return SessionResponse.from_orm_session(session)


@router.get(
    "",
    response_model=list[SessionResponse],
    summary="List all sessions, most recently created first.",
)
async def list_sessions(db: DBSession = Depends(get_db)) -> list[SessionResponse]:
    sessions = workflow_manager.list_sessions(db)
    return [SessionResponse.from_orm_session(session) for session in sessions]


@router.post(
    "/{session_id}/slide",
    response_model=SessionResponse,
    responses=_ERROR_RESPONSES,
    summary="Upload presentation slides (Presentation mode only). Analysis runs in the background.",
)
async def upload_slide(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Presentation slides (.pptx)."),
    db: DBSession = Depends(get_db),
) -> SessionResponse:
    extension = validate_extension(file, settings.ALLOWED_PPTX_EXTENSIONS)
    saved_path: Path = await save_upload_file(file, extension)

    try:
        session = await workflow_manager.start_slide_upload(db, session_id, str(saved_path))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc

    background_tasks.add_task(_background_run_slide_analysis, session_id)
    return SessionResponse.from_orm_session(session)


@router.post(
    "/{session_id}/resume",
    response_model=SessionResponse,
    responses=_ERROR_RESPONSES,
    summary="Upload a resume/CV (Interview mode only). Analysis runs in the background.",
)
async def upload_resume(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Resume/CV (.pdf)."),
    db: DBSession = Depends(get_db),
) -> SessionResponse:
    extension = validate_extension(file, settings.ALLOWED_PDF_EXTENSIONS)
    saved_path: Path = await save_upload_file(file, extension)

    try:
        session = await workflow_manager.start_resume_upload(db, session_id, str(saved_path))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc

    background_tasks.add_task(_background_run_resume_analysis, session_id)
    return SessionResponse.from_orm_session(session)


@router.post(
    "/{session_id}/video",
    response_model=SessionResponse,
    responses=_ERROR_RESPONSES,
    summary=(
        "Upload the presentation/interview video. Runs vision + speech analysis, "
        "then its own preliminary score + reasoning pass, then the full "
        "Fusion -> Scoring -> Reasoning -> Recommending final-synthesis tail, "
        "in the background."
    ),
)
async def upload_video(
    session_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="Presentation or interview video (.mp4/.mov/.m4v)."),
    db: DBSession = Depends(get_db),
) -> SessionResponse:
    extension = validate_extension(file, settings.ALLOWED_VIDEO_EXTENSIONS)
    saved_path: Path = await save_upload_file(file, extension, max_size_bytes=settings.MAX_VIDEO_SIZE_BYTES)

    try:
        session = await workflow_manager.start_video_upload(db, session_id, str(saved_path))
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except InvalidTransitionError as exc:
        raise _conflict(exc) from exc

    background_tasks.add_task(_background_run_video_analysis, session_id)
    return SessionResponse.from_orm_session(session)


@router.post(
    "/{session_id}/retry",
    response_model=SessionResponse,
    responses=_ERROR_RESPONSES,
    summary="Retry a FAILED session from the exact stage it failed at (runs in the background).",
)
async def retry_session(
    session_id: uuid.UUID, background_tasks: BackgroundTasks, db: DBSession = Depends(get_db)
) -> SessionResponse:
    try:
        session = workflow_manager.get_session(db, session_id)
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    if session.state.value != "failed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session {session_id} is not in a FAILED state (state={session.state.value}).",
        )

    background_tasks.add_task(_background_retry, session_id)
    return SessionResponse.from_orm_session(session)


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses=_ERROR_RESPONSES,
    summary="Get a session's current state and progress. Poll this after any upload.",
)
async def get_session(session_id: uuid.UUID, db: DBSession = Depends(get_db)) -> SessionResponse:
    try:
        session = workflow_manager.get_session(db, session_id)
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    return SessionResponse.from_orm_session(session)


@router.get(
    "/{session_id}/report",
    response_model=SessionReportResponse,
    responses=_ERROR_RESPONSES,
    summary="Get the final evaluation report. Only available once state == COMPLETED.",
)
async def get_report(session_id: uuid.UUID, db: DBSession = Depends(get_db)) -> SessionReportResponse:
    try:
        session = workflow_manager.get_session(db, session_id)
        report = workflow_manager.get_report(db, session_id)
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except ReportNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    scores = session.score_result
    derived = session.unified_feature
    return SessionReportResponse(
        session_id=session.id,
        mode=session.mode,
        scores={
            "resume_score": scores.resume_score,
            "slide_score": scores.slide_score,
            "speech_score": scores.speech_score,
            "transcript_score": scores.transcript_score,
            "emotion_score": scores.emotion_score,
            "eye_contact_score": scores.eye_contact_score,
            "voice_confidence_score": scores.voice_confidence_score,
            "presentation_score": scores.presentation_score,
            "communication_score": scores.communication_score,
            "overall_score": scores.overall_score,
        },
        derived_features={
            "professionalism": derived.professionalism,
            "presentation_density": derived.presentation_density,
            "communication_confidence": derived.communication_confidence,
            "visual_engagement": derived.visual_engagement,
            "voice_confidence": derived.voice_confidence,
            "presentation_readiness": derived.presentation_readiness,
        },
        reasoning={
            "strengths": report.strengths,
            "weaknesses": report.weaknesses,
            "improvement_plan": report.improvement_plan,
            "presentation_feedback": report.presentation_feedback,
            "interview_feedback": report.interview_feedback,
            "interview_questions": report.interview_questions,
            "suggestions": report.suggestions,
        },
        scoring_engine_version=scores.scoring_engine_version,
        fusion_engine_version=derived.fusion_engine_version,
        reasoning_engine_name=report.reasoning_engine_name,
        reasoning_engine_version=report.reasoning_engine_version,
        generated_at=report.generated_at,
    )


@router.get(
    "/{session_id}/preliminary/{stage}",
    response_model=PreliminaryEvaluationResponse,
    responses=_ERROR_RESPONSES,
    summary=(
        "Get the preliminary (single-material) score + reasoning for one stage "
        "(slide, resume, or video). Available as soon as that material finishes "
        "analysis, well before the rest of the session's materials are uploaded "
        "or the final report is ready."
    ),
)
async def get_preliminary_evaluation(
    session_id: uuid.UUID, stage: EvaluationStage, db: DBSession = Depends(get_db)
) -> PreliminaryEvaluationResponse:
    try:
        row = workflow_manager.get_preliminary_evaluation(db, session_id, stage)
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except PreliminaryEvaluationNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PreliminaryEvaluationResponse.from_orm_row(row)


@router.get(
    "/{session_id}/recommendations",
    response_model=RecommendationListResponse,
    responses=_ERROR_RESPONSES,
    summary=(
        "Get the ranked learning-resource recommendations generated automatically "
        "once the final report exists. Only available once state == COMPLETED "
        "(recommendations run as the RECOMMENDING stage, right after REASONING)."
    ),
)
async def get_recommendations(session_id: uuid.UUID, db: DBSession = Depends(get_db)) -> RecommendationListResponse:
    try:
        session = workflow_manager.get_session(db, session_id)
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
    if session.state.value != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session {session_id} is not complete yet (state={session.state.value}).",
        )
    rows = workflow_manager.get_recommendations(db, session_id)
    return RecommendationListResponse.from_orm_rows(session_id, rows)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_ERROR_RESPONSES,
    summary="Delete a session and every feature/score/report row derived from it.",
)
async def delete_session(session_id: uuid.UUID, db: DBSession = Depends(get_db)) -> None:
    try:
        workflow_manager.delete_session(db, session_id)
    except SessionNotFoundError as exc:
        raise _not_found(exc) from exc
