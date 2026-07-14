"""
routers/analyze.py

Standalone Layer 2 analyzer API group. Exposes each AI Vision / Speech
Intelligence / deterministic analyzer independently of the full evaluation
pipeline — useful for debugging, testing, and for clients (e.g. Mode B
callers) who want to assemble a `UnifiedFeatureModel` incrementally.
Gemini is never invoked by any endpoint in this router.

    POST /analyze/resume      -> ResumeAnalysisFeature   (from a ResumeFeature body)
    POST /analyze/slide       -> SlideAnalysisFeature     (from a SlideFeature body)
    POST /analyze/transcript  -> TranscriptFeature         (from a raw transcript string)
    POST /analyze/speech      -> SpeechIntelligenceFeature (Whisper, from an audio upload)
    POST /analyze/video       -> VideoVisionResponse       (HSEmotion + MediaPipe, from a video upload)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field

from config import settings
from models.features import (
    ResumeAnalysisFeature,
    ResumeFeature,
    SlideAnalysisFeature,
    SlideFeature,
    SpeechIntelligenceFeature,
    TranscriptFeature,
)
from models.responses import ErrorResponse, VideoVisionResponse
from services.ai_orchestrator import ai_orchestrator
from utils.file_utils import cleanup_file, save_upload_file, validate_extension
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/analyze", tags=["Analyze"])

_ERROR_RESPONSES = {400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}}


class TranscriptRequest(BaseModel):
    """Request body for the standalone transcript analyzer endpoint."""

    transcript: str = Field(..., min_length=1, description="Raw speech transcript text.")


@router.post(
    "/resume",
    response_model=ResumeAnalysisFeature,
    summary="Run the deterministic resume analyzer on an already-extracted ResumeFeature.",
)
async def analyze_resume(resume: ResumeFeature = Body(...)) -> ResumeAnalysisFeature:
    """Analyze a `ResumeFeature` (e.g. from `/extract/resume`) into a `ResumeAnalysisFeature`."""
    return ai_orchestrator.analyze_resume(resume)


@router.post(
    "/slide",
    response_model=SlideAnalysisFeature,
    summary="Run the deterministic slide analyzer on an already-extracted SlideFeature.",
)
async def analyze_slide(slide: SlideFeature = Body(...)) -> SlideAnalysisFeature:
    """Analyze a `SlideFeature` (e.g. from `/extract/slide`) into a `SlideAnalysisFeature`."""
    return ai_orchestrator.analyze_slide(slide)


@router.post(
    "/transcript",
    response_model=TranscriptFeature,
    summary="Run the deterministic transcript linguistic analyzer on raw transcript text.",
)
async def analyze_transcript(payload: TranscriptRequest) -> TranscriptFeature:
    """Analyze a raw transcript string into a `TranscriptFeature`."""
    return ai_orchestrator.analyze_transcript(payload.transcript)


@router.post(
    "/speech",
    response_model=SpeechIntelligenceFeature,
    responses={**_ERROR_RESPONSES, 503: {"model": ErrorResponse}},
    summary="Run Whisper speech-to-text on an audio recording.",
)
async def analyze_speech(
    file: UploadFile = File(..., description="Speech recording (MP3/WAV/M4A)."),
) -> SpeechIntelligenceFeature:
    """Transcribe an audio recording with Whisper into a `SpeechIntelligenceFeature`."""
    extension = validate_extension(file, settings.ALLOWED_AUDIO_EXTENSIONS)
    saved_path: Path | None = None
    try:
        saved_path = await save_upload_file(file, extension)
        return ai_orchestrator.analyze_speech(saved_path)
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Speech analysis failed")
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
    "/video",
    response_model=VideoVisionResponse,
    responses={**_ERROR_RESPONSES, 503: {"model": ErrorResponse}},
    summary="Run HSEmotion + MediaPipe Face Mesh vision analysis on a presentation video.",
)
async def analyze_video(
    file: UploadFile = File(..., description="Presentation video (MP4/MOV/M4V)."),
) -> VideoVisionResponse:
    """Run the full vision pipeline (extraction + emotion + face mesh) on a video."""
    extension = validate_extension(file, settings.ALLOWED_VIDEO_EXTENSIONS)
    saved_path: Path | None = None
    try:
        saved_path = await save_upload_file(file, extension, max_size_bytes=settings.MAX_VIDEO_SIZE_BYTES)
        video, emotion, facemesh = ai_orchestrator.analyze_video_vision(saved_path)
        return VideoVisionResponse(video=video, emotion=emotion, facemesh=facemesh)
    except HTTPException:
        raise
    except RuntimeError as exc:
        logger.exception("Video vision analysis failed")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Required dependency not installed: {exc}",
        ) from exc
    finally:
        if saved_path is not None:
            cleanup_file(saved_path)
