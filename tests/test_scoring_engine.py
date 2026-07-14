"""Unit tests for services/scoring_engine.py (Layer 4 — Deterministic Scoring Engine)."""

from __future__ import annotations

from models.features import UnifiedFeatureModel
from services.feature_fusion import FeatureFusionEngine
from services.scoring_engine import ScoringEngine


class TestScoringEngine:
    def test_full_features_produce_all_scores(self, sample_unified_features: UnifiedFeatureModel) -> None:
        derived = FeatureFusionEngine().fuse(sample_unified_features)
        scores = ScoringEngine().score(sample_unified_features, derived)

        for score in (
            scores.resume_score,
            scores.slide_score,
            scores.speech_score,
            scores.transcript_score,
            scores.emotion_score,
            scores.eye_contact_score,
            scores.voice_confidence_score,
            scores.presentation_score,
            scores.communication_score,
        ):
            assert score is not None
            assert 0 <= score <= 100

        assert 0 <= scores.overall_score <= 100

    def test_missing_material_yields_none_subscore(self, sample_unified_features: UnifiedFeatureModel) -> None:
        partial = sample_unified_features.model_copy(update={"resume": None, "resume_analysis": None})
        derived = FeatureFusionEngine().fuse(partial)
        scores = ScoringEngine().score(partial, derived)
        assert scores.resume_score is None
        # Overall score still gets computed from whatever remains available.
        assert 0 <= scores.overall_score <= 100

    def test_no_material_yields_zero_overall_and_all_none(self) -> None:
        empty = UnifiedFeatureModel()
        derived = FeatureFusionEngine().fuse(empty)
        scores = ScoringEngine().score(empty, derived)

        assert scores.resume_score is None
        assert scores.slide_score is None
        assert scores.speech_score is None
        assert scores.transcript_score is None
        assert scores.emotion_score is None
        assert scores.eye_contact_score is None
        assert scores.voice_confidence_score is None
        assert scores.presentation_score is None
        assert scores.communication_score is None
        assert scores.overall_score == 0

    def test_scoring_is_deterministic(self, sample_unified_features: UnifiedFeatureModel) -> None:
        derived = FeatureFusionEngine().fuse(sample_unified_features)
        engine = ScoringEngine()
        first = engine.score(sample_unified_features, derived)
        second = engine.score(sample_unified_features, derived)
        assert first == second
