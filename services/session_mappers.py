"""
services/session_mappers.py

Two-way conversion between the persistence layer (`db/models.py` ORM rows)
and the pipeline's strongly-typed Pydantic feature models
(`models/features.py`, `models/events.py`) for the self-practice pipeline.

Convention: `*_to_orm` builds (but does not `add`/`commit`) an ORM row from
a Pydantic model; `orm_to_*` rebuilds the Pydantic model from a persisted
row. Round-tripping through these functions must be lossless for every
field the pipeline actually uses.

(This module used to also map resume/slide/video/speech/transcript/emotion/
facemesh features for the old scoring pipeline — removed along with it.)
"""

from __future__ import annotations

import uuid

from db.models import PoseFeatureORM, PresentationEventORM
from models.events import PresentationEvent
from models.features import LandmarkGroupAvailability, PoseFeature, PoseFrameSample, PoseMetric

# ---------------------------------------------------------------------------
# Pose / events (specs/in-class-analysis) — self-practice sessions only.
#
# PoseFeature's seven metrics are nested PoseMetric objects (value/measured/
# reason), not bare floats, so a plain `**feature.model_dump()` would try to
# hand the ORM a dict for each metric column instead of the three flattened
# columns it actually has. These two functions do that flattening
# explicitly, once, instead of at every caller.
# ---------------------------------------------------------------------------

_POSE_METRIC_NAMES = (
    "head_up_ratio",
    "postural_sway",
    "movement_range",
    "gesture_rate",
    "closed_posture_ratio",
    "shoulder_tilt",
    "turned_away_ratio",
)


def pose_to_orm(session_id: uuid.UUID, feature: PoseFeature) -> PoseFeatureORM:
    metric_columns = {}
    for name in _POSE_METRIC_NAMES:
        metric: PoseMetric = getattr(feature, name)
        metric_columns[name] = metric.value
        metric_columns[f"{name}_measured"] = metric.measured
        metric_columns[f"{name}_reason"] = metric.reason

    return PoseFeatureORM(
        session_id=session_id,
        profile=feature.profile,
        profile_version=feature.profile_version,
        frames_analyzed=feature.frames_analyzed,
        pose_detected_ratio=feature.pose_detected_ratio,
        available_landmark_groups=[group.value for group in feature.available_landmark_groups],
        landmark_group_availability=[entry.model_dump(mode="json") for entry in feature.landmark_group_availability],
        sampling_rate_hz=feature.sampling_rate_hz,
        sampling_warning=feature.sampling_warning,
        **metric_columns,
        series_json=[sample.model_dump(mode="json") for sample in feature.series],
    )


def orm_to_pose(row: PoseFeatureORM) -> PoseFeature:
    metric_kwargs = {}
    for name in _POSE_METRIC_NAMES:
        metric_kwargs[name] = PoseMetric(
            value=getattr(row, name),
            measured=getattr(row, f"{name}_measured"),
            reason=getattr(row, f"{name}_reason"),
        )

    return PoseFeature(
        profile=row.profile,
        profile_version=row.profile_version,
        frames_analyzed=row.frames_analyzed,
        pose_detected_ratio=row.pose_detected_ratio,
        available_landmark_groups=list(row.available_landmark_groups),
        landmark_group_availability=[
            LandmarkGroupAvailability.model_validate(entry) for entry in row.landmark_group_availability
        ],
        sampling_rate_hz=row.sampling_rate_hz,
        sampling_warning=row.sampling_warning,
        series=[PoseFrameSample.model_validate(entry) for entry in row.series_json],
        **metric_kwargs,
    )


def presentation_event_to_orm(session_id: uuid.UUID, event: PresentationEvent) -> PresentationEventORM:
    return PresentationEventORM(
        session_id=session_id,
        profile=event.profile,
        type=event.type,
        start_sec=event.start_sec,
        duration_sec=event.duration_sec,
        measured_value=event.measured_value,
        unit=event.unit,
        label=event.label,
        rule_version=event.rule_version,
    )


def orm_to_presentation_event(row: PresentationEventORM) -> PresentationEvent:
    return PresentationEvent(
        session_id=str(row.session_id),
        profile=row.profile,
        type=row.type,
        start_sec=row.start_sec,
        duration_sec=row.duration_sec,
        measured_value=row.measured_value,
        unit=row.unit,
        label=row.label,
        rule_version=row.rule_version,
        detected_at=row.detected_at,
    )
