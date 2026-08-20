"""
Guards the invariant `tests/conftest.py` claims: no test in this suite can
reach a real reasoning provider.

The invariant used to be enforced by mocking one concrete provider module,
which meant it silently held only while `config/providers.yaml` happened to
name that same provider. Flipping that one line for local development
un-hooked the mock, sent a real request out carrying the suite's dummy API
key, and failed a dozen tests with an authentication error unrelated to
anything they were testing.

These tests fail loudly if that coupling ever comes back.
"""

from __future__ import annotations

import pytest

from models.responses import ReasoningPayload, RecommendationPayload
from providers.registry import provider_registry
from services.reasoning.claude_engine import ClaudeReasoningEngine
from services.reasoning.gemini_engine import GeminiReasoningEngine
from services.reasoning.lmstudio_engine import LMStudioReasoningEngine

REAL_ENGINES = (GeminiReasoningEngine, ClaudeReasoningEngine, LMStudioReasoningEngine)


class TestReasoningEngineIsolation:
    def test_the_resolved_engine_is_never_a_real_provider(self) -> None:
        engine = provider_registry.get_reasoning_engine()
        assert not isinstance(engine, REAL_ENGINES), (
            f"Tests resolved a real reasoning provider ({type(engine).__name__}). "
            "The autouse `stub_reasoning_engine` fixture in conftest.py should have "
            "replaced it — a real one here means live network calls from the suite."
        )
        assert engine.name == "stub"

    def test_the_stub_is_what_every_consumer_resolves(self, stub_reasoning_engine) -> None:
        """
        Production code reaches its engine only via
        `provider_registry.get_reasoning_engine()`, so patching that one
        place is what makes the whole suite provider-independent.
        """
        assert provider_registry.get_reasoning_engine() is stub_reasoning_engine

    async def test_the_stub_dispatches_on_the_response_schema(self, stub_reasoning_engine) -> None:
        stub_reasoning_engine.reasoning = ReasoningPayload(presentation_feedback="hello")
        stub_reasoning_engine.recommendation = RecommendationPayload()

        reasoning = await stub_reasoning_engine.generate_structured("p", ReasoningPayload)
        recommendation = await stub_reasoning_engine.generate_structured("p", RecommendationPayload)

        assert reasoning.presentation_feedback == "hello"
        assert isinstance(recommendation, RecommendationPayload)
        assert len(stub_reasoning_engine.calls) == 2

    async def test_the_stub_can_be_made_to_fail(self, stub_reasoning_engine) -> None:
        """How a test exercises the engine-failure path without a real provider."""
        stub_reasoning_engine.error = RuntimeError("boom")
        with pytest.raises(RuntimeError, match="boom"):
            await stub_reasoning_engine.generate_structured("p", ReasoningPayload)

    def test_no_test_module_patches_a_concrete_provider(self) -> None:
        """
        The pattern this whole file exists to prevent: reaching into one
        provider's module to mock it. Do it through the registry instead, so
        `config/providers.yaml` cannot decide whether the suite passes.
        """
        from pathlib import Path

        offenders: list[str] = []
        for path in sorted(Path(__file__).parent.glob("test_*.py")):
            if path.name == Path(__file__).name:
                continue
            source = path.read_text(encoding="utf-8")
            for provider in ("gemini_service", "claude_service", "lmstudio_service"):
                if f"{provider}.{provider}.generate_structured" in source:
                    offenders.append(f"{path.name} patches {provider} directly")

        assert not offenders, (
            "Patch `provider_registry.get_reasoning_engine()` (see the autouse "
            "`stub_reasoning_engine` fixture) instead of a concrete provider module: "
            + "; ".join(offenders)
        )
