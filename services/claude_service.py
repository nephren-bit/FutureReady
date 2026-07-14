"""
services/claude_service.py

Layer 6 -- Claude Reasoning service.

Thin service layer wrapping the Claude API via the official `anthropic` SDK.
Centralizes client creation, prompt execution, and structured-output
validation, so routers and the orchestrator never talk to the SDK directly.
Mirrors `services/gemini_service.py`'s responsibilities exactly -- this is a
second, swappable implementation behind the same `BaseReasoningEngine`
contract (see `services/reasoning/claude_engine.py`), not a parallel pipeline.

Claude is ONLY ever invoked with a finished prompt built by
`services/prompt_builder.py`, containing already-extracted, already-scored
structured data. It never receives a raw file and is never asked to
produce a numeric score.

Unlike Gemini's `response_schema`, Claude's `messages.parse()` derives the
JSON schema from the Pydantic model itself, strips schema keywords the API
doesn't support, and validates the response against that same model --
no manual schema-stripping step is needed here (contrast
`GeminiService._to_gemini_schema`).
"""

from __future__ import annotations

from typing import TypeVar

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)

# Reasoning payloads here are bounded lists of short strings (strengths,
# weaknesses, suggestions, ...), never long-form generation -- comfortably
# under the ~16K threshold where the SDK requires streaming.
_MAX_TOKENS = 8000


class ClaudeServiceError(Exception):
    """Raised when the Claude API call fails or returns an unparsable response."""


class ClaudeService:
    """Wraps Claude API access for text-in / structured-JSON-out reasoning prompts."""

    def __init__(self) -> None:
        """Initialize the Claude client using the API key from settings."""
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._model = settings.CLAUDE_MODEL

    async def generate_structured(self, prompt: str, response_model: type[ModelT]) -> ModelT:
        """
        Send a prompt to Claude, constrained to a Pydantic response schema,
        and return the validated result.

        Args:
            prompt: The full prompt text.
            response_model: The Pydantic model describing the required
                response shape. `messages.parse()` builds the JSON schema
                from this model and validates `parsed_output` against it.

        Returns:
            An instance of `response_model`.

        Raises:
            ClaudeServiceError: If the API call fails, the model declined to
                answer (safety refusal), or the response didn't parse.
        """
        try:
            response = await self._client.messages.parse(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                output_format=response_model,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Claude API call failed")
            raise ClaudeServiceError(f"Claude API call failed: {exc}") from exc

        if response.stop_reason == "refusal":
            raise ClaudeServiceError("Claude declined to respond to this prompt (safety refusal).")

        parsed = response.parsed_output
        if parsed is None:
            raise ClaudeServiceError("Claude response did not match the expected schema.")
        return parsed


# Module-level singleton so the Claude client is reused across requests.
claude_service = ClaudeService()
