"""
services/reasoning/claude_engine.py

`ClaudeReasoningEngine` -- a `BaseReasoningEngine` implementation backed by
the Claude API. Thin adapter around `services/claude_service.ClaudeService`
(unchanged; nothing about Claude access is rewritten here), so it satisfies
the `BaseReasoningEngine` contract without duplicating any Claude-specific
logic. Mirrors `services/reasoning/gemini_engine.py`.
"""

from __future__ import annotations

from config import settings
from services.claude_service import ClaudeService, claude_service
from services.reasoning.base import BaseReasoningEngine, ModelT


class ClaudeReasoningEngine(BaseReasoningEngine):
    """Adapts the existing `ClaudeService` singleton to the `BaseReasoningEngine` contract."""

    def __init__(self, service: ClaudeService | None = None) -> None:
        self._service = service or claude_service

    @property
    def name(self) -> str:
        return "claude"

    @property
    def version(self) -> str | None:
        return settings.CLAUDE_MODEL

    async def generate_structured(self, prompt: str, response_model: type[ModelT]) -> ModelT:
        return await self._service.generate_structured(prompt, response_model)
