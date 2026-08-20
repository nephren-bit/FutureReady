"""
analyzers/landmark_availability.py

Decides which groups of MediaPipe Pose landmarks were *stably* visible in a
recording, and therefore which metrics are allowed to be computed at all.

This module must run **before** any metric is computed. The failure it exists
to prevent is silent and expensive: someone sits in front of a laptop, the
frame is cropped at chest height, the hips are never in shot, and every
hip-centred metric happily returns a number derived from landmarks MediaPipe
merely guessed at. Nothing errors. The number is garbage and looks exactly
like a real one.

So the contract is: a metric whose landmark groups are not available returns
`không đo được` **with a reason**, never `0.0`. Showing fewer metrics beats
showing wrong ones.

Which groups each metric needs is declared per context profile
(`config/profiles/*.yaml`), not here — this module only reports what the
camera actually saw.
"""

from __future__ import annotations

from dataclasses import dataclass

from models.features import LandmarkGroupAvailability
from models.profiles import ContextProfile, LandmarkGroup
from utils.logger import get_logger

logger = get_logger(__name__)

# MediaPipe Pose (BlazePose, 33 landmarks) index membership per group.
# https://developers.google.com/mediapipe/solutions/vision/pose_landmarker
LANDMARK_GROUP_INDICES: dict[LandmarkGroup, tuple[int, ...]] = {
    # Nose + both eyes + both ears. Enough to place the head against the
    # shoulder line, which is all `head_up_ratio` needs.
    LandmarkGroup.HEAD: (0, 2, 5, 7, 8),
    LandmarkGroup.SHOULDERS: (11, 12),
    # Shoulders + elbows + wrists. Arms are what `gesture_rate` and
    # `closed_posture_ratio` read.
    LandmarkGroup.UPPER_BODY: (11, 12, 13, 14, 15, 16),
    LandmarkGroup.HIPS: (23, 24),
    LandmarkGroup.LEGS: (25, 26, 27, 28),
}

# Human-readable group names, used verbatim in the reason shown to users.
GROUP_LABELS_VI: dict[LandmarkGroup, str] = {
    LandmarkGroup.HEAD: "đầu",
    LandmarkGroup.SHOULDERS: "vai",
    LandmarkGroup.UPPER_BODY: "thân trên",
    LandmarkGroup.HIPS: "hông",
    LandmarkGroup.LEGS: "chân",
}

# Framing advice per group, so the user is told how to fix the shot rather
# than only that something is missing.
GROUP_FIX_HINT_VI: dict[LandmarkGroup, str] = {
    LandmarkGroup.HEAD: "đưa camera lên cao hơn để thấy rõ mặt",
    LandmarkGroup.SHOULDERS: "lùi camera ra để thấy cả hai vai",
    LandmarkGroup.UPPER_BODY: "lùi camera ra để thấy cả hai tay",
    LandmarkGroup.HIPS: "lùi camera ra hoặc hạ thấp góc máy để thấy từ hông trở lên",
    LandmarkGroup.LEGS: "lùi camera ra để thấy toàn thân",
}


