"""
app.py

FastAPI application entry point for FutureReady (EmpathAI).

Wires together the Session API (the primary, session-centric interface),
the Live Practice API (standalone, audio-only WebSocket streaming), and
the legacy stateless routers (extract/analyze/evaluate — kept in parallel,
marked deprecated per the migration plan; the standalone Audio API was
removed entirely since audio is now only ever analyzed as part of a
session's video upload). Also configures CORS, exposes a health-check
endpoint, and validates configuration on startup. Run with:

    uvicorn app:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from providers.registry import provider_registry
from routers import analyze, evaluate, extract, practice, sessions
from utils.logger import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler: validate config on startup."""
    logger.info("Starting FutureReady API...")
    settings.validate()
    engine = provider_registry.get_reasoning_engine()
    logger.info(
        "Configuration validated. Reasoning engine: %s (%s) | Whisper model: %s",
        engine.name,
        engine.version,
        settings.WHISPER_MODEL_SIZE,
    )
    yield
    logger.info("Shutting down FutureReady API...")


app = FastAPI(
    title="FutureReady API",
    description=(
        "AI-powered communication coaching platform. Evaluates resumes, "
        "presentation slides, and recorded speech/video using traditional "
        "AI, computer vision, and deterministic scoring — with Gemini 2.5 "
        "Flash used only for the final reasoning layer.\n\n"
        "The Session API (`/sessions/*`) is the supported way to run an "
        "evaluation: create a session (Presentation or Interview), upload "
        "its materials, and poll for progress/results. The Live Practice "
        "API (`/practice/*`) is a separate, standalone audio-only "
        "WebSocket streaming feature for quick speaking practice, not part "
        "of the Session API's state machine. The stateless `/extract`, "
        "`/analyze`, and `/evaluate` routers are kept for debugging and "
        "backward compatibility but are deprecated."
    ),
    version="3.0.0",
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

# Primary interface: session-centric evaluation workflow.
app.include_router(sessions.router)

# Live Practice: standalone, audio-only WebSocket streaming practice
# (see routers/practice.py) -- not part of the Session API state machine.
app.include_router(practice.router)

# Legacy stateless routers — kept in parallel, deprecated. No standalone
# Audio API exists anymore; audio is only ever analyzed as part of a
# session's video upload (see services/workflow_manager.py).
app.include_router(extract.router, deprecated=True)
app.include_router(analyze.router, deprecated=True)
app.include_router(evaluate.router, deprecated=True)


@app.get("/health", tags=["Health"], summary="Health check")
async def health_check() -> dict[str, str]:
    """Simple health-check endpoint used to verify the service is running."""
    return {"status": "ok", "service": "FutureReady API"}
