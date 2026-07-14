"""
services/gemini_service.py

Layer 6 -- Gemini Reasoning service.

Thin service layer wrapping the Gemini API via the `google-genai` SDK
(`from google import genai`). Centralizes client creation, prompt
execution, response-schema enforcement, JSON parsing, and error handling so
routers and the orchestrator never talk to the SDK directly.

Gemini is ONLY ever invoked with a finished prompt built by
`services/prompt_builder.py`, containing already-extracted, already-scored
structured data. It never receives a raw file and is never asked to
produce a numeric score.

The underlying SDK call is synchronous, so it is executed in a worker
thread via `asyncio.to_thread` to keep FastAPI's event loop non-blocking.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, TypeVar

# Must run before `google.genai` (and the `requests`/urllib3 stack it calls
# into) creates any SSL context. Swaps in the OS certificate store (Windows
# Certificate Store / macOS Keychain / OpenSSL on Linux) instead of the
# `certifi` bundle, so locally-trusted root CAs are honored too -- e.g. the
# self-signed root many antivirus products (AVG, Avast, Kaspersky, ESET...)
# inject when doing HTTPS/TLS scanning, which is trusted by Windows and
# browsers but not by `certifi`, and otherwise fails with
# "CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate".
import truststore

truststore.inject_into_ssl()

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

from config import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Matches a JSON object/array possibly wrapped in ```json ... ``` fences.
_JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)

ModelT = TypeVar("ModelT", bound=BaseModel)


class GeminiServiceError(Exception):
    """Raised when the Gemini API call fails or returns an unparsable response."""


class GeminiService:
    """Wraps Gemini API access for text-in / JSON-out reasoning prompts."""

    def __init__(self) -> None:
        """Initialize the Gemini client using the API key from settings."""
        self._client = genai.Client(api_key=settings.GEMINI_API_KEY)
        self._model = settings.GEMINI_MODEL

    async def generate_json(self, prompt: str) -> dict[str, Any]:
        """
        Send a prompt to Gemini and parse the response as a JSON object.

        Args:
            prompt: The full prompt text, expected to instruct the model to
                return a strict JSON object.

        Returns:
            The parsed JSON response as a Python dict.

        Raises:
            GeminiServiceError: If the API call fails or the response is not
                valid JSON.
        """
        response = await self._call(prompt, response_schema=None)
        text = self._extract_text(response)
        return self._parse_json(text)

    async def generate_structured(self, prompt: str, response_model: type[ModelT]) -> ModelT:
        """
        Send a prompt to Gemini, constrained to a Pydantic response schema,
        and validate the result against that schema.

        Args:
            prompt: The full prompt text.
            response_model: The Pydantic model describing the required
                response shape. Passed to Gemini as a `response_schema` so
                the model is constrained at generation time, then re-
                validated locally as a safety net.

        Returns:
            An instance of `response_model`.

        Raises:
            GeminiServiceError: If the API call fails, the response is not
                valid JSON, or it fails schema validation.
        """
        response = await self._call(prompt, response_schema=response_model)
        text = self._extract_text(response)
        parsed = self._parse_json(text)
        try:
            return response_model.model_validate(parsed)
        except ValidationError as exc:
            logger.error("Gemini structured response failed validation: %s", exc)
            raise GeminiServiceError(
                f"Gemini response did not match the expected schema: {exc}"
            ) from exc

    async def _call(self, prompt: str, response_schema: type[BaseModel] | None) -> Any:
        """Dispatch the (synchronous) Gemini call to a worker thread."""
        try:
            return await asyncio.to_thread(self._call_gemini, prompt, response_schema)
        except GeminiServiceError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Gemini API call failed")
            raise GeminiServiceError(f"Gemini API call failed: {exc}") from exc

    def _call_gemini(self, prompt: str, response_schema: type[BaseModel] | None) -> Any:
        """Perform the actual (synchronous) call to the Gemini API."""
        config_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
            "temperature": 0.4,
        }
        if response_schema is not None:
            config_kwargs["response_schema"] = self._to_gemini_schema(response_schema)

        return self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=types.GenerateContentConfig(**config_kwargs),
        )

    @staticmethod
    def _to_gemini_schema(model: type[BaseModel]) -> dict[str, Any]:
        """
        Build a Gemini-compatible JSON schema from a Pydantic model.

        The Gemini API's `response_schema` is a constrained subset of
        OpenAPI 3.0 schema and rejects a handful of keywords that standard
        JSON Schema (and therefore Pydantic's `model_json_schema()`) emits
        freely -- most notably `default`, which every field on
        `ReasoningPayload` has (`default_factory=list` / `= ""`) so the
        model still validates cleanly if Gemini omits an optional-feeling
        field. Passing the raw Pydantic model straight through as
        `response_schema` therefore fails with:
        "Default value is not supported in the response schema for the
        Gemini API." Strip `default` (and any nested occurrences, e.g.
        inside `items`/`properties`/`$defs`) from the JSON schema before
        sending it, rather than reshaping the Pydantic models themselves --
        their defaults are still useful for local `model_validate()`.
        """
        return GeminiService._strip_key(model.model_json_schema(), "default")

    @staticmethod
    def _strip_key(node: Any, key: str) -> Any:
        """Recursively remove every occurrence of `key` from a nested dict/list structure."""
        if isinstance(node, dict):
            return {k: GeminiService._strip_key(v, key) for k, v in node.items() if k != key}
        if isinstance(node, list):
            return [GeminiService._strip_key(item, key) for item in node]
        return node

    @staticmethod
    def _extract_text(response: Any) -> str:
        """Extract the plain text payload from a Gemini response object."""
        text = getattr(response, "text", None)
        if text:
            return text

        # Fallback: manually walk candidates/parts if `.text` is unavailable.
        candidates = getattr(response, "candidates", None) or []
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            parts = getattr(content, "parts", None) or []
            for part in parts:
                part_text = getattr(part, "text", None)
                if part_text:
                    return part_text

        raise GeminiServiceError("Gemini response contained no text content.")

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """
        Parse a JSON object out of raw model text, tolerating markdown fences.

        Args:
            text: Raw text returned by the model.

        Returns:
            Parsed JSON as a dict.

        Raises:
            GeminiServiceError: If no valid JSON object can be parsed.
        """
        candidate_text = text.strip()

        fence_match = _JSON_FENCE_PATTERN.search(candidate_text)
        if fence_match:
            candidate_text = fence_match.group(1).strip()

        try:
            parsed = json.loads(candidate_text)
        except json.JSONDecodeError as exc:
            logger.error("Failed to parse Gemini JSON response: %s", text[:500])
            raise GeminiServiceError(f"Gemini returned invalid JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise GeminiServiceError("Gemini JSON response was not a JSON object.")

        return parsed


# Module-level singleton so the Gemini client is reused across requests.
gemini_service = GeminiService()
