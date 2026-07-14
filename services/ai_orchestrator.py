"""
services/ai_orchestrator.py

The AI Orchestrator is the single Facade the routers talk to. It wires
together every Layer 1 extractor and Layer 2 analyzer (constructor-injected,
each conforming to `BaseExtractor`/`BaseAnalyzer`) and drives them through
the full pipeline:

    Extraction (L1) -> AI Vision & Speech Intelligence + deterministic
    analysis (L2) -> Feature Fusion (L3) -> Deterministic Scoring (L4) ->
    Prompt Building (L5) -> Gemini Reasoning (L6)

Routers never import extractors, analyzers, or `GeminiService` directly —
they depend only on this orchestrator and on `models.features`. To add a new
extractor/analyzer, inject an alternate instance via the constructor (or add
a new constructor parameter for a genuinely new modality); no pipeline
method that already exists needs to change.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from analyzers.cv_analyzer import ResumeAnalyzer
from analyzers.emotion_analyzer import EmotionAnalyzer
from analyzers.facemesh_analyzer import FaceMeshAnalyzer
from analyzers.slide_analyzer import SlideAnalyzer
from analyzers.speech_analyzer import SpeechAnalyzer
from analyzers.transcript_analyzer import TranscriptAnalyzer
from extractors.audio_extractor import AudioExtractor
from extractors.pdf_extractor import PDFExtractor
from extractors.ppt_extractor import PPTExtractor
from extractors.video_extractor import VideoExtractor
from models.features import (
    AudioFeature,
    EmotionFeature,
    FaceMeshFeature,
    ResumeAnalysisFeature,
    ResumeFeature,
    SlideAnalysisFeature,
    SlideFeature,
    SpeechIntelligenceFeature,
    TranscriptFeature,
    UnifiedFeatureModel,
    VideoFeature,
)
from models.responses import EvaluationReport, ReasoningPayload
from services.feature_fusion import FeatureFusionEngine
from services.gemini_service import GeminiService, gemini_service
from services.prompt_builder import PromptBuilder, PromptTask, prompt_builder
from services.scoring_engine import ScoringEngine
from utils.logger import get_logger

logger = get_logger(__name__)


class AIOrchestrator:
    """Coordinates the full FutureReady pipeline across all six layers."""

    def __init__(
        self,
        pdf_extractor: PDFExtractor | None = None,
        ppt_extractor: PPTExtractor | None = None,
        audio_extractor: AudioExtractor | None = None,
        video_extractor: VideoExtractor | None = None,
        resume_analyzer: ResumeAnalyzer | None = None,
        slide_analyzer: SlideAnalyzer | None = None,
        transcript_analyzer: TranscriptAnalyzer | None = None,
        speech_analyzer: SpeechAnalyzer | None = None,
        emotion_analyzer: EmotionAnalyzer | None = None,
        facemesh_analyzer: FaceMeshAnalyzer | None = None,
        fusion_engine: FeatureFusionEngine | None = None,
        scoring_engine: ScoringEngine | None = None,
        builder: PromptBuilder | None = None,
        gemini: GeminiService | None = None,
    ) -> None:
        self._pdf_extractor = pdf_extractor or PDFExtractor()
        self._ppt_extractor = ppt_extractor or PPTExtractor()
        self._audio_extractor = audio_extractor or AudioExtractor()
        self._video_extractor = video_extractor or VideoExtractor()

        self._resume_analyzer = resume_analyzer or ResumeAnalyzer()
        self._slide_analyzer = slide_analyzer or SlideAnalyzer()
        self._transcript_analyzer = transcript_analyzer or TranscriptAnalyzer()
        self._speech_analyzer = speech_analyzer or SpeechAnalyzer()
        self._emotion_analyzer = emotion_analyzer or EmotionAnalyzer()
        self._facemesh_analyzer = facemesh_analyzer or FaceMeshAnalyzer()

        self._fusion_engine = fusion_engine or FeatureFusionEngine()
        self._scoring_engine = scoring_engine or ScoringEngine()
        self._prompt_builder = builder or prompt_builder
        self._gemini = gemini or gemini_service

    # ------------------------------------------------------------------
    # Layer 1 — standalone extraction (used by /extract/* endpoints)
    # ------------------------------------------------------------------

    def extract_resume(self, file_path: Path) -> ResumeFeature:
        """Run only Layer 1 extraction on a resume PDF."""
        return self._pdf_extractor.extract(file_path)

    def extract_slide(self, file_path: Path) -> SlideFeature:
        """Run only Layer 1 extraction on a presentation PPTX."""
        return self._ppt_extractor.extract(file_path)

    def extract_audio(self, file_path: Path) -> AudioFeature:
        """Run only Layer 1 extraction on an audio recording."""
        return self._audio_extractor.extract(file_path)

    def extract_video(self, file_path: Path) -> VideoFeature:
        """Run only Layer 1 extraction on a presentation video."""
        return self._video_extractor.extract(file_path)

    # ------------------------------------------------------------------
    # Layer 2 — standalone analysis (used by /analyze/* endpoints)
    # ------------------------------------------------------------------

    def analyze_resume(self, resume: ResumeFeature) -> ResumeAnalysisFeature:
        """Run the deterministic resume-content analyzer."""
        return self._resume_analyzer.analyze(resume)

    def analyze_slide(self, slide: SlideFeature) -> SlideAnalysisFeature:
        """Run the deterministic slide-design analyzer."""
        return self._slide_analyzer.analyze(slide)

    def analyze_transcript(self, transcript_text: str) -> TranscriptFeature:
        """Run the deterministic transcript linguistic analyzer."""
        return self._transcript_analyzer.analyze(transcript_text)

    def analyze_speech(self, audio_path: Path) -> SpeechIntelligenceFeature:
        """Run the Whisper-based speech intelligence analyzer."""
        return self._speech_analyzer.analyze(audio_path)

    def analyze_video_vision(
        self, video_path: Path
    ) -> tuple[VideoFeature, EmotionFeature, FaceMeshFeature]:
        """
        Run Layer 1 video extraction plus both vision analyzers in one pass,
        decoding the video only once and sharing the sampled frames.
        """
        video_feature, frames, timestamps = self._video_extractor.extract_with_frames(video_path)
        frames_with_timestamps = list(zip(frames, timestamps))
        emotion_feature = self._emotion_analyzer.analyze(frames_with_timestamps)
        facemesh_feature = self._facemesh_analyzer.analyze(frames_with_timestamps)
        return video_feature, emotion_feature, facemesh_feature

    # ------------------------------------------------------------------
    # Full Mode A pipeline: raw files -> UnifiedFeatureModel
    # ------------------------------------------------------------------

    async def build_unified_features(
        self,
        resume_path: Path | None = None,
        slide_path: Path | None = None,
        audio_path: Path | None = None,
        video_path: Path | None = None,
    ) -> UnifiedFeatureModel:
        """
        Run Layers 1-2 across every supplied file and assemble a
        `UnifiedFeatureModel`. Each material is optional; any subset may be
        supplied. Blocking extraction/analysis work is dispatched to worker
        threads so the event loop stays responsive.

        Args:
            resume_path: Path to a resume PDF, if supplied.
            slide_path: Path to a presentation PPTX, if supplied.
            audio_path: Path to a standalone speech recording, if supplied.
            video_path: Path to a presentation video, if supplied.

        Returns:
            A `UnifiedFeatureModel` populated with every feature that could
            be derived from the supplied materials.
        """
        resume_feature: ResumeFeature | None = None
        resume_analysis: ResumeAnalysisFeature | None = None
        slide_feature: SlideFeature | None = None
        slide_analysis: SlideAnalysisFeature | None = None
        audio_feature: AudioFeature | None = None
        speech_intelligence: SpeechIntelligenceFeature | None = None
        transcript_feature: TranscriptFeature | None = None
        video_feature: VideoFeature | None = None
        emotion_feature: EmotionFeature | None = None
        facemesh_feature: FaceMeshFeature | None = None

        if resume_path is not None:
            resume_feature = await asyncio.to_thread(self.extract_resume, resume_path)
            resume_analysis = await asyncio.to_thread(self.analyze_resume, resume_feature)

        if slide_path is not None:
            slide_feature = await asyncio.to_thread(self.extract_slide, slide_path)
            slide_analysis = await asyncio.to_thread(self.analyze_slide, slide_feature)

        if audio_path is not None:
            audio_feature = await asyncio.to_thread(self.extract_audio, audio_path)
            speech_intelligence = await asyncio.to_thread(self.analyze_speech, audio_path)
            transcript_feature = await asyncio.to_thread(
                self.analyze_transcript, speech_intelligence.transcript
            )

        if video_path is not None:
            video_feature, emotion_feature, facemesh_feature = await asyncio.to_thread(
                self.analyze_video_vision, video_path
            )
            # If no standalone speech file was given, transcribe the video's
            # own audio track so transcript-based scoring still runs.
            if audio_path is None:
                try:
                    speech_intelligence = await asyncio.to_thread(self.analyze_speech, video_path)
                    transcript_feature = await asyncio.to_thread(
                        self.analyze_transcript, speech_intelligence.transcript
                    )
                except RuntimeError:
                    logger.warning(
                        "Could not extract a speech track from the video; "
                        "transcript-based scoring will be skipped."
                    )

        return UnifiedFeatureModel(
            resume=resume_feature,
            slide=slide_feature,
            audio=audio_feature,
            video=video_feature,
            speech_intelligence=speech_intelligence,
            transcript=transcript_feature,
            emotion=emotion_feature,
            facemesh=facemesh_feature,
            resume_analysis=resume_analysis,
            slide_analysis=slide_analysis,
        )

    # ------------------------------------------------------------------
    # Layers 3-6: UnifiedFeatureModel -> EvaluationReport
    # ------------------------------------------------------------------

    async def evaluate(self, features: UnifiedFeatureModel, language: str = "vi") -> EvaluationReport:
        """
        Run Feature Fusion, Deterministic Scoring, Prompt Building, and
        Gemini Reasoning on an already-assembled `UnifiedFeatureModel`.

        This is the shared tail of both evaluation modes: Mode A calls
        `build_unified_features(...)` first; Mode B receives the
        `UnifiedFeatureModel` directly from the client and calls this
        method immediately.
        """
        derived = self._fusion_engine.fuse(features)
        scores = self._scoring_engine.score(features, derived)

        prompt = self._prompt_builder.build(
            PromptTask.EVALUATE, features, scores, derived, language=language
        )
        reasoning = await self._gemini.generate_structured(prompt, ReasoningPayload)

        return EvaluationReport.from_parts(scores, derived, reasoning, features)


# Module-level singleton, reused across requests (mirrors `gemini_service`).
ai_orchestrator = AIOrchestrator()
