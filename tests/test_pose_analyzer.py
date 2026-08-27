"""
Unit tests for the body-movement analyzer, the landmark-availability gate,
and the event detector (Group A of specs/in-class-analysis/tasks.md).

MediaPipe never runs here: `PoseAnalyzer.analyze_landmarks` takes already-
detected landmarks, so the metric math is exercised on synthetic skeletons
that are exact by construction. That is the only way to assert things like
"the same person at two camera distances gives the same movement range" —
with a real recording you could never separate a metric bug from the video.
"""

from __future__ import annotations

import math

import pytest

from analyzers.landmark_availability import LandmarkAvailabilityChecker
from analyzers.pose_analyzer import LandmarkFrame, PoseAnalyzer, apply_head_pose_fallback
from events.detector import EventDetector
from events.rules import EventRule, Segment, SpeculativeLabelError, assert_descriptive, format_number
from models.features import FaceMeshFeature, PoseFeature, PoseFrameSample, PoseMetric
from models.notes import SelfNote
from models.profiles import ContextProfile, EventRuleSpec, LandmarkGroup, RuleReport
from services.profile_loader import available_profiles, load_profile

# MediaPipe Pose indices the synthetic skeleton fills in.
NOSE, L_SHOULDER, R_SHOULDER = 0, 11, 12
L_WRIST, R_WRIST = 15, 16
L_HIP, R_HIP = 23, 24
LANDMARK_COUNT = 33


def make_frame(
    timestamp: float,
    *,
    center_x: float = 500.0,
    shoulder_width: float = 200.0,
    head_above: float = 0.6,
    tilt_px: float = 0.0,
    hips_visible: bool = True,
    arms_visible: bool = True,
    wrist_elevation: float = 0.4,
    wrists_crossed: bool = False,
    detected: bool = True,
) -> LandmarkFrame:
    """
    Build one synthetic skeleton in pixel space.

    Distances are expressed as multiples of `shoulder_width` so a test can
    re-shoot the same pose at a different camera distance by changing only
    that one number.
    """
    if not detected:
        return LandmarkFrame(timestamp, None, None)

    points = [(0.0, 0.0)] * LANDMARK_COUNT
    visibilities = [0.0] * LANDMARK_COUNT

    shoulder_y = 300.0
    half = shoulder_width / 2.0
    points[L_SHOULDER] = (center_x - half, shoulder_y - tilt_px / 2.0)
    points[R_SHOULDER] = (center_x + half, shoulder_y + tilt_px / 2.0)
    points[NOSE] = (center_x, shoulder_y - head_above * shoulder_width)
    for index in (NOSE, 2, 5, 7, 8, L_SHOULDER, R_SHOULDER):
        visibilities[index] = 0.95

    hip_y = shoulder_y + 1.5 * shoulder_width
    if hips_visible:
        points[L_HIP] = (center_x - half * 0.8, hip_y)
        points[R_HIP] = (center_x + half * 0.8, hip_y)
        visibilities[L_HIP] = visibilities[R_HIP] = 0.95

    if arms_visible:
        wrist_y = hip_y - wrist_elevation * shoulder_width
        if wrists_crossed:
            # Each wrist well past the torso midline, away from its own shoulder.
            points[L_WRIST] = (center_x + half * 0.5, wrist_y)
            points[R_WRIST] = (center_x - half * 0.5, wrist_y)
        else:
            points[L_WRIST] = (center_x - half * 0.9, wrist_y)
            points[R_WRIST] = (center_x + half * 0.9, wrist_y)
        for index in (13, 14, L_WRIST, R_WRIST):
            visibilities[index] = 0.95

    return LandmarkFrame(timestamp, points, visibilities)


def standing_clip(count: int = 30, **kwargs) -> list[LandmarkFrame]:
    """A clip of `count` frames one second apart, all identical."""
    return [make_frame(float(i), **kwargs) for i in range(count)]


