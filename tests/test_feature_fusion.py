"""Unit tests for services/feature_fusion.py (Layer 3 — Feature Fusion Engine)."""

from __future__ import annotations

import pytest

from models.features import UnifiedFeatureModel
from services.feature_fusion import FeatureFusionEngine


class TestFeatureFusionEngine:
    def test_full_features_produce_bounded_derived_features(
        self, sample_unified_features: UnifiedFeatureModel
    ) -> None:
        derived = FeatureFusionEngine().fuse(sample_unified_features)
        for value in (
            derived.professionalism,
            derived.presentation_density,
            derived.communication_confidence,
            derived.visual_engagement,
            derived.voice_confidence,
            derived.presentation_readiness,
        ):
            assert 0.0 <= value <= 100.0

    def test_empty_features_fall_back_to_neutral(self) -> None:
        derived = FeatureFusionEngine().fuse(UnifiedFeatureModel())
        assert derived.professionalism == 50.0
        assert derived.presentation_density == 50.0
        assert derived.communication_confidence == 50.0
        assert derived.visual_engagement == 50.0
        assert derived.voice_confidence == 50.0
        assert derived.presentation_readiness == 50.0

    def test_presentation_readiness_is_average_of_the_rest(
        self, sample_unified_features: UnifiedFeatureModel
    ) -> None:
        derived = FeatureFusionEngine().fuse(sample_unified_features)
        expected = (
            derived.professionalism
            + derived.presentation_density
            + derived.communication_confidence
            + derived.visual_engagement
            + derived.voice_confidence
        ) / 5
        assert derived.presentation_readiness == pytest.approx(expected, abs=0.05)

    def test_reproducible_given_same_input(self, sample_unified_features: UnifiedFeatureModel) -> None:
        engine = FeatureFusionEngine()
        first = engine.fuse(sample_unified_features)
        second = engine.fuse(sample_unified_features)
        assert first == second
