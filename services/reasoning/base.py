"""
services/reasoning/base.py

`BaseReasoningEngine` — the contract every Layer 6 reasoning provider must
implement (Gemini today; Claude/GPT/a local model/a fine-tuned model in the
future). `EvaluationWorkflowManager` only ever talks to whatever
`provider_registry.get_reasoning_engine()` returns; it never imports a
concrete engine class directly.

Hard constraints on every implementation (enforced by convention/code
review, not by the type system alone — see the project README's "Design
Principle" section):

* MUST NOT calculate, adjust, clamp, or otherwise touch any numeric score.
  Scores exist only in `ScoreBreakdown` / `ScoreResultORM`, produced solely
  by `services/scoring_engine.py`.
* MUST NOT read raw uploaded files (PDF/PPTX/MP4/etc). It only ever
  receives an already-built prompt string (from `PromptBuilder`) plus the
  Pydantic response model it must conform to.
* MUST NOT mutate `UnifiedFeatureModel`, business logic, or workflow state.
  It has no access to the DB session or `AnalysisSession` at all — it is a
  pure text-in / structured-object-out function.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TypeVar

from pydantic import BaseModel

ModelT = TypeVar("ModelT", bound=BaseModel)


class BaseReasoningEngine(ABC):
    """Contract for a Layer 6 reasoning provider."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short, stable identifier stamped onto `ReportORM.reasoning_engine_name` (e.g. `"gemini"`)."""
        raise NotImplementedError

    @property
    def version(self) -> str | None:
        """Optional model/version string stamped onto `ReportORM.reasoning_engine_version`."""
        return None

    @abstractmethod
    async def generate_structured(self, prompt: str, response_model: type[ModelT]) -> ModelT:
        """
        Send `prompt` to the underlying model and return a validated
        instance of `response_model`.

        Args:
            prompt: The finished prompt text built by `PromptBuilder`.
            response_model: The Pydantic model the response must conform to
                (always `ReasoningPayload` today, per `models/responses.py`).

        Returns:
            A validated instance of `response_model`.

        Raises:
            Exception: Implementations should raise on any failure (network,
                schema validation, etc.) — `EvaluationWorkflowManager`
                catches it and records `state=FAILED` on the session.
        """
        raise NotImplementedError
