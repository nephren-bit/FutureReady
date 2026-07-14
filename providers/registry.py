"""
providers/registry.py

`ProviderRegistry` — the single place that decides which concrete
implementation backs each swappable provider contract, driven by
`config/providers.yaml` rather than hard-coded imports scattered through
the codebase.

Today this only covers `BaseReasoningEngine` (Gemini now; Claude/GPT/a
local/fine-tuned model later). `EvaluationWorkflowManager` never imports
`GeminiReasoningEngine` (or any other concrete engine) directly — it only
ever calls `provider_registry.get_reasoning_engine()`. Adding a new engine
means: (1) implement `BaseReasoningEngine`, (2) register it in
`_REASONING_ENGINE_FACTORIES` below, (3) point `reasoning_engine:` in
config/providers.yaml at its name. No other file changes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import yaml

from services.reasoning.base import BaseReasoningEngine
from services.reasoning.gemini_engine import GeminiReasoningEngine
from utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "providers.yaml"

# Registered reasoning-engine factories, keyed by the name used in
# config/providers.yaml. Register a new implementation here to make it
# selectable without touching any other file.
_REASONING_ENGINE_FACTORIES: dict[str, Callable[[], BaseReasoningEngine]] = {
    "gemini": GeminiReasoningEngine,
}


class ProviderRegistryError(Exception):
    """Raised when `config/providers.yaml` names a provider with no registered implementation."""


class ProviderRegistry:
    """Resolves and caches the configured provider implementations."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or _DEFAULT_CONFIG_PATH
        self._config: dict[str, str] | None = None
        self._reasoning_engine: BaseReasoningEngine | None = None

    def _load_config(self) -> dict[str, str]:
        if self._config is None:
            if self._config_path.exists():
                with open(self._config_path, encoding="utf-8") as f:
                    self._config = yaml.safe_load(f) or {}
            else:
                logger.warning(
                    "config/providers.yaml not found at %s; falling back to defaults.", self._config_path
                )
                self._config = {}
        return self._config

    def get_reasoning_engine(self) -> BaseReasoningEngine:
        """
        Return the configured `BaseReasoningEngine` singleton, constructing
        it on first use. Cached for the lifetime of the process — reasoning
        engines are stateless aside from their own internal client, so
        there is no reason to rebuild one per request.
        """
        if self._reasoning_engine is not None:
            return self._reasoning_engine

        config = self._load_config()
        name = config.get("reasoning_engine", "gemini")
        factory = _REASONING_ENGINE_FACTORIES.get(name)
        if factory is None:
            raise ProviderRegistryError(
                f"Unknown reasoning_engine '{name}' in {self._config_path}. "
                f"Registered engines: {sorted(_REASONING_ENGINE_FACTORIES)}"
            )
        self._reasoning_engine = factory()
        logger.info("Reasoning engine resolved to '%s' (from %s)", name, self._config_path)
        return self._reasoning_engine

    def reset(self) -> None:
        """Clear cached instances. Used by tests to force re-resolution after changing config."""
        self._config = None
        self._reasoning_engine = None


# Module-level singleton, mirrors `ai_orchestrator` / `gemini_service`.
provider_registry = ProviderRegistry()
