"""
routers/practice.py

Live Practice API -- a WebSocket endpoint for audio-only "live" speaking
practice, plus two REST endpoints for retrieving a session's status/result
after the fact. See `services/practice_session_manager.py` for the
orchestration logic and `db.models.PracticeSessionORM`/`PracticeSessionState`
for persistence.

This is intentionally a small, separate router from `routers/sessions.py`:
practice sessions are not part of the Presentation/Interview state machine,
have no uploaded files (audio streams in over the socket), and produce a
single, standalone evaluation rather than participating in a multi-material
report + recommendation flow.

Wire protocol for `WS /practice/stream?language=vi&audio_format=wav`:

    client -> server: binary frames, raw already-encoded audio chunks
                       (wav/webm/ogg/mp3/m4a -- whatever `audio_format`
                       declares; the server just appends bytes to a file
                       with that extension and lets Whisper/Librosa decode
                       the accumulated file)
    client -> server: one text frame `{"type": "end_session"}` when done

    server -> client: {"type": "session_started", "session_id": "..."}
    server -> client: {"type": "partial_transcript", "transcript": "..."}
                       (sent periodically while streaming)
    server -> client: {"type": "live_tip", "message": "..."}
                       (sent alongside a partial_transcript when there is
                       something worth flagging -- see
                       `PracticeSessionManager.partial_transcript_tip`)
    server -> client: {"type": "final_evaluation", "session_id": "...", ...}
                       (sent once, after `end_session`, then the socket
                       closes -- same field shape as
                       `GET /practice/{id}/evaluation`)
    server -> client: {"type": "final_evaluation_failed", "session_id": "...",
                       "error_message": "..."} if the finalize pipeline
                       raised (Whisper/Gemini failure, etc.)

If the client disconnects without sending `end_session`, the server still
finalizes the recording captured so far on a best-effort basis -- the result
is retrievable later via `GET /practice/{id}/evaluation` even though there
is no socket left to push it over.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session as DBSession

from config import settings
from db.models import PracticeSessionORM, PracticeSessionState
from db.session import SessionLocal, get_db
from models.practice_models import (
    PracticeEvaluationResponse,
    PracticeSessionCreateRequest,
    PracticeSessionResponse,
)
from services.ai_orchestrator import ai_orchestrator
from services.practice_session_manager import (
    PracticeEvaluationNotReadyError,
    PracticeMaterialError,
    PracticeSessionNotFoundError,
    practice_session_manager,
)
from utils.file_utils import save_upload_file, validate_extension
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/practice", tags=["Live Practice"])

# How many audio chunks accumulate before the server re-runs Whisper on the
# buffered recording so far and pushes back a partial transcript + live tip.
# A tighter interval feels more "live" but costs a full Whisper pass each
# time; 5 is a pragmatic default for the base Whisper model on typical
# MediaRecorder-sized chunks (~1s of audio each).
_PARTIAL_TRANSCRIBE_EVERY_N_CHUNKS = 5

_ALLOWED_AUDIO_FORMATS = {"wav", "webm", "ogg", "mp3", "m4a"}


@router.websocket("/stream")
async def practice_stream(
    websocket: WebSocket,
    language: str = "vi",
    audio_format: str = "wav",
    practice_session_id: uuid.UUID | None = None,
) -> None:
    """
    Live speaking-practice WebSocket endpoint. See module docstring for the
    wire protocol.

    `practice_session_id` is optional: pass the id of a session already
    created via `POST /practice` (and optionally with a slide/resume
    attached via `POST /practice/{id}/slide`/`/resume`) to stream into it;
    omit it for a plain audio-only practice, in which case a fresh session
    is created here exactly as before.
    """
    if audio_format not in _ALLOWED_AUDIO_FORMATS:
        await websocket.accept()
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.accept()
    db = SessionLocal()

    try:
        if practice_session_id is not None:
            try:
                session = practice_session_manager.get_session(db, practice_session_id)
            except PracticeSessionNotFoundError:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
            if session.state is not PracticeSessionState.CONNECTING:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
                return
        else:
            session = practice_session_manager.create_session(db, language=language)

        settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        audio_path = settings.UPLOAD_DIR / f"practice_{session.id}.{audio_format}"
        session = practice_session_manager.start_streaming(db, session.id, audio_path)

        await websocket.send_json({"type": "session_started", "session_id": str(session.id)})

        ended_cleanly = await _stream_audio(websocket, db, session.id, audio_path)

        final_session = await practice_session_manager.finalize(db, session.id)

        if ended_cleanly:
            await _try_send(websocket, _final_payload(final_session))
            await _try_close(websocket)
    finally:
        db.close()


async def _stream_audio(websocket: WebSocket, db: DBSession, session_id: uuid.UUID, audio_path: Path) -> bool:
    """
    Reads binary audio chunks off the socket and appends them to
    `audio_path`, periodically triggering a partial-transcript update.
    Returns True if the client ended the session cleanly (sent
    `end_session`), False if it disconnected instead.
    """
    chunk_count = 0
    try:
        async with aiofiles.open(audio_path, "wb") as out_file:
            while True:
                message = await websocket.receive()

                if message.get("type") == "websocket.disconnect":
                    return False

                data = message.get("bytes")
                if data is not None:
                    await out_file.write(data)
                    chunk_count += 1
                    if chunk_count % _PARTIAL_TRANSCRIBE_EVERY_N_CHUNKS == 0:
                        await out_file.flush()
                        await _send_partial_update(websocket, db, session_id, audio_path)
                    continue

                text = message.get("text")
                if text is not None:
                    try:
                        payload = json.loads(text)
                    except ValueError:
                        continue
                    if payload.get("type") == "end_session":
                        return True
    except WebSocketDisconnect:
        return False


async def _send_partial_update(websocket: WebSocket, db: DBSession, session_id: uuid.UUID, audio_path: Path) -> None:
    """Best-effort partial transcription + live tip; a decode failure on a mid-stream buffer never kills the stream."""
    try:
        speech = await asyncio.to_thread(ai_orchestrator.analyze_speech, audio_path)
    except Exception:  # noqa: BLE001
        logger.debug("Partial transcription skipped for practice session %s (buffer not yet decodable)", session_id)
        return

    transcript = speech.transcript
    session = practice_session_manager.get_session(db, session_id)
    session.transcript_so_far = transcript
    db.commit()

    if not await _try_send(websocket, {"type": "partial_transcript", "transcript": transcript}):
        return

    tip = practice_session_manager.partial_transcript_tip(transcript)
    if tip:
        await _try_send(websocket, {"type": "live_tip", "message": tip})


def _final_payload(session: PracticeSessionORM) -> dict:
    if session.evaluation is None:
        return {
            "type": "final_evaluation_failed",
            "session_id": str(session.id),
            "error_message": session.error_message,
        }
    evaluation = PracticeEvaluationResponse.from_orm_row(session.evaluation)
    return {"type": "final_evaluation", "session_id": str(session.id), **evaluation.model_dump(mode="json")}


async def _try_send(websocket: WebSocket, payload: dict) -> bool:
    """Sends a JSON frame, swallowing errors from a socket that closed out from under us."""
    try:
        await websocket.send_json(payload)
        return True
    except (RuntimeError, WebSocketDisconnect):
        return False


async def _try_close(websocket: WebSocket) -> None:
    try:
        await websocket.close()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# REST endpoints -- pre-streaming setup (optional) + retrieval
# ---------------------------------------------------------------------------


def _not_found(exc: PracticeSessionNotFoundError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _material_conflict(exc: PracticeMaterialError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.post(
    "",
    response_model=PracticeSessionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a practice session ahead of streaming, so a slide deck/resume can be attached first.",
)
async def create_practice_session(
    payload: PracticeSessionCreateRequest, db: DBSession = Depends(get_db)
) -> PracticeSessionResponse:
    session = practice_session_manager.create_session(db, mode=payload.mode, language=payload.language)
    return PracticeSessionResponse.from_orm_session(session)


@router.post(
    "/{practice_session_id}/slide",
    response_model=PracticeSessionResponse,
    summary="Attach presentation slides (.pptx) before streaming starts (Presentation mode only).",
)
async def upload_practice_slide(
    practice_session_id: uuid.UUID,
    file: UploadFile = File(..., description="Presentation slides (.pptx)."),
    db: DBSession = Depends(get_db),
) -> PracticeSessionResponse:
    extension = validate_extension(file, settings.ALLOWED_PPTX_EXTENSIONS)
    saved_path = await save_upload_file(file, extension)

    try:
        session = practice_session_manager.attach_slide(db, practice_session_id, str(saved_path))
    except PracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except PracticeMaterialError as exc:
        raise _material_conflict(exc) from exc
    return PracticeSessionResponse.from_orm_session(session)


@router.post(
    "/{practice_session_id}/resume",
    response_model=PracticeSessionResponse,
    summary="Attach a resume/CV (.pdf) before streaming starts (Interview mode only).",
)
async def upload_practice_resume(
    practice_session_id: uuid.UUID,
    file: UploadFile = File(..., description="Resume/CV (.pdf)."),
    db: DBSession = Depends(get_db),
) -> PracticeSessionResponse:
    extension = validate_extension(file, settings.ALLOWED_PDF_EXTENSIONS)
    saved_path = await save_upload_file(file, extension)

    try:
        session = practice_session_manager.attach_resume(db, practice_session_id, str(saved_path))
    except PracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except PracticeMaterialError as exc:
        raise _material_conflict(exc) from exc
    return PracticeSessionResponse.from_orm_session(session)


@router.get(
    "/{practice_session_id}",
    response_model=PracticeSessionResponse,
    summary="Get a live-practice session's current status.",
)
async def get_practice_session(
    practice_session_id: uuid.UUID, db: DBSession = Depends(get_db)
) -> PracticeSessionResponse:
    try:
        session = practice_session_manager.get_session(db, practice_session_id)
    except PracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    return PracticeSessionResponse.from_orm_session(session)


@router.get(
    "/{practice_session_id}/evaluation",
    response_model=PracticeEvaluationResponse,
    summary="Get the final evaluation of a completed live-practice session.",
)
async def get_practice_evaluation(
    practice_session_id: uuid.UUID, db: DBSession = Depends(get_db)
) -> PracticeEvaluationResponse:
    try:
        row = practice_session_manager.get_evaluation(db, practice_session_id)
    except PracticeSessionNotFoundError as exc:
        raise _not_found(exc) from exc
    except PracticeEvaluationNotReadyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return PracticeEvaluationResponse.from_orm_row(row)
