"""
models/self_practice_models.py

Pydantic request/response schemas for the Self Practice API
(`routers/self_practice.py`, specs/in-class-analysis Task 7/8).

`SelfPracticeSessionResponse.notes` is built through `SelfPracticeManager`
rather than read off the ORM relationship directly, so the shape of "the
human-marked layer on this timeline" stays stable if Nhom C later swaps
`SelfNote` for `PeerNote` here — the response field does not need to change,
only what feeds it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from db.models import SelfNoteORM, SelfPracticeSessionORM, SelfPracticeState
from models.events import PresentationEvent
from models.features import PoseFeature

__all__ = [
    "SelfPracticeState",
    "SelfPracticeSessionResponse",
    "SelfPracticeSessionSummary",
    "SelfNoteResponse",
    "SelfNoteCreateRequest",
    "SelfNoteUpdateRequest",
]


class SelfNoteResponse(BaseModel):
    """One self-review note, as returned to the client."""

    note_id: uuid.UUID
    session_id: uuid.UUID
    mark_sec: float
    text: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_note(cls, note: SelfNoteORM) -> "SelfNoteResponse":
        return cls(
            note_id=note.id,
            session_id=note.session_id,
            mark_sec=note.mark_sec,
            text=note.text,
            created_at=note.created_at,
            updated_at=note.updated_at,
        )


class SelfNoteCreateRequest(BaseModel):
    """Request body for `POST /self-practice/{id}/notes`."""

    mark_sec: float = Field(..., ge=0.0)
    text: str = ""


class SelfNoteUpdateRequest(BaseModel):
    """Request body for `PATCH /self-practice/{id}/notes/{note_id}`. Both fields optional."""

    mark_sec: float | None = Field(None, ge=0.0)
    text: str | None = None


class SelfPracticeSessionSummary(BaseModel):
    """One row of `GET /self-practice` -- the dashboard's session list. No pose/events/notes payload."""

    id: uuid.UUID
    profile: str
    state: SelfPracticeState
    created_at: datetime

    @classmethod
    def from_orm_session(cls, session: SelfPracticeSessionORM) -> "SelfPracticeSessionSummary":
        return cls(id=session.id, profile=session.profile, state=session.state, created_at=session.created_at)


class SelfPracticeSessionResponse(BaseModel):
    """
    Response for `POST /self-practice` and `GET /self-practice/{id}`.

    `pose_feature`/`events` are only populated once `state == COMPLETED`;
    `notes` is always populated (a person can add notes while a recording
    is still processing).
    """

    id: uuid.UUID
    profile: str
    state: SelfPracticeState
    error_message: str | None = None
    pose_feature: PoseFeature | None = None
    events: list[PresentationEvent] = Field(default_factory=list)
    notes: list[SelfNoteResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_orm_session(
        cls,
        session: SelfPracticeSessionORM,
        *,
        pose_feature: PoseFeature | None,
        events: list[PresentationEvent],
        notes: list[SelfNoteORM],
    ) -> "SelfPracticeSessionResponse":
        return cls(
            id=session.id,
            profile=session.profile,
            state=session.state,
            error_message=session.error_message,
            pose_feature=pose_feature,
            events=events,
            notes=[SelfNoteResponse.from_orm_note(note) for note in notes],
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
