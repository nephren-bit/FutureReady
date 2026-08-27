"""
analyzers/pose_analyzer.py

Body-movement analyzer (Layer 2E), built on MediaPipe Pose (BlazePose, 33
full-body landmarks). Consumes the frames already sampled by
`extractors/video_extractor.py` and produces a `PoseFeature`: seven
body-movement metrics plus the per-frame time series that
`events/detector.py` turns into timestamped events.

Holistic vs. separate graphs
----------------------------
MediaPipe 0.10.x still ships `mp.solutions.holistic` (pose + face + hands in
one graph), but it belongs to the frozen legacy `solutions` bundle: Google's
maintained line is the Tasks API, which deliberately has **no** holistic
task — pose, face, and hand are separate landmarkers there. Betting the core
metric set on a bundle with no forward path is the expensive mistake here.

Decision: run Pose **separately** from Face Mesh, using
`mp.solutions.pose`, matching how `analyzers/facemesh_analyzer.py` already
calls `mp.solutions.face_mesh`. Concretely this buys:

* One consistent MediaPipe API across both vision analyzers today, and one
  independent migration to `PoseLandmarker`/`FaceLandmarker` later, instead
  of a rewrite of a merged graph.
* No `.task` model file to download and ship — the legacy solution bundles
  its own weights, so this runs offline in a classroom.
* Face Mesh stays skippable. At classroom distance a 468-point face mesh
  often fails to lock on while 33-point full-body pose keeps working, and
  the two must be allowed to fail independently.

The cost is decoding pose and face landmarks in two passes over the same
frames. The frames are already in memory (`extract_with_frames` decodes the
video once and shares them), so the cost is CPU on ~60 sampled frames, not
another video decode.

Camera-distance invariance
--------------------------
Every distance-derived number is divided by the subject's shoulder width in
the same frame, so the same person filmed from two metres and from five
produces the same metric values. Landmark coordinates are converted to
pixels first (x * width, y * height) — MediaPipe's normalized coordinates
are scaled by each axis separately, so distances computed on them are skewed
by the frame's aspect ratio.

What this analyzer refuses to do
--------------------------------
It never invents a number. A metric whose landmark groups were not stably
visible comes back `measured=False` with a reason (see
`analyzers/landmark_availability.py`), never `0.0`.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

import numpy as np

from analyzers.base import BaseAnalyzer
from analyzers.landmark_availability import AvailabilityReport, LandmarkAvailabilityChecker
from models.features import FaceMeshFeature, PoseFeature, PoseFrameSample, PoseMetric
from models.profiles import ContextProfile, LandmarkGroup
from services.profile_loader import load_profile
from utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# MediaPipe Pose landmark indices actually used by the metric set.
# ---------------------------------------------------------------------------

_NOSE = 0
_LEFT_SHOULDER = 11
_RIGHT_SHOULDER = 12
_LEFT_WRIST = 15
_RIGHT_WRIST = 16
_LEFT_HIP = 23
_RIGHT_HIP = 24

_LANDMARK_COUNT = 33

# ---------------------------------------------------------------------------
# Per-frame signal names. `config/profiles/*.yaml` addresses these by name in
# its event rules, so they are part of the configuration contract: renaming
# one here without renaming it in every profile silently disables a rule.
# ---------------------------------------------------------------------------

SIGNAL_HEAD_UP = "head_up"
SIGNAL_MOTION_RATE = "motion_rate"
SIGNAL_HORIZONTAL_RATE = "horizontal_rate"
SIGNAL_TURNED_AWAY = "turned_away"
SIGNAL_SHOULDER_WIDTH_RATIO = "shoulder_width_ratio"
SIGNAL_CLOSED_POSTURE = "closed_posture"
SIGNAL_GESTURE_ACTIVE = "gesture_active"
SIGNAL_SHOULDER_TILT = "shoulder_tilt_deg"
# Distance of this frame's hip centre from the recording's own mean hip
# centre, in shoulder widths -- the per-frame counterpart of the
# `postural_sway` aggregate (which is the RMS of exactly this value across
# every frame). Lets `events/rules.py` flag *when* someone swayed away from
# their settled position, not just report one number for the whole video.
SIGNAL_POSTURAL_SWAY_DEV = "postural_sway_dev"

# Which metric each signal belongs to. A signal is only emitted when its
# backing metric is measurable, so the landmark requirements declared once in
# the profile govern the time series too — they are not restated here.
SIGNAL_METRIC: dict[str, str] = {
    SIGNAL_HEAD_UP: "head_up_ratio",
    SIGNAL_MOTION_RATE: "movement_range",
    SIGNAL_HORIZONTAL_RATE: "movement_range",
    SIGNAL_TURNED_AWAY: "turned_away_ratio",
    SIGNAL_SHOULDER_WIDTH_RATIO: "turned_away_ratio",
    SIGNAL_CLOSED_POSTURE: "closed_posture_ratio",
    SIGNAL_GESTURE_ACTIVE: "gesture_rate",
    SIGNAL_SHOULDER_TILT: "shoulder_tilt",
    SIGNAL_POSTURAL_SWAY_DEV: "postural_sway",
}

# Percentile of observed shoulder widths taken as "facing the camera square
# on". A max would latch onto a single bad frame; the 90th percentile is the
# same idea with a robust estimator.
_FACING_REFERENCE_PERCENTILE = 90

# Number of decimals every metric and signal is rounded to. Same run, same
# video, same numbers — see tests/test_pose_analyzer.py.
_ROUND_DECIMALS = 4

# Fallback used when a metric declares no geometry constant of its own.
_DEFAULT_PARAMS: dict[str, float] = {
    "head_up_margin_ratio": 0.35,
    "gesture_elevation_ratio": 0.35,
    "gesture_lateral_ratio": 0.45,
    "low_wrist_elevation_ratio": 0.05,
    "crossed_wrist_overlap_ratio": 0.10,
    "turned_width_ratio": 0.62,
    "facemesh_fallback_min_faces_ratio": 0.6,
}


def apply_head_pose_fallback(
    pose: PoseFeature,
    facemesh: FaceMeshFeature | None,
    profile: ContextProfile | None = None,
) -> PoseFeature:
    """
    Fill in `head_up_ratio` from Face Mesh when Pose could not measure it.

    Pose is always tried first, and this only ever runs afterwards. In a
    classroom the presenter faces the audience rather than the lens, so the
    shoulder line is the meaningful reference for "head up or head down" and
    a face-based estimate is the weaker signal — but at classroom distance
    the shoulder landmarks are also the ones most likely to be cropped out,
    which is exactly when this fallback earns its place.

    It fires only when the face was found in enough frames to trust
    (`facemesh_fallback_min_faces_ratio` in the profile). Otherwise the
    metric stays `không đo được`, which is the honest answer.

    Args:
        pose: The analyzed recording.
        facemesh: The Face Mesh feature for the same recording, if any.
        profile: Profile supplying the thresholds; defaults to the one the
            `PoseFeature` was computed with.

    Returns:
        A copy of `pose` with `head_up_ratio` filled in, or `pose` unchanged.
    """
    if pose.head_up_ratio.measured:
        return pose
    if facemesh is None or facemesh.head_up_ratio is None:
        return pose

    profile = profile or load_profile(pose.profile or None)
    params = profile.metric_params("head_up_ratio")
    minimum_faces = params.get(
        "facemesh_fallback_min_faces_ratio",
        _DEFAULT_PARAMS["facemesh_fallback_min_faces_ratio"],
    )
    if facemesh.faces_detected_ratio < minimum_faces:
        logger.info(
            "Not using the Face Mesh fallback for head_up_ratio: a face was found in only "
            "%.0f%% of frames, under the profile's %.0f%% floor.",
            facemesh.faces_detected_ratio * 100,
            minimum_faces * 100,
        )
        return pose

    filled = pose.model_copy(deep=True)
    filled.head_up_ratio = PoseMetric.measure(
        facemesh.head_up_ratio, profile.metric_unit("head_up_ratio")
    )
    logger.info(
        "head_up_ratio taken from the Face Mesh fallback (%.3f); Pose could not measure it.",
        facemesh.head_up_ratio,
    )
    return filled


@dataclass(frozen=True)
class LandmarkFrame:
    """
    One sampled frame after pose inference, decoupled from MediaPipe.

    `points` holds pixel-space (x, y) per landmark index and `visibilities`
    the matching confidence, or both are `None` when no person was found.
    Keeping this struct between inference and geometry lets the whole metric
    layer be tested without MediaPipe or a video file.
    """

    timestamp_sec: float
    points: list[tuple[float, float]] | None
    visibilities: list[float] | None

    @property
    def detected(self) -> bool:
        """Whether a person was found in this frame."""
        return self.points is not None


@dataclass(frozen=True)
class _FrameGeometry:
    """Scale-normalized geometry for one detected frame."""

    timestamp_sec: float
    shoulder_width_px: float
    shoulder_tilt_deg: float
    head_elevation_ratio: float | None
    hip_center_px: tuple[float, float] | None
    wrist_elevation_ratios: tuple[float, float] | None
    wrist_lateral_ratios: tuple[float, float] | None
    wrists_crossed: bool | None


class PoseAnalyzer(BaseAnalyzer[list[tuple[np.ndarray, float]], PoseFeature]):
    """MediaPipe Pose analyzer over sampled video frames (Layer 2E)."""

    def __init__(self, profile: ContextProfile | str | None = None) -> None:
        """
        Args:
            profile: Context profile, its name, or `None` for the default
                (`presentation_class`). The profile decides which metrics
                apply, which landmark groups each of them needs, and every
                geometry constant used below.
        """
        if isinstance(profile, ContextProfile):
            self._profile = profile
        else:
            self._profile = load_profile(profile) if profile else load_profile()

    # ------------------------------------------------------------------
    # Entry points
    # ------------------------------------------------------------------

    def analyze(self, data: list[tuple[np.ndarray, float]], source_fps: float = 0.0) -> PoseFeature:
        """
        Args:
            data: List of (BGR frame, timestamp_sec) tuples, as produced by
                `VideoExtractor.extract_with_frames`.
            source_fps: The original video's frame rate (`VideoFeature.fps`),
                carried onto the result so `events/rules.py` can report a
                real frame number for an event's start instead of a raw
                decimal timestamp. Optional -- callers that don't have a
                `VideoFeature` (tests, synthetic clips) can omit it.

        Returns:
            A `PoseFeature` with the seven body-movement metrics, the
            landmark-availability verdict, and the per-frame time series.
        """
        return self.analyze_landmarks(self._detect(data), source_fps=source_fps)

    def analyze_landmarks(self, frames: list[LandmarkFrame], source_fps: float = 0.0) -> PoseFeature:
        """
        Compute every metric from already-detected landmarks.

        Split out from `analyze` so the metric math can be exercised on
        synthetic landmarks, with no MediaPipe and no video file involved.
        """
        checker = LandmarkAvailabilityChecker(self._profile)
        availability = checker.check([frame.visibilities for frame in frames])

        # Kept index-aligned with `frames` (None where the frame had no usable
        # person) so the time series can pair the two up positionally.
        per_frame = [self._frame_geometry(frame) for frame in frames]
        geometries = [geo for geo in per_frame if geo is not None]
        reference_width = self._facing_reference_width(geometries)

        metrics = self._compute_metrics(geometries, availability, reference_width, frames)
        mean_hip_center = self._mean_hip_center(geometries)
        series = self._build_series(frames, per_frame, availability, reference_width, mean_hip_center)

        sampling_rate = self._sampling_rate_hz(frames)
        minimum_rate = self._profile.frame_requirements.min_sample_rate_hz
        sampling_warning: str | None = None
        if sampling_rate < minimum_rate:
            sampling_warning = (
                f"Tần số lấy mẫu {sampling_rate:.2f} khung hình/giây thấp hơn mức tối thiểu "
                f"{minimum_rate:.2f} của hồ sơ '{self._profile.profile}'. Các sự kiện ngắn có "
                "thể bị bỏ sót -- bản ghi có thể quá dài so với mức lấy mẫu tối đa cho phép "
                "(xem extractors/video_extractor.py, _MAX_SAMPLE_COUNT)."
            )
            logger.warning(sampling_warning)

        feature = PoseFeature(
            profile=self._profile.profile,
            profile_version=self._profile.version,
            frames_analyzed=len(frames),
            pose_detected_ratio=availability.pose_detected_ratio,
            available_landmark_groups=list(availability.available_groups),
            landmark_group_availability=availability.to_models(),
            sampling_rate_hz=round(sampling_rate, _ROUND_DECIMALS),
            sampling_warning=sampling_warning,
            source_fps=source_fps,
            series=series,
            **metrics,
        )
        logger.info(
            "Pose analysis (profile=%s v%s): %d frames, person detected in %.0f%%, measured metrics: %s",
            feature.profile,
            feature.profile_version,
            feature.frames_analyzed,
            feature.pose_detected_ratio * 100,
            ", ".join(feature.measured_metrics()) or "none",
        )
        return feature

    # ------------------------------------------------------------------
    # MediaPipe inference
    # ------------------------------------------------------------------

    def _detect(self, data: list[tuple[np.ndarray, float]]) -> list[LandmarkFrame]:
        """Run MediaPipe Pose over every sampled frame."""
        if not data:
            return []

        import mediapipe as mp  # local import: keep optional dependency lazy

        frames: list[LandmarkFrame] = []
        mp_pose = mp.solutions.pose
        with mp_pose.Pose(
            # Per-frame inference rather than the tracking path: the frames
            # handed to us are sampled seconds apart, so a tracker would be
            # carrying stale state between them. It also makes the analyzer
            # deterministic, which the acceptance check depends on.
            static_image_mode=True,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=0.5,
        ) as pose:
            for frame, timestamp in data:
                import cv2  # local import: keep optional dependency lazy

                height, width = frame.shape[:2]
                results = pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

                if not results.pose_landmarks:
                    frames.append(LandmarkFrame(timestamp, None, None))
                    continue

                landmarks = results.pose_landmarks.landmark
                frames.append(
                    LandmarkFrame(
                        timestamp_sec=timestamp,
                        points=[(mark.x * width, mark.y * height) for mark in landmarks],
                        visibilities=[float(mark.visibility) for mark in landmarks],
                    )
                )
        return frames

    # ------------------------------------------------------------------
    # Per-frame geometry
    # ------------------------------------------------------------------

    def _frame_geometry(self, frame: LandmarkFrame) -> _FrameGeometry | None:
        """
        Reduce one frame's landmarks to scale-normalized geometry, or `None`
        when there is no usable person in it. Shoulders are the anchor: with
        no shoulder width there is nothing to normalize against, so no
        distance-derived number from that frame can be trusted.
        """
        points, visibilities = frame.points, frame.visibilities
        if points is None or visibilities is None or len(points) < _LANDMARK_COUNT:
            return None

        threshold = self._profile.frame_requirements.min_landmark_visibility

        def seen(*indices: int) -> bool:
            return all(visibilities[index] >= threshold for index in indices)

        if not seen(_LEFT_SHOULDER, _RIGHT_SHOULDER):
            return None

        left_shoulder = points[_LEFT_SHOULDER]
        right_shoulder = points[_RIGHT_SHOULDER]
        shoulder_width = math.dist(left_shoulder, right_shoulder)
        if shoulder_width <= 0:
            return None

        shoulder_mid_y = (left_shoulder[1] + right_shoulder[1]) / 2.0
        shoulder_mid_x = (left_shoulder[0] + right_shoulder[0]) / 2.0
        tilt = abs(
            math.degrees(
                math.atan2(left_shoulder[1] - right_shoulder[1], left_shoulder[0] - right_shoulder[0])
            )
        )
        # Fold to [0, 90]: a 175-degree shoulder line is 5 degrees off level,
        # not 175 — which side is which does not matter for tilt.
        tilt = min(tilt, 180.0 - tilt)

        # Head: how far the nose sits above the shoulder line, in shoulder
        # widths. Image y grows downward, hence shoulder minus nose.
        head_elevation: float | None = None
        if seen(_NOSE):
            head_elevation = (shoulder_mid_y - points[_NOSE][1]) / shoulder_width

        hip_center: tuple[float, float] | None = None
        if seen(_LEFT_HIP, _RIGHT_HIP):
            hip_center = (
                (points[_LEFT_HIP][0] + points[_RIGHT_HIP][0]) / 2.0,
                (points[_LEFT_HIP][1] + points[_RIGHT_HIP][1]) / 2.0,
            )

        wrist_elevations: tuple[float, float] | None = None
        wrist_laterals: tuple[float, float] | None = None
        crossed: bool | None = None
        if hip_center is not None and seen(_LEFT_WRIST, _RIGHT_WRIST):
            left_wrist = points[_LEFT_WRIST]
            right_wrist = points[_RIGHT_WRIST]
            hip_line_y = hip_center[1]
            wrist_elevations = (
                (hip_line_y - left_wrist[1]) / shoulder_width,
                (hip_line_y - right_wrist[1]) / shoulder_width,
            )
            wrist_laterals = (
                abs(left_wrist[0] - left_shoulder[0]) / shoulder_width,
                abs(right_wrist[0] - right_shoulder[0]) / shoulder_width,
            )
            crossed = self._wrists_crossed(
                left_wrist, right_wrist, left_shoulder, right_shoulder, shoulder_mid_x, shoulder_width
            )

        return _FrameGeometry(
            timestamp_sec=frame.timestamp_sec,
            shoulder_width_px=shoulder_width,
            shoulder_tilt_deg=tilt,
            head_elevation_ratio=head_elevation,
            hip_center_px=hip_center,
            wrist_elevation_ratios=wrist_elevations,
            wrist_lateral_ratios=wrist_laterals,
            wrists_crossed=crossed,
        )

    def _wrists_crossed(
        self,
        left_wrist: tuple[float, float],
        right_wrist: tuple[float, float],
        left_shoulder: tuple[float, float],
        right_shoulder: tuple[float, float],
        torso_mid_x: float,
        shoulder_width: float,
    ) -> bool:
        """
        Whether both wrists have crossed the torso midline away from their own
        shoulder — the geometric definition of folded arms, and free of any
        assumption about which way the subject is facing (MediaPipe labels
        landmarks anatomically, but the image is mirrored or not depending on
        the camera).
        """
        overlap = self._param("closed_posture_ratio", "crossed_wrist_overlap_ratio") * shoulder_width
        pairs = ((left_wrist, left_shoulder), (right_wrist, right_shoulder))
        for wrist, shoulder in pairs:
            shoulder_side = math.copysign(1.0, shoulder[0] - torso_mid_x)
            wrist_offset = wrist[0] - torso_mid_x
            crossed_far_enough = (
                math.copysign(1.0, wrist_offset) != shoulder_side and abs(wrist_offset) >= overlap
            )
            if not crossed_far_enough:
                return False
        return True

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    def _compute_metrics(
        self,
        geometries: list[_FrameGeometry],
        availability: AvailabilityReport,
        reference_width: float | None,
        frames: list[LandmarkFrame],
    ) -> dict[str, PoseMetric]:
        """Aggregate the per-frame geometry into the seven metrics."""
        return {
            "head_up_ratio": self._head_up_ratio(geometries, availability),
            "postural_sway": self._postural_sway(geometries, availability),
            "movement_range": self._movement_range(geometries, availability),
            "gesture_rate": self._gesture_rate(geometries, availability, frames),
            "closed_posture_ratio": self._closed_posture_ratio(geometries, availability),
            "shoulder_tilt": self._shoulder_tilt(geometries, availability),
            "turned_away_ratio": self._turned_away_ratio(geometries, availability, reference_width),
        }

    def _gate(self, metric: str, availability: AvailabilityReport) -> PoseMetric | None:
        """
        The single choke point every metric passes through.

        Returns a `không đo được` metric when this profile does not apply the
        metric at all, or when the landmark groups it declared were not
        stably visible. Returns `None` to mean "go ahead and compute".
        """
        spec = self._profile.metrics.get(metric)
        if spec is None:
            return PoseMetric.not_measured(
                unit="",
                reason=(
                    f"Hồ sơ '{self._profile.profile}' không áp dụng chỉ số này."
                ),
            )
        reason = availability.reason_for(spec.required_landmark_groups)
        if reason is not None:
            return PoseMetric.not_measured(unit=spec.unit, reason=reason)
        return None

    def _insufficient(self, metric: str, sample_count: int) -> PoseMetric:
        """Landmark groups were available overall, but this metric had too few usable frames."""
        return PoseMetric.not_measured(
            unit=self._profile.metric_unit(metric),
            reason=(
                f"Chỉ có {sample_count} khung hình đủ dữ liệu cho chỉ số này, "
                "không đủ để tính. Cách khắc phục: quay lại với khung hình thấy rõ người nói hơn."
            ),
        )

    def _param(self, metric: str, name: str) -> float:
        """One geometry constant, from the profile, falling back to the module default."""
        return self._profile.metric_params(metric).get(name, _DEFAULT_PARAMS[name])

    def _head_up_ratio(
        self, geometries: list[_FrameGeometry], availability: AvailabilityReport
    ) -> PoseMetric:
        """
        Share of frames where the nose sits far enough above the shoulder line.

        Computed from Pose, never from Face Mesh head pose: at classroom
        distance the face mesh often fails to lock on, while the shoulder line
        stays reliable. `services/feature_fusion.py` may fall back to Face
        Mesh pitch only when this comes back not measured *and* a face was
        clearly detected.
        """
        blocked = self._gate("head_up_ratio", availability)
        if blocked:
            return blocked

        margin = self._param("head_up_ratio", "head_up_margin_ratio")
        values = [geo.head_elevation_ratio for geo in geometries if geo.head_elevation_ratio is not None]
        if not values:
            return self._insufficient("head_up_ratio", 0)

        up_frames = sum(1 for value in values if value >= margin)
        return PoseMetric.measure(up_frames / len(values), self._profile.metric_unit("head_up_ratio"))

    def _postural_sway(
        self, geometries: list[_FrameGeometry], availability: AvailabilityReport
    ) -> PoseMetric:
        """RMS wander of the hip centre around its own mean, in shoulder widths."""
        blocked = self._gate("postural_sway", availability)
        if blocked:
            return blocked

        centers = [geo.hip_center_px for geo in geometries if geo.hip_center_px is not None]
        scale = self._median_shoulder_width(geometries)
        if len(centers) < 2 or scale is None:
            return self._insufficient("postural_sway", len(centers))

        mean_x = statistics.fmean(center[0] for center in centers)
        mean_y = statistics.fmean(center[1] for center in centers)
        rms = math.sqrt(
            statistics.fmean(
                (center[0] - mean_x) ** 2 + (center[1] - mean_y) ** 2 for center in centers
            )
        )
        return PoseMetric.measure(rms / scale, self._profile.metric_unit("postural_sway"))

    def _movement_range(
        self, geometries: list[_FrameGeometry], availability: AvailabilityReport
    ) -> PoseMetric:
        """Total horizontal travel of the hip centre, in shoulder widths."""
        blocked = self._gate("movement_range", availability)
        if blocked:
            return blocked

        xs = [geo.hip_center_px[0] for geo in geometries if geo.hip_center_px is not None]
        scale = self._median_shoulder_width(geometries)
        if len(xs) < 2 or scale is None:
            return self._insufficient("movement_range", len(xs))

        return PoseMetric.measure((max(xs) - min(xs)) / scale, self._profile.metric_unit("movement_range"))

    def _gesture_rate(
        self,
        geometries: list[_FrameGeometry],
        availability: AvailabilityReport,
        frames: list[LandmarkFrame],
    ) -> PoseMetric:
        """
        Times per minute a wrist leaves the torso region — counted as rising
        edges, so one long held gesture counts once rather than once per frame.
        """
        blocked = self._gate("gesture_rate", availability)
        if blocked:
            return blocked

        usable = [geo for geo in geometries if geo.wrist_elevation_ratios is not None]
        span_sec = self._span_sec(frames)
        if len(usable) < 2 or span_sec <= 0:
            return self._insufficient("gesture_rate", len(usable))

        events = 0
        was_active = False
        for geo in usable:
            active = self._gesture_active(geo) is True
            if active and not was_active:
                events += 1
            was_active = active

        return PoseMetric.measure(events / (span_sec / 60.0), self._profile.metric_unit("gesture_rate"))

    def _closed_posture_ratio(
        self, geometries: list[_FrameGeometry], availability: AvailabilityReport
    ) -> PoseMetric:
        """Share of frames with arms folded, or both hands hanging below the hip line."""
        blocked = self._gate("closed_posture_ratio", availability)
        if blocked:
            return blocked

        flags = [self._closed_posture(geo) for geo in geometries]
        usable = [flag for flag in flags if flag is not None]
        if not usable:
            return self._insufficient("closed_posture_ratio", 0)

        return PoseMetric.measure(
            sum(1 for flag in usable if flag) / len(usable),
            self._profile.metric_unit("closed_posture_ratio"),
        )

    def _shoulder_tilt(
        self, geometries: list[_FrameGeometry], availability: AvailabilityReport
    ) -> PoseMetric:
        """Mean absolute angle of the shoulder line off horizontal, in degrees."""
        blocked = self._gate("shoulder_tilt", availability)
        if blocked:
            return blocked
        if not geometries:
            return self._insufficient("shoulder_tilt", 0)

        return PoseMetric.measure(
            statistics.fmean(geo.shoulder_tilt_deg for geo in geometries),
            self._profile.metric_unit("shoulder_tilt"),
        )

    def _turned_away_ratio(
        self,
        geometries: list[_FrameGeometry],
        availability: AvailabilityReport,
        reference_width: float | None,
    ) -> PoseMetric:
        """
        Share of frames where the shoulder line projects narrow enough to mean
        the torso has rotated away from the camera. The reference is the
        subject's own widest-facing frames in the same recording, so this
        needs no assumption about build or camera distance.
        """
        blocked = self._gate("turned_away_ratio", availability)
        if blocked:
            return blocked
        if reference_width is None or not geometries:
            return self._insufficient("turned_away_ratio", len(geometries))

        limit = self._param("turned_away_ratio", "turned_width_ratio")
        turned = sum(1 for geo in geometries if geo.shoulder_width_px / reference_width < limit)
        return PoseMetric.measure(
            turned / len(geometries), self._profile.metric_unit("turned_away_ratio")
        )

    # ------------------------------------------------------------------
    # Per-frame signals -> time series
    # ------------------------------------------------------------------

    def _build_series(
        self,
        frames: list[LandmarkFrame],
        per_frame: list[_FrameGeometry | None],
        availability: AvailabilityReport,
        reference_width: float | None,
        mean_hip_center: tuple[float, float] | None,
    ) -> list[PoseFrameSample]:
        """
        Build the per-frame time series `events/detector.py` runs its rules
        over. A signal is written only when its backing metric is measurable
        and that specific frame carries the landmarks it needs — a missing
        signal is left out of the map rather than zeroed, so a rule can never
        fire on a frame it had no data for.

        Args:
            frames: The sampled frames.
            per_frame: Geometry index-aligned with `frames`, `None` where the
                frame yielded none.
            mean_hip_center: The recording's own mean hip centre, from
                `_mean_hip_center` -- what `SIGNAL_POSTURAL_SWAY_DEV` measures
                each frame's distance from.
        """
        allowed = {
            signal
            for signal, metric in SIGNAL_METRIC.items()
            if self._metric_is_measurable(metric, availability)
        }

        samples: list[PoseFrameSample] = []
        previous: _FrameGeometry | None = None

        for frame, geo in zip(frames, per_frame):
            signals: dict[str, float] = {}

            if geo is not None:
                self._write_static_signals(signals, geo, allowed, reference_width, mean_hip_center)
                self._write_rate_signals(signals, geo, previous, allowed)
                previous = geo
            else:
                # A gap in detection breaks the motion chain: a rate computed
                # across a stretch where the person was not visible measures
                # the detector, not the person.
                previous = None

            samples.append(
                PoseFrameSample(
                    timestamp_sec=round(frame.timestamp_sec, _ROUND_DECIMALS),
                    pose_detected=frame.detected,
                    visible_groups=self._frame_visible_groups(frame),
                    signals=signals,
                )
            )
        return samples

    def _write_static_signals(
        self,
        signals: dict[str, float],
        geo: _FrameGeometry,
        allowed: set[str],
        reference_width: float | None,
        mean_hip_center: tuple[float, float] | None,
    ) -> None:
        """Signals derived from a single frame in isolation."""
        if SIGNAL_HEAD_UP in allowed and geo.head_elevation_ratio is not None:
            margin = self._param("head_up_ratio", "head_up_margin_ratio")
            signals[SIGNAL_HEAD_UP] = 1.0 if geo.head_elevation_ratio >= margin else 0.0

        if SIGNAL_SHOULDER_TILT in allowed:
            signals[SIGNAL_SHOULDER_TILT] = round(geo.shoulder_tilt_deg, _ROUND_DECIMALS)

        if reference_width:
            width_ratio = geo.shoulder_width_px / reference_width
            if SIGNAL_SHOULDER_WIDTH_RATIO in allowed:
                signals[SIGNAL_SHOULDER_WIDTH_RATIO] = round(width_ratio, _ROUND_DECIMALS)
            if SIGNAL_TURNED_AWAY in allowed:
                limit = self._param("turned_away_ratio", "turned_width_ratio")
                signals[SIGNAL_TURNED_AWAY] = 1.0 if width_ratio < limit else 0.0

        if SIGNAL_CLOSED_POSTURE in allowed:
            closed = self._closed_posture(geo)
            if closed is not None:
                signals[SIGNAL_CLOSED_POSTURE] = 1.0 if closed else 0.0

        if SIGNAL_GESTURE_ACTIVE in allowed:
            active = self._gesture_active(geo)
            if active is not None:
                signals[SIGNAL_GESTURE_ACTIVE] = 1.0 if active else 0.0

        if (
            SIGNAL_POSTURAL_SWAY_DEV in allowed
            and geo.hip_center_px is not None
            and mean_hip_center is not None
            and geo.shoulder_width_px > 0
        ):
            deviation = math.dist(geo.hip_center_px, mean_hip_center) / geo.shoulder_width_px
            signals[SIGNAL_POSTURAL_SWAY_DEV] = round(deviation, _ROUND_DECIMALS)

    def _write_rate_signals(
        self,
        signals: dict[str, float],
        geo: _FrameGeometry,
        previous: _FrameGeometry | None,
        allowed: set[str],
    ) -> None:
        """Signals that need the previous frame: displacement per second, in shoulder widths."""
        if previous is None or geo.hip_center_px is None or previous.hip_center_px is None:
            return

        delta_t = geo.timestamp_sec - previous.timestamp_sec
        if delta_t <= 0:
            return

        scale = (geo.shoulder_width_px + previous.shoulder_width_px) / 2.0
        if scale <= 0:
            return

        delta_x = geo.hip_center_px[0] - previous.hip_center_px[0]
        delta_y = geo.hip_center_px[1] - previous.hip_center_px[1]

        if SIGNAL_MOTION_RATE in allowed:
            signals[SIGNAL_MOTION_RATE] = round(
                math.hypot(delta_x, delta_y) / scale / delta_t, _ROUND_DECIMALS
            )
        if SIGNAL_HORIZONTAL_RATE in allowed:
            signals[SIGNAL_HORIZONTAL_RATE] = round(abs(delta_x) / scale / delta_t, _ROUND_DECIMALS)

    def _frame_visible_groups(self, frame: LandmarkFrame) -> list[LandmarkGroup]:
        """Which landmark groups were visible in this one frame."""
        from analyzers.landmark_availability import LANDMARK_GROUP_INDICES

        if frame.visibilities is None:
            return []
        threshold = self._profile.frame_requirements.min_landmark_visibility
        return [
            group
            for group, indices in LANDMARK_GROUP_INDICES.items()
            if all(
                index < len(frame.visibilities) and frame.visibilities[index] >= threshold
                for index in indices
            )
        ]

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _metric_is_measurable(self, metric: str, availability: AvailabilityReport) -> bool:
        """Whether this profile applies the metric and the landmarks for it were there."""
        spec = self._profile.metrics.get(metric)
        if spec is None:
            return False
        return availability.reason_for(spec.required_landmark_groups) is None

    def _gesture_active(self, geo: _FrameGeometry) -> bool | None:
        """Whether either wrist is outside the torso region in this frame."""
        if geo.wrist_elevation_ratios is None or geo.wrist_lateral_ratios is None:
            return None
        elevation_limit = self._param("gesture_rate", "gesture_elevation_ratio")
        lateral_limit = self._param("gesture_rate", "gesture_lateral_ratio")
        return any(
            elevation >= elevation_limit or lateral >= lateral_limit
            for elevation, lateral in zip(geo.wrist_elevation_ratios, geo.wrist_lateral_ratios)
        )

    def _closed_posture(self, geo: _FrameGeometry) -> bool | None:
        """Whether arms are folded, or both hands hang below the hip line, in this frame."""
        if geo.wrist_elevation_ratios is None:
            return None
        if geo.wrists_crossed:
            return True
        low_limit = self._param("closed_posture_ratio", "low_wrist_elevation_ratio")
        return all(elevation <= low_limit for elevation in geo.wrist_elevation_ratios)

    @staticmethod
    def _median_shoulder_width(geometries: list[_FrameGeometry]) -> float | None:
        """Median shoulder width in pixels — the scale every distance is divided by."""
        widths = [geo.shoulder_width_px for geo in geometries if geo.shoulder_width_px > 0]
        if not widths:
            return None
        return statistics.median(widths)

    @staticmethod
    def _mean_hip_center(geometries: list[_FrameGeometry]) -> tuple[float, float] | None:
        """
        The recording's own mean hip centre — the point `_postural_sway`
        measures RMS wander around for the whole-video aggregate, and what
        `SIGNAL_POSTURAL_SWAY_DEV` measures each individual frame's distance
        from for `E_POSTURAL_SWAY_SPIKE`.
        """
        centers = [geo.hip_center_px for geo in geometries if geo.hip_center_px is not None]
        if not centers:
            return None
        return (statistics.fmean(c[0] for c in centers), statistics.fmean(c[1] for c in centers))

    @staticmethod
    def _facing_reference_width(geometries: list[_FrameGeometry]) -> float | None:
        """The subject's own square-to-camera shoulder width, used by `turned_away_ratio`."""
        widths = sorted(geo.shoulder_width_px for geo in geometries if geo.shoulder_width_px > 0)
        if not widths:
            return None
        if len(widths) == 1:
            return widths[0]
        # Nearest-rank percentile: no interpolation, so the value is one the
        # recording actually contained and the result stays reproducible.
        rank = max(1, math.ceil(_FACING_REFERENCE_PERCENTILE / 100.0 * len(widths)))
        return widths[rank - 1]

    @staticmethod
    def _span_sec(frames: list[LandmarkFrame]) -> float:
        """Wall-clock span covered by the sampled frames."""
        if len(frames) < 2:
            return 0.0
        timestamps = [frame.timestamp_sec for frame in frames]
        return max(timestamps) - min(timestamps)

    @classmethod
    def _sampling_rate_hz(cls, frames: list[LandmarkFrame]) -> float:
        """Sampled frames per second of source video."""
        span = cls._span_sec(frames)
        if span <= 0:
            return 0.0
        return (len(frames) - 1) / span
