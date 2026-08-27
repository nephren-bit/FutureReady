"""
models/peer_review.py

`PeerReviewInvite` and `PeerNote` -- the peer-review flow (specs/in-class-
analysis, Nhom C Task 15-16): the session owner (A) invites a friend (B) to
watch their recording and mark it blind, before B ever sees what the
machine detected. This is the plan's **only** independent-judgment data
source for calibrating event thresholds (Task 9/14) -- `SelfNote` is
explicitly excluded from that role (see `models/notes.py`), because the
owner already knows what they just said and has no independent perspective.

`PeerNote` is a **separate table from `SelfNote` and `PresentationEvent`**,
never merged: the whole calibration plan is "table A (machine) against
table B (human)", and a merged table with a `source` flag works right up
until somebody forgets the filter and the accuracy numbers silently start
measuring nothing (same reasoning as `models/events.py`'s split from
`SelfNote`).

Two kinds of row share this one table, distinguished by `mark_sec`:
- A **moment mark** (`mark_sec` set, `rubric_scores` empty): B flagged
  something noteworthy while watching, blind.
- The **rubric submission** (`mark_sec` is `None`, `rubric_scores` filled):
  B's one required end-of-video rating. Submitting this is what completes
  the invite and reveals the machine's results -- see
  `services/peer_review_manager.py`.

Every row created through this flow has `created_before_reveal = True`,
since the API refuses to reveal machine results until the rubric is
submitted (there is currently no "B revisits after reveal and adds more"
path -- the field exists so that future addition doesn't quietly
contaminate the calibration data, not because any row is `False` today).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

# The one required rating, fixed at exactly these three profile-neutral
# criteria (plan.md's own example, "ro ràng / bám câu hỏi / tự tin", swaps
# the interview-specific middle one for "thu hút" so the same rubric works
# for presentation_solo and interview_solo alike). No freeform criteria --
# a configurable rubric would depress B's completion rate for no accuracy
# benefit (see plan.md, "Rủi ro riêng của tính năng này").
RUBRIC_CRITERIA = ("clarity", "confidence", "engagement")
RUBRIC_MIN = 1
RUBRIC_MAX = 5


def _new_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class PeerReviewInvite(BaseModel):
    """One "nhờ bạn chấm hộ" invite, identified by an unguessable `token`."""

    invite_id: str = Field(default_factory=_new_id)
    session_id: str
    inviter_user_id: str

    token: str
    status: str = Field("pending", description="pending | completed | expired | revoked")

    created_at: datetime = Field(default_factory=_now)
    expires_at: datetime


class PeerNote(BaseModel):
    """One row of B's blind review: either a moment mark or the final rubric."""

    note_id: str = Field(default_factory=_new_id)
    session_id: str
    rater_user_id: str
    invite_id: str

    mark_sec: float | None = Field(None, ge=0.0, description="None for the rubric row.")
    created_before_reveal: bool = True
    rubric_scores: dict[str, int] = Field(default_factory=dict)
    text: str | None = None

    created_at: datetime = Field(default_factory=_now)
