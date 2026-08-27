"""
services/peer_review_manager.py

Orchestrates "nhờ bạn chấm hộ" (Nhom C, Task 15-16): create an invite,
accept a rater's blind marks against it, and reveal the machine's results
only once the one required rubric row is submitted.

"B never sees machine results before submitting" is enforced here
(`_require_open_and_not_owner`, `get_by_token`'s lazy expiry), not only in
`routers/peer_review.py` -- one place decides it, the router just reports
whatever this raises.
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session as DBSession

from db.models import PeerNoteORM, PeerReviewInviteORM, PeerReviewStatus, SelfPracticeSessionORM

# How long a "nhờ bạn chấm hộ" link stays usable. Long enough that B doesn't
# have to drop everything right away (plan.md: "B phải chủ động dành thời
# gian riêng để xem và chấm"), short enough that a link posted somewhere
# public doesn't stay live indefinitely.
INVITE_TTL = timedelta(days=14)

# secrets.token_urlsafe(24) -> 32 chars, comfortably under the token
# column's 64-char limit with room to grow.
_TOKEN_BYTES = 24


class PeerReviewInviteNotFoundError(Exception):
    """Raised when a token or (invite_id, session_id) pair matches no invite."""


class PeerReviewInviteNotOpenError(Exception):
    """Raised when an action requires `status == PENDING` but the invite isn't."""


class SelfReviewNotAllowedError(Exception):
    """Raised when a session's own owner tries to peer-review it -- not blind, not independent."""


def _as_utc(value: datetime) -> datetime:
    """SQLite (tests) returns naive datetimes; values are always written as UTC."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class PeerReviewManager:
    """Orchestrates the peer-review invite/mark/submit/reveal lifecycle."""

    # ------------------------------------------------------------------
    # Invites (owner-facing)
    # ------------------------------------------------------------------

    def create_invite(
        self, db: DBSession, session: SelfPracticeSessionORM, inviter_user_id: uuid.UUID
    ) -> PeerReviewInviteORM:
        invite = PeerReviewInviteORM(
            session_id=session.id,
            inviter_user_id=inviter_user_id,
            token=secrets.token_urlsafe(_TOKEN_BYTES),
            status=PeerReviewStatus.PENDING,
            expires_at=datetime.now(timezone.utc) + INVITE_TTL,
        )
        db.add(invite)
        db.commit()
        db.refresh(invite)
        return invite

    def list_invites(self, db: DBSession, session_id: uuid.UUID) -> list[PeerReviewInviteORM]:
        return (
            db.query(PeerReviewInviteORM)
            .filter(PeerReviewInviteORM.session_id == session_id)
            .order_by(PeerReviewInviteORM.created_at.desc())
            .all()
        )

    def get_invite(self, db: DBSession, invite_id: uuid.UUID, session_id: uuid.UUID) -> PeerReviewInviteORM:
        invite = (
            db.query(PeerReviewInviteORM)
            .filter(PeerReviewInviteORM.id == invite_id, PeerReviewInviteORM.session_id == session_id)
            .one_or_none()
        )
        if invite is None:
            raise PeerReviewInviteNotFoundError(f"No invite {invite_id} on session {session_id}")
        return invite

    def revoke_invite(self, db: DBSession, invite: PeerReviewInviteORM) -> PeerReviewInviteORM:
        """A no-op on an already-completed/expired/revoked invite -- there is nothing left to revoke."""
        if invite.status == PeerReviewStatus.PENDING:
            invite.status = PeerReviewStatus.REVOKED
            db.commit()
            db.refresh(invite)
        return invite

    # ------------------------------------------------------------------
    # Rater-facing (by token)
    # ------------------------------------------------------------------

    def get_by_token(self, db: DBSession, token: str) -> PeerReviewInviteORM:
        """
        The live invite for `token`, with expiry checked and applied
        lazily -- there is no background sweep, the next read is what
        notices a pending invite's `expires_at` has passed.
        """
        invite = db.query(PeerReviewInviteORM).filter(PeerReviewInviteORM.token == token).one_or_none()
        if invite is None:
            raise PeerReviewInviteNotFoundError(f"No invite with token={token!r}")

        if invite.status == PeerReviewStatus.PENDING and datetime.now(timezone.utc) > _as_utc(invite.expires_at):
            invite.status = PeerReviewStatus.EXPIRED
            db.commit()
            db.refresh(invite)
        return invite

    def add_mark(
        self,
        db: DBSession,
        invite: PeerReviewInviteORM,
        rater_user_id: uuid.UUID,
        mark_sec: float,
        text: str | None,
    ) -> PeerNoteORM:
        self._require_open_and_not_owner(invite, rater_user_id)
        note = PeerNoteORM(
            session_id=invite.session_id,
            rater_user_id=rater_user_id,
            invite_id=invite.id,
            mark_sec=mark_sec,
            rubric_scores={},
            text=text,
        )
        db.add(note)
        db.commit()
        db.refresh(note)
        return note

    def submit_rubric(
        self,
        db: DBSession,
        invite: PeerReviewInviteORM,
        rater_user_id: uuid.UUID,
        rubric_scores: dict[str, int],
        text: str | None,
    ) -> PeerNoteORM:
        """The one required end-of-video rating. Completes the invite, which is what reveals the machine's results."""
        self._require_open_and_not_owner(invite, rater_user_id)
        note = PeerNoteORM(
            session_id=invite.session_id,
            rater_user_id=rater_user_id,
            invite_id=invite.id,
            mark_sec=None,
            rubric_scores=rubric_scores,
            text=text,
        )
        db.add(note)
        invite.status = PeerReviewStatus.COMPLETED
        db.commit()
        db.refresh(note)
        db.refresh(invite)
        return note

    def list_own_marks(self, db: DBSession, invite_id: uuid.UUID, rater_user_id: uuid.UUID) -> list[PeerNoteORM]:
        """This rater's own rows on this invite -- moment marks plus the rubric row, once submitted."""
        return (
            db.query(PeerNoteORM)
            .filter(PeerNoteORM.invite_id == invite_id, PeerNoteORM.rater_user_id == rater_user_id)
            .order_by(PeerNoteORM.created_at.asc())
            .all()
        )

    # ------------------------------------------------------------------
    # Owner-facing reveal (Task 17)
    # ------------------------------------------------------------------

    def list_completed_peer_notes(self, db: DBSession, session_id: uuid.UUID) -> list[PeerNoteORM]:
        """
        Every peer note from a COMPLETED invite on this session -- the
        second timeline layer the owner sees on their own session view.
        Rows from a still-PENDING invite never appear here: that rater's
        marks stay blind until they submit, even to the session's own owner.
        """
        return (
            db.query(PeerNoteORM)
            .join(PeerReviewInviteORM, PeerNoteORM.invite_id == PeerReviewInviteORM.id)
            .filter(
                PeerReviewInviteORM.session_id == session_id,
                PeerReviewInviteORM.status == PeerReviewStatus.COMPLETED,
            )
            .order_by(PeerNoteORM.created_at.asc())
            .all()
        )

    def _require_open_and_not_owner(self, invite: PeerReviewInviteORM, rater_user_id: uuid.UUID) -> None:
        if invite.status != PeerReviewStatus.PENDING:
            raise PeerReviewInviteNotOpenError(f"Invite is {invite.status.value}, not pending")
        if invite.inviter_user_id == rater_user_id:
            raise SelfReviewNotAllowedError("The session's own owner cannot peer-review it")


peer_review_manager = PeerReviewManager()
