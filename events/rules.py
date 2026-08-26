"""
events/rules.py

One detection rule, and the vocabulary rules share.

Every threshold lives in `config/profiles/*.yaml`; nothing here hard-codes a
number. This module turns a `EventRuleSpec` from a profile into something
executable: does this frame match, is this rule even applicable to this
recording, what number goes on the event, and what does its label read.

Label discipline
----------------
A label states the measurement and stops. `Cúi mặt liên tục 5,2 giây` is a
label. `Thiếu tự tin` is a diagnosis the measurement layer has no standing to
make — and the moment a teacher spots one wrong diagnosis, the whole tool
loses its credibility. `SPECULATIVE_LABEL_TERMS` is checked when rules are
loaded, so a speculative template in a YAML file fails fast at startup rather
than reaching a classroom.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from models.features import PoseFeature, PoseFrameSample
from models.profiles import ContextProfile, EventRuleSpec
from utils.logger import get_logger

logger = get_logger(__name__)

# Terms that interpret a cause rather than report a measurement. Substring
# match, lowercased — `tự tin` therefore also catches `thiếu tự tin`.
SPECULATIVE_LABEL_TERMS: tuple[str, ...] = (
    "ngắc ngứ",
    "tự tin",
    "lo lắng",
    "mất bình tĩnh",
    "bình tĩnh",
    "hồi hộp",
    "căng thẳng",
    "bối rối",
    "lúng túng",
    "sợ",
    "chán",
    "tập trung",
    "yếu kém",
    "kém",
    "tệ",
    "dở",
)

# Aggregates accepted in a rule's `report.value` field.
_AGGREGATES = {
    "mean": statistics.fmean,
    "max": max,
    "min": min,
}


class SpeculativeLabelError(ValueError):
    """Raised when a profile's label template interprets rather than reports."""


def assert_descriptive(event_code: str, template: str) -> None:
    """
    Reject a label template that speculates about a cause.

    Raises:
        SpeculativeLabelError: If the template contains a speculative term.
    """
    lowered = template.lower()
    for term in SPECULATIVE_LABEL_TERMS:
        if term in lowered:
            raise SpeculativeLabelError(
                f"Nhãn của sự kiện {event_code} chứa từ suy đoán '{term}': \"{template}\". "
                "Nhãn chỉ được mô tả cái đo được, không diễn giải nguyên nhân."
            )


def format_number(value: float) -> str:
    """Format a number the way it is read in Vietnamese: `4,2` rather than `4.2`."""
    rounded = round(value, 1)
    text = f"{rounded:.1f}"
    if text.endswith(".0"):
        text = text[:-2]
    return text.replace(".", ",")


@dataclass(frozen=True)
class Segment:
    """A run of consecutive matching frames, before it becomes an event."""

    start_sec: float
    end_sec: float
    samples: tuple[PoseFrameSample, ...]

    @property
    def duration_sec(self) -> float:
        """Length of the run, from its first matching frame to its last."""
        return max(self.end_sec - self.start_sec, 0.0)

    def merged_with(self, other: "Segment") -> "Segment":
        """One segment spanning both, used when two runs sit close together."""
        return Segment(
            start_sec=min(self.start_sec, other.start_sec),
            end_sec=max(self.end_sec, other.end_sec),
            samples=self.samples + other.samples,
        )


