"""
services/practice_session_manager.py

Orchestrates a "live practice" session (see `routers/practice.py`): the
client streams raw audio chunks over a WebSocket while practicing speaking,
and receives:

  - periodic partial transcripts + a cheap, deterministic "live tip" (no LLM
    call per chunk -- Whisper re-transcribes the buffered audio so far every
    few chunks, then the existing deterministic `TranscriptAnalyzer` flags
    filler words / repetition, exactly the same analyzer already used for
    full sessions, just run more often and on a growing prefix)
  - one FINAL evaluation once the client signals it is done: the complete
    recording is analyzed exactly like a session's audio-only material
    (Librosa `AudioFeature` + Whisper `SpeechIntelligenceFeature` +
    `TranscriptFeature`, via `AIOrchestrator.build_unified_features`),
    scored via the same `ScoringEngine`, and reasoned about via the same
    preliminary-review prompt shape used for slide/resume/video (see
    `prompts/preliminary_prompt.py`, stage="practice"), then persisted as a
    `PracticeEvaluationORM`.

Deliberately NOT built on `EvaluationWorkflowManager`'s state machine --
practice sessions are single-material (audio only, no slide/resume/video),
ephemeral, and repeatable, so forcing them through the 20-state
Presentation/Interview machine would add complexity with no benefit. This
manager is its own, much smaller, orchestrator with its own
`PracticeSessionState` (see `db/models.py`).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session as DBSession

from config import settings
from db.models import EvaluationMode, PracticeEvaluationORM, PracticeSessionORM, PracticeSessionState
from models.responses import ReasoningPayload
from providers.registry import provider_registry
from services.ai_orchestrator import AIOrchestrator, ai_orchestrator
from services.feature_fusion import FeatureFusionEngine
from services.prompt_builder import PromptBuilder, prompt_builder
from services.scoring_engine import ScoringEngine
from utils.logger import get_logger

logger = get_logger(__name__)

# Below this many words, a partial transcript is too short for the
# deterministic TranscriptAnalyzer's ratios (filler-word ratio, vocabulary
# diversity, ...) to mean anything -- skip tipping rather than emit noise.
_LIVE_TIP_MIN_WORDS = 8


class PracticeSessionNotFoundError(Exception):
    """Raised when an operation references a `PracticeSessionORM.id` that does not exist."""


class PracticeEvaluationNotReadyError(Exception):
    """Raised when the final evaluation is requested before the session has finished."""


class PracticeMaterialError(Exception):
    """
    Raised when a slide/resume upload doesn't fit the session -- wrong mode
    (e.g. a resume on a presentation-mode session), a mode conflict (already
    set to the other mode), or the session has already started streaming
    (material can only be attached beforehand).
    """


class PracticeSessionManager:
    """Orchestrates the live-practice lifecycle (Layers 1/2 -> Fusion -> Scoring -> Prompt -> Reasoning)."""

    def __init__(
        self,
        orchestrator: AIOrchestrator | None = None,
        fusion_engine: FeatureFusionEngine | None = None,
        scoring_engine: ScoringEngine | None = None,
        builder: PromptBuilder | None = None,
    ) -> None:
        self._orchestrator = orchestrator or ai_orchestrator
        self._fusion_engine = fusion_engine or FeatureFusionEngine()
        self._scoring_engine = scoring_engine or ScoringEngine()
        self._prompt_builder = builder or prompt_builder

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def get_session(self, db: DBSession, session_id: uuid.UUID) -> PracticeSessionORM:
        session = db.get(PracticeSessionORM, session_id)
        if session is None:
            raise PracticeSessionNotFoundError(f"No practice session with id={session_id}")
        return session

    def create_session(
        self, db: DBSession, mode: EvaluationMode | None = None, language: str = "vi"
    ) -> PracticeSessionORM:
        session = PracticeSessionORM(language=language, state=PracticeSessionState.CONNECTING, mode=mode)
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    def start_streaming(self, db: DBSession, session_id: uuid.UUID, audio_file_path: Path) -> PracticeSessionORM:
        """Marks the session STREAMING and records where its assembled audio is being written."""
        session = self.get_session(db, session_id)
        session.state = PracticeSessionState.STREAMING
        session.audio_file_path = str(audio_file_path)
        session.started_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(session)
        return session

    # ------------------------------------------------------------------
    # Optional material -- attached before streaming starts, analyzed
    # alongside the recorded audio at finalize time.
    # ------------------------------------------------------------------

    def attach_slide(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> PracticeSessionORM:
        session = self._validate_material_attach(db, session_id, EvaluationMode.PRESENTATION)
        session.slide_file_path = file_path
        db.commit()
        db.refresh(session)
        return session

    def attach_resume(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> PracticeSessionORM:
        session = self._validate_material_attach(db, session_id, EvaluationMode.INTERVIEW)
        session.resume_file_path = file_path
        db.commit()
        db.refresh(session)
        return session

    def _validate_material_attach(
        self, db: DBSession, session_id: uuid.UUID, required_mode: EvaluationMode
    ) -> PracticeSessionORM:
        session = self.get_session(db, session_id)
        if session.state is not PracticeSessionState.CONNECTING:
            raise PracticeMaterialError(
                f"Practice session {session_id} has already started streaming "
                f"(state={session.state.value}); material can only be attached beforehand."
            )
        if session.mode is not None and session.mode is not required_mode:
            raise PracticeMaterialError(
                f"Practice session {session_id} is in '{session.mode.value}' mode, "
                f"cannot attach {required_mode.value}-only material."
            )
        session.mode = required_mode
        return session

    def get_evaluation(self, db: DBSession, session_id: uuid.UUID) -> PracticeEvaluationORM:
        session = self.get_session(db, session_id)
        if session.evaluation is None:
            raise PracticeEvaluationNotReadyError(
                f"Practice session {session_id} has no final evaluation yet (state={session.state.value})."
            )
        return session.evaluation

    # ------------------------------------------------------------------
    # Live tips -- cheap, deterministic, called every few chunks
    # ------------------------------------------------------------------

    def partial_transcript_tip(self, transcript_text: str) -> str | None:
        """
        Cheap, deterministic "live tip" derived from the transcript-so-far
        (no LLM call -- see module docstring). Returns `None` if there is
        not enough transcript yet to say anything meaningful.
        """
        if len(transcript_text.split()) < _LIVE_TIP_MIN_WORDS:
            return None

        feature = self._orchestrator.analyze_transcript(transcript_text)
        if feature.filler_word_ratio > 0.08:
            return (
                "Bạn đang d\xf9ng kh\xe1 nhiều từ đệm "
                "(ừm, \xe0, kiểu như) -- thử n\xf3i chậm lại "
                "v\xe0 ngừng một nhịp thay v\xec ch\xeam từ đệm."
            )
        if feature.vocabulary_diversity < 0.4:
            return (
                "Từ vựng đang kh\xe1 lặp lại -- thử diễn "
                "đạt c\xf9ng một \xfd bằng những từ kh\xe1c nhau."
            )
        return "Đang n\xf3i tốt, tiếp tục duy tr\xec nhịp độ n\xe0y."

    # ------------------------------------------------------------------
    # Finalization -- the one LLM call in the whole flow
    # ------------------------------------------------------------------

    async def finalize(self, db: DBSession, session_id: uuid.UUID) -> PracticeSessionORM:
        """
        Run the full audio-only pipeline (Layer 1/2 -> Fusion -> Scoring ->
        Prompt -> Reasoning) on the complete recording and persist a
        `PracticeEvaluationORM`. Mirrors a session's single-material
        preliminary evaluation (see
        `EvaluationWorkflowManager._run_preliminary_evaluation`) but without
        any session-state-machine coupling.
        """
        session = self.get_session(db, session_id)

        audio_path = Path(session.audio_file_path) if session.audio_file_path else None
        if audio_path is None or not audio_path.exists() or audio_path.stat().st_size == 0:
            session.state = PracticeSessionState.FAILED
            session.error_message = "No audio was recorded before end_session."
            db.commit()
            db.refresh(session)
            return session

        session.state = PracticeSessionState.FINALIZING
        db.commit()

        slide_path = Path(session.slide_file_path) if session.slide_file_path else None
        resume_path = Path(session.resume_file_path) if session.resume_file_path else None

        try:
            features = await self._orchestrator.build_unified_features(
                audio_path=audio_path, slide_path=slide_path, resume_path=resume_path
            )
            derived = self._fusion_engine.fuse(features)
            scores = self._scoring_engine.score(features, derived)

            prompt = self._prompt_builder.build_preliminary("practice", features, scores, language=session.language)
            engine = provider_registry.get_reasoning_engine()
            reasoning: ReasoningPayload = await engine.generate_structured(prompt, ReasoningPayload)

            db.add(
                PracticeEvaluationORM(
                    practice_session_id=session.id,
                    **scores.model_dump(),
                    scoring_engine_version=settings.SCORING_ENGINE_VERSION,
                    **reasoning.model_dump(),
                    reasoning_engine_name=engine.name,
                    reasoning_engine_version=engine.version,
                )
            )
            if features.speech_intelligence is not None:
                session.transcript_so_far = features.speech_intelligence.transcript
            session.state = PracticeSessionState.COMPLETED
            session.ended_at = datetime.now(timezone.utc)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Practice session %s finalize failed", session.id)
            db.rollback()
            session = self.get_session(db, session_id)
            session.state = PracticeSessionState.FAILED
            session.error_message = str(exc)
            session.ended_at = datetime.now(timezone.utc)
            db.commit()

        db.refresh(session)
        return session


practice_session_manager = PracticeSessionManager()
