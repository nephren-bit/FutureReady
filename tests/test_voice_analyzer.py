"""
Unit tests for the voice analyzer, the audio extractor, and the
generalization of events/detector.py to run over a VoiceFeature the same
way it already runs over a PoseFeature (Group A of specs/in-class-analysis/
tasks.md's follow-up: voice analysis and marking).

No real speech recognition runs here: `VoiceAnalyzer.analyze` takes a
`transcribe_fn` callable, so filler-word detection is exercised against a
fake transcript instead of a real (slow, CPU-only) Whisper call -- the same
reason tests/test_pose_analyzer.py never runs real MediaPipe.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import pytest

from analyzers.voice_analyzer import (
    FILLER_WORDS,
    SIGNAL_FILLER_WORD,
    SIGNAL_LOW_VOLUME,
    SIGNAL_SILENT,
    VoiceAnalyzer,
)
from events.detector import EventDetector
from extractors.audio_extractor import AudioExtractionError, AudioExtractor
from models.features import PoseFeature, PoseFrameSample, PoseMetric, VoiceFeature, VoiceFrameSample
from services.profile_loader import load_profile

_SAMPLE_RATE = 8000  # low but plenty for RMS-window tests; keeps arrays small


def _tone(duration_sec: float, amplitude: float, sample_rate: int = _SAMPLE_RATE) -> np.ndarray:
    """A steady 220 Hz sine segment at the given amplitude -- 0.0 amplitude is silence."""
    count = int(duration_sec * sample_rate)
    t = np.arange(count) / sample_rate
    return (amplitude * np.sin(2 * np.pi * 220.0 * t)).astype(np.float32)


def _concat(*segments: np.ndarray) -> np.ndarray:
    return np.concatenate(segments)


class TestFrameSampleValidity:
    def test_pose_frame_sample_is_valid_mirrors_pose_detected(self) -> None:
        assert PoseFrameSample(pose_detected=True).is_valid is True
        assert PoseFrameSample(pose_detected=False).is_valid is False

    def test_voice_frame_sample_is_valid_mirrors_audio_analyzed(self) -> None:
        assert VoiceFrameSample(audio_analyzed=True).is_valid is True
        assert VoiceFrameSample(audio_analyzed=False).is_valid is False


class TestVoiceAnalyzerLoudness:
    def test_silence_ratio_and_e_long_silence(self) -> None:
        # 3 windows loud, 8 windows silent (>= E_LONG_SILENCE's 3.0s minimum
        # once the run's own under-counted duration is taken -- see the
        # comment on Segment.duration_sec in events/rules.py), 3 windows loud.
        samples = _concat(
            _tone(1.5, 0.5), np.zeros(4000 * 8, dtype=np.float32), _tone(1.5, 0.5)
        )
        feature = VoiceAnalyzer("presentation_solo").analyze(samples, _SAMPLE_RATE, duration_sec=7.0)

        assert feature.silence_ratio.measured is True
        assert feature.silence_ratio.value == pytest.approx(8 / 14, abs=1e-4)
        assert feature.windows_analyzed == 14

        # First 3 windows non-silent, next 8 silent -- signal written explicitly both ways.
        assert [round(s.signals[SIGNAL_SILENT]) for s in feature.series] == [0, 0, 0] + [1] * 8 + [0, 0, 0]

        events = EventDetector("presentation_solo").detect("s1", feature)
        silence_events = [e for e in events if e.type == "E_LONG_SILENCE"]
        assert len(silence_events) == 1
        assert silence_events[0].start_sec == pytest.approx(1.5, abs=1e-6)
        assert silence_events[0].duration_sec == pytest.approx(3.5, abs=1e-6)
        assert "Im lặng" in silence_events[0].label

    def test_low_volume_ratio_and_e_low_volume(self) -> None:
        # 6 loud windows, 8 quiet-but-audible windows, 6 loud windows -- the
        # quiet stretch is well under 40% of the recording's own median
        # voiced RMS (its own reference, like postural_sway), but never
        # below the silence floor.
        samples = _concat(
            _tone(3.0, 0.5), _tone(4.0, 0.05), _tone(3.0, 0.5)
        )
        feature = VoiceAnalyzer("presentation_solo").analyze(samples, _SAMPLE_RATE, duration_sec=10.0)

        assert feature.silence_ratio.value == pytest.approx(0.0, abs=1e-6)
        assert feature.low_volume_ratio.measured is True
        assert feature.low_volume_ratio.value == pytest.approx(8 / 20, abs=1e-6)

        events = EventDetector("presentation_solo").detect("s1", feature)
        low_volume_events = [e for e in events if e.type == "E_LOW_VOLUME"]
        assert len(low_volume_events) == 1
        assert low_volume_events[0].start_sec == pytest.approx(3.0, abs=1e-6)
        assert low_volume_events[0].duration_sec == pytest.approx(3.5, abs=1e-6)
        assert "Nói nhỏ" in low_volume_events[0].label

    def test_entirely_silent_recording_leaves_low_volume_not_measured(self) -> None:
        feature = VoiceAnalyzer("presentation_solo").analyze(
            np.zeros(4000 * 4, dtype=np.float32), _SAMPLE_RATE, duration_sec=2.0
        )
        assert feature.silence_ratio.value == pytest.approx(1.0)
        assert feature.low_volume_ratio.measured is False
        assert feature.low_volume_ratio.reason

    def test_no_windows_reports_not_measured_not_zero(self) -> None:
        feature = VoiceAnalyzer("presentation_solo").analyze(
            np.array([], dtype=np.float32), _SAMPLE_RATE, duration_sec=0.0
        )
        assert feature.silence_ratio.measured is False
        assert feature.silence_ratio.value is None
        assert feature.low_volume_ratio.measured is False


class TestVoiceAnalyzerFillerWords:
    def test_without_transcribe_fn_filler_word_rate_is_not_measured(self) -> None:
        feature = VoiceAnalyzer("presentation_solo").analyze(_tone(2.0, 0.5), _SAMPLE_RATE, duration_sec=2.0)
        assert feature.filler_word_rate.measured is False
        assert feature.filler_word_rate.reason

    def test_filler_words_counted_and_marked_at_the_right_windows(self) -> None:
        words = [
            {"text": "Xin", "start": 0.1, "end": 0.4},  # not a filler word
            {"text": "ừm,", "start": 2.0, "end": 2.2},  # filler, punctuation/case stripped
            {"text": "À", "start": 8.0, "end": 8.1},  # filler, far from the first -- separate event
        ]
        feature = VoiceAnalyzer("presentation_solo").analyze(
            _tone(10.0, 0.5), _SAMPLE_RATE, duration_sec=10.0, transcribe_fn=lambda s, sr: words
        )

        assert feature.filler_word_rate.measured is True
        assert feature.filler_word_rate.value == pytest.approx(2 / (10.0 / 60.0), abs=1e-6)

        # Window 4 (2.0s / 0.5s) and window 16 (8.0s / 0.5s) carry the marker;
        # every other window explicitly carries 0.0, not an absent key.
        assert feature.series[4].signals[SIGNAL_FILLER_WORD] == 1.0
        assert feature.series[16].signals[SIGNAL_FILLER_WORD] == 1.0
        assert feature.series[0].signals[SIGNAL_FILLER_WORD] == 0.0

        events = EventDetector("presentation_solo").detect("s1", feature)
        filler_events = [e for e in events if e.type == "E_FILLER_WORD"]
        assert len(filler_events) == 2
        assert all(e.duration_sec == 0.0 for e in filler_events)
        assert filler_events[0].label == "Dùng từ đệm"

    def test_filler_words_within_merge_gap_collapse_into_one_occurrence(self) -> None:
        # 2.0s and 3.0s are 1s apart (<= E_FILLER_WORD's 2.0s merge_gap_sec)
        # and land in non-adjacent windows (4 and 6, window 5 stays 0) --
        # this exercises the dedupe path, not just adjacent-window merging.
        words = [{"text": "ừm", "start": 2.0, "end": 2.1}, {"text": "à", "start": 3.0, "end": 3.1}]
        feature = VoiceAnalyzer("presentation_solo").analyze(
            _tone(6.0, 0.5), _SAMPLE_RATE, duration_sec=6.0, transcribe_fn=lambda s, sr: words
        )
        assert feature.filler_word_rate.value == pytest.approx(2 / (6.0 / 60.0), abs=1e-6)

        events = EventDetector("presentation_solo").detect("s1", feature)
        filler_events = [e for e in events if e.type == "E_FILLER_WORD"]
        assert len(filler_events) == 1

    def test_a_failing_transcribe_fn_leaves_filler_word_rate_not_measured(self) -> None:
        def _boom(samples, sample_rate):
            raise RuntimeError("model unavailable")

        feature = VoiceAnalyzer("presentation_solo").analyze(
            _tone(2.0, 0.5), _SAMPLE_RATE, duration_sec=2.0, transcribe_fn=_boom
        )
        assert feature.filler_word_rate.measured is False
        assert "model unavailable" in feature.filler_word_rate.reason

    def test_filler_word_list_is_lowercase_and_whole_words(self) -> None:
        # Sanity check on the list itself: no accidental substrings/mixed case.
        assert all(word == word.lower() for word in FILLER_WORDS)
        assert " " not in "".join(FILLER_WORDS)  # every entry is a single token


class TestEventDetectorRunsOverEitherFeatureType:
    """
    events/detector.py's EventRule/EventDetector are written against "a
    series of timestamped samples exposing .is_valid/.signals plus a
    .metric(name)" -- not against PoseFeature specifically. A rule whose
    requires_metrics names the other analyzer's metric must be silently
    skipped, never crash and never fire on the wrong feature.
    """

    def test_a_pose_feature_never_fires_voice_rules(self) -> None:
        measured = PoseMetric.measure(0.5, "x")
        pose = PoseFeature(
            profile="presentation_solo",
            profile_version=load_profile("presentation_solo").version,
            series=[PoseFrameSample(timestamp_sec=0.0, pose_detected=True, signals={"head_up": 1.0})],
            head_up_ratio=measured,
            postural_sway=measured,
            movement_range=measured,
            gesture_rate=measured,
            closed_posture_ratio=measured,
            shoulder_tilt=measured,
            turned_away_ratio=measured,
        )
        events = EventDetector("presentation_solo").detect("s1", pose)
        assert all(not e.type.startswith(("E_LONG_SILENCE", "E_LOW_VOLUME", "E_FILLER_WORD")) for e in events)

    def test_a_voice_feature_never_fires_pose_rules(self) -> None:
        feature = VoiceAnalyzer("presentation_solo").analyze(
            np.zeros(4000 * 8, dtype=np.float32), _SAMPLE_RATE, duration_sec=4.0
        )
        events = EventDetector("presentation_solo").detect("s1", feature)
        pose_only_types = {
            "E_HEAD_DOWN", "E_STATIC", "E_PACING", "E_TURNED_AWAY",
            "E_CLOSED_POSTURE", "E_GESTURE", "E_HEAD_UP", "E_POSTURAL_SWAY_SPIKE",
        }
        assert not any(e.type in pose_only_types for e in events)
        assert any(e.type == "E_LONG_SILENCE" for e in events)


class TestAudioExtractor:
    def test_a_file_with_no_audio_track_raises(self, tmp_path: Path) -> None:
        garbage = tmp_path / "not_a_video.mp4"
        garbage.write_bytes(b"this is not a real video file")
        with pytest.raises(AudioExtractionError):
            AudioExtractor().extract_with_samples(garbage)

    def test_extracts_a_real_audio_track_via_ffmpeg(self, tmp_path: Path) -> None:
        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not on PATH in this environment")

        video_path = tmp_path / "tone.mp4"
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                "-f", "lavfi", "-i", "color=c=blue:size=64x64:duration=2",
                "-shortest", str(video_path),
            ],
            capture_output=True,
        )
        if result.returncode != 0:
            pytest.skip(f"could not synthesize a test clip with this ffmpeg build: {result.stderr[-300:]!r}")

        feature, samples = AudioExtractor().extract_with_samples(video_path)
        assert feature.duration_sec == pytest.approx(2.0, abs=0.15)
        assert feature.sample_rate == 16000
        assert len(samples) > 0
        assert np.any(samples)
