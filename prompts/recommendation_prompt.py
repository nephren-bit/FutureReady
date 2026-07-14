"""
prompts/recommendation_prompt.py

Builds the Recommendation Engine's prompt (see `services/recommendation_engine.py`):
the session's final score breakdown + reasoning (weaknesses/improvement_plan/
feedback) plus a candidate catalog of learning resources, asking the
reasoning engine to pick and rank the resources best targeted at this
candidate's weakest areas. The reasoning engine is deliberately given a
closed candidate list rather than free rein — it is instructed to select,
never to invent a resource_id/title/URL that was not supplied, mirroring
the "Gemini reasons over already-computed structured data" guardrail used
throughout this codebase (it never gets to score itself either; see
`prompts/base_prompt.SCORE_GUARDRAIL`).
"""

from __future__ import annotations

from models.features import ScoreBreakdown
from models.responses import ReasoningPayload
from prompts.base_prompt import PERSONA_INTRO, build_json_only_instruction, language_name, to_json_block

_RECOMMENDATION_SCHEMA = """{
  "picks": [
    {
      "resource_id": "<id copied EXACTLY from the candidate list below>",
      "rationale": "<1-2 sentences, grounded in a specific weak score or weakness above>",
      "target_skill_tags": [<string>, ...]
    },
    ...
  ]
}"""


def build_recommendation_prompt(
    scores: ScoreBreakdown,
    reasoning: ReasoningPayload,
    candidates: list[dict],
    language: str = "vi",
) -> str:
    """
    Build the Recommendation Engine prompt.

    Args:
        scores: The session's final `ScoreBreakdown`.
        reasoning: The session's final `ReasoningPayload` (weaknesses/
            improvement_plan/feedback already written for the candidate).
        candidates: The learning-resource candidate list the reasoning
            engine may pick from, each a dict of `{id, title, skill_tags,
            category, language, resource_type}` (see
            `services.recommendation_engine.RecommendationEngine.build_prompt`).
        language: Output language code ("vi" or "en") for the rationale text.

    Returns:
        The finished prompt string.
    """
    language_label = language_name(language)

    weak_areas_payload = {
        "scores": scores.model_dump(),
        "weaknesses": reasoning.weaknesses,
        "improvement_plan": reasoning.improvement_plan,
        "presentation_feedback": reasoning.presentation_feedback,
        "interview_feedback": reasoning.interview_feedback,
    }

    return f"""{PERSONA_INTRO}

You are now acting as a learning-path advisor. The candidate has already
received their full evaluation (shown below). Your ONLY job is to pick,
from the CANDIDATE RESOURCE LIST below, the resources that would most help
THIS candidate improve — you are not writing new feedback and not
re-scoring anything.

## Candidate's Weak Areas (from their evaluation)

```json
{to_json_block(weak_areas_payload)}
```

## Candidate Resource List

Pick ONLY from these. Never invent a resource_id, title, or URL that is not
in this list — any pick referencing an id not shown here will be discarded.

```json
{to_json_block(candidates)}
```

## Your Task

Select 3-5 resources from the candidate list above that best address this
candidate's specific weak areas (prefer resources whose `skill_tags`
overlap with whichever score fields are lowest, and with the themes in
`weaknesses`/`improvement_plan`). For each pick:
- `resource_id`: copied EXACTLY from the candidate list (do not alter it).
- `rationale`: 1-2 sentences, in {language_label}, explaining why THIS
  candidate specifically would benefit — reference a concrete weak score or
  weakness, not a generic description of the resource.
- `target_skill_tags`: which of the candidate's weak areas (using the same
  skill_tags vocabulary as the candidate list) this resource addresses.

Order picks by relevance (most relevant first). Respond entirely in
{language_label} for the `rationale` text.

{build_json_only_instruction(_RECOMMENDATION_SCHEMA)}
"""
