"""
routers/evaluate.py

Evaluation API group — the only place in the API that invokes Gemini.

    POST /evaluate                -> Mode A: upload raw files, run the full
                                     pipeline (Extraction -> Analysis ->
                                     Fusion -> Scoring -> Prompt -> Gemini).
    POST /evaluate/from-features  -> Mode B: submit an already-built
                                     `UnifiedFeatureModel`, skip extraction,
                                     and run Fusion -> Scoring -> Prompt ->
                                     Gemini directly.

Every material in Mode A is optional (resume / presentation / speech /
video), but at least one must be supplied.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from pydantic import ValidationError

from config import settings
from models.requests import EvaluateFeaturesRequest
from models.responses import ErrorResponse, EvaluationReport
from services.ai_orchestrator import ai_orchestrator
from services.gemini_service import GeminiServiceError
from utils.file_utils import cleanup_file, save_upload_file, validate_extension
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/evaluate", tags=["Evaluate"])

_ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    502: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.post(
    "",
    response_model=EvaluationReport,
    responses=_ERROR_RESPONSES,
    summary="Evaluation Mode A: upload raw files and run the full six-layer pipeline.",
)
async def evaluate_from_files(
    resume: UploadFile | None = File(None, description="Resume/CV file in PDF format."),
    presentation: UploadFile | None = File(None, description="Presentation file in PPTX format."),
    speech: UploadFile | None = File(None, description="Interview speech recording (MP3/WAV/M4A)."),
    video: UploadFile | None = File(None, description="Recorded presentation video (MP4/MOV/M4V)."),
    language: str = Form("vi", description="Feedback language: 'vi' or 'en'."),
) -> EvaluationReport:
    """
    Run the full pipeline on one or more uploaded materials.

    Workflow: validate + save whichever files were supplied -> Layer 1
    extraction -> Layer 2 analysis -> Layer 3 fusion -> Layer 4 scoring ->
    Layer 5 prompt building -> Layer 6 Gemini reasoning -> `EvaluationReport`.
    """
    if not any((resume, presentation, speech, video)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one of resume, presentation, speech, or video must be supplied.",
        )

    saved_paths: list[Path] = []
    try:
        resume_path = await _save_if_present(resume, settings.ALLOWED_PDF_EXTENSIONS, saved_paths)
        presentation_path = await _save_if_present(
            presentation, settings.ALLOWED_PPTX_EXTENSIONS, saved_paths
        )
        speech_path = await _save_if_present(speech, settings.ALLOWED_AUDIO_EXTENSIONS, saved_paths)
        video_path = await _save_if_present(
            video,
            settings.ALLOWED_VIDEO_EXTENSIONS,
            saved_paths,
            max_size_bytes=settings.MAX_VIDEO_SIZE_BYTES,
        )

        features = await ai_orchestrator.build_unified_features(
            resume_path=resume_path,
            slide_path=presentation_path,
            audio_path=speech_path,
            video_path=video_path,
        )
        return await ai_orchestrator.evaluate(features, language=language)

    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Extraction/analysis failed during evaluation")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except GeminiServiceError as exc:
        logger.exception("Gemini call failed during evaluation")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValidationError as exc:
        logger.exception("Gemini response failed schema validation during evaluation")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini response did not match the expected schema: {exc}",
        ) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Required dependency not installed: {exc}",
        ) from exc
    finally:
        for path in saved_paths:
            cleanup_file(path)


@router.post(
    "/from-features",
    response_model=EvaluationReport,
    responses={402: {"model": ErrorResponse}, **_ERROR_RESPONSES},
    summary="Evaluation Mode B: submit a pre-built UnifiedFeatureModel, skip extraction.",
)
async def evaluate_from_features(payload: EvaluateFeaturesRequest) -> EvaluationReport:
    """
    Run Fusion -> Scoring -> Prompt -> Gemini directly on a caller-supplied
    `UnifiedFeatureModel`, skipping Layer 1/2 entirely.
    """
    try:
        return await ai_orchestrator.evaluate(payload.features, language=payload.language)
    except GeminiServiceError as exc:
        logger.exception("Gemini call failed during feature-based evaluation")
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except ValidationError as exc:
        logger.exception("Gemini response failed schema validation during feature-based evaluation")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Gemini response did not match the expected schema: {exc}",
        ) from exc


async def _save_if_present(
    file: UploadFile | None,
    allowed_extensions: set[str],
    saved_paths: list[Path],
    max_size_bytes: int | None = None,
) -> Path | None:
    """Validate, save, and track an optional upload; returns None if not supplied."""
    if file is None:
        return None
    extension = validate_extension(file, allowed_extensions)
    path = await save_upload_file(file, extension, max_size_bytes=max_size_bytes)
    saved_paths.append(path)
    return path
