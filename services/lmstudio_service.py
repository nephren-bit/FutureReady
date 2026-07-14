"""
services/lmstudio_service.py

Layer 6 -- LM Studio Reasoning service.

Thin service layer wrapping a local LM Studio server via its OpenAI-compatible
REST API (see https://lmstudio.ai/docs/local-server), using the official
`openai` SDK pointed at LM Studio's `base_url` instead of OpenAI's. Mirrors
`services/gemini_service.py` / `services/claude_service.py`'s responsibilities
exactly -- a third, swappable implementation behind the same
`BaseReasoningEngine` contract (see `services/reasoning/lmstudio_engine.py`),
not a parallel pipeline.

LM Studio is ONLY ever invoked with a finished prompt built by
`services/prompt_builder.py`, containing already-extracted, already-scored
structured data. It never receives a raw file and is never asked to
produce a numeric score.

Structured output note: unlike Gemini (`response_schema`) and Claude
(`messages.parse`), LM Studio's constrained decoding is driven by a plain
JSON Schema passed as `response_format`. Locally-loaded models are commonly
small enough that an *unconstrained* schema (the raw output of
`model.model_json_schema()`, which Pydantic leaves without a top-level
`required` list once every field has a default) lets the model satisfy the
grammar with an empty `{}` and skip generating content entirely. Forcing
every property into `required` (mirroring OpenAI's own strict-mode
convention) is what actually makes the model fill in every field --
`_to_strict_schema` below applies that recursively, including through
`$defs` for nested models (e.g. `RecommendationPayload.picks`).
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Matches a JSON object/array possibly wrapped in ```json ... ``` fences --
# small local models don't always honor "no markdown fences" instructions.
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

ModelT = TypeVar("ModelT", bound=BaseModel)


class LMStudioServiceError(Exception):
    """Raised when the LM Studio API call fails or returns an unparsable response."""


class LMStudioService:
    """Wraps LM Studio's local OpenAI-compatible API for text-in / JSON-out reasoning prompts."""

    def __init__(self) -> None:
        """Initialize the OpenAI-compatible client pointed at the local LM Studio server."""
        self._client = AsyncOpenAI(base_url=settings.LMSTUDIO_BASE_URL, api_key=settings.LMSTUDIO_API_KEY)
        self._model = settings.LMSTUDIO_MODEL

    async def generate_structured(self, prompt: str, response_model: type[ModelT]) -> ModelT:
        """
        Send a prompt to the local LM Studio model, constrained to a JSON
        Schema derived from `response_model`, and return the validated
        result.

        Args:
            prompt: The full prompt text, expected to instruct the model to
                return a strict JSON object (see `prompts/base_prompt.py`).
            response_model: The Pydantic model describing the required
                response shape.

        Returns:
            An instance of `response_model`.

        Raises:
            LMStudioServiceError: If the API call fails, the response isn't
                valid JSON, or it fails schema validation.
        """
        schema = self._to_strict_schema(response_model.model_json_schema())
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": schema,
                    },
                },
                temperature=0.4,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("LM Studio API call failed")
            raise LMStudioServiceError(f"LM Studio API call failed: {exc}") from exc

        text = response.choices[0].message.content
        if not text:
            raise LMStudioServiceError("LM Studio response contained no content.")

        parsed = self._parse_json(text)
        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            logger.error("LM Studio structured response failed validation: %s", exc)
            raise LMStudioServiceError(
                f"LM Studio response did not match the expected schema: {exc}"
            ) from exc

    @staticmethod
    def _to_strict_schema(node: Any) -> Any:
        """
        Recursively force every object node's properties into `required`
        and set `additionalProperties: false` -- see the module docstring
        for why this is necessary for small local models to reliably
        populate every field instead of returning `{}`.
        """
        if isinstance(node, dict):
            result = {k: LMStudioService._to_strict_schema(v) for k, v in node.items()}
            if result.get("type") == "object" and "properties" in result:
                result["additionalProperties"] = False
                result["required"] = list(result["properties"].keys())
            return result
        if isinstance(node, list):
            return [LMStudioService._to_strict_schema(item) for item in node]
        return node

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """
        Parse a JSON object out of raw model text, tolerating markdown fences.

        Args:
            text: Raw text returned by the model.

        Returns:
            Parsed JSON as a dict.

        Raises:
            LMStudioServiceError: If no valid JSON object can be parsed.
        """
        candidate_text = text.strip()

        fence_match = _JSON_FENCE_PATTERN.search(candidate_text)
        if fence_match:
            candidate_text = fence_match.group(1).strip()

        try:
            parsed = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse LM Studio JSON response: %s", text[:500])
            raise LMStudioServiceError(f"LM Studio returned invalid JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise LMStudioServiceError("LM Studio JSON response was not a JSON object.")

        return parsed


# Module-level singleton so the LM Studio client is reused across requests.
lmstudio_service = LMStudioService()
