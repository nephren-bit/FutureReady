"""
models/profiles.py

Schema for a *context profile* — the YAML files in `config/profiles/`.

A context profile is the single place where every tunable number lives: which
metrics apply in this setting, which landmark groups each metric needs before
it may be computed at all, how good the framing has to be, which event codes
the profile is allowed to emit, and the threshold set for each of them.

Design rules this schema exists to enforce:

* **No hard-coded thresholds anywhere else.** Changing a number in a profile
  file and re-running must change the detected-event count without a single
  line of code being edited.
* **Every field is optional with a safe default.** Dropping an empty fourth
  YAML file into `config/profiles/` must load cleanly and simply produce no
  events, never a crash.
* **`version` is stamped onto every emitted event** (`rule_version`), so a
  stored result stays attributable to the exact threshold set that produced
  it after the thresholds are later recalibrated (Task 10).

Loaded and cached by `services/profile_loader.py`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LandmarkGroup(str, Enum):
    """
    Named groups of MediaPipe Pose landmarks that a metric can depend on.

    A metric declares which groups it needs; `analyzers/landmark_availability.py`
    decides which groups are actually visible often enough in this recording.
    The intersection is what makes a metric `measured` or not.
    """

    HEAD = "head"
    SHOULDERS = "shoulders"
    UPPER_BODY = "upper_body"
    HIPS = "hips"
    LEGS = "legs"


class Comparison(str, Enum):
    """How a per-frame signal is compared against a rule threshold."""

    BELOW = "below"
    AT_MOST = "at_most"
    ABOVE = "above"
    AT_LEAST = "at_least"

    def holds(self, value: float, threshold: float) -> bool:
        """Evaluate this comparison for one frame."""
        if self is Comparison.BELOW:
            return value < threshold
        if self is Comparison.AT_MOST:
            return value <= threshold
        if self is Comparison.ABOVE:
            return value > threshold
        return value >= threshold


class FrameRequirements(BaseModel):
    """Minimum framing quality below which metrics report `not measurable`."""

    model_config = ConfigDict(extra="forbid")

    min_pose_detected_ratio: float = Field(
        0.5, ge=0.0, le=1.0,
        description="Below this share of frames containing a detected person, nothing is measurable.",
    )
    min_landmark_visibility: float = Field(
        0.5, ge=0.0, le=1.0,
        description="A landmark whose MediaPipe visibility is under this counts as not seen.",
    )
    min_group_frame_ratio: float = Field(
        0.6, ge=0.0, le=1.0,
        description="A landmark group counts as stably visible only above this share of frames.",
    )
    min_sample_rate_hz: float = Field(
        1.0, ge=0.0,
        description="Sampling rate under which event detection is flagged as unreliable.",
    )


class MetricSpec(BaseModel):
    """One metric's contract: its unit, its landmark prerequisites, its geometry constants."""

    model_config = ConfigDict(extra="forbid")

    unit: str = ""
    required_landmark_groups: list[LandmarkGroup] = Field(default_factory=list)
    params: dict[str, float] = Field(default_factory=dict)


class RuleCondition(BaseModel):
    """A single per-frame test: `signal <comparison> threshold`."""

    model_config = ConfigDict(extra="forbid")

    signal: str
    comparison: Comparison
    threshold: float


class RuleReport(BaseModel):
    """
    What goes into `PresentationEvent.measured_value` / `.unit` for a segment.

    `value` is one of `duration`, or `<aggregate>:<signal>` where aggregate is
    `mean`, `max`, or `min`.
    """

    model_config = ConfigDict(extra="forbid")

    value: str = "duration"
    unit: str = "giây"


class EventRuleSpec(BaseModel):
    """
    The full threshold set for one event code.

    All conditions must hold simultaneously for a frame to be "in" the event —
    that is what makes `E_STABLE_SEGMENT` (every metric inside its good band)
    expressible with the same machinery as the single-condition rules.
    """

    model_config = ConfigDict(extra="forbid")

    requires_metrics: list[str] = Field(
        default_factory=list,
        description="Rule is skipped entirely unless every listed metric came back measured.",
    )
    conditions: list[RuleCondition] = Field(default_factory=list)
    min_duration_sec: float = Field(0.0, ge=0.0)
    merge_gap_sec: float = Field(0.0, ge=0.0)
    report: RuleReport = Field(default_factory=RuleReport)
    label_template: str = ""


class ContextProfile(BaseModel):
    """
    One `config/profiles/*.yaml` file, parsed.

    An entirely empty file parses into this model with every default applied:
    no metrics, no event catalog, no rules — a profile that measures nothing
    and emits nothing, which is exactly the correct behavior for a profile
    whose thresholds have not been calibrated yet.
    """

    model_config = ConfigDict(extra="forbid")

    profile: str = ""
    version: str = "0.0.0"
    description: str = ""

    frame_requirements: FrameRequirements = Field(default_factory=FrameRequirements)
    metrics: dict[str, MetricSpec] = Field(default_factory=dict)
    event_catalog: list[str] = Field(default_factory=list)
    events: dict[str, EventRuleSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _rules_must_be_declared(self) -> "ContextProfile":
        """A profile may only carry thresholds for event codes it declared."""
        undeclared = sorted(set(self.events) - set(self.event_catalog))
        if undeclared:
            raise ValueError(
                f"Profile '{self.profile}' defines thresholds for event codes missing "
                f"from `event_catalog`: {', '.join(undeclared)}"
            )
        return self

    def metric_params(self, metric: str) -> dict[str, float]:
        """Geometry constants for one metric, or an empty dict if it does not apply here."""
        spec = self.metrics.get(metric)
        return dict(spec.params) if spec else {}

    def metric_unit(self, metric: str) -> str:
        """Display unit for one metric, or an empty string if it does not apply here."""
        spec = self.metrics.get(metric)
        return spec.unit if spec else ""
