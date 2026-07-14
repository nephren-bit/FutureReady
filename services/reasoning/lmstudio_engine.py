"""
services/reasoning/lmstudio_engine.py

`LMStudioReasoningEngine` -- a `BaseReasoningEngine` implementation backed by
a local LM Studio server. Thin adapter around
`services/lmstudio_service.LMStudioService` (unchanged; nothing about LM
Studio access is rewritten here), so it satisfies the `BaseReasoningEngine`
contract without duplicating any LM-Studio-specific logic. Mirrors
`services/reasoning/gemini_engine.py` / `claude_engine.py`.
"""

from __future__ import annotations

from config import settings
from services.lmstudio_service import LMStudioService, lmstudio_service
from services.reasoning.base import BaseReasoningEngine, ModelT


class LMStudioReasoningEngine(BaseReasoningEngine):
    """Adapts the existing `LMStudioService` singleton to the `BaseReasoningEngine` contract."""

    def __init__(self, service: LMStudioService | None = None) -> None:
        self._service = service or lmstudio_service

    @property
    def name(self) -> str:
        return "lmstudio"

    @property
    def version(self) -> str | None:
        return settings.LMSTUDIO_MODEL

    async def generate_structured(self, prompt: str, response_model: type[ModelT]) -> ModelT:
        return await self._service.generate_structured(prompt, response_model)