class TestLandmarkAvailability:
    def test_full_body_framing_sees_every_group(self) -> None:
        checker = LandmarkAvailabilityChecker(load_profile())
        report = checker.check([[0.9] * LANDMARK_COUNT for _ in range(20)])
        assert report.pose_detected_ratio == 1.0
        assert LandmarkGroup.HIPS in report.available_groups
        assert report.reason_for([LandmarkGroup.HIPS]) is None

    def test_chest_up_framing_reports_hips_missing_with_a_reason(self) -> None:
        checker = LandmarkAvailabilityChecker(load_profile())
        # Everything from the hips down (index 23+) below the visibility floor.
        report = checker.check([[0.9] * 23 + [0.1] * 10 for _ in range(20)])
        assert LandmarkGroup.SHOULDERS in report.available_groups
        assert LandmarkGroup.HIPS not in report.available_groups

        reason = report.reason_for([LandmarkGroup.HIPS])
        assert reason is not None
        assert "hông" in reason
        assert "khắc phục" in reason  # tells the user how to fix the framing

    def test_person_mostly_absent_blocks_everything(self) -> None:
        checker = LandmarkAvailabilityChecker(load_profile())
        frames: list[list[float] | None] = [[0.9] * LANDMARK_COUNT for _ in range(3)]
        frames += [None] * 17
        report = checker.check(frames)
        assert report.available_groups == ()
        assert report.pose_detection_reason is not None
        assert report.reason_for([LandmarkGroup.SHOULDERS]) is not None


class TestPoseMetrics:
    def test_reports_detection_ratio_and_analyzed_frame_count(self) -> None:
        frames = standing_clip(20) + [make_frame(float(i), detected=False) for i in range(20, 25)]
        feature = PoseAnalyzer().analyze_landmarks(frames)
        assert feature.frames_analyzed == 25
        assert feature.pose_detected_ratio == 0.8
        assert feature.profile == "presentation_class"

    def test_head_up_and_head_down_clips_are_distinguished(self) -> None:
        analyzer = PoseAnalyzer()
        up = analyzer.analyze_landmarks(standing_clip(head_above=0.6))
        down = analyzer.analyze_landmarks(standing_clip(head_above=0.1))
        assert up.head_up_ratio.measured is True
        assert up.head_up_ratio.value == 1.0
        assert down.head_up_ratio.value == 0.0

    def test_hip_metrics_are_not_measurable_without_hips(self) -> None:
        """The acceptance check for Task 2: chest-up framing, no numbers invented."""
        feature = PoseAnalyzer().analyze_landmarks(standing_clip(hips_visible=False, arms_visible=False))

        for name in ("postural_sway", "movement_range", "gesture_rate", "closed_posture_ratio"):
            metric = getattr(feature, name)
            assert metric.measured is False, f"{name} should not be measurable"
            assert metric.value is None, f"{name} returned a number instead of `không đo được`"
            assert metric.reason, f"{name} gives no reason"

        # Metrics that only need head + shoulders still work.
        assert feature.head_up_ratio.measured is True
        assert feature.shoulder_tilt.measured is True

    def test_shoulder_tilt_is_measured_in_degrees(self) -> None:
        # A 200 px shoulder line raised 200 px end to end is 45 degrees.
        feature = PoseAnalyzer().analyze_landmarks(standing_clip(shoulder_width=200.0, tilt_px=200.0))
        assert feature.shoulder_tilt.value == pytest.approx(45.0, abs=0.01)
        assert feature.shoulder_tilt.unit == "độ"

    def test_movement_range_counts_horizontal_travel_in_shoulder_widths(self) -> None:
        frames = [make_frame(float(i), center_x=500.0 + 100.0 * i, shoulder_width=200.0) for i in range(3)]
        feature = PoseAnalyzer().analyze_landmarks(frames)
        # 200 px of travel over a 200 px shoulder width.
        assert feature.movement_range.value == pytest.approx(1.0, abs=1e-6)

    def test_closed_posture_detects_crossed_arms(self) -> None:
        analyzer = PoseAnalyzer()
        crossed = analyzer.analyze_landmarks(standing_clip(wrists_crossed=True))
        open_arms = analyzer.analyze_landmarks(standing_clip(wrist_elevation=0.4))
        assert crossed.closed_posture_ratio.value == 1.0
        assert open_arms.closed_posture_ratio.value == 0.0

    def test_closed_posture_detects_hands_held_low(self) -> None:
        low = PoseAnalyzer().analyze_landmarks(standing_clip(wrist_elevation=-0.2))
        assert low.closed_posture_ratio.value == 1.0

    def test_turned_away_uses_the_subject_as_their_own_reference(self) -> None:
        # Ten frames square to camera, then ten with the shoulder line at 40%.
        frames = [make_frame(float(i), shoulder_width=200.0) for i in range(10)]
        frames += [make_frame(float(i), shoulder_width=80.0) for i in range(10, 20)]
        feature = PoseAnalyzer().analyze_landmarks(frames)
        assert feature.turned_away_ratio.value == pytest.approx(0.5, abs=1e-6)

    def test_gesture_rate_counts_rising_edges_per_minute(self) -> None:
        # Two separate raises across a 60-second clip -> 2 per minute.
        frames: list[LandmarkFrame] = []
        for i in range(61):
            raising = i in range(10, 20) or i in range(40, 50)
            frames.append(make_frame(float(i), wrist_elevation=0.8 if raising else 0.1))
        feature = PoseAnalyzer().analyze_landmarks(frames)
        assert feature.gesture_rate.value == pytest.approx(2.0, abs=1e-6)

    def test_postural_sway_dev_signal_is_gated_by_hips_like_its_aggregate(self) -> None:
        """`postural_sway_dev` (per-frame) backs `E_POSTURAL_SWAY_SPIKE`, the
        same way `postural_sway` (whole-video RMS) backs its own metric card --
        both need the hips landmark group, so both go missing together."""
        with_hips = PoseAnalyzer().analyze_landmarks(standing_clip(3))
        assert "postural_sway_dev" in with_hips.series[0].signals

        without_hips = PoseAnalyzer().analyze_landmarks(
            standing_clip(3, hips_visible=False, arms_visible=False)
        )
        assert "postural_sway_dev" not in without_hips.series[0].signals


