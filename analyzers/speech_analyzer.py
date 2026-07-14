"""
analyzers/speech_analyzer.py

Speech Intelligence analyzer (Layer 2A): runs OpenAI Whisper on a speech
recording to produce a transcript with per-segment timestamps and
confidence, detected language, duration, and words-per-minute. This is the
ONLY place in the pipeline that turns audio into text; everything
downstream (TranscriptAnalyzer, Gemini) works from this transcript, never
from raw audio.

Whisper is loaded lazily (on first use) and cached as a module-level
singleton per model size, since loading the model is expensive and the
model is stateless/thread-safe for inference.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from analyzers.base import BaseAnalyzer
from config import settings
from models.features import SpeechIntelligenceFeature, TranscriptSegment
from utils.logger import get_logger

logger = get_logger(__name__)

_MODEL_CACHE: dict[str, Any] = {}


def _load_whisper_model(model_size: str) -> Any:
    """Load (and cache) a Whisper model by size, e.g. 'base', 'small'."""
    if model_size not in _MODEL_CACHE:
        import whisper  # local import: keep this heavy optional dependency lazy

        logger.info("Loading Whisper model '%s' (first use, this may take a while)...", model_size)
        _MODEL_CACHE[model_size] = whisper.load_model(model_size)
    return _MODEL_CACHE[model_size]


class SpeechAnalyzer(BaseAnalyzer[Path, SpeechIntelligenceFeature]):
    """Whisper-based speech-to-text analyzer (Layer 2A)."""

    def __init__(self, model_size: str | None = None) -> None:
        """
        Args:
            model_size: Whisper model size (tiny/base/small/medium/large).
                Defaults to `settings.WHISPER_MODEL_SIZE`.
        """
        self._model_size = model_size or settings.WHISPER_MODEL_SIZE

    def analyze(self, data: Path) -> SpeechIntelligenceFeature:
        """
        Transcribe an audio file and return a `SpeechIntelligenceFeature`.

        Args:
            data: Path to the audio (or extracted-audio) file on disk.

        Returns:
            A `SpeechIntelligenceFeature` with transcript, language,
            timestamped segments, confidence, duration, and WPM.

        Raises:
            RuntimeError: If Whisper fails to transcribe the file.
        """
        try:
            model = _load_whisper_model(self._model_size)
            result = model.transcribe(str(data), verbose=False)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Whisper transcription failed for %s", data)
            raise RuntimeError(f"Speech transcription failed: {exc}") from exc

        segments_raw = result.get("segments", []) or []
        segments = [
            TranscriptSegment(
                start_sec=round(float(seg.get("start", 0.0)), 2),
                end_sec=round(float(seg.get("end", 0.0)), 2),
                text=str(seg.get("text", "")).strip(),
                confidence=self._logprob_to_confidence(seg.get("avg_logprob", 0.0)),
            )
            for seg in segments_raw
        ]

        transcript = str(result.get("text", "")).strip()
        language = str(result.get("language", "")) or "unknown"
        duration_sec = segments[-1].end_sec if segments else 0.0
        word_count = len(transcript.split())
        words_per_minute = (
            round(word_count / (duration_sec / 60.0), 2) if duration_sec > 0 else 0.0
        )
        average_confidence = (
            round(sum(seg.confidence for seg in segments) / len(segments), 3) if segments else 0.0
        )

        return SpeechIntelligenceFeature(
            transcript=transcript,
            language=language,
            segments=segments,
            average_confidence=average_confidence,
            duration_sec=duration_sec,
            words_per_minute=words_per_minute,
            word_count=word_count,
        )

    @staticmethod
    def _logprob_to_confidence(avg_logprob: float) -> float:
        """
        Convert Whisper's `avg_logprob` (a log-probability, typically in
        [-1, 0] for confident segments) into a bounded [0, 1] confidence
        score via `exp(avg_logprob)`, clipped defensively.
        """
        try:
            confidence = math.exp(float(avg_logprob))
        except (OverflowError, ValueError):
            confidence = 0.0
        return round(min(max(confidence, 0.0), 1.0), 3)
