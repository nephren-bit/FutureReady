"""Unit tests for providers/registry.py (BaseReasoningEngine resolution)."""

from __future__ import annotations

import pytest

from providers.registry import ProviderRegistry, ProviderRegistryError
from services.reasoning.gemini_engine import GeminiReasoningEngine


class TestProviderRegistry:
    def test_defaults_to_gemini(self, tmp_path) -> None:
        config_file = tmp_path / "providers.yaml"
        config_file.write_text("reasoning_engine: gemini\n")
        registry = ProviderRegistry(config_path=config_file)
        engine = registry.get_reasoning_engine()
        assert isinstance(engine, GeminiReasoningEngine)
        assert engine.name == "gemini"

    def test_caches_engine_instance(self, tmp_path) -> None:
        config_file = tmp_path / "providers.yaml"
        config_file.write_text("reasoning_engine: gemini\n")
        registry = ProviderRegistry(config_path=config_file)
        first = registry.get_reasoning_engine()
        second = registry.get_reasoning_engine()
        assert first is second

    def test_unknown_engine_raises(self, tmp_path) -> None:
        config_file = tmp_path / "providers.yaml"
        config_file.write_text("reasoning_engine: not-a-real-engine\n")
        registry = ProviderRegistry(config_path=config_file)
        with pytest.raises(ProviderRegistryError):
            registry.get_reasoning_engine()

    def test_missing_config_falls_back_to_gemini(self, tmp_path) -> None:
        registry = ProviderRegistry(config_path=tmp_path / "does-not-exist.yaml")
        engine = registry.get_reasoning_engine()
        assert engine.name == "gemini"

    def test_reset_clears_cache(self, tmp_path) -> None:
        config_file = tmp_path / "providers.yaml"
        config_file.write_text("reasoning_engine: gemini\n")
        registry = ProviderRegistry(config_path=config_file)
        first = registry.get_reasoning_engine()
        registry.reset()
        second = registry.get_reasoning_engine()
        assert first is not second
