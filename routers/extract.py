"""
routers/extract.py

Feature Extraction API group (Layer 1 only — Gemini is never invoked here).

    POST /extract/resume    -> ResumeFeature
    POST /extract/slide     -> SlideFeature
    POST /extract/audio     -> AudioFeature
    POST /extract/video     -> VideoFeature

Each endpoint validates and saves the upload, delegates to the
`AIOrchestrator` for pure Layer 1 extraction, cleans up the temporary file,
and returns the resulting structured feature model.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status

from config import settings
from models.features import AudioFeature, ResumeFeature, SlideFeature, VideoFeature
from models.responses import ErrorResponse
from services.ai_orchestrator import ai_orchestrator
from utils.file_utils import cleanup_file, save_upload_file, validate_extension
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/extract", tags=["Extract"])

_ERROR_RESPONSES = {
    400: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


@router.post(
    "/resume",
    response_model=ResumeFeature,
    responses=_ERROR_RESPONSES,
    summary="Extract structured features from a resume PDF (no Gemini).",
)
async def extract_resume(
    file: UploadFile = File(..., description="Resume/CV file in PDF format."),
) -> ResumeFeature:
    """Extract structured features from a resume PDF using PyMuPDF."""
    extension = validate_extension(file, settings.ALLOWED_PDF_EXTENSIONS)
    saved_path: Path | None = None
    try:
        saved_path = await save_upload_file(file, extension)
        return ai_orchestrator.extract_resume(saved_path)
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Resume extraction failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Required dependency not installed: {exc}",
        ) from exc
    finally:
        if saved_path is not None:
            cleanup_file(saved_path)


@router.post(
    "/slide",
    response_model=SlideFeature,
    responses=_ERROR_RESPONSES,
    summary="Extract structured features from a presentation PPTX (no Gemini).",
)
async def extract_slide(
    file: UploadFile = File(..., description="Presentation file in PPTX format."),
) -> SlideFeature:
    """Extract structured features from a presentation deck using python-pptx."""
    extension = validate_extension(file, settings.ALLOWED_PPTX_EXTENSIONS)
    saved_path: Path | None = None
    try:
        saved_path = await save_upload_file(file, extension)
        return ai_orchestrator.extract_slide(saved_path)
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Slide extraction failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        if saved_path is not None:
            cleanup_file(saved_path)


@router.post(
    "/audio",
    response_model=AudioFeature,
    responses=_ERROR_RESPONSES,
    summary="Extract raw acoustic features from a speech recording (no Gemini).",
)
async def extract_audio(
    file: UploadFile = File(..., description="Speech recording (MP3/WAV/M4A)."),
) -> AudioFeature:
    """Extract raw acoustic features from an audio recording using Librosa."""
    extension = validate_extension(file, settings.ALLOWED_AUDIO_EXTENSIONS)
    saved_path: Path | None = None
    try:
        saved_path = await save_upload_file(file, extension)
        return ai_orchestrator.extract_audio(saved_path)
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Audio extraction failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    finally:
        if saved_path is not None:
            cleanup_file(saved_path)


@router.post(
    "/video",
    response_model=VideoFeature,
    responses=_ERROR_RESPONSES,
    summary="Extract structured CV features from a presentation video (no Gemini).",
)
async def extract_video(
    file: UploadFile = File(..., description="Presentation video (MP4/MOV/M4V)."),
) -> VideoFeature:
    """Extract structured features (resolution, motion, blur, etc.) from a video using OpenCV."""
    extension = validate_extension(file, settings.ALLOWED_VIDEO_EXTENSIONS)
    saved_path: Path | None = None
    try:
        saved_path = await save_upload_file(file, extension, max_size_bytes=settings.MAX_VIDEO_SIZE_BYTES)
        return ai_orchestrator.extract_video(saved_path)
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Video extraction failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Required dependency not installed: {exc}",
        ) from exc
    finally:
        if saved_path is not None:
            cleanup_file(saved_path)