class TestCameraDistanceInvariance:
    """Task 3's acceptance check: same movement, two camera distances, same numbers."""

    @staticmethod
    def _walk(shoulder_width: float) -> PoseFeature:
        # The subject moves one shoulder width per second, whatever the zoom.
        frames = [
            make_frame(
                float(i),
                center_x=400.0 + shoulder_width * i,
                shoulder_width=shoulder_width,
            )
            for i in range(10)
        ]
        return PoseAnalyzer().analyze_landmarks(frames)

    def test_movement_range_within_10_percent_across_distances(self) -> None:
        near = self._walk(300.0).movement_range.value
        far = self._walk(90.0).movement_range.value
        assert near is not None and far is not None
        assert abs(near - far) / near < 0.10

    def test_postural_sway_within_10_percent_across_distances(self) -> None:
        near = self._walk(300.0).postural_sway.value
        far = self._walk(90.0).postural_sway.value
        assert near is not None and far is not None
        assert abs(near - far) / near < 0.10


class TestDeterminism:
    """Task 3's acceptance check: two runs, identical to four decimals."""

    def test_identical_input_gives_identical_metrics(self) -> None:
        frames = [
            make_frame(
                float(i),
                center_x=500.0 + 37.0 * math.sin(i / 3.0),
                shoulder_width=200.0 + 10.0 * math.cos(i / 5.0),
                head_above=0.3 + 0.2 * math.sin(i / 2.0),
                wrist_elevation=0.2 + 0.5 * math.sin(i / 4.0),
            )
            for i in range(40)
        ]
        first = PoseAnalyzer().analyze_landmarks(frames)
        second = PoseAnalyzer().analyze_landmarks(frames)
        assert first.model_dump() == second.model_dump()


