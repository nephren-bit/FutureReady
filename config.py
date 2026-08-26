"""
config.py

Centralized application configuration.

Loads environment variables from a .env file (via python-dotenv) and exposes
a single `settings` object that the rest of the application imports from.

(This module used to also configure API keys/models for three LLM reasoning
providers and document-upload limits for a larger evaluation pipeline --
removed along with that pipeline. See git history before the removal commit
if any of that is needed again.)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

# Load environment variables from a .env file located at the project root.
# If no .env file is present, environment variables set in the shell are used.
load_dotenv()


class Settings:
    """
    Application settings.

    Attributes:
        VIDEO_SAMPLE_FRAME_COUNT: Number of frames sampled per video for the
            pose analyzer.
        UPLOAD_DIR: Directory where uploaded recordings are stored.
        MAX_VIDEO_SIZE_MB: Maximum allowed upload size for video files, in MB.
        LOG_LEVEL: Logging verbosity for the application logger.
        DATABASE_URL: SQLAlchemy connection string for the session-persistence
            PostgreSQL database (see db/session.py). Uses the psycopg3 driver
            by default (`postgresql+psycopg://...`).
    """

    VIDEO_SAMPLE_FRAME_COUNT: Final[int] = int(os.getenv("VIDEO_SAMPLE_FRAME_COUNT", "60"))

    UPLOAD_DIR: Final[Path] = Path(os.getenv("UPLOAD_DIR", "uploads"))

    MAX_FILE_SIZE_MB: Final[int] = int(os.getenv("MAX_FILE_SIZE_MB", "25"))
    MAX_FILE_SIZE_BYTES: Final[int] = MAX_FILE_SIZE_MB * 1024 * 1024

    MAX_VIDEO_SIZE_MB: Final[int] = int(os.getenv("MAX_VIDEO_SIZE_MB", "300"))
    MAX_VIDEO_SIZE_BYTES: Final[int] = MAX_VIDEO_SIZE_MB * 1024 * 1024

    LOG_LEVEL: Final[str] = os.getenv("LOG_LEVEL", "INFO")

    DATABASE_URL: Final[str] = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://futureready:futureready@localhost:5432/futureready",
    )


settings = Settings()
