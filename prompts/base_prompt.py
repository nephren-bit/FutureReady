"""
prompts/base_prompt.py

Shared prompt-building building blocks used by every prompt module
(cv_prompt, slide_prompt, transcript_prompt, speech_prompt,
evaluation_prompt). Centralizing the persona framing, language handling,
and the "do not invent facts / do not recompute scores" guardrail keeps
every generated prompt consistent and keeps prompt text out of routers and
services entirely (per the Design Principle: Gemini only reasons).
"""

from __future__ import annotations

import json
from typing import Any

LANGUAGE_NAMES: dict[str, str] = {"vi": "Vietnamese", "en": "English"}


def language_name(language: str) -> str:
    """Resolve a language code to its display name, defaulting to Vietnamese."""
    return LANGUAGE_NAMES.get(language, "Vietnamese")


def to_json_block(data: Any) -> str:
    """Render a JSON-serializable object as a fenced ```json code block body (no fences)."""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


PERSONA_INTRO = (
    "You are EmpathAI, a senior communication coach combining the expertise of a "
    "technical recruiter, a presentation design consultant, and a professional "
    "speech/interview coach. You never fabricate facts, and you never invent or "
    "recompute numeric scores."
)

SCORE_GUARDRAIL = (
    "IMPORTANT: All numeric scores below were already computed by a deterministic, "
    "rule-based scoring engine BEFORE this prompt was written. They are ground truth. "
    "Do not recalculate them, do not contradict them, and do not output any new score "
    "fields. Your only job is qualitative reasoning: explain what the numbers mean, "
    "identify strengths and weaknesses grounded in the structured data below, and give "
    "concrete, actionable coaching advice."
)


def build_json_only_instruction(schema_description: str) -> str:
    """
    Build the final instruction block enforcing strict JSON output.

    Args:
        schema_description: A pretty-printed example of the exact JSON shape
            the model must return (typically produced from the target
            Pydantic model's field descriptions).

    Returns:
        The instruction text to append at the end of a prompt.
    """
    return f"""Return ONLY a valid JSON object with EXACTLY this schema, no extra text,
no markdown code fences, no explanation before or after:

{schema_description}

Rules:
- Output must be valid JSON only, parseable by `json.loads`.
- Do not include any field not listed in the schema above.
- Do not output any numeric "score" fields — scores are provided to you, not requested of you.
- Write all free-text content in the requested language.
- Ground every claim in the structured data provided; never invent facts not supported by it.
"""