class TestContextProfiles:
    def test_all_three_profiles_load(self) -> None:
        assert {"presentation_class", "presentation_solo", "interview_solo"} <= set(available_profiles())

    def test_presentation_profiles_carry_thresholds_interview_does_not(self) -> None:
        # presentation_solo's thresholds are carried over from presentation_class
        # as a starting point (see config/profiles/presentation_solo.yaml) — not
        # yet calibrated for the close-webcam context. interview_solo still has
        # none at all.
        assert load_profile("presentation_class").events
        assert load_profile("presentation_solo").events
        assert load_profile("interview_solo").events == {}

    def test_an_empty_fourth_profile_does_not_break_anything(self) -> None:
        """Task 4's acceptance check: an empty profile loads and simply detects nothing."""
        empty = ContextProfile(profile="quay_thu")
        detector = EventDetector(empty)
        feature = PoseAnalyzer(empty).analyze_landmarks(standing_clip())

        assert detector.detect("s1", feature) == []
        # Every metric reports itself as out of scope for this profile, with a reason.
        assert feature.measured_metrics() == []
        assert feature.head_up_ratio.reason is not None

    def test_a_profile_may_not_declare_thresholds_it_never_catalogued(self) -> None:
        with pytest.raises(ValueError):
            ContextProfile.model_validate(
                {"profile": "x", "event_catalog": [], "events": {"E_HEAD_DOWN": {}}}
            )


def series_from(signals_per_frame: list[dict[str, float]]) -> list[PoseFrameSample]:
    """Build a one-frame-per-second time series directly from signal values."""
    return [
        PoseFrameSample(timestamp_sec=float(i), pose_detected=True, signals=dict(signals))
        for i, signals in enumerate(signals_per_frame)
    ]


def pose_with(series: list[PoseFrameSample]) -> PoseFeature:
    """A `PoseFeature` whose every metric is measured, so no rule is skipped."""
    measured = PoseMetric.measure(0.5, "x")
    return PoseFeature(
        profile="presentation_class",
        profile_version="0.1.0",
        frames_analyzed=len(series),
        pose_detected_ratio=1.0,
        series=series,
        head_up_ratio=measured,
        postural_sway=measured,
        movement_range=measured,
        gesture_rate=measured,
        closed_posture_ratio=measured,
        shoulder_tilt=measured,
        turned_away_ratio=measured,
    )


NEUTRAL = {
    "head_up": 1.0,
    "motion_rate": 0.2,
    "horizontal_rate": 0.1,
    "turned_away": 0.0,
    "closed_posture": 0.0,
    "shoulder_tilt_deg": 3.0,
    "shoulder_width_ratio": 1.0,
}


