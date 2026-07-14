"""
services/reasoning/gemini_engine.py

`GeminiReasoningEngine` — the current, only-implemented `BaseReasoningEngine`.
Thin adapter around the existing `services/gemini_service.GeminiService`
(unchanged; nothing about Gemini access is rewritten here), so it satisfies
the `BaseReasoningEngine` contract without duplicating any Gemini-specific
logic.
"""

from __future__ import annotations

from config import settings
from services.gemini_service import GeminiService, gemini_service
from services.reasoning.base import BaseReasoningEngine, ModelT


class GeminiReasoningEngine(BaseReasoningEngine):
    """Adapts the existing `GeminiService` singleton to the `BaseReasoningEngine` contract."""

    def __init__(self, service: GeminiService | None = None) -> None:
        self._service = service or gemini_service

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def version(self) -> str | None:
        return settings.GEMINI_MODEL

    async def generate_structured(self, prompt: str, response_model: type[ModelT]) -> ModelT:
        return await self._service.generate_structured(prompt, response_model)
