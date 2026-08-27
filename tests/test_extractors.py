"""
Unit tests for `extractors/video_extractor.py`, the self-practice pipeline's
one remaining extractor. Builds a minimal, valid video fixture on the fly
via OpenCV rather than shipping a binary test asset; skipped automatically
if OpenCV can't encode an MP4 in this environment.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from models.features import VideoFeature


class TestVideoExtractor:
    def test_extract_returns_video_feature(self, tmp_path: Path) -> None:
        cv2 = pytest.importorskip("cv2")
        from extractors.video_extractor import VideoExtractor

        video_path = tmp_path / "clip.mp4"
        writer = cv2.VideoWriter(
            str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 64)
        )
        for i in range(20):
            frame = np.full((64, 64, 3), fill_value=(i * 10) % 256, dtype=np.uint8)
            writer.write(frame)
        writer.release()

        if not video_path.exists() or video_path.stat().st_size == 0:
            pytest.skip("OpenCV could not encode an MP4 in this environment (missing codec).")

        result = VideoExtractor(sample_count=5).extract(video_path)
        assert isinstance(result, VideoFeature)
        assert result.frame_count == 20
        assert result.sampled_frame_count > 0

    def test_min_sample_rate_hz_raises_the_sample_count_above_the_fixed_floor(self, tmp_path: Path) -> None:
        """
        A profile's own min_sample_rate_hz must win over a low fixed
        sample_count -- this is what fixes the "sampling too sparse"
        warning real several-minute recordings were hitting with a fixed
        count of 60.
        """
        cv2 = pytest.importorskip("cv2")
        from extractors.video_extractor import VideoExtractor

        video_path = tmp_path / "clip.mp4"
        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 64))
        for i in range(20):  # 20 frames @ 10 fps = 2.0s clip
            writer.write(np.full((64, 64, 3), fill_value=(i * 10) % 256, dtype=np.uint8))
        writer.release()
        if not video_path.exists() or video_path.stat().st_size == 0:
            pytest.skip("OpenCV could not encode an MP4 in this environment (missing codec).")

        # sample_count=1 alone would sample a single frame; a 10 Hz floor on
        # a 2s clip needs ~20 -- capped at the video's own 20 real frames.
        result = VideoExtractor(sample_count=1, min_sample_rate_hz=10.0).extract(video_path)
        assert result.sampled_frame_count > 1

    def test_min_sample_rate_hz_never_lowers_a_higher_requested_count(self, tmp_path: Path) -> None:
        cv2 = pytest.importorskip("cv2")
        from extractors.video_extractor import VideoExtractor

        video_path = tmp_path / "clip.mp4"
        writer = cv2.VideoWriter(str(video_path), cv2.VideoWriter_fourcc(*"mp4v"), 10.0, (64, 64))
        for i in range(20):
            writer.write(np.full((64, 64, 3), fill_value=(i * 10) % 256, dtype=np.uint8))
        writer.release()
        if not video_path.exists() or video_path.stat().st_size == 0:
            pytest.skip("OpenCV could not encode an MP4 in this environment (missing codec).")

        # A tiny min_sample_rate_hz asks for far fewer samples than the
        # explicit sample_count=15 already requests.
        result = VideoExtractor(sample_count=15, min_sample_rate_hz=0.01).extract(video_path)
        assert result.sampled_frame_count >= 15

    def test_min_sample_rate_hz_is_capped_for_a_very_long_recording(self) -> None:
        """
        An hour-long recording at a 1 Hz floor would ask for 3600 samples --
        capped so the background pipeline never tries to run MediaPipe over
        an unbounded frame count (see extractors.video_extractor._MAX_SAMPLE_COUNT).
        """
        from extractors.video_extractor import _MAX_SAMPLE_COUNT, VideoExtractor

        extractor = VideoExtractor(min_sample_rate_hz=1.0)
        assert extractor._resolve_sample_count(duration_sec=3600.0) == _MAX_SAMPLE_COUNT