class TestEventDetector:
    def test_every_event_carries_time_value_unit_and_rule_version(self) -> None:
        """Task 5's first acceptance check."""
        frames = [dict(NEUTRAL) for _ in range(20)]
        for i in range(5, 15):
            frames[i]["head_up"] = 0.0
        events = EventDetector().detect("s1", pose_with(series_from(frames)))

        assert events, "expected at least one event"
        for event in events:
            assert event.start_sec >= 0.0
            assert event.duration_sec > 0.0
            assert isinstance(event.measured_value, float)
            assert event.unit
            assert event.rule_version == load_profile().version
            assert event.profile == "presentation_class"

    def test_no_label_speculates_about_a_cause(self) -> None:
        """Task 5's second acceptance check."""
        frames = [dict(NEUTRAL) for _ in range(60)]
        for i in range(5, 20):
            frames[i]["head_up"] = 0.0
        for i in range(25, 45):
            frames[i]["closed_posture"] = 1.0
        events = EventDetector().detect("s1", pose_with(series_from(frames)))

        banned = ("ngắc ngứ", "thiếu tự tin", "lo lắng", "mất bình tĩnh")
        for event in events:
            lowered = event.label.lower()
            for term in banned:
                assert term not in lowered, f"label speculates: {event.label}"

    def test_runs_shorter_than_the_minimum_are_dropped(self) -> None:
        frames = [dict(NEUTRAL) for _ in range(20)]
        frames[5]["head_up"] = 0.0
        frames[6]["head_up"] = 0.0  # 1 second, well under E_HEAD_DOWN's 4
        assert EventDetector().detect("s1", pose_with(series_from(frames))) == []

    def test_close_runs_of_the_same_type_merge_into_one(self) -> None:
        frames = [dict(NEUTRAL) for _ in range(30)]
        for i in list(range(0, 6)) + list(range(7, 14)):  # one frame of interruption
            frames[i]["head_up"] = 0.0
        events = [e for e in EventDetector().detect("s1", pose_with(series_from(frames)))
                  if e.type == "E_HEAD_DOWN"]
        assert len(events) == 1
        assert events[0].duration_sec == pytest.approx(13.0)

    def test_a_rule_is_skipped_when_its_metric_was_not_measurable(self) -> None:
        frames = [dict(NEUTRAL) for _ in range(20)]
        for i in range(5, 18):
            frames[i]["head_up"] = 0.0

        pose = pose_with(series_from(frames))
        pose.head_up_ratio = PoseMetric.not_measured("tỷ lệ 0-1", "Không thấy đầu.")
        assert [e.type for e in EventDetector().detect("s1", pose)] == []

    def test_a_frame_missing_the_signal_never_matches(self) -> None:
        frames = [dict(NEUTRAL) for _ in range(20)]
        for i in range(5, 18):
            frames[i].pop("head_up")  # landmarks absent, not "head was down"
        assert EventDetector().detect("s1", pose_with(series_from(frames))) == []

    def test_changing_one_threshold_changes_the_event_count(self) -> None:
        """Task 4's acceptance check, without editing a line of code."""
        frames = [dict(NEUTRAL) for _ in range(30)]
        for i in range(5, 12):  # a 6-second run of head-down
            frames[i]["head_up"] = 0.0
        pose = pose_with(series_from(frames))

        strict = load_profile("presentation_class").model_copy(deep=True)
        strict.events["E_HEAD_DOWN"].min_duration_sec = 20.0
        lenient = load_profile("presentation_class").model_copy(deep=True)
        lenient.events["E_HEAD_DOWN"].min_duration_sec = 2.0

        strict_count = len([e for e in EventDetector(strict).detect("s", pose) if e.type == "E_HEAD_DOWN"])
        lenient_count = len([e for e in EventDetector(lenient).detect("s", pose) if e.type == "E_HEAD_DOWN"])
        assert strict_count == 0
        assert lenient_count == 1

    def test_stable_segment_needs_every_signal_in_its_good_band(self) -> None:
        good = [dict(NEUTRAL) for _ in range(40)]
        events = [e for e in EventDetector().detect("s1", pose_with(series_from(good)))
                  if e.type == "E_STABLE_SEGMENT"]
        assert len(events) == 1

        # One signal out of band for the whole clip, and the segment is gone.
        bad = [dict(NEUTRAL, shoulder_tilt_deg=25.0) for _ in range(40)]
        assert [e for e in EventDetector().detect("s1", pose_with(series_from(bad)))
                if e.type == "E_STABLE_SEGMENT"] == []


class TestEdgeTrigger:
    """
    `trigger: edge` (models/profiles.py, events/detector.py) reports one
    zero-duration point per occurrence, instead of a sustained run -- for
    something that IS the event by happening at all (a gesture, the head
    coming back up), not by lasting.
    """

    @staticmethod
    def _edge_profile(merge_gap_sec: float = 2.0) -> ContextProfile:
        spec = EventRuleSpec(
            conditions=[dict(signal="active", comparison="at_least", threshold=1.0)],
            trigger="edge",
            merge_gap_sec=merge_gap_sec,
            report=RuleReport(value="frame", unit="khung hình"),
            label_template="Sự kiện (khung hình {value})",
        )
        return ContextProfile(profile="x", event_catalog=["E_TEST"], events={"E_TEST": spec})

    def test_one_zero_duration_point_per_rising_edge(self) -> None:
        frames = [{"active": 0.0} for _ in range(20)]
        for i in (3, 4, 5):  # one continuous occurrence
            frames[i]["active"] = 1.0
        frames[15]["active"] = 1.0  # a second, separate occurrence
        pose = pose_with(series_from(frames))
        events = EventDetector(self._edge_profile()).detect("s1", pose)

        assert len(events) == 2
        assert all(event.duration_sec == 0.0 for event in events)
        assert [event.start_sec for event in events] == [3.0, 15.0]

    def test_a_one_frame_flicker_does_not_double_count(self) -> None:
        frames = [{"active": 0.0} for _ in range(20)]
        frames[3]["active"] = 1.0
        # Drops out for exactly one sample, back on 2 seconds after the first
        # edge -- within merge_gap_sec, so it must read as one occurrence,
        # not a second gesture.
        frames[5]["active"] = 1.0
        pose = pose_with(series_from(frames))
        events = EventDetector(self._edge_profile(merge_gap_sec=2.0)).detect("s1", pose)
        assert len(events) == 1

    def test_edge_rule_rejects_a_nonzero_min_duration(self) -> None:
        """An edge rule's events are always zero-duration -- a nonzero
        min_duration_sec would just silently drop every one of them."""
        with pytest.raises(ValueError):
            EventRuleSpec(trigger="edge", min_duration_sec=1.0)


