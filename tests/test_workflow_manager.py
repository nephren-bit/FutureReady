"""
Integration tests for services/workflow_manager.py against an in-memory
SQLite database. All Layer 1/2 AI calls (extractors/analyzers/Gemini) are
mocked here — this suite verifies orchestration, persistence, and state
transitions, not the AI models themselves (those are covered by
test_analyzers.py / test_extractors.py / test_scoring_engine.py).
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from db.base import Base
import db.models as dbm
from models.features import (
    EmotionFeature,
    FaceMeshFeature,
    ResumeAnalysisFeature,
    ResumeFeature,
    SlideAnalysisFeature,
    SlideFeature,
    SpeechIntelligenceFeature,
    TranscriptFeature,
    VideoFeature,
)
from models.responses import RecommendationItem, RecommendationPayload, ReasoningPayload
from services.session_state_machine import InvalidTransitionError
from services.workflow_manager import (
    EvaluationWorkflowManager,
    PreliminaryEvaluationNotReadyError,
    ReportNotReadyError,
    SessionNotFoundError,
)


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with DBSession(engine) as session:
        yield session


@pytest.fixture()
def mock_orchestrator(sample_slide_feature: SlideFeature):
    orchestrator = AsyncMock()
    # Layer 1/2 calls in the manager are sync and dispatched via asyncio.to_thread,
    # so the mocked methods themselves must be plain (non-async) callables.
    orchestrator.extract_slide = lambda path: sample_slide_feature
    orchestrator.analyze_slide = lambda feature: SlideAnalysisFeature(
        text_density_score=0.5,
        visual_richness_score=0.6,
        consistency_score=0.7,
        notes_usage_ratio=0.4,
        title_presence_ratio=1.0,
        structure_balance_score=0.8,
    )
    orchestrator.extract_resume = lambda path: ResumeFeature(
        text="dummy", page_count=1, word_count=10, avg_words_per_page=10.0
    )
    orchestrator.analyze_resume = lambda feature: ResumeAnalysisFeature(
        keyword_density=0.5,
        action_verb_ratio=0.5,
        quantified_achievement_count=2,
        section_completeness=0.8,
        contact_info_present=True,
        length_appropriateness=0.9,
    )
    orchestrator.analyze_video_vision = lambda path: (
        VideoFeature(
            fps=30.0, frame_count=900, duration_sec=30.0, sampled_frame_count=60,
            brightness_mean=120.0, contrast_mean=40.0,
        ),
        EmotionFeature(dominant_emotion="neutral", emotion_consistency=0.6),
        FaceMeshFeature(frames_analyzed=60, faces_detected_ratio=0.9, eye_contact_ratio=0.7),
    )
    orchestrator.analyze_speech = lambda path: SpeechIntelligenceFeature(
        transcript="Hello and welcome to this presentation about our results.",
        language="en",
        average_confidence=0.9,
        duration_sec=30.0,
        words_per_minute=120.0,
        word_count=10,
    )
    orchestrator.analyze_transcript = lambda text: TranscriptFeature(
        word_count=10, sentence_count=1, vocabulary_diversity=0.8, has_opening=True, has_conclusion=True
    )
    return orchestrator


def _dispatching_generate_structured(reasoning_payload: ReasoningPayload, recommendation_payload: RecommendationPayload):
    """
    A `generate_structured(prompt, response_model)` fake that returns the
    right fixture based on `response_model`, since a session's pipeline
    calls it with three different schemas (preliminary `ReasoningPayload`,
    final `ReasoningPayload`, and `RecommendationPayload`) over its
    lifetime — a single fixed `return_value` mock can't serve all three.
    """

    async def _fake(prompt: str, response_model: type):
        if response_model is RecommendationPayload:
            return recommendation_payload
        return reasoning_payload

    return _fake


@pytest.fixture()
def manager(mock_orchestrator, monkeypatch):
    mgr = EvaluationWorkflowManager(orchestrator=mock_orchestrator)
    fake_reasoning = ReasoningPayload(
        strengths=["Clear structure"],
        weaknesses=["Could improve pacing"],
        improvement_plan=["Practice pausing between points"],
        presentation_feedback="Solid overall delivery.",
    )
    monkeypatch.setattr(
        "services.lmstudio_service.lmstudio_service.generate_structured",
        AsyncMock(side_effect=_dispatching_generate_structured(fake_reasoning, RecommendationPayload())),
    )
    return mgr


class TestPresentationHappyPath:
    async def test_full_pipeline_reaches_completed(self, db_session, manager) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        assert session.state == dbm.SessionState.EMPTY

        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        assert session.state == dbm.SessionState.WAITING_FOR_VIDEO
        assert session.slide_feature is not None

        session = await manager.attach_video(db_session, session.id, "/tmp/fake.mp4")
        assert session.state == dbm.SessionState.COMPLETED
        assert session.error_message is None

        report = manager.get_report(db_session, session.id)
        assert report.presentation_feedback == "Solid overall delivery."
        assert report.reasoning_engine_name == "lmstudio"
        assert session.score_result.overall_score >= 0
        assert session.unified_feature is not None

    async def test_report_not_ready_before_completion(self, db_session, manager) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        with pytest.raises(ReportNotReadyError):
            manager.get_report(db_session, session.id)

    async def test_wrong_mode_upload_rejected(self, db_session, manager) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.INTERVIEW)
        with pytest.raises(InvalidTransitionError):
            await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")


class TestInterviewHappyPath:
    async def test_full_pipeline_reaches_completed(self, db_session, manager) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.INTERVIEW)
        session = await manager.attach_resume(db_session, session.id, "/tmp/fake.pdf")
        assert session.state == dbm.SessionState.WAITING_FOR_VIDEO

        session = await manager.attach_video(db_session, session.id, "/tmp/fake.mp4")
        assert session.state == dbm.SessionState.COMPLETED


class TestPreliminaryEvaluation:
    """
    Covers the new "preliminary score + reasoning per material" pipeline:
    each material gets its own quick review as soon as it finishes analysis
    (visible via `get_preliminary_evaluation` / the dedicated endpoint),
    well before the rest of the session's materials are uploaded, and the
    final `overall_score` is a combination of the preliminary scores rather
    than a fresh recomputation from the merged feature set.
    """

    async def test_slide_preliminary_evaluation_persisted_before_video(self, db_session, manager) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        assert session.state == dbm.SessionState.WAITING_FOR_VIDEO

        prelim = manager.get_preliminary_evaluation(db_session, session.id, dbm.EvaluationStage.SLIDE)
        assert prelim.stage == dbm.EvaluationStage.SLIDE
        assert 0 <= prelim.overall_score <= 100
        assert prelim.reasoning_engine_name == "lmstudio"
        assert prelim.presentation_feedback == "Solid overall delivery."

        # The video hasn't been uploaded yet, so its preliminary evaluation doesn't exist.
        with pytest.raises(PreliminaryEvaluationNotReadyError):
            manager.get_preliminary_evaluation(db_session, session.id, dbm.EvaluationStage.VIDEO)

    async def test_resume_preliminary_evaluation_persisted_before_video(self, db_session, manager) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.INTERVIEW)
        session = await manager.attach_resume(db_session, session.id, "/tmp/fake.pdf")
        assert session.state == dbm.SessionState.WAITING_FOR_VIDEO

        prelim = manager.get_preliminary_evaluation(db_session, session.id, dbm.EvaluationStage.RESUME)
        assert prelim.stage == dbm.EvaluationStage.RESUME
        assert 0 <= prelim.overall_score <= 100

    async def test_both_preliminary_evaluations_persisted_and_combined_at_completion(
        self, db_session, manager
    ) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        session = await manager.attach_video(db_session, session.id, "/tmp/fake.mp4")
        assert session.state == dbm.SessionState.COMPLETED

        assert len(session.preliminary_evaluations) == 2
        slide_prelim = manager.get_preliminary_evaluation(db_session, session.id, dbm.EvaluationStage.SLIDE)
        video_prelim = manager.get_preliminary_evaluation(db_session, session.id, dbm.EvaluationStage.VIDEO)

        # The final overall_score is an equal-weighted combination of the two
        # preliminary overall_scores (per the product decision), not a fresh
        # ScoringEngine.score() recomputation from the merged feature set.
        expected = round((slide_prelim.overall_score + video_prelim.overall_score) / 2)
        assert session.score_result.overall_score == expected

    async def test_get_preliminary_evaluation_unknown_session_raises(self, db_session, manager) -> None:
        with pytest.raises(SessionNotFoundError):
            manager.get_preliminary_evaluation(db_session, uuid.uuid4(), dbm.EvaluationStage.SLIDE)

    async def test_preliminary_evaluation_not_ready_before_any_upload(self, db_session, manager) -> None:
        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        with pytest.raises(PreliminaryEvaluationNotReadyError):
            manager.get_preliminary_evaluation(db_session, session.id, dbm.EvaluationStage.SLIDE)


class TestRecommendationEngine:
    """
    Covers the Recommendation Engine (`RECOMMENDING` state, runs right after
    the final report exists): learning-resource picks are generated from
    the seeded `learning_resources` catalog, invalid/hallucinated picks are
    dropped, and an unseeded (empty) catalog degrades gracefully rather
    than blocking session completion.
    """

    def _seed_resources(self, db_session) -> list[dbm.LearningResourceORM]:
        resources = [
            dbm.LearningResourceORM(
                title="The skill of self confidence",
                url="https://example.com/confidence-talk",
                resource_type="video",
                platform="Youtube",
                language="en",
                skill_tags=["confidence"],
                category_label="Cải thiện độ tự tin",
            ),
            dbm.LearningResourceORM(
                title="How to speak so that people want to listen",
                url="https://example.com/speaking-talk",
                resource_type="video",
                platform="Youtube",
                language="en",
                skill_tags=["speaking"],
                category_label="Kỹ năng nói",
            ),
        ]
        for resource in resources:
            db_session.add(resource)
        db_session.commit()
        for resource in resources:
            db_session.refresh(resource)
        return resources

    async def test_recommendations_generated_after_completion(self, db_session, mock_orchestrator, monkeypatch) -> None:
        resources = self._seed_resources(db_session)
        fake_reasoning = ReasoningPayload(presentation_feedback="Solid overall delivery.")
        fake_recommendations = RecommendationPayload(
            picks=[
                RecommendationItem(
                    resource_id=str(resources[0].id),
                    rationale="Your confidence score was low; this talk addresses that directly.",
                    target_skill_tags=["confidence"],
                )
            ]
        )
        monkeypatch.setattr(
            "services.lmstudio_service.lmstudio_service.generate_structured",
            AsyncMock(side_effect=_dispatching_generate_structured(fake_reasoning, fake_recommendations)),
        )
        manager = EvaluationWorkflowManager(orchestrator=mock_orchestrator)

        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        session = await manager.attach_video(db_session, session.id, "/tmp/fake.mp4")
        assert session.state == dbm.SessionState.COMPLETED

        recs = manager.get_recommendations(db_session, session.id)
        assert len(recs) == 1
        assert recs[0].rank == 1
        assert recs[0].resource_id == resources[0].id
        assert recs[0].generated_by == "llm"
        assert recs[0].reasoning_engine_name == "lmstudio"

    async def test_invalid_resource_id_pick_is_dropped(self, db_session, mock_orchestrator, monkeypatch) -> None:
        self._seed_resources(db_session)
        fake_reasoning = ReasoningPayload(presentation_feedback="Solid overall delivery.")
        fake_recommendations = RecommendationPayload(
            picks=[
                RecommendationItem(
                    resource_id=str(uuid.uuid4()),  # does not match any seeded resource
                    rationale="Hallucinated pick.",
                    target_skill_tags=["confidence"],
                )
            ]
        )
        monkeypatch.setattr(
            "services.lmstudio_service.lmstudio_service.generate_structured",
            AsyncMock(side_effect=_dispatching_generate_structured(fake_reasoning, fake_recommendations)),
        )
        manager = EvaluationWorkflowManager(orchestrator=mock_orchestrator)

        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        session = await manager.attach_video(db_session, session.id, "/tmp/fake.mp4")
        assert session.state == dbm.SessionState.COMPLETED
        assert manager.get_recommendations(db_session, session.id) == []

    async def test_empty_catalog_does_not_block_completion(self, db_session, manager) -> None:
        # No learning_resources seeded at all (the `manager` fixture's DB is empty).
        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        session = await manager.attach_video(db_session, session.id, "/tmp/fake.mp4")
        assert session.state == dbm.SessionState.COMPLETED
        assert manager.get_recommendations(db_session, session.id) == []

    async def test_get_recommendations_unknown_session_raises(self, db_session, manager) -> None:
        with pytest.raises(SessionNotFoundError):
            manager.get_recommendations(db_session, uuid.uuid4())


class TestFailureAndRetry:
    async def test_slide_analysis_failure_then_retry_succeeds(self, db_session, mock_orchestrator, monkeypatch) -> None:
        calls = {"count": 0}
        original_extract_slide = mock_orchestrator.extract_slide

        def flaky_extract_slide(path):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("Simulated PPTX parse failure")
            return original_extract_slide(path)

        mock_orchestrator.extract_slide = flaky_extract_slide
        manager = EvaluationWorkflowManager(orchestrator=mock_orchestrator)
        monkeypatch.setattr(
            "services.lmstudio_service.lmstudio_service.generate_structured",
            AsyncMock(side_effect=_dispatching_generate_structured(ReasoningPayload(), RecommendationPayload())),
        )

        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        assert session.state == dbm.SessionState.FAILED
        assert session.failed_state == dbm.SessionState.SLIDE_ANALYZING
        assert calls["count"] == 1

        session = await manager.retry(db_session, session.id)
        assert session.state == dbm.SessionState.WAITING_FOR_VIDEO
        assert calls["count"] == 2

    async def test_preliminary_evaluation_failure_then_retry_succeeds(
        self, db_session, mock_orchestrator, monkeypatch
    ) -> None:
        """
        A failure during the slide's own preliminary score/reasoning pass
        (e.g. the reasoning engine call itself) should be retried from
        SLIDE_ANALYZED — re-running only the preliminary pass, not
        re-extracting/re-analyzing the slide deck.
        """
        calls = {"count": 0}
        real_reasoning = ReasoningPayload(presentation_feedback="Solid overall delivery.")

        async def flaky_generate_structured(prompt, schema):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("Simulated reasoning-engine timeout")
            if schema is RecommendationPayload:
                return RecommendationPayload()
            return real_reasoning

        monkeypatch.setattr(
            "services.lmstudio_service.lmstudio_service.generate_structured",
            AsyncMock(side_effect=flaky_generate_structured),
        )
        manager = EvaluationWorkflowManager(orchestrator=mock_orchestrator)

        session = manager.create_session(db_session, dbm.EvaluationMode.PRESENTATION)
        session = await manager.attach_slide(db_session, session.id, "/tmp/fake.pptx")
        assert session.state == dbm.SessionState.FAILED
        assert session.failed_state == dbm.SessionState.SLIDE_ANALYZED

        session = await manager.retry(db_session, session.id)
        assert session.state == dbm.SessionState.WAITING_FOR_VIDEO
        prelim = manager.get_preliminary_evaluation(db_session, session.id, dbm.EvaluationStage.SLIDE)
        assert prelim.presentation_feedback == "Solid overall delivery."
