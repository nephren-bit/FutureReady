"""
models/events.py

`PresentationEvent` — one machine-detected moment in a recording, with a
timestamp the reviewer can jump to.

Deliberately a **separate model and separate table** from
`models/notes.TeacherNote`. The two are displayed on one timeline, but they
are never stored together, because the whole verification plan (Task 15)
rests on comparing "what the machine found" against "what the teacher
marked". Two tables makes that comparison impossible to get wrong: it is
table A against table B. One table with a `source` flag works right up until
somebody forgets the filter, and then the accuracy numbers silently start
measuring nothing.

Rules for `label`, enforced by `events/rules.py` and by
`tests/test_event_detector.py`: it describes **only what was measured**. It
says `khoảng lặng 4,2 giây`, never `ngắc ngứ`. Inferring a cause from a
measurement is where a tool loses a teacher's trust in about two seconds,
and it never gets it back.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _new_id() -> str:
    """Fresh identifier for a detected event."""
    return str(uuid.uuid4())


def _now() -> datetime:
    """Timezone-aware creation timestamp."""
    return datetime.now(timezone.utc)


class PresentationEvent(BaseModel):
    """
    One detected event on a session's timeline.

    Every field below the timestamp exists so a reviewer can audit the claim:
    `measured_value` + `unit` say what the number actually was, and
    `rule_version` says which threshold set decided it counted. Once
    thresholds are recalibrated (Task 10) and the profile version bumps, old
    events remain attributable to the rules that produced them.
    """

    event_id: str = Field(default_factory=_new_id)
    session_id: str

    profile: str = Field(..., description="Context profile code used, e.g. `presentation_class`.")
    type: str = Field(..., description="Event code, e.g. `E_HEAD_DOWN`.")

    start_sec: float = Field(..., ge=0.0, description="Offset into the recording, in seconds.")
    duration_sec: float = Field(..., ge=0.0)

    measured_value: float = Field(..., description="The number the rule actually observed.")
    unit: str = Field(..., description="Unit of `measured_value`: giây, từ/phút, %, lần/phút, ...")

    label: str = Field(
        ...,
        description="Display sentence. Describes the measurement only, never an inferred cause.",
    )
    rule_version: str = Field(..., description="Version of the profile threshold set that fired.")

    detected_at: datetime = Field(default_factory=_now)

    @property
    def end_sec(self) -> float:
        """Where this event stops, in seconds."""
        return self.start_sec + self.duration_sec