class TestPresentationSoloCountEvents:
    """
    E_GESTURE / E_HEAD_UP / E_POSTURAL_SWAY_SPIKE (config/profiles/
    presentation_solo.yaml) -- new, provisional thresholds added alongside
    `trigger: edge` so the detected-events panel can say "ngẩng đầu lên 1
    lần" instead of only a whole-video ratio. E_POSTURAL_SWAY_SPIKE stays
    `trigger: sustained` on purpose: the ask was "lắc lư TRONG BAO NHIÊU
    GIÂY", a duration, not a count.
    """

    @staticmethod
    def _pose(frames: list[dict[str, float]]) -> PoseFeature:
        pose = pose_with(series_from(frames))
        pose.profile = "presentation_solo"
        return pose

    def test_head_up_moment_is_reported_once_per_recovery(self) -> None:
        frames = [dict(NEUTRAL, head_up=0.0) for _ in range(20)]
        for i in (8, 9, 10):  # head comes up for 3 frames, one recovery
            frames[i]["head_up"] = 1.0
        events = [
            e for e in EventDetector("presentation_solo").detect("s1", self._pose(frames))
            if e.type == "E_HEAD_UP"
        ]
        assert len(events) == 1
        assert events[0].duration_sec == 0.0

    def test_gesture_is_counted_once_per_occurrence(self) -> None:
        frames = [dict(NEUTRAL, gesture_active=0.0) for _ in range(30)]
        for i in (3, 4):  # first gesture
            frames[i]["gesture_active"] = 1.0
        frames[20]["gesture_active"] = 1.0  # a second, separate gesture
        events = [
            e for e in EventDetector("presentation_solo").detect("s1", self._pose(frames))
            if e.type == "E_GESTURE"
        ]
        assert len(events) == 2

    def test_postural_sway_spike_still_reports_a_duration_not_a_count(self) -> None:
        frames = [dict(NEUTRAL, postural_sway_dev=0.0) for _ in range(20)]
        for i in range(5, 10):  # 4 seconds above the sway threshold
            frames[i]["postural_sway_dev"] = 0.8
        events = [
            e for e in EventDetector("presentation_solo").detect("s1", self._pose(frames))
            if e.type == "E_POSTURAL_SWAY_SPIKE"
        ]
        assert len(events) == 1
        assert events[0].duration_sec == pytest.approx(4.0)


class TestFrameReporting:
    """
    `report.value: frame` (config/profiles/presentation_solo.yaml's
    E_STATIC/E_PACING/E_TURNED_AWAY) reports the source video's frame number
    at a segment's start -- a plain whole number, instead of a normalized
    ratio like "0,04 lần rộng vai mỗi giây" that only means something to
    someone who already knows the metric's unit.
    """

    @staticmethod
    def _frame_rule() -> EventRule:
        spec = EventRuleSpec(report=RuleReport(value="frame", unit="khung hình"), label_template="{value}")
        return EventRule("E_TEST", spec, ContextProfile(profile="x"))

    def test_frame_number_is_the_start_second_times_source_fps(self) -> None:
        segment = Segment(start_sec=2.5, end_sec=3.5, samples=())
        assert self._frame_rule().measured_value(segment, source_fps=30.0) == 75

    def test_frame_number_is_a_whole_number_not_a_ratio(self) -> None:
        segment = Segment(start_sec=1.0 / 3.0, end_sec=1.0, samples=())
        value = self._frame_rule().measured_value(segment, source_fps=24.0)
        assert value == int(value)

    def test_missing_source_fps_falls_back_to_the_plain_second(self) -> None:
        segment = Segment(start_sec=4.2, end_sec=5.0, samples=())
        assert self._frame_rule().measured_value(segment, source_fps=0.0) == 4


