"""
models/notes.py

`TeacherNote` — one mark a teacher made by pressing a single key while the
student was still speaking.

Why this is worth more than it looks
------------------------------------
The direct value is that the teacher gets their own timeline marks to jump
back to, independent of whether the machine detected anything useful — which
means the product is worth using even while the thresholds have never once
been calibrated.

The indirect value is larger. Every class session produces a pair of mark
sets on one shared time axis: machine-detected and human-marked. That is
precisely the ground-truth data the accuracy work (Task 10, Task 15) would
otherwise need an expensive labelling campaign to obtain — collected free,
continuously, by a domain expert, under real conditions.

Four constraints hold that up, and each is enforced here or by the router:

1. **One action while recording.** One key press creates one note at the
   current moment, with empty `text` and no `category`. Typing and
   categorising happen later during review. Ask for two steps mid-class and
   the teacher goes back to pen and paper.
2. **Original notes are immutable.** Edits create a *new* note pointing back
   via `revision_of`; the original row is never updated. Only notes made
   before the teacher saw the machine's output
   (`created_during_recording=True` and `revision_of is None`) may be used as
   ground truth — otherwise the accuracy numbers slowly degrade into a
   measure of how often humans agree with the machine.
3. **Private by default.** A note typed in a hurry about a named person is
   not a considered written assessment. `visibility` defaults to `private`
   and takes an explicit per-note action to share.
4. **Stored apart from machine events.** See `models/events.py`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


def _new_id() -> str:
    """Fresh identifier for a note."""
    return str(uuid.uuid4())


def _now() -> datetime:
    """Timezone-aware creation timestamp."""
    return datetime.now(timezone.utc)


class NoteVisibility(str, Enum):
    """Who may see a note. Defaults to the teacher alone."""

    PRIVATE = "private"
    SHARED_WITH_STUDENT = "shared_with_student"


class NoteCategory(str, Enum):
    """
    Optional classification, assigned during review and never while
    recording. Kept open-ended on purpose: this is the teacher's own
    vocabulary, not the machine's event catalog.
    """

    CONTENT = "noi_dung"
    DELIVERY = "trinh_bay"
    BODY_LANGUAGE = "ngon_ngu_co_the"
    VOICE = "giong_noi"
    SLIDE = "slide"
    OTHER = "khac"


class TeacherNote(BaseModel):
    """One teacher mark on a session timeline."""

    note_id: str = Field(default_factory=_new_id)
    session_id: str

    mark_sec: float = Field(
        ..., ge=0.0, description="Offset into the recording at the moment the key was pressed."
    )

    created_during_recording: bool = Field(
        False,
        description=(
            "True only for marks made live, before the machine had produced anything. "
            "The ground-truth filter for accuracy measurement."
        ),
    )

    text: str = Field("", description="Empty at press time; filled in during review.")
    category: NoteCategory | None = Field(None, description="Assigned during review, optional.")

    visibility: NoteVisibility = Field(
        NoteVisibility.PRIVATE,
        description="Private unless the teacher explicitly shares this one note.",
    )

    revision_of: str | None = Field(
        None,
        description="Set on an edited copy, pointing at the original note, which stays untouched.",
    )

    created_at: datetime = Field(default_factory=_now)

    @property
    def is_original(self) -> bool:
        """Whether this is an original mark rather than a later revision of one."""
        return self.revision_of is None

    @property
    def is_ground_truth(self) -> bool:
        """
        Whether this note may be counted as ground truth.

        Both conditions matter: made live, and not a revision. A note edited
        after the teacher read the machine's output tells you whether the
        human agreed with the machine, not whether the machine was right.
        """
        return self.created_during_recording and self.is_original

    def revise(self, *, text: str | None = None, category: NoteCategory | None = None,
               visibility: NoteVisibility | None = None) -> "TeacherNote":
        """
        Build a new note that supersedes this one, leaving this one untouched.

        The revision is never itself ground truth: `created_during_recording`
        is deliberately not carried over.
        """
        return TeacherNote(
            session_id=self.session_id,
            mark_sec=self.mark_sec,
            created_during_recording=False,
            text=self.text if text is None else text,
            category=self.category if category is None else category,
            visibility=self.visibility if visibility is None else visibility,
            revision_of=self.note_id,
        )
