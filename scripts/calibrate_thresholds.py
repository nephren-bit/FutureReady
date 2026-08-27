"""
scripts/calibrate_thresholds.py

Task 9's tooling (specs/in-class-analysis/plan.md, "Testing Approach"): once
someone has collected 10 real recordings for a profile and a person has
marked ground-truth timestamps on them *before* seeing the machine's output,
this script runs the real pipeline on each recording and prints, per event
type, how often the machine agreed with the human.

This script does not run Task 9 itself -- it cannot: Task 9 needs a human to
watch 10 recordings and mark them blind, which is not something this tool
can do honestly on anyone's behalf (see plan.md and tasks.md's note on why
Task 9 is out of scope for this milestone). What this script removes is the
need to write any code once that data exists -- collecting it and running
one command is all Task 9 will take.

Ground-truth file format (CSV, header required):

    video_id,type,start_sec,duration_sec
    clip_01,E_HEAD_DOWN,12.0,5.0
    clip_01,E_STABLE_SEGMENT,40.0,22.0
    clip_02,E_TURNED_AWAY,3.5,6.0

`video_id` must match the video file's stem (`clip_01.mp4` -> `clip_01`).

Matching rule: a system event matches a human mark when they share the same
`type` and the system event's [start, start+duration] interval falls within
the human mark's interval padded by `--tolerance-sec` on each side. This is
deliberately generous about *when* inside the window it fired and strict
about *what* it called it -- matching the product's "describe, don't
diagnose" discipline (events/rules.py) carrying over into how they're graded.

Usage:

    python -m scripts.calibrate_thresholds \\
        --videos-dir data/calibration/presentation_solo \\
        --ground-truth data/calibration/presentation_solo/ground_truth.csv \\
        --profile presentation_solo
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from analyzers.pose_analyzer import PoseAnalyzer
from events.detector import EventDetector
from extractors.video_extractor import VideoExtractor
from models.events import PresentationEvent
from services.profile_loader import DEFAULT_PROFILE, available_profiles, load_profile
from utils.logger import get_logger

logger = get_logger(__name__)

_VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}


@dataclass(frozen=True)
class GroundTruthMark:
    """One human-marked moment, read from the ground-truth CSV."""

    video_id: str
    type: str
    start_sec: float
    duration_sec: float

    @property
    def end_sec(self) -> float:
        return self.start_sec + self.duration_sec


@dataclass
class TypeTally:
    """Running counts for one event type, across every video processed."""

    system_events: int = 0
    system_matched: int = 0
    human_marks: int = 0
    human_missed: int = 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--videos-dir", type=Path, required=True, help="Directory holding the recordings.")
    parser.add_argument(
        "--ground-truth", type=Path, required=True, help="CSV of human-marked timestamps (see module docstring)."
    )
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=available_profiles(),
        help=f"Context profile to run (default: {DEFAULT_PROFILE}).",
    )
    parser.add_argument(
        "--tolerance-sec",
        type=float,
        default=3.0,
        help="How far a system event's window may sit from a human mark's and still count as the same moment.",
    )
    return parser.parse_args(argv)


def load_ground_truth(path: Path) -> list[GroundTruthMark]:
    """Read the ground-truth CSV. Raises `ValueError` on a malformed row rather than silently skipping it."""
    marks: list[GroundTruthMark] = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"video_id", "type", "start_sec", "duration_sec"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Ground-truth CSV is missing column(s): {sorted(missing)}")
        for row_number, row in enumerate(reader, start=2):  # header is row 1
            try:
                marks.append(
                    GroundTruthMark(
                        video_id=row["video_id"].strip(),
                        type=row["type"].strip(),
                        start_sec=float(row["start_sec"]),
                        duration_sec=float(row["duration_sec"]),
                    )
                )
            except (KeyError, ValueError) as exc:
                raise ValueError(f"Ground-truth CSV row {row_number} is malformed: {row!r}") from exc
    return marks


def find_video_file(videos_dir: Path, video_id: str) -> Path | None:
    """The recording whose filename stem is `video_id`, whatever its extension."""
    for extension in _VIDEO_EXTENSIONS:
        candidate = videos_dir / f"{video_id}{extension}"
        if candidate.is_file():
            return candidate
    return None


def run_pipeline_on(video_path: Path, profile_name: str) -> list[PresentationEvent]:
    """
    The same three-stage chain as scripts/check_pose_pipeline.py and
    services/self_practice_manager.py, on one file. Sampling at the
    profile's own `min_sample_rate_hz` matters more here than anywhere else
    in the codebase: an accuracy figure measured against a too-sparsely
    sampled recording just reports how often the sampling happened to line
    up with a human mark, not whether the thresholds are right.
    """
    profile = load_profile(profile_name)
    video_feature, frames, timestamps = VideoExtractor(
        min_sample_rate_hz=profile.frame_requirements.min_sample_rate_hz
    ).extract_with_frames(video_path)
    pose = PoseAnalyzer(profile).analyze(list(zip(frames, timestamps)), source_fps=video_feature.fps)
    return EventDetector(profile).detect(session_id=video_path.stem, pose=pose)


def _overlaps(event: PresentationEvent, mark: GroundTruthMark, tolerance_sec: float) -> bool:
    """Whether a system event's window falls inside a human mark's window, padded by tolerance."""
    window_start = mark.start_sec - tolerance_sec
    window_end = mark.end_sec + tolerance_sec
    return event.type == mark.type and event.start_sec <= window_end and event.end_sec >= window_start


def score_video(
    events: list[PresentationEvent], marks: list[GroundTruthMark], tolerance_sec: float, tallies: dict[str, TypeTally]
) -> None:
    """Update `tallies` in place with one video's comparison."""
    for event in events:
        tally = tallies[event.type]
        tally.system_events += 1
        if any(_overlaps(event, mark, tolerance_sec) for mark in marks if mark.type == event.type):
            tally.system_matched += 1

    for mark in marks:
        tally = tallies[mark.type]
        tally.human_marks += 1
        if not any(_overlaps(event, mark, tolerance_sec) for event in events if event.type == mark.type):
            tally.human_missed += 1


