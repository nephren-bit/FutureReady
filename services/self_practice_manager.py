"""
services/self_practice_manager.py

Orchestrates the self-practice flow (specs/in-class-analysis): a person
records themselves with a webcam, the pipeline already built for Tasks 1-3/5
(`VideoExtractor` -> `PoseAnalyzer` -> `EventDetector`) runs on it once in the
background, alongside a second, independent pass over the same recording's
audio track (`AudioExtractor` -> `VoiceAnalyzer` -> the same `EventDetector`
again, see `_detect_voice_events`), and the result is one combined set of
`PresentationEvent`s (pose and voice mixed together, ordinary event rows
either way) plus whatever `SelfNote`s the person adds while reviewing.

This is the only pipeline in the codebase: it never computes a total score,
which is this product's core principle, and there is no separate
scoring-oriented manager left to accidentally couple it to.

Errors from the background analysis pass are caught and stored on the
session row (`state=FAILED` + `error_message`) rather than raised, since
there is no HTTP response left to report them to by the time it runs.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from analyzers.pose_analyzer import PoseAnalyzer
from analyzers.voice_analyzer import VoiceAnalyzer, transcribe_with_whisper
from db.models import SelfNoteORM, SelfPracticeSessionORM, SelfPracticeState
from events.detector import EventDetector
from extractors.audio_extractor import AudioExtractionError, AudioExtractor
from extractors.video_extractor import VideoExtractor
from models.events import PresentationEvent
from models.notes import SelfNote
from models.profiles import ContextProfile
from services.profile_loader import load_profile
from services.session_mappers import (
    orm_to_pose,
    orm_to_presentation_event,
    pose_to_orm,
    presentation_event_to_orm,
)
from utils.file_utils import cleanup_file
from utils.logger import get_logger

logger = get_logger(__name__)

# The two context profiles this flow accepts. `presentation_class` (the old
# in-classroom profile) is intentionally excluded here even though it is a
# valid `available_profiles()` entry -- it belongs to the retired teacher
# entry point, not self-practice (see plan.md, "Ho so boi canh").
SELF_PRACTICE_PROFILES = frozenset({"presentation_solo", "interview_solo"})


class SelfPracticeSessionNotFoundError(Exception):
    """Raised when an operation references a `SelfPracticeSessionORM.id` that does not exist."""


class SelfNoteNotFoundError(Exception):
    """Raised when an operation references a `SelfNoteORM.id` that does not exist."""


class InvalidSelfPracticeProfileError(ValueError):
    """Raised when `create_session` is asked to use a profile outside `SELF_PRACTICE_PROFILES`."""


class SelfPracticeManager:
    """Orchestrates the self-practice lifecycle (record -> analyze -> review -> note)."""

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def get_session(self, db: DBSession, session_id: uuid.UUID) -> SelfPracticeSessionORM:
        session = db.get(SelfPracticeSessionORM, session_id)
        if session is None:
            raise SelfPracticeSessionNotFoundError(f"No self-practice session with id={session_id}")
        return session

    def list_sessions(
        self, db: DBSession, owner_id: uuid.UUID | None = None
    ) -> list[SelfPracticeSessionORM]:
        """
        Most recently created first. `owner_id=None` returns every session
        (the admin view); a real id restricts the list to that owner's own
        sessions (routers/self_practice.py passes the caller's own id unless
        they're an admin).
        """
        query = db.query(SelfPracticeSessionORM).order_by(SelfPracticeSessionORM.created_at.desc())
        if owner_id is not None:
            query = query.filter(SelfPracticeSessionORM.user_id == owner_id)
        return query.all()

    def delete_session(self, db: DBSession, session_id: uuid.UUID) -> None:
        """Deletes the session row (cascading to its pose feature/events/notes) and its video file."""
        session = self.get_session(db, session_id)
        video_path = Path(session.video_file_path)
        db.delete(session)
        db.commit()
        cleanup_file(video_path)

    def create_session(
        self, db: DBSession, profile: str, video_file_path: str, user_id: uuid.UUID | None = None
    ) -> SelfPracticeSessionORM:
        """
        Create a session row in PROCESSING state. Does not run the pipeline
        itself -- the caller schedules `run_pipeline` as a background task
        once this has committed, so the HTTP response doesn't wait on it.
        `user_id` is the owner (routers/self_practice.py always passes the
        authenticated caller's id; it's optional here only because sessions
        recorded before accounts existed have none).
        """
        if profile not in SELF_PRACTICE_PROFILES:
            raise InvalidSelfPracticeProfileError(
                f"'{profile}' is not a self-practice profile. Allowed: {sorted(SELF_PRACTICE_PROFILES)}"
            )
        session = SelfPracticeSessionORM(
            profile=profile,
            video_file_path=video_file_path,
            state=SelfPracticeState.PROCESSING,
            user_id=user_id,
        )
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def run_pipeline(self, db: DBSession, session_id: uuid.UUID) -> None:
        """
        Run VideoExtractor -> PoseAnalyzer -> EventDetector once, then the
        same for voice (VideoExtractor's audio track -> VoiceAnalyzer ->
        the same EventDetector, run a second time -- see `_detect_voice_events`),
        and persist the combined result. Never raises: any failure is caught
        and stored on the session row as FAILED + `error_message`, matching
        every other background-task pattern in this codebase (see
        `routers/sessions.py`'s `_background_run_*` wrappers) so one bad
        recording can't crash the worker.
        """
        session = self.get_session(db, session_id)
        try:
            profile = load_profile(session.profile)
            video_path = Path(session.video_file_path)

            # A fixed sample count samples a 5-minute recording exactly as
            # sparsely as a 30-second one -- ask for the profile's own
            # minimum sampling rate instead (see VideoExtractor.__init__).
            video_feature, frames, timestamps = VideoExtractor(
                min_sample_rate_hz=profile.frame_requirements.min_sample_rate_hz
            ).extract_with_frames(video_path)
            pose = PoseAnalyzer(profile).analyze(list(zip(frames, timestamps)), source_fps=video_feature.fps)
            detector = EventDetector(profile)
            events = detector.detect(str(session_id), pose)
            events += self._detect_voice_events(detector, profile, video_path, video_feature.fps, session_id)

            db.add(pose_to_orm(session_id, pose))
            for event in events:
                db.add(presentation_event_to_orm(session_id, event))

            session.state = SelfPracticeState.COMPLETED
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Self-practice session %s pipeline failed", session_id)
            db.rollback()
            session = self.get_session(db, session_id)
            session.state = SelfPracticeState.FAILED
            session.error_message = str(exc)
            db.commit()

    def _detect_voice_events(
        self,
        detector: EventDetector,
        profile: ContextProfile,
        video_path: Path,
        source_fps: float,
        session_id: uuid.UUID,
    ) -> list[PresentationEvent]:
        """
        Voice analysis is best-effort: a recording with no audio track, or a
        transcription failure, must not fail the whole session -- the pose
        events are already a complete, useful result on their own. Runs the
        *same* `EventDetector` instance used for pose a second time against
        a `VoiceFeature` (see events/detector.py's module docstring for why
        that is enough to make voice rules fire and pose rules skip, with no
        voice-specific code in the detector itself).
        """
        try:
            audio_feature, samples = AudioExtractor().extract_with_samples(video_path)
        except AudioExtractionError as exc:
            logger.info("Session %s: voice analysis skipped -- %s", session_id, exc)
            return []

        try:
            voice = VoiceAnalyzer(profile).analyze(
                samples,
                audio_feature.sample_rate,
                audio_feature.duration_sec,
                source_fps=source_fps,
                transcribe_fn=transcribe_with_whisper,
            )
        except Exception:  # noqa: BLE001 -- best-effort, see docstring
            logger.exception("Session %s: voice analysis failed", session_id)
            return []

        return detector.detect(str(session_id), voice)

    # ------------------------------------------------------------------
    # Review data
    # ------------------------------------------------------------------

    def list_events(self, db: DBSession, session_id: uuid.UUID) -> list:
        session = self.get_session(db, session_id)
        return [orm_to_presentation_event(row) for row in session.presentation_events]

    def get_pose_feature(self, db: DBSession, session_id: uuid.UUID):
        session = self.get_session(db, session_id)
        return orm_to_pose(session.pose_feature) if session.pose_feature is not None else None

    # ------------------------------------------------------------------
    # SelfNote CRUD
    # ------------------------------------------------------------------

    def list_notes(self, db: DBSession, session_id: uuid.UUID) -> list[SelfNoteORM]:
        session = self.get_session(db, session_id)
        return sorted(session.self_notes, key=lambda note: note.mark_sec)

    def create_note(self, db: DBSession, session_id: uuid.UUID, mark_sec: float, text: str = "") -> SelfNoteORM:
        self.get_session(db, session_id)
        note = SelfNote(session_id=str(session_id), mark_sec=mark_sec, text=text)
        row = SelfNoteORM(
            id=uuid.UUID(note.note_id),
            session_id=session_id,
            mark_sec=note.mark_sec,
            text=note.text,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def _get_note(self, db: DBSession, note_id: uuid.UUID) -> SelfNoteORM:
        row = db.get(SelfNoteORM, note_id)
        if row is None:
            raise SelfNoteNotFoundError(f"No self note with id={note_id}")
        return row

    def update_note(
        self, db: DBSession, note_id: uuid.UUID, mark_sec: float | None = None, text: str | None = None
    ) -> SelfNoteORM:
        """
        Edits the row in place -- unlike `TeacherNote.revise()`, `SelfNote`
        keeps no revision chain (see `models/notes.py`), so there is no new
        row to insert here.
        """
        row = self._get_note(db, note_id)
        if mark_sec is not None:
            row.mark_sec = mark_sec
        if text is not None:
            row.text = text
        db.commit()
        db.refresh(row)
        return row

    def delete_note(self, db: DBSession, note_id: uuid.UUID) -> None:
        row = self._get_note(db, note_id)
        db.delete(row)
        db.commit()


self_practice_manager = SelfPracticeManager()
