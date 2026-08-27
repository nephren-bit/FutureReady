"""
routers/self_practice.py

The Self Practice API (specs/in-class-analysis, Task 7/8): record a
practice video, run the pose/event pipeline on it in the background, review
the result, and attach `SelfNote`s while reviewing.

Two-phase upload: save the file and create the session row synchronously,
run the actual analysis as a `BackgroundTasks` job so the HTTP response
doesn't wait on it. Talks only to `SelfPracticeManager` -- this product
never computes a total score (see `specs/in-class-analysis/plan.md`).

Every route requires a valid token and enforces ownership (Nhóm B, Task 13
/ Plans.md B4): a session belongs to whoever created it, and an admin can
reach any session, including one with no owner at all (`user_id IS NULL`
-- recorded before accounts existed; never silently claimed by whoever
happens to know its id).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session as DBSession

from config import settings
from db.models import SelfPracticeSessionORM, UserORM
from db.session import SessionLocal, get_db
from models.responses import ErrorResponse
from models.self_practice_models import (
    SelfNoteCreateRequest,
    SelfNoteResponse,
    SelfNoteUpdateRequest,
    SelfPracticeSessionResponse,
    SelfPracticeSessionSummary,
)
from routers.deps import get_current_user, get_current_user_from_header_or_query
from services.peer_review_manager import peer_review_manager
from services.self_practice_manager import (
    InvalidSelfPracticeProfileError,
    SelfNoteNotFoundError,
    SelfPracticeSessionNotFoundError,
    self_practice_manager,
)
from utils.file_utils import cleanup_file, save_upload_file, validate_extension
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/self-practice", tags=["Self Practice"])

_ERROR_RESPONSES = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    400: {"model": ErrorResponse},
}


def _ensure_owner(session: SelfPracticeSessionORM, current_user: UserORM) -> None:
    """
    403 unless the caller is an admin or the session's own `user_id`.
    A NULL `user_id` (a session recorded before accounts existed) is never
    treated as "unowned, so anyone can take it" -- only an admin passes.
    """
    if current_user.is_admin:
        return
    if session.user_id is None or session.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Không có quyền truy cập phiên này."
        )


# Browsers' MediaRecorder commonly produces .webm (Chrome/Firefox) or .mp4
# (Safari); broader than settings.ALLOWED_VIDEO_EXTENSIONS, which is the
# separate upload-and-score flow's set for pre-recorded files.
_ALLOWED_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
_MEDIA_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime", ".m4v": "video/x-m4v", ".webm": "video/webm"}


def _not_found(exc: Exception) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


async def _background_run_pipeline(session_id: uuid.UUID) -> None:
    db = SessionLocal()
    try:
        self_practice_manager.run_pipeline(db, session_id)
    except Exception:  # noqa: BLE001
        logger.exception("Self-practice pipeline crashed for session %s", session_id)
    finally:
        db.close()


def _to_response(db: DBSession, session_id: uuid.UUID) -> SelfPracticeSessionResponse:
    session = self_practice_manager.get_session(db, session_id)
    pose_feature = self_practice_manager.get_pose_feature(db, session_id)
    events = self_practice_manager.list_events(db, session_id)
    notes = self_practice_manager.list_notes(db, session_id)
    # Only from COMPLETED invites (Nhom C, Task 17) -- a still-pending
    # rater's blind marks never leak into the owner's own view either.
    peer_notes = peer_review_manager.list_completed_peer_notes(db, session_id)
    return SelfPracticeSessionResponse.from_orm_session(
        session, pose_feature=pose_feature, events=events, notes=notes, peer_notes=peer_notes
    )


@router.get(
    "",
    response_model=list[SelfPracticeSessionSummary],
    summary="List the caller's own self-practice sessions, most recently created first (every session, for an admin).",
)
async def list_self_practice_sessions(
    current_user: UserORM = Depends(get_current_user), db: DBSession = Depends(get_db)
) -> list[SelfPracticeSessionSummary]:
    owner_id = None if current_user.is_admin else current_user.id
    sessions = self_practice_manager.list_sessions(db, owner_id=owner_id)
    return [SelfPracticeSessionSummary.from_orm_session(session) for session in sessions]


@router.post(
    "",
    response_model=SelfPracticeSessionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_ERROR_RESPONSES,
    summary="Upload a self-practice recording. Analysis runs in the background.",
)
async def create_self_practice_session(
    background_tasks: BackgroundTasks,
    profile: str = Form(..., description="presentation_solo or interview_solo."),
    video: UploadFile = File(..., description="Self-practice recording (.mp4/.mov/.m4v/.webm)."),
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SelfPracticeSessionResponse:
    extension = validate_extension(video, _ALLOWED_EXTENSIONS)
    # A practice recording is a video, not the small PDF/pptx uploads
    # save_upload_file's default limit is sized for -- same override
    # routers/sessions.py uses for its own /video upload.
    saved_path: Path = await save_upload_file(video, extension, max_size_bytes=settings.MAX_VIDEO_SIZE_BYTES)

    try:
        session = self_practice_manager.create_session(db, profile, str(saved_path), user_id=current_user.id)
    except InvalidSelfPracticeProfileError as exc:
        cleanup_file(saved_path)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    background_tasks.add_task(_background_run_pipeline, session.id)
    return _to_response(db, session.id)


@router.get(
    "/{session_id}",
    response_model=SelfPracticeSessionResponse,
    responses=_ERROR_RESPONSES,
    summary="Get a self-practice session: state, pose metrics, events, and notes.",
)
async def get_self_practice_session(
    session_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SelfPracticeSessionResponse:
    try:
        session = self_practice_manager.get_session(db, session_id)
    except SelfPracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    _ensure_owner(session, current_user)
    return _to_response(db, session_id)


@router.get(
    "/{session_id}/video",
    responses=_ERROR_RESPONSES,
    summary="Stream the recorded video for the review player.",
)
async def get_self_practice_video(
    session_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user_from_header_or_query),
    db: DBSession = Depends(get_db),
) -> FileResponse:
    try:
        session = self_practice_manager.get_session(db, session_id)
    except SelfPracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    _ensure_owner(session, current_user)

    video_path = Path(session.video_file_path)
    if not video_path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recording file is missing on disk.")
    media_type = _MEDIA_TYPES.get(video_path.suffix.lower(), "application/octet-stream")
    return FileResponse(video_path, media_type=media_type)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_ERROR_RESPONSES,
    summary="Delete a self-practice session, its pose data/events/notes, and its video file.",
)
async def delete_self_practice_session(
    session_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> None:
    try:
        session = self_practice_manager.get_session(db, session_id)
    except SelfPracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    _ensure_owner(session, current_user)
    self_practice_manager.delete_session(db, session_id)


@router.post(
    "/{session_id}/notes",
    response_model=SelfNoteResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_ERROR_RESPONSES,
    summary="Add a self-review note at a point on the timeline.",
)
async def create_self_note(
    session_id: uuid.UUID,
    body: SelfNoteCreateRequest,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SelfNoteResponse:
    try:
        session = self_practice_manager.get_session(db, session_id)
    except SelfPracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    _ensure_owner(session, current_user)
    note = self_practice_manager.create_note(db, session_id, body.mark_sec, body.text)
    return SelfNoteResponse.from_orm_note(note)


@router.patch(
    "/{session_id}/notes/{note_id}",
    response_model=SelfNoteResponse,
    responses=_ERROR_RESPONSES,
    summary="Edit a self-review note in place.",
)
async def update_self_note(
    session_id: uuid.UUID,
    note_id: uuid.UUID,
    body: SelfNoteUpdateRequest,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> SelfNoteResponse:
    try:
        session = self_practice_manager.get_session(db, session_id)
        _ensure_owner(session, current_user)
        note = self_practice_manager.update_note(db, note_id, mark_sec=body.mark_sec, text=body.text)
    except (SelfPracticeSessionNotFoundError, SelfNoteNotFoundError) as exc:
        raise _not_found(exc) from exc
    return SelfNoteResponse.from_orm_note(note)


@router.delete(
    "/{session_id}/notes/{note_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
    responses=_ERROR_RESPONSES,
    summary="Delete a self-review note.",
)
async def delete_self_note(
    session_id: uuid.UUID,
    note_id: uuid.UUID,
    current_user: UserORM = Depends(get_current_user),
    db: DBSession = Depends(get_db),
) -> None:
    try:
        session = self_practice_manager.get_session(db, session_id)
        _ensure_owner(session, current_user)
        self_practice_manager.delete_note(db, note_id)
    except (SelfPracticeSessionNotFoundError, SelfNoteNotFoundError) as exc:
        raise _not_found(exc) from exc
