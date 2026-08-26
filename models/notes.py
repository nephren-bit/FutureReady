"""
models/notes.py

`SelfNote` — a note a person attaches to a point on their own self-practice
recording's timeline, while reviewing it. Deliberately simple:

- **No ground-truth flag.** `SelfNote` is never used to calibrate anything
  (see `specs/in-class-analysis/plan.md`) — the person and the machine's
  subject are the same person, so there is no independent judgment to
  protect. It can be written at any time.
- **No revision chain.** Nothing depends on being able to tell an original
  mark from an edited one, so a `SelfNote` can just be updated in place —
  see `edited()` below.
- **No visibility.** Only the session's owner ever sees their own notes —
  there is no one else to share with or hide from.

(This module used to also define `TeacherNote`, for a teacher-in-classroom
entry point that was retired before it ever wrote a row — see plan.md, "Vì
sao bỏ lối vào giáo viên" — and later removed here entirely along with the
scoring pipeline it belonged to.)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _new_id() -> str:
    """Fresh identifier for a note."""
    return str(uuid.uuid4())


def _now() -> datetime:
    """Timezone-aware creation timestamp."""
    return datetime.now(timezone.utc)


class SelfNote(BaseModel):
    """One self-review note on a `self_practice_sessions` timeline."""

    note_id: str = Field(default_factory=_new_id)
    session_id: str

    mark_sec: float = Field(
        ..., ge=0.0, description="Point in the recording this note is attached to."
    )

    text: str = Field("", description="Freeform note, written any time during review.")

    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)

    def edited(self, *, mark_sec: float | None = None, text: str | None = None) -> "SelfNote":
        """
        Return a copy with the given fields changed and `updated_at` bumped.

        Persisted over the same row -- there is no ground-truth chain to
        protect, so an edit never creates a new note.
        """
        return self.model_copy(
            update={
                "mark_sec": self.mark_sec if mark_sec is None else mark_sec,
                "text": self.text if text is None else text,
                "updated_at": _now(),
            }
        )
