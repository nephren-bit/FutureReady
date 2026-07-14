"""
extractors/video_extractor.py

Extracts structured, deterministic features from a recorded presentation
video (MP4) using OpenCV: resolution, fps, duration, brightness/contrast,
inter-frame motion, scene-cut count, and blur. Layer 1 only — no face
detection, no emotion, no reasoning happens here.

Frame sampling is also exposed via `extract_with_frames`, which returns the
same `VideoFeature` plus the raw sampled frames (as BGR numpy arrays) and
their timestamps. The AI Orchestrator uses this second method to feed
frames into the Layer 2 vision analyzers (`EmotionAnalyzer`,
`FaceMeshAnalyzer`) without re-decoding the video twice. The plain
`extract()` method (required by `BaseExtractor`) is used by the standalone
`/extract/video` endpoint, which never needs the raw frames.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from extractors.base import BaseExtractor
from models.features import VideoFeature
from utils.logger import get_logger

logger = get_logger(__name__)

# Target number of frames to sample across the whole video for downstream
# vision analyzers (emotion / face mesh). Sampling instead of decoding every
# frame keeps analysis time bounded regardless of video length.
_DEFAULT_SAMPLE_COUNT = 60

# A frame-to-frame mean absolute pixel difference above this (0-255 scale)
# is counted as an abrupt scene cut rather than ordinary motion.
_SCENE_CUT_THRESHOLD = 35.0


class VideoExtractor(BaseExtractor[VideoFeature]):
    """Extracts structured data from a presentation video file (Layer 1)."""

    def __init__(self, sample_count: int = _DEFAULT_SAMPLE_COUNT) -> None:
        """
        Args:
            sample_count: Number of frames to evenly sample across the video
                for downstream analysis (motion/blur stats and, later,
                vision analyzers).
        """
        self._sample_count = sample_count

    def extract(self, file_path: Path) -> VideoFeature:
        """Run extraction and return only the structured `VideoFeature`."""
        feature, _frames, _timestamps = self.extract_with_frames(file_path)
        return feature

    def extract_with_frames(
        self, file_path: Path
    ) -> tuple[VideoFeature, list[np.ndarray], list[float]]:
        """
        Run full extraction on a video file, also returning sampled frames.

        Args:
            file_path: Path to the .mp4 file on disk.

        Returns:
            A 3-tuple of (VideoFeature, sampled BGR frames, their timestamps
            in seconds). The frames are only used in-process by Layer 2
            vision analyzers and are never serialized in an API response.

        Raises:
            RuntimeError: If the video cannot be opened or contains no frames.
        """
        import cv2  # local import: keep this optional dependency out of app import time

        capture = cv2.VideoCapture(str(file_path))
        if not capture.isOpened():
            raise RuntimeError(f"Could not open video file: {file_path}")

        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0.0)
            frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

            if frame_count <= 0:
                raise RuntimeError("Video file reports zero frames; it may be corrupt.")

            duration_sec = frame_count / fps if fps > 0 else 0.0

            sample_indices = self._compute_sample_indices(frame_count)
            frames: list[np.ndarray] = []
            timestamps: list[float] = []

            for index in sample_indices:
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                success, frame = capture.read()
                if not success or frame is None:
                    continue
                frames.append(frame)
                timestamps.append(index / fps if fps > 0 else 0.0)

            if not frames:
                raise RuntimeError("No readable frames could be sampled from the video.")

            brightness_mean, brightness_std, contrast_mean, blur_mean = self._frame_quality_stats(
                frames, cv2
            )
            motion_mean, motion_std, scene_cuts = self._motion_stats(frames, cv2)

            feature = VideoFeature(
                fps=round(fps, 2),
                frame_count=frame_count,
                duration_sec=round(duration_sec, 2),
                width=width,
                height=height,
                sampled_frame_count=len(frames),
                brightness_mean=brightness_mean,
                brightness_std=brightness_std,
                contrast_mean=contrast_mean,
                motion_score_mean=motion_mean,
                motion_score_std=motion_std,
                scene_cut_count=scene_cuts,
                blur_score_mean=blur_mean,
            )
            return feature, frames, timestamps
        finally:
            capture.release()

    def _compute_sample_indices(self, frame_count: int) -> list[int]:
        """Evenly space sample indices across the whole video."""
        count = min(self._sample_count, frame_count)
        if count <= 1:
            return [0]
        step = frame_count / count
        return [int(i * step) for i in range(count)]

    def _frame_quality_stats(
        self, frames: list[np.ndarray], cv2_module
    ) -> tuple[float, float, float, float]:
        """Compute brightness, contrast, and blur statistics across sampled frames."""
        brightness_values: list[float] = []
        contrast_values: list[float] = []
        blur_values: list[float] = []

        for frame in frames:
            gray = cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2GRAY)
            brightness_values.append(float(np.mean(gray)))
            contrast_values.append(float(np.std(gray)))
            laplacian = cv2_module.Laplacian(gray, cv2_module.CV_64F)
            blur_values.append(float(np.var(laplacian)))

        return (
            round(float(np.mean(brightness_values)), 2),
            round(float(np.std(brightness_values)), 2),
            round(float(np.mean(contrast_values)), 2),
            round(float(np.mean(blur_values)), 2),
        )

    def _motion_stats(
        self, frames: list[np.ndarray], cv2_module
    ) -> tuple[float, float, int]:
        """Compute inter-frame motion statistics and count abrupt scene cuts."""
        if len(frames) < 2:
            return 0.0, 0.0, 0

        diffs: list[float] = []
        scene_cuts = 0
        previous_gray = cv2_module.cvtColor(frames[0], cv2_module.COLOR_BGR2GRAY)

        for frame in frames[1:]:
            gray = cv2_module.cvtColor(frame, cv2_module.COLOR_BGR2GRAY)
            diff = float(np.mean(cv2_module.absdiff(gray, previous_gray)))
            diffs.append(diff)
            if diff >= _SCENE_CUT_THRESHOLD:
                scene_cuts += 1
            previous_gray = gray

        return (
            round(float(np.mean(diffs)), 2),
            round(float(np.std(diffs)), 2),
            scene_cuts,
        )