class TestLabelDiscipline:
    def test_a_speculative_template_is_rejected_at_load_time(self) -> None:
        with pytest.raises(SpeculativeLabelError):
            assert_descriptive("E_TEST", "Người nói thiếu tự tin trong {duration} giây")

    def test_a_descriptive_template_passes(self) -> None:
        assert_descriptive("E_TEST", "Khoảng lặng {duration} giây")

    def test_numbers_are_formatted_as_plain_whole_numbers(self) -> None:
        assert format_number(4.24) == "4"
        assert format_number(4.6) == "5"
        assert format_number(12.0) == "12"

    def test_every_shipped_profile_has_descriptive_labels(self) -> None:
        for name in available_profiles():
            profile = load_profile(name)
            for code, rule in profile.events.items():
                assert_descriptive(code, rule.label_template)


class TestHeadPoseFallback:
    """Task 3: head_up_ratio comes from Pose first, Face Mesh only as a fallback."""

    @staticmethod
    def _unmeasured() -> PoseFeature:
        return PoseFeature(
            profile="presentation_class",
            head_up_ratio=PoseMetric.not_measured("tỷ lệ 0-1", "Không thấy vai."),
        )

    def test_pose_wins_when_it_measured_the_metric(self) -> None:
        pose = PoseFeature(profile="presentation_class", head_up_ratio=PoseMetric.measure(0.42, "x"))
        facemesh = FaceMeshFeature(faces_detected_ratio=0.95, head_up_ratio=0.90)
        assert apply_head_pose_fallback(pose, facemesh).head_up_ratio.value == 0.42

    def test_face_mesh_fills_in_when_the_face_was_clearly_detected(self) -> None:
        facemesh = FaceMeshFeature(faces_detected_ratio=0.95, head_up_ratio=0.80)
        filled = apply_head_pose_fallback(self._unmeasured(), facemesh)
        assert filled.head_up_ratio.measured is True
        assert filled.head_up_ratio.value == 0.80

    def test_a_barely_detected_face_is_not_good_enough(self) -> None:
        facemesh = FaceMeshFeature(faces_detected_ratio=0.2, head_up_ratio=0.80)
        still_unmeasured = apply_head_pose_fallback(self._unmeasured(), facemesh)
        assert still_unmeasured.head_up_ratio.measured is False
        assert still_unmeasured.head_up_ratio.value is None

    def test_no_face_mesh_at_all_leaves_the_metric_alone(self) -> None:
        assert apply_head_pose_fallback(self._unmeasured(), None).head_up_ratio.measured is False

    def test_the_fallback_does_not_mutate_its_input(self) -> None:
        pose = self._unmeasured()
        apply_head_pose_fallback(pose, FaceMeshFeature(faces_detected_ratio=0.95, head_up_ratio=0.8))
        assert pose.head_up_ratio.measured is False


class TestSelfNote:
    """Task 4: SelfNote edits in place, carries no ground-truth machinery."""

    def test_a_note_starts_with_no_ground_truth_machinery(self) -> None:
        note = SelfNote(session_id="s1", mark_sec=12.0)
        assert note.text == ""
        assert not hasattr(note, "visibility")
        assert not hasattr(note, "created_during_recording")

    def test_editing_updates_the_same_note_instead_of_revising(self) -> None:
        original = SelfNote(session_id="s1", mark_sec=12.0, text="ban dau")
        edited = original.edited(text="da sua")

        assert edited.note_id == original.note_id  # same row, not a new one
        assert edited.text == "da sua"
        assert edited.mark_sec == original.mark_sec
        assert edited.updated_at >= original.updated_at

    def test_editing_only_the_given_fields_leaves_the_rest_alone(self) -> None:
        original = SelfNote(session_id="s1", mark_sec=12.0, text="ghi chu")
        moved = original.edited(mark_sec=20.0)
        assert moved.mark_sec == 20.0
        assert moved.text == "ghi chu"
