"""
models/responses.py

Shared API response payloads. Used to also define the old scoring
pipeline's response shapes (`EvaluationReport`, `ReasoningPayload`,
`RecommendationPayload`, `VideoVisionResponse`) — removed along with that
pipeline; `ErrorResponse` is the one piece every router still needs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error payload returned on failures."""

    detail: str = Field(..., description="Human-readable error message.")