class EventRule:
    """
    One event code plus the threshold set that decides when it fires.

    All conditions must hold in the same frame. That is what lets
    `E_STABLE_SEGMENT` — every metric simultaneously inside its good band —
    use exactly the same machinery as the single-condition rules, instead of
    a special case.
    """

    def __init__(self, code: str, spec: EventRuleSpec, profile: ContextProfile) -> None:
        assert_descriptive(code, spec.label_template)
        self.code = code
        self.spec = spec
        self.profile = profile

    # -- applicability ------------------------------------------------

    def unmet_metrics(self, pose: PoseFeature) -> list[str]:
        """Metrics this rule needs that did not come back measured for this recording."""
        unmet: list[str] = []
        for name in self.spec.requires_metrics:
            metric = pose.metric(name)
            if metric is None or not metric.measured:
                unmet.append(name)
        return unmet

    def applies_to(self, pose: PoseFeature) -> bool:
        """
        Whether this rule may run at all.

        A rule with no conditions never fires — that is how an uncalibrated
        profile stays silent instead of guessing.
        """
        return bool(self.spec.conditions) and not self.unmet_metrics(pose)

    # -- per-frame evaluation -----------------------------------------

    def matches(self, sample: PoseFrameSample) -> bool:
        """
        Whether one frame satisfies every condition.

        A frame missing a signal the rule reads is *not* a match. The signal
        is absent because that frame lacked the landmarks for it, and a rule
        must never fire on data that was not there.
        """
        if not sample.pose_detected:
            return False
        for condition in self.spec.conditions:
            value = sample.signals.get(condition.signal)
            if value is None:
                return False
            if not condition.comparison.holds(value, condition.threshold):
                return False
        return True

    # -- reporting ----------------------------------------------------

    def measured_value(self, segment: Segment, source_fps: float = 0.0) -> float:
        """
        The number that goes on the event, per the rule's `report.value`.

        `duration` reports the segment length; `frame` reports the source
        video's frame number at the segment's start (a plain whole number --
        easier to place than a raw decimal second or a normalized ratio);
        `mean:<signal>` / `max:<signal>` / `min:<signal>` aggregate one
        signal across the segment. An aggregate over a signal no frame
        carried falls back to the duration, so an event always carries a
        real observation.
        """
        spec = self.spec.report.value
        if spec == "duration":
            return round(segment.duration_sec, 4)
        if spec == "frame":
            return self._frame_number(segment.start_sec, source_fps)

        aggregate_name, _, signal = spec.partition(":")
        aggregate = _AGGREGATES.get(aggregate_name)
        if aggregate is None or not signal:
            logger.warning(
                "Rule %s declares an unknown report value '%s'; reporting duration instead.",
                self.code,
                spec,
            )
            return round(segment.duration_sec, 4)

        values = [
            sample.signals[signal] for sample in segment.samples if signal in sample.signals
        ]
        if not values:
            logger.warning(
                "Rule %s reports '%s' but no frame in the segment carried that signal; "
                "reporting duration instead.",
                self.code,
                spec,
            )
            return round(segment.duration_sec, 4)
        return round(float(aggregate(values)), 4)

    @staticmethod
    def _frame_number(start_sec: float, source_fps: float) -> float:
        """
        The source video's frame number at a segment's start.

        Falls back to the raw second if `source_fps` isn't available (a
        synthetic `PoseFeature` in a test, never a real self-practice
        recording -- `services/self_practice_manager.py` always supplies
        `VideoFeature.fps`), logged so a missing fps doesn't silently read as
        a real frame number.
        """
        if source_fps <= 0:
            logger.warning("No source_fps available; reporting the start second as the frame number instead.")
            return round(start_sec)
        return round(start_sec * source_fps)

    def render_label(self, segment: Segment, value: float) -> str:
        """Fill the profile's label template. Describes the measurement, nothing more."""
        return self.spec.label_template.format(
            duration=format_number(segment.duration_sec),
            value=format_number(value),
            unit=self.spec.report.unit,
            start=format_number(segment.start_sec),
        )


def load_rules(profile: ContextProfile) -> list[EventRule]:
    """
    Build every rule declared in a profile, in `event_catalog` order.

    A profile with no calibrated thresholds yields an empty list — the
    correct behaviour for `interview_solo` in this milestone (`presentation_solo`
    now carries thresholds too, borrowed from `presentation_class` as a starting
    point — see `config/profiles/presentation_solo.yaml`), and for any fourth
    profile dropped in later.

    Raises:
        SpeculativeLabelError: If any label template interprets a cause.
    """
    rules = [
        EventRule(code, profile.events[code], profile)
        for code in profile.event_catalog
        if code in profile.events
    ]
    if not rules:
        logger.info(
            "Profile '%s' (v%s) has no calibrated event rules; no events will be detected.",
            profile.profile,
            profile.version,
        )
    return rules
