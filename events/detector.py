"""
events/detector.py

Turns the per-frame time series on a `PoseFeature` into a list of discrete,
timestamped `PresentationEvent`s a reviewer can click and jump to.

The same six steps run for every rule, whatever it measures:

1. **Measure each frame** — already done; `PoseFeature.series` carries it.
2. **Compare against the threshold** — every condition of the rule must hold
   in the same frame (`EventRule.matches`).
3. **Find consecutive runs** of matching frames.
4. **Drop runs that are too short** (`min_duration_sec`).
5. **Merge same-type runs that sit close together** (`merge_gap_sec`).
6. **Attach the measured value and `rule_version`.**

Steps 4 and 5 are in that order on purpose: filtering before merging means
two brief runs never add up into an event neither of them earned. That is
the "rather miss it than call it wrongly" bias, applied at the one place it
is cheapest to apply.

A rule is skipped entirely when any metric it declares came back not
measured. Not "treated as zero" — skipped. The reviewer sees the metric
marked `không đo được` with its reason, which is honest, instead of an event
list quietly built on landmarks the camera never saw.
"""

from __future__ import annotations

from models.events import PresentationEvent
from models.features import PoseFeature, PoseFrameSample
from models.profiles import ContextProfile
from services.profile_loader import load_profile
from utils.logger import get_logger

from events.rules import EventRule, Segment, load_rules

logger = get_logger(__name__)


class EventDetector:
    """Runs every rule of one context profile over one recording's time series."""

    def __init__(self, profile: ContextProfile | str | None = None) -> None:
        """
        Args:
            profile: Context profile, its name, or `None` for the default
                (`presentation_class`).
        """
        if isinstance(profile, ContextProfile):
            self._profile = profile
        else:
            self._profile = load_profile(profile) if profile else load_profile()
        self._rules = load_rules(self._profile)

    @property
    def profile(self) -> ContextProfile:
        """The profile whose thresholds this detector applies."""
        return self._profile

    def detect(self, session_id: str, pose: PoseFeature) -> list[PresentationEvent]:
        """
        Args:
            session_id: Session these events belong to.
            pose: The analyzed recording, including its per-frame `series`.

        Returns:
            Every detected event, ordered by start time. Empty when the
            profile carries no calibrated thresholds, or when no metric the
            rules need was measurable.
        """
        if not pose.series:
            logger.info("No pose time series for session %s; no events detected.", session_id)
            return []

        events: list[PresentationEvent] = []
        for rule in self._rules:
            unmet = rule.unmet_metrics(pose)
            if unmet:
                logger.info(
                    "Skipping rule %s for session %s: metric(s) not measurable in this recording: %s",
                    rule.code,
                    session_id,
                    ", ".join(unmet),
                )
                continue
            if not rule.applies_to(pose):
                continue
            events.extend(self._detect_one(session_id, rule, pose.series, pose.source_fps))

        events.sort(key=lambda event: (event.start_sec, event.type))
        logger.info(
            "Detected %d event(s) for session %s using profile %s v%s.",
            len(events),
            session_id,
            self._profile.profile,
            self._profile.version,
        )
        return events

    # ------------------------------------------------------------------
    # The six steps
    # ------------------------------------------------------------------

    def _detect_one(
        self, session_id: str, rule: EventRule, series: list[PoseFrameSample], source_fps: float
    ) -> list[PresentationEvent]:
        """Run one rule end to end over the time series."""
        runs = self._consecutive_runs(rule, series)                       # steps 2-3
        long_enough = [run for run in runs if run.duration_sec >= rule.spec.min_duration_sec]  # step 4
        merged = self._merge_close(long_enough, rule.spec.merge_gap_sec)  # step 5
        return [self._to_event(session_id, rule, segment, source_fps) for segment in merged]  # step 6

    @staticmethod
    def _consecutive_runs(rule: EventRule, series: list[PoseFrameSample]) -> list[Segment]:
        """
        Steps 2-3: compare each frame against the rule, and collect the runs
        of consecutive matches.

        A run's duration spans its first matching frame to its last, which
        under-counts by up to one sampling interval at each end. That
        under-count is deliberate: it can only ever shorten an event, never
        invent one.
        """
        runs: list[Segment] = []
        current: list[PoseFrameSample] = []

        for sample in series:
            if rule.matches(sample):
                current.append(sample)
                continue
            if current:
                runs.append(EventDetector._close_run(current))
                current = []

        if current:
            runs.append(EventDetector._close_run(current))
        return runs

    @staticmethod
    def _close_run(samples: list[PoseFrameSample]) -> Segment:
        """Freeze an accumulating run into a `Segment`."""
        return Segment(
            start_sec=samples[0].timestamp_sec,
            end_sec=samples[-1].timestamp_sec,
            samples=tuple(samples),
        )

    @staticmethod
    def _merge_close(segments: list[Segment], merge_gap_sec: float) -> list[Segment]:
        """
        Step 5: fuse same-type segments separated by no more than
        `merge_gap_sec`, so one behaviour briefly interrupted reads as one
        event rather than three.
        """
        if not segments:
            return []

        ordered = sorted(segments, key=lambda segment: segment.start_sec)
        merged = [ordered[0]]
        for segment in ordered[1:]:
            previous = merged[-1]
            if segment.start_sec - previous.end_sec <= merge_gap_sec:
                merged[-1] = previous.merged_with(segment)
            else:
                merged.append(segment)
        return merged

    def _to_event(self, session_id: str, rule: EventRule, segment: Segment, source_fps: float) -> PresentationEvent:
        """Step 6: attach the measured value, the unit, the label, and the rule version."""
        value = rule.measured_value(segment, source_fps)
        return PresentationEvent(
            session_id=session_id,
            profile=self._profile.profile,
            type=rule.code,
            start_sec=round(segment.start_sec, 4),
            duration_sec=round(segment.duration_sec, 4),
            measured_value=value,
            unit=rule.spec.report.unit,
            label=rule.render_label(segment, value),
            rule_version=self._profile.version,
        )
