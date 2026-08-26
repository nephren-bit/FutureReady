"""
models/features.py

Strongly-typed feature schema for the self-practice pipeline
(specs/in-class-analysis): `extractors/video_extractor.py` produces
`VideoFeature`, `analyzers/pose_analyzer.py` produces `PoseFeature` from it,
and `events/detector.py` turns `PoseFeature.series` into `PresentationEvent`s
(models/events.py). `FaceMeshFeature` stays defined here too even though
nothing currently produces one -- `analyzers/pose_analyzer.py`'s
`apply_head_pose_fallback` is written against it, and `presentation_solo.yaml`
already anticipates a Face Mesh fallback for `head_up_ratio`.

This module used to be the shared schema for a much larger evaluation
pipeline (resume/slide/speech/transcript/emotion analysis, feature fusion,
scoring). That pipeline and its models were removed -- see git history
before the removal commit if any of that is needed again.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from models.profiles import LandmarkGroup

# ---------------------------------------------------------------------------
# Video (extractors/video_extractor.py)
# ---------------------------------------------------------------------------


class VideoFeature(BaseModel):
    """Raw structured features extracted from a video (OpenCV)."""

    fps: float = Field(..., ge=0)
    frame_count: int = Field(..., ge=0)
    duration_sec: float = Field(..., ge=0)
    width: int = 0
    height: int = 0
    sampled_frame_count: int = Field(
        ..., ge=0, description="Number of frames sampled for downstream vision analyzers."
    )
    brightness_mean: float = 0.0
    brightness_std: float = 0.0
    contrast_mean: float = 0.0
    motion_score_mean: float = Field(
        0.0, description="Mean inter-frame pixel difference, a proxy for overall movement."
    )
    motion_score_std: float = 0.0
    scene_cut_count: int = Field(
        0, description="Number of abrupt frame-to-frame changes above threshold."
    )
    blur_score_mean: float = Field(
        0.0, description="Mean variance-of-Laplacian; lower means blurrier footage."
    )


# ---------------------------------------------------------------------------
# Face Mesh -- kept for `apply_head_pose_fallback`'s signature even though no
# analyzer currently produces one (see module docstring).
# ---------------------------------------------------------------------------


class FaceMeshFeature(BaseModel):
    """Output of a MediaPipe Face Mesh analyzer, if one is ever wired back in."""

    frames_analyzed: int = 0
    faces_detected_ratio: float = Field(0.0, ge=0.0, le=1.0)
    blink_rate_per_min: float = 0.0
    eye_openness_mean: float = Field(0.0, ge=0.0, le=1.0)
    eye_contact_ratio: float = Field(
        0.0, ge=0.0, le=1.0, description="Fraction of analyzed frames where gaze is toward camera."
    )
    head_up_ratio: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Fallback head-up signal for `PoseFeature.head_up_ratio`, from the nose's "
            "position between the eye line and the chin. None when no face was found."
        ),
    )
    head_pose_pitch_std: float = 0.0
    head_pose_yaw_std: float = 0.0
    head_pose_roll_std: float = 0.0
    head_movement_score: float = Field(0.0, ge=0.0, le=1.0)
    face_stability_ratio: float = Field(0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Pose (analyzers/pose_analyzer.py) -- the self-practice pipeline's core output
# ---------------------------------------------------------------------------


class PoseMetric(BaseModel):
    """
    One body-movement metric, carrying its own `measured` flag.

    A metric is only ever `measured=True` when every landmark group it
    declared in the context profile was stably visible. Otherwise `value`
    stays `None` and `reason` says why — **never 0.0**. A zero is a legitimate
    measurement ("did not move at all"); returning one for "could not see the
    hips" is the exact failure this flag exists to make impossible.
    """

    value: float | None = None
    measured: bool = False
    unit: str = ""
    reason: str | None = Field(
        None, description="Vietnamese explanation of why the metric is not measurable."
    )

    @classmethod
    def not_measured(cls, unit: str, reason: str) -> "PoseMetric":
        """Build a `không đo được` metric carrying its reason."""
        return cls(value=None, measured=False, unit=unit, reason=reason)

    @classmethod
    def measure(cls, value: float, unit: str) -> "PoseMetric":
        """Build a measured metric, rounded to the pipeline's 4-decimal contract."""
        return cls(value=round(float(value), 4), measured=True, unit=unit, reason=None)


