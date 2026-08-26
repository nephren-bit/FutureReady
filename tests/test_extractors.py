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
