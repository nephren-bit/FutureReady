"""
services/quality_tracking.py

The detection-quality dashboard (specs/in-class-analysis, Nhom B Task 14 /
Nhom C Task 18): "is the product actually working?" -- the plan's own
answer for why this is cheap (read-only) but important.

The only allowed data source is `PeerNote` (plan.md, "Hiệu chỉnh liên tục
từ luyện tập chéo"): `SelfNote` is explicitly excluded (the owner already
knows what they just did, so it isn't independent judgment -- see
`models/notes.py`), and only rows from a COMPLETED invite with
`created_before_reveal = True` count. Using anything else here would
silently start measuring "did the rater agree with the machine" instead of
"was the machine right."

Matching rule, adapted from `scripts/calibrate_thresholds.py`'s
`_overlaps` for Task 9's one-time calibration: a `PeerNote` moment-mark is
a single point in time with **no event type** (the blind-review screen
never asks the rater to classify what they saw -- plan.md keeps that
screen deliberately simple), unlike Task 9's typed ground truth. So the
two directions of this comparison are asymmetric, on purpose:

- **Precision, per event type**: does a machine event of type X have *any*
  peer mark nearby, of any kind? A nearby mark is read as "a human
  independently noticed something around here too" -- supporting evidence
  the event was real, not a specific confirmation of what it was.
- **Miss rate, aggregate only**: does a peer's mark have *any* machine
  event nearby, of any type? A mark with nothing nearby is read as "the
  human saw something, the machine caught nothing" -- it can't be
  attributed to one event type, because the rater never named one.

Both readings are approximate signals for the ongoing/lightweight
calibration loop -- not a replacement for Task 9's one rigorous typed
calibration pass, which plan.md keeps separate for exactly this reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session as DBSession, selectinload

from db.models import (
    PeerNoteORM,
    PeerReviewInviteORM,
    PeerReviewStatus,
    PresentationEventORM,
    SelfPracticeSessionORM,
    SelfPracticeState,
)

# Wider than Task 9's calibration default (3.0s, scripts/calibrate_thresholds.py):
# a peer's mark is a casual single click while watching, not a deliberately
# placed ground-truth boundary, so it deserves more slack.
DEFAULT_TOLERANCE_SEC = 5.0


@dataclass
class EventTypeTally:
    """Running precision counts for one (profile, event_type) pair."""

    profile: str
    event_type: str
    system_events: int = 0
    system_matched: int = 0

    @property
    def precision(self) -> float | None:
        return self.system_matched / self.system_events if self.system_events else None


@dataclass
class QualityReport:
    generated_at: datetime
    tolerance_sec: float
    by_event_type: list[EventTypeTally] = field(default_factory=list)
    peer_marks_total: int = 0
    peer_marks_missed: int = 0
    invites_total: int = 0
    invites_completed: int = 0
    sessions_with_peer_review: int = 0

    @property
    def miss_rate(self) -> float | None:
        return self.peer_marks_missed / self.peer_marks_total if self.peer_marks_total else None

    @property
    def invite_completion_rate(self) -> float | None:
        return self.invites_completed / self.invites_total if self.invites_total else None


def _overlaps(event: PresentationEventORM, mark_sec: float, tolerance_sec: float) -> bool:
    """Whether a point-in-time peer mark falls inside a machine event's window, padded by tolerance."""
    window_start = event.start_sec - tolerance_sec
    window_end = event.start_sec + event.duration_sec + tolerance_sec
    return window_start <= mark_sec <= window_end


def _calibration_marks(session: SelfPracticeSessionORM) -> list[float]:
    """
    This session's peer marks that are actually allowed to count:
    from a COMPLETED invite, blind (`created_before_reveal`), and a real
    moment-mark rather than the rubric row (`mark_sec is not None`).
    """
    return [
        note.mark_sec
        for note in session.peer_notes
        if note.mark_sec is not None
        and note.created_before_reveal
        and note.invite.status == PeerReviewStatus.COMPLETED
    ]


def compute_quality_report(db: DBSession, tolerance_sec: float = DEFAULT_TOLERANCE_SEC) -> QualityReport:
    """
    Builds the whole dashboard from scratch on every call -- there is no
    stored/cached report. Fine at this product's scale (a read-only admin
    screen, queried rarely, over a session count nowhere near needing
    pre-aggregation); revisit if that stops being true.
    """
    sessions = (
        db.query(SelfPracticeSessionORM)
        .filter(SelfPracticeSessionORM.state == SelfPracticeState.COMPLETED)
        .options(
            selectinload(SelfPracticeSessionORM.presentation_events),
            selectinload(SelfPracticeSessionORM.peer_notes).selectinload(PeerNoteORM.invite),
        )
        .all()
    )

    tallies: dict[tuple[str, str], EventTypeTally] = {}
    peer_marks_total = 0
    peer_marks_missed = 0
    sessions_with_peer_review = 0

    for session in sessions:
        mark_secs = _calibration_marks(session)
        if not mark_secs:
            continue
        sessions_with_peer_review += 1

        for event in session.presentation_events:
            key = (session.profile, event.type)
            tally = tallies.setdefault(key, EventTypeTally(profile=session.profile, event_type=event.type))
            tally.system_events += 1
            if any(_overlaps(event, mark_sec, tolerance_sec) for mark_sec in mark_secs):
                tally.system_matched += 1

        for mark_sec in mark_secs:
            peer_marks_total += 1
            if not any(_overlaps(event, mark_sec, tolerance_sec) for event in session.presentation_events):
                peer_marks_missed += 1

    invites_total = db.query(PeerReviewInviteORM).count()
    invites_completed = (
        db.query(PeerReviewInviteORM).filter(PeerReviewInviteORM.status == PeerReviewStatus.COMPLETED).count()
    )

    return QualityReport(
        generated_at=datetime.now(timezone.utc),
        tolerance_sec=tolerance_sec,
        by_event_type=sorted(tallies.values(), key=lambda t: (t.profile, t.event_type)),
        peer_marks_total=peer_marks_total,
        peer_marks_missed=peer_marks_missed,
        invites_total=invites_total,
        invites_completed=invites_completed,
        sessions_with_peer_review=sessions_with_peer_review,
    )
