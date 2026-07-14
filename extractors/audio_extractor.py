"""
extractors/audio_extractor.py

Extracts low-level acoustic features from a speech recording (MP3/WAV/M4A)
using Librosa: pitch, tempo, RMS energy, MFCC, chroma, spectral features,
zero-crossing rate, and silence detection. The result is a typed
`AudioFeature` model — Layer 1 only, no AI reasoning.

Speech rate / words-per-minute is intentionally NOT computed here: it
requires a transcript, which is produced later by the Whisper-based
`analyzers/speech_analyzer.py` (Layer 2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import librosa
import numpy as np

from extractors.base import BaseExtractor
from models.features import AudioFeature
from utils.logger import get_logger

logger = get_logger(__name__)

# RMS energy below this threshold (relative to max) is treated as silence.
_SILENCE_RMS_THRESHOLD_RATIO = 0.05
# Minimum duration (seconds) of a low-energy region to count as a pause.
_MIN_PAUSE_DURATION_SEC = 0.3


class AudioExtractor(BaseExtractor[AudioFeature]):
    """Extracts structured acoustic features from an audio file (Layer 1)."""

    def extract(self, file_path: Path) -> AudioFeature:
        """
        Run full feature extraction on an audio file.

        Args:
            file_path: Path to the audio file (mp3/wav/m4a) on disk.

        Returns:
            An `AudioFeature` model with metadata and acoustic statistics.

        Raises:
            RuntimeError: If the audio file cannot be loaded or analyzed.
        """
        try:
            y, sr = librosa.load(str(file_path), sr=None, mono=True)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to load audio %s", file_path)
            raise RuntimeError(f"Could not load audio file: {exc}") from exc

        if y.size == 0:
            raise RuntimeError("Audio file contains no audio data.")

        duration = float(librosa.get_duration(y=y, sr=sr))

        pitch_stats = self._extract_pitch(y, sr)
        tempo = self._extract_tempo(y, sr)
        rms = librosa.feature.rms(y=y)[0]
        mfcc_stats = self._extract_mfcc(y, sr)
        chroma_stats = self._extract_chroma(y, sr)
        spectral_stats = self._extract_spectral(y, sr)
        zcr_stats = self._extract_zcr(y)
        silence_info = self._detect_silence(rms, sr, hop_length=512)

        return AudioFeature(
            sample_rate=int(sr),
            duration_sec=round(duration, 2),
            channels=1,
            pitch_mean_hz=pitch_stats["mean_hz"],
            pitch_std_hz=pitch_stats["std_hz"],
            pitch_min_hz=pitch_stats["min_hz"],
            pitch_max_hz=pitch_stats["max_hz"],
            voiced_ratio=pitch_stats["voiced_ratio"],
            tempo_bpm=tempo,
            rms_mean=round(float(np.mean(rms)), 4) if rms.size else 0.0,
            rms_std=round(float(np.std(rms)), 4) if rms.size else 0.0,
            mfcc_mean=mfcc_stats["mean"],
            mfcc_std=mfcc_stats["std"],
            chroma_mean=chroma_stats["mean"],
            spectral_centroid_mean=spectral_stats["centroid_mean"],
            spectral_bandwidth_mean=spectral_stats["bandwidth_mean"],
            spectral_rolloff_mean=spectral_stats["rolloff_mean"],
            zcr_mean=zcr_stats["zcr_mean"],
            zcr_std=zcr_stats["zcr_std"],
            silence_ratio=silence_info["silence_ratio"],
            total_silence_sec=silence_info["total_silence_sec"],
            silent_region_count=silence_info["silent_region_count"],
        )

    @staticmethod
    def _summarize(values: np.ndarray, label: str) -> dict[str, float]:
        """Compute basic descriptive statistics for a 1D feature array."""
        if values.size == 0:
            return {f"{label}_mean": 0.0, f"{label}_std": 0.0}
        return {
            f"{label}_mean": round(float(np.mean(values)), 4),
            f"{label}_std": round(float(np.std(values)), 4),
        }

    def _extract_pitch(self, y: np.ndarray, sr: int) -> dict[str, float]:
        """Estimate fundamental frequency (pitch) statistics using pyin."""
        try:
            f0, voiced_flag, _ = librosa.pyin(
                y,
                fmin=librosa.note_to_hz("C2"),
                fmax=librosa.note_to_hz("C7"),
                sr=sr,
            )
            voiced_f0 = f0[voiced_flag] if voiced_flag is not None else np.array([])
            voiced_f0 = voiced_f0[~np.isnan(voiced_f0)]
        except Exception:  # noqa: BLE001
            logger.warning("Pitch extraction failed; falling back to empty result.")
            voiced_f0 = np.array([])
            f0 = np.array([])

        if voiced_f0.size == 0:
            return {"mean_hz": 0.0, "std_hz": 0.0, "min_hz": 0.0, "max_hz": 0.0, "voiced_ratio": 0.0}

        return {
            "mean_hz": round(float(np.mean(voiced_f0)), 2),
            "std_hz": round(float(np.std(voiced_f0)), 2),
            "min_hz": round(float(np.min(voiced_f0)), 2),
            "max_hz": round(float(np.max(voiced_f0)), 2),
            "voiced_ratio": round(float(voiced_f0.size / max(f0.size, 1)), 3),
        }

    def _extract_tempo(self, y: np.ndarray, sr: int) -> float:
        """Estimate tempo in BPM using onset-strength-based beat tracking."""
        try:
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo, _ = librosa.beat.beat_track(onset_envelope=onset_env, sr=sr)
            tempo_value = float(tempo[0]) if hasattr(tempo, "__len__") else float(tempo)
            return round(tempo_value, 2)
        except Exception:  # noqa: BLE001
            logger.warning("Tempo extraction failed; defaulting to 0.0")
            return 0.0

    def _extract_mfcc(self, y: np.ndarray, sr: int, n_mfcc: int = 13) -> dict[str, Any]:
        """Compute MFCC coefficients and summarize their mean/std per coefficient."""
        mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc)
        return {
            "mean": [round(float(v), 3) for v in np.mean(mfcc, axis=1)],
            "std": [round(float(v), 3) for v in np.std(mfcc, axis=1)],
        }

    def _extract_chroma(self, y: np.ndarray, sr: int) -> dict[str, Any]:
        """Compute chroma features and summarize their mean per pitch class."""
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        return {"mean": [round(float(v), 3) for v in np.mean(chroma, axis=1)]}

    def _extract_spectral(self, y: np.ndarray, sr: int) -> dict[str, float]:
        """Compute spectral centroid, bandwidth, and rolloff statistics."""
        centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
        bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)[0]
        rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)[0]
        return {
            "centroid_mean": round(float(np.mean(centroid)), 2),
            "bandwidth_mean": round(float(np.mean(bandwidth)), 2),
            "rolloff_mean": round(float(np.mean(rolloff)), 2),
        }

    def _extract_zcr(self, y: np.ndarray) -> dict[str, float]:
        """Compute zero-crossing rate statistics."""
        zcr = librosa.feature.zero_crossing_rate(y)[0]
        return self._summarize(zcr, "zcr")

    def _detect_silence(
        self, rms: np.ndarray, sr: int, hop_length: int = 512
    ) -> dict[str, Any]:
        """
        Detect silent regions based on an RMS energy threshold.

        Args:
            rms: Frame-wise RMS energy array.
            sr: Sample rate.
            hop_length: Hop length used when computing `rms`.

        Returns:
            Dict with total silence duration, silence ratio, and count of
            silent regions long enough to be considered pauses.
        """
        if rms.size == 0:
            return {"silence_ratio": 0.0, "total_silence_sec": 0.0, "silent_region_count": 0}

        threshold = float(np.max(rms)) * _SILENCE_RMS_THRESHOLD_RATIO
        is_silent = rms < threshold

        frame_duration = hop_length / sr
        total_silence_sec = float(np.sum(is_silent)) * frame_duration

        # Count contiguous silent regions that exceed the minimum pause duration.
        min_frames = max(int(_MIN_PAUSE_DURATION_SEC / frame_duration), 1)
        region_count = 0
        run_length = 0
        for silent in is_silent:
            if silent:
                run_length += 1
            else:
                if run_length >= min_frames:
                    region_count += 1
                run_length = 0
        if run_length >= min_frames:
            region_count += 1

        total_duration_sec = rms.size * frame_duration
        silence_ratio = round(total_silence_sec / total_duration_sec, 3) if total_duration_sec else 0.0

        return {
            "silence_ratio": silence_ratio,
            "total_silence_sec": round(total_silence_sec, 2),
            "silent_region_count": region_count,
        }