class LandmarkGroupAvailability(BaseModel):
    """How reliably one landmark group was visible across the sampled frames."""

    group: LandmarkGroup
    visible_frame_ratio: float = Field(0.0, ge=0.0, le=1.0)
    available: bool = False


class PoseFrameSample(BaseModel):
    """
    One sampled frame's worth of per-frame signals, in profile-independent
    units (everything distance-based is already divided by shoulder width, so
    the same person filmed from 2 m and from 5 m produces the same numbers).

    `signals` is a flat name -> value map rather than fixed fields because
    `config/profiles/*.yaml` addresses signals by name; adding a signal is
    then an analyzer change plus a YAML change, with no schema migration.
    Missing signals are absent from the map, not zero.
    """

    timestamp_sec: float = 0.0
    pose_detected: bool = False
    visible_groups: list[LandmarkGroup] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)


class PoseFeature(BaseModel):
    """
    Output of the MediaPipe Pose analyzer (`analyzers/pose_analyzer.py`).

    This is the body-movement replacement for the eye-contact signal: in a
    classroom the presenter should be looking at the audience, not at the
    lens, so measuring gaze-into-camera measures the wrong thing entirely.
    """

    profile: str = Field("", description="Context profile code used to compute these metrics.")
    profile_version: str = Field("0.0.0", description="Version of that profile's threshold set.")

    frames_analyzed: int = 0
    pose_detected_ratio: float = Field(0.0, ge=0.0, le=1.0)
    available_landmark_groups: list[LandmarkGroup] = Field(default_factory=list)
    landmark_group_availability: list[LandmarkGroupAvailability] = Field(default_factory=list)

    sampling_rate_hz: float = Field(
        0.0, description="Sampled frames per second of source video, for event-detection reliability."
    )
    sampling_warning: str | None = Field(
        None, description="Set when sampling is too sparse for the profile's event rules."
    )
    source_fps: float = Field(
        0.0,
        description=(
            "The original video's frame rate (not the sampling rate above). Lets "
            "events/rules.py report a real frame number for `report.value: frame` "
            "instead of a raw decimal timestamp."
        ),
    )

    head_up_ratio: PoseMetric = Field(default_factory=PoseMetric)
    postural_sway: PoseMetric = Field(default_factory=PoseMetric)
    movement_range: PoseMetric = Field(default_factory=PoseMetric)
    gesture_rate: PoseMetric = Field(default_factory=PoseMetric)
    closed_posture_ratio: PoseMetric = Field(default_factory=PoseMetric)
    shoulder_tilt: PoseMetric = Field(default_factory=PoseMetric)
    turned_away_ratio: PoseMetric = Field(default_factory=PoseMetric)

    series: list[PoseFrameSample] = Field(
        default_factory=list,
        description="Per-frame time series, consumed by events/detector.py.",
    )

    def metric(self, name: str) -> PoseMetric | None:
        """Look a metric up by its profile name, or `None` if there is no such metric."""
        value = getattr(self, name, None)
        return value if isinstance(value, PoseMetric) else None

    def measured_metrics(self) -> list[str]:
        """Names of every metric that actually came back with a value."""
        return [
            name
            for name in (
                "head_up_ratio",
                "postural_sway",
                "movement_range",
                "gesture_rate",
                "closed_posture_ratio",
                "shoulder_tilt",
                "turned_away_ratio",
            )
            if getattr(self, name).measured
        ]
