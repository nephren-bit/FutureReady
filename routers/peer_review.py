"""
routers/peer_review.py

The Peer Review API ("nhờ bạn chấm hộ", Nhom C Task 15-16): the session
owner (A) invites a friend (B) to blind-review a recording before B ever
sees what the machine detected.

Two audiences, two sets of routes:
- Owner-facing, nested under `/self-practice/{session_id}/peer-invites`:
  create/list/revoke invites. Gated by the same `_ensure_owner` as every
  other self-practice route (imported from routers.self_practice, not
  duplicated).
- Rater-facing, under `/peer-review/invites/{token}`: any authenticated
  user can open a link, add blind moment-marks, and submit the one
  required rubric -- gated only by the invite's own validity (not
  expired/revoked), never by session ownership, since the whole point is
  that B is *not* the owner. `services/peer_review_manager.py` is what
  actually enforces "no machine results before the rubric is submitted";
  this router only translates its exceptions into HTTP responses.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession

from db.models import PeerReviewStatus, SelfPracticeState, UserORM
from db.session import get_db
from models.peer_review_models import (
    AddMarkRequest,
    PeerNoteResponse,
    PeerReviewInviteResponse,
    PeerReviewStateResponse,
    SubmitRubricRequest,
)
from models.responses import ErrorResponse
from routers.deps import get_current_user, get_current_user_from_header_or_query
from routers.self_practice import _MEDIA_TYPES, _ensure_owner, _not_found
from services.peer_review_manager import (
    PeerReviewInviteNotFoundError,
    PeerReviewInviteNotOpenError,
    SelfReviewNotAllowedError,
    peer_review_manager,
)
from services.self_practice_manager import SelfPracticeSessionNotFoundError, self_practice_manager
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["Peer Review"])

_ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    409: {"model": ErrorResponse},
    410: {"model": ErrorResponse},
}

_DEAD_INVITE_DETAIL = {
    PeerReviewStatus.EXPIRED: "Lời mời đã hết hạn.",
    PeerReviewStatus.REVOKED: "Lời mời đã bị thu hồi.",
}


def _reject_if_dead(invite) -> None:
    """410 for a link that will never work again -- distinct from 409 (not open yet/anymore, but not dead)."""
    detail = _DEAD_INVITE_DETAIL.get(invite.status)
    if detail is not None:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail=detail)


def _build_state_response(
    db: DBSession, invite, current_user: UserORM
) -> PeerReviewStateResponse:
    session = self_practice_manager.get_session(db, invite.session_id)
    own_marks = [
        PeerNoteResponse.from_orm_note(note)
        for note in peer_review_manager.list_own_marks(db, invite.id, current_user.id)
    ]

    if invite.status != PeerReviewStatus.COMPLETED:
        # Pending: withhold the machine's results entirely -- that's the
        # one rule this whole feature exists to enforce.
        return PeerReviewStateResponse(
            status=invite.status,
            session_id=session.id,
            profile=session.profile,
            own_marks=own_marks,
        )

    return PeerReviewStateResponse(
        status=invite.status,
        session_id=session.id,
        profile=session.profile,
        pose_feature=self_practice_manager.get_pose_feature(db, session.id),
        events=self_practice_manager.list_events(db, session.id),
        own_marks=own_marks,
    )


# ---------------------------------------------------------------------------
# Owner-facing: manage invites sent from one of the owner's own sessions.
# ---------------------------------------------------------------------------


@router.post(
    "/self-practice/{session_id}/peer-invites",
    response_model=PeerReviewInviteResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
    summary="Create a 'nhờ bạn chấm hộ' invite link for this session.",
)
async def create_peer_invite(
    session_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PeerReviewInviteResponse:
    try:
        session = self_practice_manager.get_session(db, session_id)
    except SelfPracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    _ensure_owner(session, current_user)

    if session.state != SelfPracticeState.COMPLETED:
        # Inviting on a still-PROCESSING/FAILED session would let a rubric
        # submission "complete" the invite and reveal nothing -- plan.md's
        # flow only ever offers this button once a session has finished.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chỉ tạo được lời mời cho phiên đã xử lý xong.",
        )

    invite = peer_review_manager.create_invite(db, session, inviter_user_id=current_user.id)
    return PeerReviewInviteResponse.from_orm_invite(invite)


@router.get(
    "/self-practice/{session_id}/peer-invites",
    response_model=list[PeerReviewInviteResponse],
    responses=_ERROR_RESPONSES,
    summary="List every peer-review invite sent from this session.",
)
async def list_peer_invites(
    session_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> list[PeerReviewInviteResponse]:
    try:
        session = self_practice_manager.get_session(db, session_id)
    except SelfPracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    _ensure_owner(session, current_user)

    invites = peer_review_manager.list_invites(db, session_id)
    return [PeerReviewInviteResponse.from_orm_invite(invite) for invite in invites]


@router.delete(
    "/self-practice/{session_id}/peer-invites/{invite_id}",
    response_model=PeerReviewInviteResponse,
    responses=_ERROR_RESPONSES,
    summary="Revoke a pending invite. A no-op if it's already completed/expired/revoked.",
)
async def revoke_peer_invite(
    session_id: uuid.UUID,
    invite_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PeerReviewInviteResponse:
    try:
        session = self_practice_manager.get_session(db, session_id)
        _ensure_owner(session, current_user)
        invite = peer_review_manager.get_invite(db, invite_id, session_id)
    except (SelfPracticeSessionNotFoundError, PeerReviewInviteNotFoundError) as exc:
        raise _not_found(exc) from exc

    invite = peer_review_manager.revoke_invite(db, invite)
    return PeerReviewInviteResponse.from_orm_invite(invite)


# ---------------------------------------------------------------------------
# Rater-facing: opening a link and submitting a blind review. Gated by the
# invite's own validity only -- never by routers.self_practice ownership.
# ---------------------------------------------------------------------------


@router.get(
    "/peer-review/invites/{token}",
    response_model=PeerReviewStateResponse,
    responses=_ERROR_RESPONSES,
    summary="Open a peer-review invite: blind (pending) or revealed (completed).",
)
async def get_peer_review_invite(
    token: str,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PeerReviewStateResponse:
    try:
        invite = peer_review_manager.get_by_token(db, token)
    except PeerReviewInviteNotFoundError as exc:
        raise _not_found(exc) from exc
    _reject_if_dead(invite)
    return _build_state_response(db, invite, current_user)


@router.get(
    "/peer-review/invites/{token}/video",
    responses=_ERROR_RESPONSES,
    summary="Stream the recording for the blind-review player.",
)
async def get_peer_review_video(
    token: str,
    current_user: UserORM = Depends(get_current_user_from_header_or_query),
    db: DBSession = Depends(get_db),
) -> FileResponse:
    try:
        invite = peer_review_manager.get_by_token(db, token)
        session = self_practice_manager.get_session(db, invite.session_id)
    except (PeerReviewInviteNotFoundError, SelfPracticeSessionNotFoundError) as exc:
        raise _not_found(exc) from exc
    _reject_if_dead(invite)

    video_path = Path(session.video_file_path)
    if not video_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file is missing on disk.")
    media_type = _MEDIA_TYPES.get(video_path.suffix.lower(), "application/octet-stream")
    return FileResponse(video_path, media_type=media_type)


def _reject_not_open(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


def _reject_self_review(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))


@router.post(
    "/peer-review/invites/{token}/marks",
    response_model=PeerNoteResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
    summary="Add a blind moment-mark while watching. Only while the invite is still pending.",
)
async def add_peer_mark(
    token: str,
    body: AddMarkRequest,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PeerNoteResponse:
    try:
        invite = peer_review_manager.get_by_token(db, token)
    except PeerReviewInviteNotFoundError as exc:
        raise _not_found(exc) from exc
    _reject_if_dead(invite)

    try:
        note = peer_review_manager.add_mark(db, invite, current_user.id, body.mark_sec, body.text)
    except PeerReviewInviteNotOpenError as exc:
        raise _reject_not_open(exc) from exc
    except SelfReviewNotAllowedError as exc:
        raise _reject_self_review(exc) from exc
    return PeerNoteResponse.from_orm_note(note)


@router.post(
    "/peer-review/invites/{token}/submit",
    response_model=PeerReviewStateResponse,
    responses=_ERROR_RESPONSES,
    summary="Submit the required end-of-video rubric. Completes the invite and reveals the machine's results.",
)
async def submit_peer_rubric(
    token: str,
    body: SubmitRubricRequest,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> PeerReviewStateResponse:
    try:
        invite = peer_review_manager.get_by_token(db, token)
    except PeerReviewInviteNotFoundError as exc:
        raise _not_found(exc) from exc
    _reject_if_dead(invite)

    try:
        peer_review_manager.submit_rubric(db, invite, current_user.id, body.rubric_scores, body.text)
    except PeerReviewInviteNotOpenError as exc:
        raise _reject_not_open(exc) from exc
    except SelfReviewNotAllowedError as exc:
        raise _reject_self_review(exc) from exc

    logger.info("Peer review submitted: invite_id=%s rater_id=%s", invite.id, current_user.id)
    return _build_state_response(db, invite, current_user)
