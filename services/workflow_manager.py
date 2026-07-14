"""
services/workflow_manager.py

`EvaluationWorkflowManager` — the sole orchestration layer for the
session-centric platform. Routers never call `AIOrchestrator`,
`FeatureFusionEngine`, `ScoringEngine`, `PromptBuilder`, or any reasoning
engine directly; they only ever call methods on this class, passing a
DB `Session` and an `AnalysisSession.id`.

Pipeline shape (per material, then a final synthesis pass):

    upload material -> analyze (Layer 1/2) -> PRELIMINARY score (Layer 4,
    material-only) -> PRELIMINARY reasoning (Layer 6, material-only) ->
    material marked EVALUATED, persisted as a `PreliminaryEvaluationORM`
    row and visible immediately via `GET /sessions/{id}/preliminary/{stage}`

Both the slide/resume branch and the video branch go through this same
per-material pipeline. Once video's preliminary evaluation completes, the
shared FINAL synthesis pass runs: Feature Fusion over the FULL merged
features, a full `ScoreBreakdown` (with `overall_score` recombined from the
two preliminary `overall_score`s — see `_combine_preliminary_overall_score`),
and a final reasoning pass that is given both preliminary `ReasoningPayload`s
as context so it reconciles them into one report instead of reasoning over
the raw data as if from scratch.

Responsibilities:
    * Validate and apply state-machine transitions (`session_state_machine.py`)
      before doing any work — an illegal transition never reaches an AI call.
    * Persist every stage's output immediately (mapped via `session_mappers.py`)
      so nothing is ever re-analyzed or re-scored on retry.
    * On any failure, record `state=FAILED` + `failed_state` (the state the
      session was IN when the failing work started — i.e. the precondition
      state of whichever method was running) + `error_message`. `retry()`
      resets to that state and re-invokes the matching method.

This module reuses the existing `ai_orchestrator` singleton (Whisper,
Librosa, MediaPipe, HSEmotion, PyMuPDF, python-pptx are all unchanged) —
nothing about Layer 1/2 is rewritten here, only recomposed around
persistence and partial-evaluation semantics.
"""

from __future__ import annotations

import asyncio
import uuid

from sqlalchemy.orm import Session as DBSession

from db.models import (
    AnalysisSession,
    EvaluationMode,
    EvaluationStage,
    PreliminaryEvaluationORM,
    ReportORM,
    ScoreResultORM,
    SessionState,
    UnifiedFeatureORM,
)
from models.features import ScoreBreakdown, UnifiedFeatureModel
from models.responses import ReasoningPayload
from providers.registry import provider_registry
from services import session_mappers as mappers
from services.ai_orchestrator import AIOrchestrator, ai_orchestrator
from services.feature_fusion import FeatureFusionEngine
from services.prompt_builder import PromptBuilder, PromptTask, prompt_builder
from services.scoring_engine import ScoringEngine
from services.session_state_machine import InvalidTransitionError, next_state
from utils.logger import get_logger
from utils.scoring_math import clamp_score, weighted_average

try:
    from config import settings

    _SCORING_ENGINE_VERSION = settings.SCORING_ENGINE_VERSION
    _FEATURE_FUSION_VERSION = settings.FEATURE_FUSION_VERSION
except AttributeError:  # pragma: no cover - defensive default if config lags behind
    _SCORING_ENGINE_VERSION = "1.0.0"
    _FEATURE_FUSION_VERSION = "1.0.0"

logger = get_logger(__name__)

# The precondition state each preliminary-evaluation stage starts from, and
# the state its failure is recorded/retried against (see module docstring).
_STAGE_ENTRY_STATE = {
    EvaluationStage.SLIDE: SessionState.SLIDE_ANALYZED,
    EvaluationStage.RESUME: SessionState.RESUME_ANALYZED,
    EvaluationStage.VIDEO: SessionState.VIDEO_ANALYZED,
}
# States whose retry entry point re-runs a Layer 1/2 analysis step.
_ANALYSIS_RETRY_STATES = {
    SessionState.SLIDE_ANALYZING: "slide",
    SessionState.RESUME_ANALYZING: "resume",
    SessionState.VIDEO_ANALYZING: "video",
}
# States whose retry entry point re-enters the final synthesis tail (cheap,
# deterministic except for the reasoning-engine call in REASONING).
_TAIL_RETRY_STATES = {
    SessionState.FEATURE_FUSION,
    SessionState.SCORING,
    SessionState.PROMPT_BUILDING,
    SessionState.REASONING,
}


