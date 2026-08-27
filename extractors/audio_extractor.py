"""
extractors/audio_extractor.py

Extracts the raw audio waveform from a recorded video, for
analyzers/voice_analyzer.py. Mirrors extractors/video_extractor.py's split
between a small structured feature (AudioTrackFeature: just enough to know
what was extracted) and the raw data handed to the next stage (a numpy
sample array, never serialized or stored).

ffmpeg does the decoding (subprocess, not a Python binding) because the
video's audio track is whatever codec the browser's MediaRecorder produced
(usually AAC/Opus in a container soundfile can't read directly) --
`ffmpeg -vn` strips video and re-encodes straight to a mono 16 kHz WAV,
which soundfile always reads and which is also openai-whisper's own native
input rate, so nothing gets resampled twice.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
from pydantic import BaseModel, Field

from utils.logger import get_logger

logger = get_logger(__name__)

# openai-whisper's own native sample rate -- extracting straight to this
# means analyzers/voice_analyzer.py never has to resample before handing
# samples to Whisper.
TARGET_SAMPLE_RATE = 16000

_FFMPEG_TIMEOUT_SEC = 120


class AudioTrackFeature(BaseModel):
    """Just enough about the extracted track for the analyzer to work from."""

    duration_sec: float = Field(0.0, ge=0.0)
    sample_rate: int = Field(0, ge=0)


class AudioExtractionError(RuntimeError):
    """
    Raised when no usable audio could be extracted -- no audio track at all,
    a muted recording, or ffmpeg itself failing. Callers (`services/
    self_practice_manager.py`) treat this as "voice analysis not possible
    for this recording", not as a reason to fail the whole self-practice
    session -- the pose events are still a complete result on their own.
    """


class AudioExtractor:
    """Extracts a mono 16 kHz waveform from a video file's audio track (Layer 1)."""

    def extract_with_samples(self, file_path: Path) -> tuple[AudioTrackFeature, np.ndarray]:
        """
        Args:
            file_path: Path to the video file on disk.

        Returns:
            A 2-tuple of (AudioTrackFeature, mono float32 samples in [-1, 1]
            at `TARGET_SAMPLE_RATE`).

        Raises:
            AudioExtractionError: If the file has no audio track, ffmpeg is
                not available, or the extracted track is entirely silent.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            wav_path = Path(tmp_dir) / "audio.wav"
            try:
                result = subprocess.run(
                    [
                        "ffmpeg", "-y", "-i", str(file_path),
                        "-vn", "-ac", "1", "-ar", str(TARGET_SAMPLE_RATE),
                        str(wav_path),
                    ],
                    capture_output=True,
                    timeout=_FFMPEG_TIMEOUT_SEC,
                )
            except FileNotFoundError as exc:
                raise AudioExtractionError("Không tìm thấy ffmpeg trên hệ thống để tách âm thanh.") from exc
            except subprocess.TimeoutExpired as exc:
                raise AudioExtractionError("Tách âm thanh quá thời gian cho phép.") from exc

            if result.returncode != 0 or not wav_path.exists():
                stderr_tail = result.stderr.decode("utf-8", errors="ignore")[-400:]
                logger.info("ffmpeg audio extraction failed for %s: %s", file_path, stderr_tail)
                raise AudioExtractionError(
                    "Không trích được track âm thanh từ video (có thể video không có âm thanh, "
                    "hoặc bị tắt tiếng)."
                )

            samples, sample_rate = sf.read(str(wav_path), dtype="float32", always_2d=False)

        if samples.ndim > 1:
            samples = samples.mean(axis=1)
        duration_sec = len(samples) / sample_rate if sample_rate else 0.0

        if duration_sec <= 0 or not np.any(samples):
            raise AudioExtractionError(
                "Track âm thanh trống hoặc hoàn toàn im lặng (có thể video bị tắt tiếng)."
            )

        return AudioTrackFeature(duration_sec=round(duration_sec, 2), sample_rate=int(sample_rate)), samples