@dataclass(frozen=True)
class AvailabilityReport:
    """The verdict for one recording: which groups can be trusted, and why the rest cannot."""

    frames_analyzed: int
    frames_with_pose: int
    pose_detected_ratio: float
    group_ratios: dict[LandmarkGroup, float]
    available_groups: tuple[LandmarkGroup, ...]
    pose_detection_reason: str | None
    """Non-None when the whole recording fails the pose-detection floor."""

    def is_available(self, group: LandmarkGroup) -> bool:
        """Whether one group was stably visible."""
        return group in self.available_groups

    def missing(self, required: list[LandmarkGroup]) -> list[LandmarkGroup]:
        """Which of the required groups are not available, preserving order."""
        return [group for group in required if group not in self.available_groups]

    def reason_for(self, required: list[LandmarkGroup]) -> str | None:
        """
        The `không đo được` reason for a metric needing `required` groups, or
        `None` when the metric may be computed.
        """
        if self.pose_detection_reason is not None:
            return self.pose_detection_reason

        missing = self.missing(required)
        if not missing:
            return None

        names = ", ".join(GROUP_LABELS_VI[group] for group in missing)
        hint = GROUP_FIX_HINT_VI[missing[0]]
        ratios = ", ".join(
            f"{GROUP_LABELS_VI[group]} {self.group_ratios.get(group, 0.0):.0%}" for group in missing
        )
        return (
            f"Không thấy ổn định nhóm điểm mốc: {names} "
            f"(tỷ lệ khung hình nhìn thấy: {ratios}). "
            f"Cách khắc phục: {hint}."
        )

    def to_models(self) -> list[LandmarkGroupAvailability]:
        """Serializable form, stored on `PoseFeature.landmark_group_availability`."""
        return [
            LandmarkGroupAvailability(
                group=group,
                visible_frame_ratio=round(self.group_ratios.get(group, 0.0), 4),
                available=group in self.available_groups,
            )
            for group in LandmarkGroup
        ]


class LandmarkAvailabilityChecker:
    """Turns per-frame landmark visibilities into an `AvailabilityReport` for one profile."""

    def __init__(self, profile: ContextProfile) -> None:
        self._profile = profile

    def check(self, frame_visibilities: list[list[float] | None]) -> AvailabilityReport:
        """
        Args:
            frame_visibilities: One entry per sampled frame. Either the 33
                per-landmark `visibility` scores MediaPipe returned for that
                frame, or `None` when no person was detected in it.

        Returns:
            The availability verdict for the recording.
        """
        requirements = self._profile.frame_requirements
        frames_analyzed = len(frame_visibilities)
        detected = [entry for entry in frame_visibilities if entry is not None]
        frames_with_pose = len(detected)
        pose_ratio = frames_with_pose / frames_analyzed if frames_analyzed else 0.0

        group_ratios: dict[LandmarkGroup, float] = {}
        for group, indices in LANDMARK_GROUP_INDICES.items():
            visible_frames = sum(
                1
                for visibilities in detected
                if self._group_visible_in_frame(
                    visibilities, indices, requirements.min_landmark_visibility
                )
            )
            # Denominator is *all* sampled frames, not only the detected ones:
            # a recording where the person is in shot 30% of the time has not
            # stably shown any group, however clean those 30% were.
            group_ratios[group] = visible_frames / frames_analyzed if frames_analyzed else 0.0

        pose_reason: str | None = None
        if frames_analyzed == 0:
            pose_reason = "Không có khung hình nào được phân tích."
        elif pose_ratio < requirements.min_pose_detected_ratio:
            pose_reason = (
                f"Chỉ phát hiện được người trong {pose_ratio:.0%} số khung hình, "
                f"dưới mức tối thiểu {requirements.min_pose_detected_ratio:.0%}. "
                "Cách khắc phục: đặt camera thấy rõ toàn bộ người nói và tăng ánh sáng."
            )

        available: tuple[LandmarkGroup, ...] = ()
        if pose_reason is None:
            available = tuple(
                group
                for group, ratio in group_ratios.items()
                if ratio >= requirements.min_group_frame_ratio
            )

        report = AvailabilityReport(
            frames_analyzed=frames_analyzed,
            frames_with_pose=frames_with_pose,
            pose_detected_ratio=round(pose_ratio, 4),
            group_ratios=group_ratios,
            available_groups=available,
            pose_detection_reason=pose_reason,
        )

        logger.info(
            "Landmark availability (profile=%s): pose in %.0f%% of %d frames; available groups: %s",
            self._profile.profile,
            pose_ratio * 100,
            frames_analyzed,
            ", ".join(group.value for group in available) or "none",
        )
        return report

    @staticmethod
    def _group_visible_in_frame(
        visibilities: list[float], indices: tuple[int, ...], min_visibility: float
    ) -> bool:
        """A group counts as seen in a frame only when *every* landmark in it is seen."""
        return all(
            index < len(visibilities) and visibilities[index] >= min_visibility
            for index in indices
        )