def print_report(tallies: dict[str, TypeTally]) -> None:
    """Per-type table: how often the system was right, and how much it missed."""
    if not tallies:
        print("Không có sự kiện hoặc mốc nào để so sánh.")
        return

    header = f"{'Loại sự kiện':<20} {'Máy báo':>8} {'Báo đúng':>9} {'Tỷ lệ đúng':>11} {'Mốc thật':>9} {'Bỏ sót':>7} {'Tỷ lệ bỏ sót':>13}"
    print(header)
    print("-" * len(header))
    for event_type in sorted(tallies):
        tally = tallies[event_type]
        precision = tally.system_matched / tally.system_events if tally.system_events else float("nan")
        miss_rate = tally.human_missed / tally.human_marks if tally.human_marks else float("nan")
        print(
            f"{event_type:<20} {tally.system_events:>8} {tally.system_matched:>9} "
            f"{precision:>10.0%} {tally.human_marks:>9} {tally.human_missed:>7} {miss_rate:>12.0%}"
        )


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    if not args.videos_dir.is_dir():
        print(f"Không tìm thấy thư mục video: {args.videos_dir}", file=sys.stderr)
        return 2
    if not args.ground_truth.is_file():
        print(f"Không tìm thấy file mốc người chấm: {args.ground_truth}", file=sys.stderr)
        return 2

    try:
        marks = load_ground_truth(args.ground_truth)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    marks_by_video: dict[str, list[GroundTruthMark]] = defaultdict(list)
    for mark in marks:
        marks_by_video[mark.video_id].append(mark)

    tallies: dict[str, TypeTally] = defaultdict(TypeTally)
    processed = 0
    for video_id, video_marks in sorted(marks_by_video.items()):
        video_path = find_video_file(args.videos_dir, video_id)
        if video_path is None:
            print(f"Bỏ qua {video_id}: không tìm thấy file video tương ứng trong {args.videos_dir}", file=sys.stderr)
            continue
        print(f"Đang xử lý {video_path.name}...")
        events = run_pipeline_on(video_path, args.profile)
        score_video(events, video_marks, args.tolerance_sec, tallies)
        processed += 1

    if processed == 0:
        print("Không xử lý được video nào.", file=sys.stderr)
        return 1

    print()
    print(f"Hồ sơ bối cảnh: {args.profile} (v{load_profile(args.profile).version}), {processed} bản ghi, "
          f"dung sai {args.tolerance_sec:.1f}s")
    print_report(tallies)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
