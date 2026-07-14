"""
models/requests.py

Pydantic models describing request bodies and shared request parameters.

File uploads (PDF/PPTX/MP3/MP4) are handled natively by FastAPI via
`UploadFile` and therefore do not need a Pydantic body model. This module
covers:

* `AnalysisOptions` — shared, non-file query parameters (output language).
* `EvaluateFeaturesRequest` — the JSON body for Evaluation Mode B, where the
  caller has already produced a `UnifiedFeatureModel` (e.g. from a previous
  `/extract/*` + `/analyze/*` call) and wants to skip re-extraction.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from models.features import UnifiedFeatureModel


class AnalysisOptions(BaseModel):
    """
    Optional parameters controlling how feedback is generated.

    Attributes:
        language: Language Gemini should use when writing feedback.
    """

    language: Literal["vi", "en"] = Field(
        default="vi",
        description="Language of the generated feedback: 'vi' (Vietnamese) or 'en' (English).",
    )


class EvaluateFeaturesRequest(BaseModel):
    """
    Request body for Evaluation Mode B (`POST /evaluate/from-features`).

    Skips Layer 1 (extraction) entirely: the caller supplies an already
    populated `UnifiedFeatureModel`, and the pipeline runs Feature Fusion ->
    Scoring -> Prompt Building -> Gemini Reasoning directly on it.
    """

    features: UnifiedFeatureModel = Field(
        ..., description="Pre-computed unified feature set to evaluate."
    )
    language: Literal["vi", "en"] = Field(
        default="vi",
        description="Language of the generated feedback: 'vi' (Vietnamese) or 'en' (English).",
    )
