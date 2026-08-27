"""
models/quality_models.py

Pydantic response schema for the detection-quality dashboard
(`routers/quality.py`, Nhom B Task 14 / Nhom C Task 18).
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from services.quality_tracking import EventTypeTally, QualityReport

__all__ = ["EventTypeQualityResponse", "QualityReportResponse"]


class EventTypeQualityResponse(BaseModel):
    """Precision for one (profile, event_type) pair, against nearby peer marks."""

    profile: str
    event_type: str
    system_events: int
    system_matched: int
    precision: float | None

    @classmethod
    def from_tally(cls, tally: EventTypeTally) -> "EventTypeQualityResponse":
        return cls(
            profile=tally.profile,
            event_type=tally.event_type,
            system_events=tally.system_events,
            system_matched=tally.system_matched,
            precision=tally.precision,
        )


class QualityReportResponse(BaseModel):
    """
    Response for `GET /admin/quality-report`.

    `precision` on each row and `miss_rate`/`invite_completion_rate` here
    are all `None` -- not `0` -- when there isn't enough data yet (zero
    system events of that type, or zero peer marks/invites at all). A `0`
    would silently claim "measured, and it was zero"; `None` says "nothing
    to measure yet", which is the truth for a product with only a handful
    of peer reviews so far.
    """

    generated_at: datetime
    tolerance_sec: float
    by_event_type: list[EventTypeQualityResponse]
    peer_marks_total: int
    peer_marks_missed: int
    miss_rate: float | None
    invites_total: int
    invites_completed: int
    invite_completion_rate: float | None
    sessions_with_peer_review: int

    @classmethod
    def from_report(cls, report: QualityReport) -> "QualityReportResponse":
        return cls(
            generated_at=report.generated_at,
            tolerance_sec=report.tolerance_sec,
            by_event_type=[EventTypeQualityResponse.from_tally(t) for t in report.by_event_type],
            peer_marks_total=report.peer_marks_total,
            peer_marks_missed=report.peer_marks_missed,
            miss_rate=report.miss_rate,
            invites_total=report.invites_total,
            invites_completed=report.invites_completed,
            invite_completion_rate=report.invite_completion_rate,
            sessions_with_peer_review=report.sessions_with_peer_review,
        )