class SessionNotFoundError(Exception):
    """Raised when an operation references an `AnalysisSession.id` that does not exist."""


class ReportNotReadyError(Exception):
    """Raised when `get_report` is called before the session has reached `COMPLETED`."""


class PreliminaryEvaluationNotReadyError(Exception):
    """Raised when a preliminary evaluation is requested for a stage that hasn't completed yet."""


class EvaluationWorkflowManager:
    """Orchestrates a session's evaluation pipeline end to end."""

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
    # Lookup / lifecycle
    # ------------------------------------------------------------------

    def get_session(self, db: DBSession, session_id: uuid.UUID) -> AnalysisSession:
        session = db.get(AnalysisSession, session_id)
        if session is None:
            raise SessionNotFoundError(f"No session with id={session_id}")
        return session

    def create_session(self, db: DBSession, mode: EvaluationMode, language: str = "vi") -> AnalysisSession:
        session = AnalysisSession(mode=mode, state=SessionState.EMPTY, language=language)
        db.add(session)
        db.commit()
        db.refresh(session)
        logger.info("Created session %s (mode=%s)", session.id, mode.value)
        return session

    def delete_session(self, db: DBSession, session_id: uuid.UUID) -> None:
        session = self.get_session(db, session_id)
        db.delete(session)  # cascades to every feature/score/report/preliminary row
        db.commit()
        logger.info("Deleted session %s", session_id)

    def get_report(self, db: DBSession, session_id: uuid.UUID) -> ReportORM:
        session = self.get_session(db, session_id)
        if session.state is not SessionState.COMPLETED or session.report is None:
            raise ReportNotReadyError(
                f"Session {session_id} is not complete yet (state={session.state.value})."
            )
        return session.report

    def get_preliminary_evaluation(
        self, db: DBSession, session_id: uuid.UUID, stage: EvaluationStage
    ) -> PreliminaryEvaluationORM:
        session = self.get_session(db, session_id)
        row = next((pe for pe in session.preliminary_evaluations if pe.stage is stage), None)
        if row is None:
            raise PreliminaryEvaluationNotReadyError(
                f"Session {session_id} has no preliminary evaluation for stage '{stage.value}' yet "
                f"(state={session.state.value})."
            )
        return row

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _transition(self, session: AnalysisSession, event: str) -> None:
        """Apply one state-machine event, raising if illegal. Caller commits."""
        session.state = next_state(session.mode, session.state, event)

    def _fail(self, db: DBSession, session: AnalysisSession, attempted_state: SessionState, exc: Exception) -> None:
        logger.exception("Session %s failed while entering %s", session.id, attempted_state.value)
        session.state = SessionState.FAILED
        session.failed_state = attempted_state
        session.error_message = str(exc)
        db.commit()

    # ------------------------------------------------------------------
    # Presentation branch
    # ------------------------------------------------------------------

    async def start_slide_upload(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> AnalysisSession:
        """
        Fast, synchronous half of slide upload: validate mode/state, record the
        file path, and move into `SLIDE_ANALYZING`. No AI work happens here —
        this is what lets a router return a response immediately and schedule
        `run_slide_analysis` as a `BackgroundTasks` job.
        """
        session = self.get_session(db, session_id)
        if session.mode is not EvaluationMode.PRESENTATION:
            raise InvalidTransitionError(session.state, "upload_slide", session.mode)

        self._transition(session, "upload_slide")
        session.slide_file_path = file_path
        db.commit()

        self._transition(session, "start_slide_analysis")
        db.commit()
        db.refresh(session)
        return session

    async def run_slide_analysis(self, db: DBSession, session_id: uuid.UUID) -> AnalysisSession:
        """
        Slow half of slide upload: run Layer 1/2 analysis and persist the
        result, then immediately run the slide's own preliminary score +
        reasoning pass (see `_run_preliminary_evaluation`).
        """
        session = self.get_session(db, session_id)
        if session.state is not SessionState.SLIDE_ANALYZING:
            raise InvalidTransitionError(session.state, "slide_analysis_done", session.mode)

        try:
            slide_feature = await asyncio.to_thread(self._orchestrator.extract_slide, session.slide_file_path)
            slide_analysis = await asyncio.to_thread(self._orchestrator.analyze_slide, slide_feature)
            db.add(mappers.slide_to_orm(session.id, slide_feature, slide_analysis))
            self._transition(session, "slide_analysis_done")
            db.commit()
        except Exception as exc:  # noqa: BLE001
            self._fail(db, session, SessionState.SLIDE_ANALYZING, exc)
            return session

        db.refresh(session)
        return await self._run_preliminary_evaluation(db, session, EvaluationStage.SLIDE)

    async def attach_slide(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> AnalysisSession:
        """Convenience wrapper running both halves of slide upload synchronously (used by tests and non-background callers)."""
        session = await self.start_slide_upload(db, session_id, file_path)
        if session.state is SessionState.FAILED:
            return session
        return await self.run_slide_analysis(db, session_id)

    # ------------------------------------------------------------------
    # Interview branch
    # ------------------------------------------------------------------

    async def start_resume_upload(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> AnalysisSession:
        """Fast, synchronous half of resume upload (mirrors `start_slide_upload`)."""
        session = self.get_session(db, session_id)
        if session.mode is not EvaluationMode.INTERVIEW:
            raise InvalidTransitionError(session.state, "upload_resume", session.mode)

        self._transition(session, "upload_resume")
        session.resume_file_path = file_path
        db.commit()

        self._transition(session, "start_resume_analysis")
        db.commit()
        db.refresh(session)
        return session

    async def run_resume_analysis(self, db: DBSession, session_id: uuid.UUID) -> AnalysisSession:
        """Slow half of resume upload (mirrors `run_slide_analysis`)."""
        session = self.get_session(db, session_id)
        if session.state is not SessionState.RESUME_ANALYZING:
            raise InvalidTransitionError(session.state, "resume_analysis_done", session.mode)

        try:
            resume_feature = await asyncio.to_thread(self._orchestrator.extract_resume, session.resume_file_path)
            resume_analysis = await asyncio.to_thread(self._orchestrator.analyze_resume, resume_feature)
            db.add(mappers.resume_to_orm(session.id, resume_feature, resume_analysis))
            self._transition(session, "resume_analysis_done")
            db.commit()
        except Exception as exc:  # noqa: BLE001
            self._fail(db, session, SessionState.RESUME_ANALYZING, exc)
            return session

        db.refresh(session)
        return await self._run_preliminary_evaluation(db, session, EvaluationStage.RESUME)

    async def attach_resume(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> AnalysisSession:
        """Convenience wrapper running both halves of resume upload synchronously (used by tests and non-background callers)."""
        session = await self.start_resume_upload(db, session_id, file_path)
        if session.state is SessionState.FAILED:
            return session
        return await self.run_resume_analysis(db, session_id)

    # ------------------------------------------------------------------
    # Shared tail: video upload -> preliminary evaluation -> final synthesis
    # ------------------------------------------------------------------

    async def start_video_upload(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> AnalysisSession:
        """Fast, synchronous half of video upload (mirrors `start_slide_upload`). Legal from either mode once `WAITING_FOR_VIDEO`."""
        session = self.get_session(db, session_id)

        self._transition(session, "upload_video")
        session.video_file_path = file_path
        db.commit()

        self._transition(session, "start_video_analysis")
        db.commit()
        db.refresh(session)
        return session

    async def run_video_analysis(self, db: DBSession, session_id: uuid.UUID) -> AnalysisSession:
        """
        Slow half of video upload: OpenCV + HSEmotion + MediaPipe + Whisper,
        all run once, then the video's own preliminary score + reasoning
        pass, which itself cascades into the final synthesis pass once done
        (see `_run_preliminary_evaluation`).
        """
        session = self.get_session(db, session_id)
        if session.state is not SessionState.VIDEO_ANALYZING:
            raise InvalidTransitionError(session.state, "video_analysis_done", session.mode)

        try:
            video_feature, emotion_feature, facemesh_feature = await asyncio.to_thread(
                self._orchestrator.analyze_video_vision, session.video_file_path
            )
            speech_intelligence = await asyncio.to_thread(
                self._orchestrator.analyze_speech, session.video_file_path
            )
            transcript_feature = await asyncio.to_thread(
                self._orchestrator.analyze_transcript, speech_intelligence.transcript
            )

            db.add(mappers.video_to_orm(session.id, video_feature))
            db.add(mappers.emotion_to_orm(session.id, emotion_feature))
            db.add(mappers.facemesh_to_orm(session.id, facemesh_feature))
            speech_row = mappers.speech_to_orm(session.id, speech_intelligence)
            db.add(speech_row)
            db.flush()  # assign speech_row.id before linking the transcript row to it
            db.add(mappers.transcript_to_orm(session.id, transcript_feature, speech_feature_id=speech_row.id))

            self._transition(session, "video_analysis_done")
            db.commit()
        except Exception as exc:  # noqa: BLE001
            self._fail(db, session, SessionState.VIDEO_ANALYZING, exc)
            return session

        db.refresh(session)
        return await self._run_preliminary_evaluation(db, session, EvaluationStage.VIDEO)

    async def attach_video(self, db: DBSession, session_id: uuid.UUID, file_path: str) -> AnalysisSession:
        """Convenience wrapper running both halves of video upload (+ preliminary + final synthesis) synchronously (used by tests)."""
        session = await self.start_video_upload(db, session_id, file_path)
        if session.state is SessionState.FAILED:
            return session
        return await self.run_video_analysis(db, session_id)

    # ------------------------------------------------------------------
    # Per-material preliminary evaluation (score + reasoning, one material only)
    # ------------------------------------------------------------------

    def _hydrate_stage_only_features(self, session: AnalysisSession, stage: EvaluationStage) -> UnifiedFeatureModel:
        """
        Build a `UnifiedFeatureModel` containing ONLY the fields relevant to
        `stage`, even if other materials have since been uploaded — this is
        what makes a "preliminary" review genuinely single-material (e.g.
        the video preliminary pass never sees the slide deck).
        """
        if stage is EvaluationStage.SLIDE:
            if session.slide_feature is None:
                return UnifiedFeatureModel()
            slide, slide_analysis = mappers.orm_to_slide(session.slide_feature)
            return UnifiedFeatureModel(slide=slide, slide_analysis=slide_analysis)

        if stage is EvaluationStage.RESUME:
            if session.resume_feature is None:
                return UnifiedFeatureModel()
            resume, resume_analysis = mappers.orm_to_resume(session.resume_feature)
            return UnifiedFeatureModel(resume=resume, resume_analysis=resume_analysis)

        # EvaluationStage.VIDEO
        return UnifiedFeatureModel(
            video=mappers.orm_to_video(session.video_feature) if session.video_feature else None,
            speech_intelligence=(
                mappers.orm_to_speech_intelligence(session.speech_feature) if session.speech_feature else None
            ),
            transcript=(
                mappers.orm_to_transcript(session.transcript_feature) if session.transcript_feature else None
            ),
            emotion=mappers.orm_to_emotion(session.emotion_feature) if session.emotion_feature else None,
            facemesh=mappers.orm_to_facemesh(session.face_mesh_feature) if session.face_mesh_feature else None,
        )

    async def _run_preliminary_evaluation(
        self, db: DBSession, session: AnalysisSession, stage: EvaluationStage
    ) -> AnalysisSession:
        """
        Run Scoring (material-only) -> Reasoning (material-only) for
        `stage`, persist the result as a `PreliminaryEvaluationORM` row, and
        advance the state machine. For SLIDE/RESUME this lands on
        `WAITING_FOR_VIDEO`; for VIDEO this cascades directly into
        `_run_final_synthesis`.
        """
        entry_state = _STAGE_ENTRY_STATE[stage]
        if session.state is not entry_state:
            raise InvalidTransitionError(session.state, f"start_{stage.value}_scoring", session.mode)

        try:
            self._transition(session, f"start_{stage.value}_scoring")
            db.commit()

            narrowed_features = self._hydrate_stage_only_features(session, stage)
            derived = self._fusion_engine.fuse(narrowed_features)
            scores = self._scoring_engine.score(narrowed_features, derived)

            self._transition(session, f"{stage.value}_scoring_done")
            db.commit()

            prompt = self._prompt_builder.build_preliminary(
                stage.value, narrowed_features, scores, language=session.language
            )
            engine = provider_registry.get_reasoning_engine()
            reasoning: ReasoningPayload = await engine.generate_structured(prompt, ReasoningPayload)

            db.add(
                PreliminaryEvaluationORM(
                    session_id=session.id,
                    stage=stage,
                    **scores.model_dump(),
                    scoring_engine_version=_SCORING_ENGINE_VERSION,
                    **reasoning.model_dump(),
                    reasoning_engine_name=engine.name,
                    reasoning_engine_version=engine.version,
                    prompt_text=prompt,
                )
            )
            self._transition(session, f"{stage.value}_reasoning_done")
            db.commit()
        except Exception as exc:  # noqa: BLE001
            self._fail(db, session, entry_state, exc)
            return session

        db.refresh(session)

        if stage is EvaluationStage.VIDEO:
            self._transition(session, "start_fusion")
            db.commit()
            db.refresh(session)
            return await self._run_final_synthesis(db, session)

        self._transition(session, "await_video")
        db.commit()
        db.refresh(session)
        return session

    # ------------------------------------------------------------------
    # Final synthesis: Feature Fusion -> Scoring -> Prompt -> Reasoning
    # ------------------------------------------------------------------

    def _hydrate_unified_features(self, session: AnalysisSession) -> UnifiedFeatureModel:
        """Rebuild the FULL `UnifiedFeatureModel` from every persisted feature row, without re-analyzing anything."""
        resume = analysis = None
        if session.resume_feature is not None:
            resume, analysis = mappers.orm_to_resume(session.resume_feature)

        slide = slide_analysis = None
        if session.slide_feature is not None:
            slide, slide_analysis = mappers.orm_to_slide(session.slide_feature)

        video = mappers.orm_to_video(session.video_feature) if session.video_feature else None
        speech_intel = (
            mappers.orm_to_speech_intelligence(session.speech_feature) if session.speech_feature else None
        )
        transcript = mappers.orm_to_transcript(session.transcript_feature) if session.transcript_feature else None
        emotion = mappers.orm_to_emotion(session.emotion_feature) if session.emotion_feature else None
        facemesh = mappers.orm_to_facemesh(session.face_mesh_feature) if session.face_mesh_feature else None

        return UnifiedFeatureModel(
            resume=resume,
            resume_analysis=analysis,
            slide=slide,
            slide_analysis=slide_analysis,
            video=video,
            speech_intelligence=speech_intel,
            transcript=transcript,
            emotion=emotion,
            facemesh=facemesh,
        )

    def _combine_preliminary_overall_score(self, session: AnalysisSession) -> int | None:
        """
        Combine the material-stage and video-stage preliminary
        `overall_score`s into the session's final `overall_score` (per the
        product decision to synthesize from the two checkpoints already
        shown to the user, rather than recompute a single monolithic score
        from scratch). Equal-weighted; renormalizes if only one is present.
        Returns `None` if neither preliminary evaluation exists yet
        (should not happen in the normal flow, but keeps this defensive).
        """
        components = {
            pe.stage.value: (float(pe.overall_score), 1.0) for pe in session.preliminary_evaluations
        }
        if not components:
            return None
        return clamp_score(weighted_average(components))

    def _prior_reasoning_payloads(self, session: AnalysisSession) -> dict[str, ReasoningPayload]:
        """Rebuild each persisted `PreliminaryEvaluationORM` row's reasoning half as a `ReasoningPayload`."""
        return {
            pe.stage.value: ReasoningPayload(
                strengths=pe.strengths,
                weaknesses=pe.weaknesses,
                improvement_plan=pe.improvement_plan,
                presentation_feedback=pe.presentation_feedback,
                interview_feedback=pe.interview_feedback,
                interview_questions=pe.interview_questions,
                suggestions=pe.suggestions,
            )
            for pe in session.preliminary_evaluations
        }

    async def _run_final_synthesis(self, db: DBSession, session: AnalysisSession) -> AnalysisSession:
        """
        Run Feature Fusion -> Scoring -> Prompt Building -> Reasoning over
        the FULL merged features, reconciling the preliminary evaluations
        into one final report. Safe to call again on retry: each stage is
        skipped if its output row already exists, except Prompt Building
        (ephemeral, always rebuilt) and Reasoning (re-run only if no
        `ReportORM` exists yet).
        """
        try:
            features = self._hydrate_unified_features(session)

            if session.unified_feature is None:
                if session.state is SessionState.VIDEO_EVALUATED:
                    self._transition(session, "start_fusion")
                    db.commit()
                derived = self._fusion_engine.fuse(features)
                db.add(
                    UnifiedFeatureORM(
                        session_id=session.id,
                        **derived.model_dump(),
                        snapshot_json=features.model_dump(mode="json"),
                        fusion_engine_version=_FEATURE_FUSION_VERSION,
                    )
                )
                self._transition(session, "fusion_done")
                db.commit()
                db.refresh(session)
            else:
                derived = self._fusion_engine.fuse(features)  # recompute in-memory only; row already persisted

            if session.score_result is None:
                scores = self._scoring_engine.score(features, derived)
                combined_overall = self._combine_preliminary_overall_score(session)
                if combined_overall is not None:
                    scores = scores.model_copy(update={"overall_score": combined_overall})
                db.add(
                    ScoreResultORM(
                        session_id=session.id,
                        **scores.model_dump(),
                        scoring_engine_version=_SCORING_ENGINE_VERSION,
                    )
                )
                self._transition(session, "scoring_done")
                db.commit()
                db.refresh(session)
            else:
                row = session.score_result
                scores = ScoreBreakdown(
                    resume_score=row.resume_score,
                    slide_score=row.slide_score,
                    speech_score=row.speech_score,
                    transcript_score=row.transcript_score,
                    emotion_score=row.emotion_score,
                    eye_contact_score=row.eye_contact_score,
                    voice_confidence_score=row.voice_confidence_score,
                    presentation_score=row.presentation_score,
                    communication_score=row.communication_score,
                    overall_score=row.overall_score,
                )

            if session.report is None:
                if session.state is SessionState.SCORING:
                    self._transition(session, "scoring_done")
                    db.commit()
                prior_evaluations = self._prior_reasoning_payloads(session)
                prompt = self._prompt_builder.build(
                    PromptTask.EVALUATE,
                    features,
                    scores,
                    derived,
                    language=session.language,
                    prior_evaluations=prior_evaluations,
                )
                if session.state is SessionState.PROMPT_BUILDING:
                    self._transition(session, "prompt_built")
                    db.commit()

                # Resolved via config/providers.yaml (`reasoning_engine: gemini` by
                # default) rather than importing a concrete engine directly, so
                # swapping in Claude/GPT/a local/fine-tuned model later means
                # registering it in providers/registry.py and changing the
                # config value — this method never needs to change.
                engine = provider_registry.get_reasoning_engine()
                reasoning: ReasoningPayload = await engine.generate_structured(prompt, ReasoningPayload)
                db.add(
                    ReportORM(
                        session_id=session.id,
                        **reasoning.model_dump(),
                        reasoning_engine_name=engine.name,
                        reasoning_engine_version=engine.version,
                        prompt_text=prompt,
                        raw_response=None,
                    )
                )
                self._transition(session, "reasoning_done")
                db.commit()

            if session.state is SessionState.REPORT_GENERATED:
                self._transition(session, "finalize")
                db.commit()

            db.refresh(session)
            return session
        except Exception as exc:  # noqa: BLE001
            self._fail(db, session, session.state, exc)
            return session

    # ------------------------------------------------------------------
    # Retry
    # ------------------------------------------------------------------

    async def retry(self, db: DBSession, session_id: uuid.UUID) -> AnalysisSession:
        """
        Retry a `FAILED` session from the exact stage it failed at.

        Layer 1/2 analysis failures (`*_ANALYZING`) are retried against the
        already-uploaded file (never re-uploaded). Preliminary-evaluation
        failures (`*_ANALYZED`, i.e. the material finished analysis but its
        scoring/reasoning pass failed) re-run just that pass. Final-synthesis
        failures (Fusion/Scoring/Prompt/Reasoning) resume via
        `_run_final_synthesis`, which skips any stage whose output row was
        already persisted before the failure occurred.
        """
        session = self.get_session(db, session_id)
        if session.state is not SessionState.FAILED or session.failed_state is None:
            raise InvalidTransitionError(session.state, "retry", session.mode)

        failed_state = session.failed_state
        session.state = failed_state
        session.error_message = None
        session.failed_state = None
        db.commit()

        if failed_state is SessionState.SLIDE_ANALYZING:
            return await self.run_slide_analysis(db, session_id)
        if failed_state is SessionState.RESUME_ANALYZING:
            return await self.run_resume_analysis(db, session_id)
        if failed_state is SessionState.VIDEO_ANALYZING:
            return await self.run_video_analysis(db, session_id)

        if failed_state is SessionState.SLIDE_ANALYZED:
            db.refresh(session)
            return await self._run_preliminary_evaluation(db, session, EvaluationStage.SLIDE)
        if failed_state is SessionState.RESUME_ANALYZED:
            db.refresh(session)
            return await self._run_preliminary_evaluation(db, session, EvaluationStage.RESUME)
        if failed_state is SessionState.VIDEO_ANALYZED:
            db.refresh(session)
            return await self._run_preliminary_evaluation(db, session, EvaluationStage.VIDEO)

        if failed_state in _TAIL_RETRY_STATES:
            db.refresh(session)
            return await self._run_final_synthesis(db, session)

        raise InvalidTransitionError(session.state, "retry", session.mode)


# Module-level singleton, mirrors `ai_orchestrator` / `gemini_service`.
workflow_manager = EvaluationWorkflowManager()
