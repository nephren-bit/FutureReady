"""
analyzers/voice_analyzer.py

Turns a raw audio waveform (extractors/audio_extractor.py) into a
`VoiceFeature`: windowed loudness signals (silence / low volume, from RMS
energy alone -- always available, no speech recognition needed) and,
when a transcription function is supplied, filler-word occurrences.

Mirrors analyzers/pose_analyzer.py's split between per-window signals
(consumed by events/detector.py through the exact same generic
`EventRule`/`EventDetector` -- see that module's docstring) and
whole-recording aggregates (`PoseMetric`, reused as-is: it was never
pose-specific, just "a value with a measured flag and a reason").

Speech-to-text (openai-whisper) is optional and injected as
`transcribe_fn` rather than called directly, for the same reason
`analyzers/pose_analyzer.py` takes already-detected landmarks instead of
running MediaPipe itself: tests exercise the windowing/threshold logic on
synthetic waveforms without paying for a real (slow, CPU-only in this
environment) transcription. `transcribe_with_whisper` below is the real
implementation `services/self_practice_manager.py` wires in.

PROVISIONAL, like every threshold added alongside `trigger: edge`
(config/profiles/presentation_solo.yaml's own header comment) -- none of
the numbers here have run through Task 9's blind-rating comparison. The
Vietnamese filler-word list is incomplete by construction (it varies by
speaker and region); the RMS silence floor and the low-volume relative
threshold are starting points, not calibrated levels.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable

import numpy as np

from models.features import PoseMetric, VoiceFeature, VoiceFrameSample
from models.profiles import ContextProfile
from services.profile_loader import load_profile
from utils.logger import get_logger

logger = get_logger(__name__)

_ROUND_DECIMALS = 4

# RMS window length for the time series events/detector.py runs over. Also
# the resolution filler-word occurrences snap to (a word's window is
# whichever half-second it starts in).
_WINDOW_SEC = 0.5

# Per-metric geometry constants, overridable from config/profiles/*.yaml's
# `metrics.<name>.params` (ContextProfile.metric_params) -- same pattern as
# analyzers/pose_analyzer.py's `_param`/`_DEFAULT_PARAMS`.
_DEFAULT_PARAMS: dict[str, float] = {
    # Below this raw RMS amplitude (float samples in [-1, 1]) a window
    # counts as silence. An absolute floor, not the recording's own
    # reference (unlike low_volume_relative_threshold below): near-total
    # silence looks the same regardless of a webcam mic's gain, so there is
    # no "self as baseline" to compare against the way postural_sway does.
    "silence_rms_floor": 0.01,
    # A non-silent window counts as "low volume" when its RMS is below this
    # fraction of the recording's own median RMS among its non-silent
    # windows -- self-referential like turned_away_ratio/postural_sway,
    # because absolute loudness varies hugely by mic and distance but
    # "quieter than this person's own typical voice" does not.
    "low_volume_relative_threshold": 0.4,
}

SIGNAL_SILENT = "voice_silent"
SIGNAL_LOW_VOLUME = "voice_low_volume"
SIGNAL_FILLER_WORD = "filler_word_active"

# One transcribed word: {"text": str, "start": seconds, "end": seconds}.
TranscribeFn = Callable[[np.ndarray, int], list[dict]]

# Deliberately incomplete (see module docstring) -- extend as real
# recordings surface more. Matched as a whole word after stripping
# punctuation and lowercasing, never as a substring: "thì" alone would
# otherwise also match inside unrelated words.
FILLER_WORDS = frozenset({
    "ừ", "ừm", "ờ", "ơ", "à", "ấy", "thì", "kiểu", "này",
})

_STRIP_CHARS = ".,!?;:…\"'"


class VoiceAnalyzer:
    """Computes windowed loudness signals and (optionally) filler-word occurrences."""

    def __init__(self, profile: ContextProfile | str | None = None) -> None:
        """
        Args:
            profile: Context profile, its name, or `None` for the default
                (`presentation_class`) -- only used for `metric_params`
                lookups, same as `PoseAnalyzer`.
        """
        self._profile = profile if isinstance(profile, ContextProfile) else (
            load_profile(profile) if profile else load_profile()
        )

    def analyze(
        self,
        samples: np.ndarray,
        sample_rate: int,
        duration_sec: float,
        source_fps: float = 0.0,
        transcribe_fn: TranscribeFn | None = None,
    ) -> VoiceFeature:
        """
        Args:
            samples: Mono waveform, float in [-1, 1].
            sample_rate: Sample rate of `samples`, in Hz.
            duration_sec: Recording length -- used for `filler_word_rate`'s
                per-minute rate, not re-derived from `len(samples)` in case
                the caller trimmed silence at the edges.
            source_fps: The original video's frame rate, carried onto
                `VoiceFeature.source_fps` (see that field's docstring).
            transcribe_fn: When given, run it once to get word-level
                timestamps and derive `filler_word_rate` / the
                `filler_word_active` signal from them. When omitted,
                `filler_word_rate` reports `không đo được` -- voice analysis
                without speech recognition still yields silence/volume
                signals, it just cannot see filler words.
        """
        windows = self._window_rms(samples, sample_rate)
        series = [
            VoiceFrameSample(timestamp_sec=round(ts, _ROUND_DECIMALS), audio_analyzed=True)
            for ts, _rms in windows
        ]

        silence_ratio, low_volume_ratio = self._write_loudness_signals(series, windows)

        filler_word_rate = PoseMetric.not_measured(
            "lần/phút", "Chưa bật nhận dạng giọng nói cho bản ghi này."
        )
        if transcribe_fn is not None:
            try:
                words = transcribe_fn(samples, sample_rate)
                filler_word_rate = self._write_filler_word_signal(series, words, duration_sec)
            except Exception as exc:  # noqa: BLE001 -- best-effort, never fails the whole session
                logger.warning("Voice transcription failed: %s", exc)
                filler_word_rate = PoseMetric.not_measured(
                    "lần/phút", f"Nhận dạng giọng nói thất bại: {exc}"
                )

        return VoiceFeature(
            profile=self._profile.profile,
            profile_version=self._profile.version,
            windows_analyzed=len(series),
            source_fps=source_fps,
            silence_ratio=silence_ratio,
            low_volume_ratio=low_volume_ratio,
            filler_word_rate=filler_word_rate,
            series=series,
        )

    # ------------------------------------------------------------------

    def _param(self, metric: str, name: str) -> float:
        """One geometry constant, from the profile, falling back to the module default."""
        return self._profile.metric_params(metric).get(name, _DEFAULT_PARAMS[name])

    def _window_rms(self, samples: np.ndarray, sample_rate: int) -> list[tuple[float, float]]:
        """RMS energy of each non-overlapping `_WINDOW_SEC` window, as (timestamp_sec, rms) pairs."""
        window_len = max(1, int(_WINDOW_SEC * sample_rate))
        windows: list[tuple[float, float]] = []
        for start in range(0, len(samples), window_len):
            chunk = samples[start : start + window_len]
            if len(chunk) == 0:
                continue
            rms = float(np.sqrt(np.mean(np.square(chunk))))
            windows.append((start / sample_rate, rms))
        return windows

    def _write_loudness_signals(
        self, series: list[VoiceFrameSample], windows: list[tuple[float, float]]
    ) -> tuple[PoseMetric, PoseMetric]:
        """
        Writes `voice_silent`/`voice_low_volume` onto every window (like
        `pose_analyzer._write_static_signals` always writes 0.0 or 1.0 for a
        computable signal, never leaving a computable one absent), and
        returns the whole-recording `silence_ratio`/`low_volume_ratio`.
        """
        if not windows:
            insufficient = PoseMetric.not_measured("tỷ lệ 0-1", "Không đủ dữ liệu âm thanh để đo.")
            return insufficient, insufficient

        silence_floor = self._param("silence_ratio", "silence_rms_floor")
        rms_values = [rms for _ts, rms in windows]
        silent_flags = [rms < silence_floor for rms in rms_values]

        for sample, silent in zip(series, silent_flags):
            sample.signals[SIGNAL_SILENT] = 1.0 if silent else 0.0

        silence_ratio = PoseMetric.measure(sum(silent_flags) / len(silent_flags), "tỷ lệ 0-1")

        voiced_rms = [rms for rms, silent in zip(rms_values, silent_flags) if not silent]
        if not voiced_rms:
            low_volume_ratio = PoseMetric.not_measured(
                "tỷ lệ 0-1", "Toàn bộ bản ghi là khoảng lặng, không đo được âm lượng lời nói."
            )
            return silence_ratio, low_volume_ratio

        relative_threshold = self._param("low_volume_ratio", "low_volume_relative_threshold")
        low_volume_limit = statistics.median(voiced_rms) * relative_threshold

        low_volume_flags: list[bool] = []
        for sample, rms, silent in zip(series, rms_values, silent_flags):
            if silent:
                continue
            low = rms < low_volume_limit
            sample.signals[SIGNAL_LOW_VOLUME] = 1.0 if low else 0.0
            low_volume_flags.append(low)

        low_volume_ratio = PoseMetric.measure(sum(low_volume_flags) / len(low_volume_flags), "tỷ lệ 0-1")
        return silence_ratio, low_volume_ratio

    def _write_filler_word_signal(
        self, series: list[VoiceFrameSample], words: list[dict], duration_sec: float
    ) -> PoseMetric:
        """
        Marks the window each recognized filler word starts in, writes an
        explicit 0.0 everywhere else, and returns the whole-recording rate
        per minute (like `pose_analyzer._gesture_rate`).
        """
        for sample in series:
            sample.signals.setdefault(SIGNAL_FILLER_WORD, 0.0)

        count = 0
        for word in words:
            text = str(word.get("text", "")).strip().lower().strip(_STRIP_CHARS)
            if text not in FILLER_WORDS:
                continue
            count += 1
            if not series:
                continue
            index = min(int(float(word.get("start", 0.0)) / _WINDOW_SEC), len(series) - 1)
            series[index].signals[SIGNAL_FILLER_WORD] = 1.0

        if duration_sec <= 0:
            return PoseMetric.not_measured("lần/phút", "Bản ghi quá ngắn để tính tần suất từ đệm.")
        return PoseMetric.measure(count / (duration_sec / 60.0), "lần/phút")


# ---------------------------------------------------------------------------
# The real `transcribe_fn` -- kept separate from `VoiceAnalyzer` so tests
# never import `whisper`/`torch` (heavy, CPU-only in this environment).
# ---------------------------------------------------------------------------

_WHISPER_MODEL_NAME = "base"
_whisper_model = None


def _get_whisper_model():
    global _whisper_model
    if _whisper_model is None:
        import whisper  # local import: keep this heavy optional dependency out of app import time

        logger.info("Loading Whisper model '%s' for voice analysis...", _WHISPER_MODEL_NAME)
        _whisper_model = whisper.load_model(_WHISPER_MODEL_NAME)
    return _whisper_model


def transcribe_with_whisper(samples: np.ndarray, sample_rate: int) -> list[dict]:
    """
    The real `VoiceAnalyzer.analyze(transcribe_fn=...)` implementation --
    runs openai-whisper locally (no network call once the model is cached
    on disk; see the module docstring for the accuracy caveat). CPU-only in
    this environment, so this is the slow step of the self-practice
    pipeline: a multi-minute recording can take noticeably longer than its
    own length to transcribe. That is acceptable here because it runs in
    the background task, off the HTTP request.

    Args:
        samples: Mono waveform, float in [-1, 1].
        sample_rate: Must be Whisper's own native rate (`extractors.
            audio_extractor.TARGET_SAMPLE_RATE`) -- `AudioExtractor` already
            extracts at that rate, so no resampling happens here.
    """
    import whisper

    if sample_rate != whisper.audio.SAMPLE_RATE:
        raise ValueError(
            f"transcribe_with_whisper expects {whisper.audio.SAMPLE_RATE} Hz audio, got {sample_rate}."
        )

    model = _get_whisper_model()
    result = model.transcribe(samples.astype(np.float32), language="vi", word_timestamps=True, fp16=False)

    words: list[dict] = []
    for segment in result.get("segments", []):
        for word in segment.get("words", []):
            words.append({"text": word["word"], "start": word["start"], "end": word["end"]})
    return words
