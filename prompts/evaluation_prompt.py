"""
prompts/evaluation_prompt.py

Layer 5 — Prompt Builder (composition root).

Assembles the final prompt sent to Gemini (Layer 6) for the `/evaluate*`
endpoints out of: the shared persona/guardrail framing (`base_prompt`), one
section per material (`cv_prompt`, `slide_prompt`, `transcript_prompt`,
`speech_prompt`), the cross-modal derived features from Feature Fusion, the
full deterministic `ScoreBreakdown`, and the required JSON output schema.

No prompt text is ever hard-coded inside a router — routers call
`services.prompt_builder.PromptBuilder`, which calls this module.
"""

from __future__ import annotations

from models.features import DerivedFeatures, ScoreBreakdown, UnifiedFeatureModel
from models.responses import ReasoningPayload
from prompts.base_prompt import (
    PERSONA_INTRO,
    SCORE_GUARDRAIL,
    build_json_only_instruction,
    language_name,
    to_json_block,
)
from prompts.cv_prompt import build_resume_section
from prompts.slide_prompt import build_slide_section
from prompts.speech_prompt import build_speech_section
from prompts.transcript_prompt import build_transcript_section

_RESPONSE_SCHEMA_DESCRIPTION = """{
  "strengths": [<string>, ...],
  "weaknesses": [<string>, ...],
  "improvement_plan": [<string>, ...],
  "presentation_feedback": "<3-6 sentence assessment of the presentation/slide delivery>",
  "interview_feedback": "<3-6 sentence assessment of interview/speaking readiness>",
  "interview_questions": [<string>, ...],
  "suggestions": [<string>, ...]
}"""


def build_evaluation_prompt(
    features: UnifiedFeatureModel,
    scores: ScoreBreakdown,
    derived: DerivedFeatures,
    language: str = "vi",
    prior_evaluations: dict[str, ReasoningPayload] | None = None,
) -> str:
    """
    Build the complete Gemini evaluation prompt.

    Args:
        features: The full unified feature set for this evaluation.
        scores: The deterministic `ScoreBreakdown` (already computed).
        derived: The cross-modal `DerivedFeatures` (already computed).
        language: Output language code ("vi" or "en").
        prior_evaluations: Optional mapping of stage name (e.g. "slide",
            "video") to the preliminary `ReasoningPayload` already shown to
            the user for that material (see `prompts/preliminary_prompt.py`
            and `services/workflow_manager.py`). When supplied, this is the
            FINAL synthesis pass: the model is instructed to reconcile these
            preliminary assessments into one coherent report (not contradict
            them without reason) rather than reason over the raw data as if
            seeing it for the first time. `None`/empty for the legacy
            single-shot `/evaluate` endpoints, which have no preliminary stage.

    Returns:
        The full prompt string, ready to send to `GeminiService`.
    """
    sections = [
        build_resume_section(features.resume, features.resume_analysis, scores.resume_score),
        build_slide_section(features.slide, features.slide_analysis, scores.slide_score),
        build_transcript_section(features.transcript, scores.transcript_score),
        build_speech_section(
            features.audio,
            features.speech_intelligence,
            features.emotion,
            features.facemesh,
            scores.speech_score,
            scores.emotion_score,
            scores.eye_contact_score,
            scores.voice_confidence_score,
        ),
    ]
    materials_block = "\n".join(section for section in sections if section)

    summary_payload = {
        "derived_features": derived.model_dump(),
        "communication_score": scores.communication_score,
        "presentation_score": scores.presentation_score,
        "overall_score": scores.overall_score,
    }

    language_label = language_name(language)

    prior_block = ""
    task_intro = (
        'You are producing a holistic "future readiness" evaluation covering\n'
        "whichever of the candidate's materials were supplied: resume, presentation\n"
        "slides, and/or a recorded speech/presentation video. Some sections below may\n"
        "be absent if that material was not submitted — reason only over what is\n"
        "present."
    )
    if prior_evaluations:
        prior_payload = {stage: payload.model_dump() for stage, payload in prior_evaluations.items()}
        prior_block = f"""

## Preliminary Assessments Already Shown To The Candidate

Each material below was already reviewed individually as soon as it was
submitted, and the candidate has ALREADY SEEN this preliminary feedback.
Your job now is to produce the FINAL, synthesized report: reconcile these
preliminary assessments with each other and with the full cross-modal data
below into one coherent whole. Do not simply repeat them verbatim, and do
not contradict a preliminary point without a clear reason grounded in data
that the preliminary pass did not have access to (e.g. the slide review had
no vocal-delivery data available yet).

```json
{to_json_block(prior_payload)}
```"""
        task_intro = (
            "You are producing the FINAL, synthesized \"future readiness\" evaluation, "
            "combining preliminary per-material assessments (shown below) with the full "
            "cross-modal picture now that every material has been submitted."
        )

    return f"""{PERSONA_INTRO}

{SCORE_GUARDRAIL}

{task_intro}

{materials_block}
{prior_block}

## Cross-Modal Summary

Derived features (Feature Fusion) and composite/overall scores (Deterministic
Scoring Engine), already computed:

```json
{to_json_block(summary_payload)}
```

## Your Task

Using ONLY the structured data above, produce:
- `strengths`: 3-6 concrete strengths, each grounded in specific data points above.
- `weaknesses`: 3-6 concrete weaknesses, each grounded in specific data points above.
- `improvement_plan`: 3-6 prioritized, concrete next steps, ordered by impact.
- `presentation_feedback`: qualitative feedback on the presentation/slide delivery.
- `interview_feedback`: qualitative feedback on interview/speaking readiness.
- `interview_questions`: 3-5 realistic interview questions this candidate should
  practice, tailored to gaps visible in the data (e.g. thin experience section,
  weak vocal confidence).
- `suggestions`: 3-6 additional actionable coaching tips not already covered by
  `improvement_plan`.

Respond entirely in {language_label}.

{build_json_only_instruction(_RESPONSE_SCHEMA_DESCRIPTION)}
"""
