"""
Unit tests for scripts/calibrate_thresholds.py's matching/scoring logic --
the part that doesn't need a real video, and the part most worth locking
down before Task 9 ever runs for real.
"""

from __future__ import annotations

from collections import defaultdict

import pytest

from models.events import PresentationEvent
from scripts.calibrate_thresholds import GroundTruthMark, TypeTally, load_ground_truth, score_video


def _event(type: str, start_sec: float, duration_sec: float) -> PresentationEvent:
    return PresentationEvent(
        session_id="s1", profile="presentation_solo", type=type, start_sec=start_sec, duration_sec=duration_sec,
        measured_value=duration_sec, unit="giây", label="x", rule_version="0.1.0",
    )


class TestLoadGroundTruth:
    def test_parses_a_well_formed_csv(self, tmp_path) -> None:
        path = tmp_path / "gt.csv"
        path.write_text("video_id,type,start_sec,duration_sec\nclip_01,E_HEAD_DOWN,12.0,5.0\n", encoding="utf-8")
        marks = load_ground_truth(path)
        assert marks == [GroundTruthMark("clip_01", "E_HEAD_DOWN", 12.0, 5.0)]

    def test_missing_column_raises(self, tmp_path) -> None:
        path = tmp_path / "gt.csv"
        path.write_text("video_id,type,start_sec\nclip_01,E_HEAD_DOWN,12.0\n", encoding="utf-8")
        with pytest.raises(ValueError, match="missing column"):
            load_ground_truth(path)

    def test_non_numeric_field_raises_with_row_number(self, tmp_path) -> None:
        path = tmp_path / "gt.csv"
        path.write_text(
            "video_id,type,start_sec,duration_sec\nclip_01,E_HEAD_DOWN,not-a-number,5.0\n", encoding="utf-8"
        )
        with pytest.raises(ValueError, match="row 2"):
            load_ground_truth(path)


class TestScoreVideo:
    def test_a_matching_event_counts_as_correct_on_both_sides(self) -> None:
        events = [_event("E_HEAD_DOWN", 12.0, 5.0)]
        marks = [GroundTruthMark("clip_01", "E_HEAD_DOWN", 13.0, 4.0)]
        tallies: dict[str, TypeTally] = defaultdict(TypeTally)
        score_video(events, marks, tolerance_sec=3.0, tallies=tallies)

        tally = tallies["E_HEAD_DOWN"]
        assert tally.system_events == 1
        assert tally.system_matched == 1
        assert tally.human_marks == 1
        assert tally.human_missed == 0

    def test_a_system_event_far_outside_tolerance_does_not_match(self) -> None:
        events = [_event("E_HEAD_DOWN", 12.0, 2.0)]
        marks = [GroundTruthMark("clip_01", "E_HEAD_DOWN", 60.0, 2.0)]
        tallies: dict[str, TypeTally] = defaultdict(TypeTally)
        score_video(events, marks, tolerance_sec=3.0, tallies=tallies)

        tally = tallies["E_HEAD_DOWN"]
        assert tally.system_matched == 0
        assert tally.human_missed == 1

    def test_different_types_never_match_even_at_the_same_time(self) -> None:
        events = [_event("E_HEAD_DOWN", 10.0, 5.0)]
        marks = [GroundTruthMark("clip_01", "E_TURNED_AWAY", 10.0, 5.0)]
        tallies: dict[str, TypeTally] = defaultdict(TypeTally)
        score_video(events, marks, tolerance_sec=3.0, tallies=tallies)

        assert tallies["E_HEAD_DOWN"].system_matched == 0
        assert tallies["E_TURNED_AWAY"].human_missed == 1

    def test_a_false_alarm_the_system_reports_with_no_human_mark_is_not_counted_as_matched(self) -> None:
        events = [_event("E_HEAD_DOWN", 10.0, 5.0)]
        marks: list[GroundTruthMark] = []
        tallies: dict[str, TypeTally] = defaultdict(TypeTally)
        score_video(events, marks, tolerance_sec=3.0, tallies=tallies)

        tally = tallies["E_HEAD_DOWN"]
        assert tally.system_events == 1
        assert tally.system_matched == 0
        assert tally.human_marks == 0
