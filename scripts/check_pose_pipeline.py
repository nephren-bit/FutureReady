"""
scripts/check_pose_pipeline.py

Runs the whole Group A chain on a real video file and prints what it found:

    video_extractor -> landmark availability -> pose_analyzer -> event detector

This is the acceptance check for Task 1 ("run on a sample video, print the
number of frames analyzed and a person-detection ratio above 0") and the
quickest way to eyeball Tasks 2, 3 and 5 against real footage rather than
synthetic landmarks.

Usage:

    python -m scripts.check_pose_pipeline uploads/<file>.mp4
    python -m scripts.check_pose_pipeline uploads/<file>.mp4 --profile presentation_class
    python -m scripts.check_pose_pipeline uploads/<file>.mp4 --frames 180

Sampling note: the default frame count comes from `VIDEO_SAMPLE_FRAME_COUNT`
(60 frames spread across the whole video), which for anything longer than a
minute is far too sparse for event detection — the analyzer says so in
`sampling_warning`. Pass `--frames` to sample densely enough to mean
something.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from analyzers.pose_analyzer import PoseAnalyzer
from config import settings
from events.detector import EventDetector
from extractors.video_extractor import VideoExtractor
from services.profile_loader import DEFAULT_PROFILE, available_profiles, load_profile


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path, help="Path to a video file.")
    parser.add_argument(
        "--profile",
        default=DEFAULT_PROFILE,
        choices=available_profiles(),
        help=f"Context profile to apply (default: {DEFAULT_PROFILE}).",
    )
    parser.add_argument(
        "--frames",
        type=int,
        default=settings.VIDEO_SAMPLE_FRAME_COUNT,
        help="How many frames to sample across the video.",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run the chain and print a human-readable report. Returns a shell exit code."""
    args = parse_args(argv)
    if not args.video.is_file():
        print(f"Không tìm thấy tệp: {args.video}", file=sys.stderr)
        return 2

    profile = load_profile(args.profile)
    print(f"Hồ sơ bối cảnh : {profile.profile} (v{profile.version})")
    print(f"Tệp            : {args.video}")

    video_feature, frames, timestamps = VideoExtractor(sample_count=args.frames).extract_with_frames(
        args.video
    )
    print(
        f"Video          : {video_feature.duration_sec:.1f}s, {video_feature.fps:.1f} fps, "
        f"{video_feature.width}x{video_feature.height}"
    )

    pose = PoseAnalyzer(profile).analyze(list(zip(frames, timestamps)))

    print()
    print("--- Task 1: nhận diện người ---")
    print(f"Số khung hình đã phân tích      : {pose.frames_analyzed}")
    print(f"Tỷ lệ khung hình phát hiện người: {pose.pose_detected_ratio:.1%}")
    print(f"Tần số lấy mẫu                  : {pose.sampling_rate_hz:.2f} khung hình/giây")
    if pose.sampling_warning:
        print(f"Cảnh báo lấy mẫu                : {pose.sampling_warning}")

    print()
    print("--- Task 2: nhóm điểm mốc khả dụng ---")
    for entry in pose.landmark_group_availability:
        mark = "có" if entry.available else "không"
        print(f"  {entry.group.value:<12} {entry.visible_frame_ratio:>6.1%}  {mark}")

    print()
    print("--- Task 3: bộ chỉ số chuyển động ---")
    for name in (
        "head_up_ratio",
        "postural_sway",
        "movement_range",
        "gesture_rate",
        "closed_posture_ratio",
        "shoulder_tilt",
        "turned_away_ratio",
    ):
        metric = getattr(pose, name)
        if metric.measured:
            print(f"  {name:<22} {metric.value:>10.4f} {metric.unit}")
        else:
            print(f"  {name:<22} {'không đo được':>10}  ({metric.reason})")

    print()
    print("--- Task 5: sự kiện phát hiện được ---")
    events = EventDetector(profile).detect(session_id="check-script", pose=pose)
    if not events:
        print("  (không có sự kiện nào)")
    for event in events:
        print(
            f"  {event.start_sec:7.1f}s  {event.type:<18} "
            f"{event.measured_value:>8.2f} {event.unit:<22} rule v{event.rule_version}"
        )
        print(f"           {event.label}")

    # Task 1's acceptance check: a person was detected in at least some frames.
    if pose.pose_detected_ratio <= 0.0:
        print("\nKhông phát hiện được người trong bất kỳ khung hình nào.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
