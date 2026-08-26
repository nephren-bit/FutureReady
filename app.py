"""
app.py

FastAPI application entry point for FutureReady.

Wires together the Self Practice API (specs/in-class-analysis) -- the
product's sole entry point: record a practice video, get back measured
body-movement events on a timeline. It never computes a total score.

Also configures CORS, exposes a health-check endpoint, and ensures the
upload directory exists on startup. Run with:

    uvicorn app:app --reload

(This module used to also wire up the Session API, Live Practice, and three
legacy stateless routers for a larger upload-and-score evaluation pipeline
-- removed along with that pipeline. See git history before the removal
commit if any of that is needed again.)
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from routers import self_practice
from utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler: ensure the upload directory exists on startup."""
    logger.info("Starting FutureReady API...")
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Upload directory ready: %s", settings.UPLOAD_DIR)
    yield
    logger.info("Shutting down FutureReady API...")


app = FastAPI(
    title="FutureReady API",
    description=(
        "Self-practice presentation/interview coaching (specs/in-class-analysis). "
        "Record a practice video, and the pipeline measures body-movement metrics "
        "(head position, posture, gesture rate, ...) via MediaPipe Pose and reports "
        "detected moments on a timeline -- it never computes a total score, and it "
        "never invents a diagnosis for what it measured."
    ),
    version="4.0.0",
    lifespan=lifespan,
)

# Permissive CORS for local development / capstone demo usage. Tighten for production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(self_practice.router)


@app.get("/health", tags=["Health"], summary="Health check")
async def health_check() -> dict[str, str]:
    """Simple health-check endpoint used to verify the service is running."""
    return {"status": "ok", "service": "FutureReady API"}
