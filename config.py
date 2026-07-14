"""
config.py

Centralized application configuration.

Loads environment variables from a .env file (via python-dotenv) and exposes
a single `settings` object that the rest of the application imports from.
Keeping configuration in one place avoids scattering `os.getenv` calls
throughout the codebase and makes the app easy to reconfigure for different
environments (local, staging, production).
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Final

import yaml
from dotenv import load_dotenv

# Load environment variables from a .env file located at the project root.
# If no .env file is present, environment variables set in the shell are used.
load_dotenv()


class Settings:
    """
    Application settings.

    Attributes:
        GEMINI_API_KEY: API key used to authenticate with the Gemini API.
        GEMINI_MODEL: Name of the Gemini model to use for all requests.
        ANTHROPIC_API_KEY: API key used to authenticate with the Claude API.
        CLAUDE_MODEL: Name of the Claude model to use for all requests.
        LMSTUDIO_BASE_URL: Base URL of a local LM Studio server's
            OpenAI-compatible API (see https://lmstudio.ai/docs/local-server).
        LMSTUDIO_API_KEY: Dummy credential -- LM Studio's local server doesn't
            validate it, but the `openai` SDK requires a non-empty string.
        LMSTUDIO_MODEL: Exact identifier of the model currently loaded in LM
            Studio (see the "My Models" tab, or `GET {LMSTUDIO_BASE_URL}/models`).
        WHISPER_MODEL_SIZE: OpenAI Whisper model size used for speech-to-text
            (tiny/base/small/medium/large). Larger models are more accurate
            but slower and heavier to load.
        HSEMOTION_MODEL_NAME: HSEmotion (ONNX) model name used for facial
            emotion classification.
        VIDEO_SAMPLE_FRAME_COUNT: Number of frames sampled per video for the
            vision analyzers (emotion / face mesh) and CV feature extraction.
        UPLOAD_DIR: Directory where uploaded files are temporarily stored.
        MAX_FILE_SIZE_MB: Maximum allowed upload size for documents/audio, in MB.
        MAX_VIDEO_SIZE_MB: Maximum allowed upload size for video files, in MB
            (kept separate since videos are legitimately much larger).
        LOG_LEVEL: Logging verbosity for the application logger.
        ALLOWED_PDF_EXTENSIONS: Accepted extensions for resume uploads.
        ALLOWED_PPTX_EXTENSIONS: Accepted extensions for slide uploads.
        ALLOWED_AUDIO_EXTENSIONS: Accepted extensions for audio uploads.
        ALLOWED_VIDEO_EXTENSIONS: Accepted extensions for video uploads.
        DATABASE_URL: SQLAlchemy connection string for the session-persistence
            PostgreSQL database (see db/session.py). Uses the psycopg3 driver
            by default (`postgresql+psycopg://...`).
        SCORING_ENGINE_VERSION: Version tag stamped onto every `ScoreResult`
            row, so historical scores remain attributable to the exact
            formula revision that produced them even after the Scoring
            Engine is later updated.
        FEATURE_FUSION_VERSION: Version tag stamped onto every fused
            `UnifiedFeature` row, for the same reproducibility reason.
    """

    GEMINI_API_KEY: Final[str] = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: Final[str] = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    ANTHROPIC_API_KEY: Final[str] = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL: Final[str] = os.getenv("CLAUDE_MODEL", "claude-sonnet-5")

    LMSTUDIO_BASE_URL: Final[str] = os.getenv("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
    LMSTUDIO_API_KEY: Final[str] = os.getenv("LMSTUDIO_API_KEY", "lm-studio")
    LMSTUDIO_MODEL: Final[str] = os.getenv("LMSTUDIO_MODEL", "")

    WHISPER_MODEL_SIZE: Final[str] = os.getenv("WHISPER_MODEL_SIZE", "base")
    HSEMOTION_MODEL_NAME: Final[str] = os.getenv("HSEMOTION_MODEL_NAME", "enet_b0_8_best_afew")
    VIDEO_SAMPLE_FRAME_COUNT: Final[int] = int(os.getenv("VIDEO_SAMPLE_FRAME_COUNT", "60"))

    UPLOAD_DIR: Final[Path] = Path(os.getenv("UPLOAD_DIR", "uploads"))

    MAX_FILE_SIZE_MB: Final[int] = int(os.getenv("MAX_FILE_SIZE_MB", "25"))
    MAX_FILE_SIZE_BYTES: Final[int] = MAX_FILE_SIZE_MB * 1024 * 1024

    MAX_VIDEO_SIZE_MB: Final[int] = int(os.getenv("MAX_VIDEO_SIZE_MB", "300"))
    MAX_VIDEO_SIZE_BYTES: Final[int] = MAX_VIDEO_SIZE_MB * 1024 * 1024

    LOG_LEVEL: Final[str] = os.getenv("LOG_LEVEL", "INFO")

    ALLOWED_PDF_EXTENSIONS: Final[set[str]] = {".pdf"}
    ALLOWED_PPTX_EXTENSIONS: Final[set[str]] = {".pptx"}
    ALLOWED_AUDIO_EXTENSIONS: Final[set[str]] = {".mp3", ".wav", ".m4a"}
    ALLOWED_VIDEO_EXTENSIONS: Final[set[str]] = {".mp4", ".mov", ".m4v"}

    DATABASE_URL: Final[str] = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://futureready:futureready@localhost:5432/futureready",
    )

    SCORING_ENGINE_VERSION: Final[str] = os.getenv("SCORING_ENGINE_VERSION", "1.0.0")
    FEATURE_FUSION_VERSION: Final[str] = os.getenv("FEATURE_FUSION_VERSION", "1.0.0")

    def validate(self) -> None:
        """
        Validate that required settings are present.

        Only requires the API key for whichever `reasoning_engine` is
        currently selected in `config/providers.yaml` -- e.g. switching to
        `claude` there means `GEMINI_API_KEY` is no longer mandatory. See
        `providers/registry.py`, which reads the same file to decide which
        `BaseReasoningEngine` implementation to construct.

        Raises:
            RuntimeError: If the active engine's API key is missing.
        """
        engine = self._configured_reasoning_engine()
        if engine == "claude" and not self.ANTHROPIC_API_KEY:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Please create a .env file based on "
                ".env.example and set your Anthropic API key."
            )
        if engine == "gemini" and not self.GEMINI_API_KEY:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Please create a .env file based on "
                ".env.example and set your Gemini API key."
            )
        if engine == "lmstudio" and not self.LMSTUDIO_MODEL:
            raise RuntimeError(
                "LMSTUDIO_MODEL is not set. Please create a .env file based on "
                ".env.example and set it to the exact model identifier currently "
                "loaded in LM Studio (see the \"My Models\" tab, or "
                f"GET {self.LMSTUDIO_BASE_URL}/models)."
            )
        self.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _configured_reasoning_engine() -> str:
        """Reads `reasoning_engine` out of `config/providers.yaml` (defaults to `gemini`)."""
        config_path = Path(__file__).resolve().parent / "config" / "providers.yaml"
        if not config_path.exists():
            return "gemini"
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("reasoning_engine", "gemini")


settings = Settings()
