"""
models/peer_review_models.py

Pydantic request/response schemas for the Peer Review API
(`routers/peer_review.py`, Nhom C Task 15-16).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from db.models import PeerNoteORM, PeerReviewInviteORM, PeerReviewStatus
from models.events import PresentationEvent
from models.features import PoseFeature
from models.peer_review import RUBRIC_CRITERIA, RUBRIC_MAX, RUBRIC_MIN

__all__ = [
    "PeerReviewInviteResponse",
    "AddMarkRequest",
    "SubmitRubricRequest",
    "PeerNoteResponse",
    "PeerReviewStateResponse",
]


class PeerReviewInviteResponse(BaseModel):
    """Response for `POST`/`GET .../peer-invites` -- what the owner sees about an invite they sent."""

    invite_id: uuid.UUID
    token: str
    status: PeerReviewStatus
    created_at: datetime
    expires_at: datetime

    @classmethod
    def from_orm_invite(cls, invite: PeerReviewInviteORM) -> "PeerReviewInviteResponse":
        return cls(
            invite_id=invite.id,
            token=invite.token,
            status=invite.status,
            created_at=invite.created_at,
            expires_at=invite.expires_at,
        )


def _validate_rubric(scores: dict[str, int]) -> dict[str, int]:
    if set(scores.keys()) != set(RUBRIC_CRITERIA):
        raise ValueError(f"rubric_scores must have exactly these keys: {sorted(RUBRIC_CRITERIA)}")
    for value in scores.values():
        if not (RUBRIC_MIN <= value <= RUBRIC_MAX):
            raise ValueError(f"each rubric score must be between {RUBRIC_MIN} and {RUBRIC_MAX}")
    return scores


class AddMarkRequest(BaseModel):
    """Body for `POST /peer-review/invites/{token}/marks` -- one blind moment-mark."""

    mark_sec: float = Field(..., ge=0.0)
    text: str | None = None


class SubmitRubricRequest(BaseModel):
    """
    Body for `POST /peer-review/invites/{token}/submit` -- the one required
    end-of-video rating. Submitting this completes the invite and reveals
    the machine's results.
    """

    rubric_scores: dict[str, int]
    text: str | None = None

    @field_validator("rubric_scores")
    @classmethod
    def _check_rubric(cls, value: dict[str, int]) -> dict[str, int]:
        return _validate_rubric(value)


class PeerNoteResponse(BaseModel):
    """One row of a rater's blind review, as returned to the client."""

    note_id: uuid.UUID
    session_id: uuid.UUID
    mark_sec: float | None
    rubric_scores: dict[str, int]
    text: str | None
    created_at: datetime

    @classmethod
    def from_orm_note(cls, note: PeerNoteORM) -> "PeerNoteResponse":
        return cls(
            note_id=note.id,
            session_id=note.session_id,
            mark_sec=note.mark_sec,
            rubric_scores=note.rubric_scores,
            text=note.text,
            created_at=note.created_at,
        )


class PeerReviewStateResponse(BaseModel):
    """
    Response for `GET /peer-review/invites/{token}` -- what the rater (B)
    sees. Shape depends on `status`:

    - `pending`: `own_marks` holds only *this rater's own* marks so far (so
      refreshing the page doesn't lose blind progress); `pose_feature`/
      `events` are always `None`/empty -- the whole point of this response
      while pending is to withhold them.
    - `completed`: `pose_feature`/`events` are populated (the reveal), and
      `own_marks` includes the rater's rubric row too.
    - `expired`/`revoked`: the router raises before building this at all
      (410) -- there is nothing to withhold gracefully, the link is just
      dead.
    """

    status: PeerReviewStatus
    session_id: uuid.UUID
    profile: str
    pose_feature: PoseFeature | None = None
    events: list[PresentationEvent] = Field(default_factory=list)
    own_marks: list[PeerNoteResponse] = Field(default_factory=list)
