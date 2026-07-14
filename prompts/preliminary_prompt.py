"""
prompts/preliminary_prompt.py

Builds a *preliminary* review prompt covering exactly one material (slide
deck, resume, video, or a standalone live-practice recording) -- used as
soon as that material finishes Layer 1/2 analysis, before the rest of the
session's materials exist yet (or, for "practice", as the only material
that will ever exist for that recording). Reuses the same per-material
section builders as `evaluation_prompt.py` (no prompt text is duplicated),
just with a narrower task list and an explicit instruction not to reference
materials that have not been uploaded yet.

The FINAL synthesis prompt (`evaluation_prompt.build_evaluation_prompt`)
later receives session-scoped preliminary `ReasoningPayload`s as additional
context so the final report reconciles them rather than reasoning from
scratch. The "practice" stage is NOT part of that flow -- live-practice
recordings are their own standalone evaluation (see
`services/practice_session_manager.py`), never folded into a session report.
"""

from __future__ import annotations

from models.features import ScoreBreakdown, UnifiedFeatureModel
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

_PRELIMINARY_SCHEMA = """{
  "strengths": [<string>, ...],
  "weaknesses": [<string>, ...],
  "improvement_plan": [<string>, ...],
  "presentation_feedback": "<2-4 sentence preliminary assessment, or empty string if not applicable to this stage>",
  "interview_feedback": "<2-4 sentence preliminary assessment, or empty string if not applicable to this stage>",
  "interview_questions": [<string>, ...],
  "suggestions": [<string>, ...]
}"""

_STAGE_LABELS = {
    "slide": "presentation slide deck",
    "resume": "resume/CV",
    "video": "presentation/interview video (vocal delivery, on-camera presence, and spoken content)",
    "practice": "live speaking practice recording (vocal delivery and spoken content only)",
}


def _context_note(stage: str) -> str:
    if stage == "practice":
        return (
            "This is a standalone live speaking-practice session (audio "
            "only, no slides/resume/video involved) -- evaluate it entirely "
            "on its own terms, not as a checkpoint toward some larger, "
            "later report."
        )
    return (
        "No other material has been uploaded yet -- do not mention, assume "
        "the existence of, or apologize for the absence of any material "
        "other than what is shown below. This is an early checkpoint, not "
        "the final report; a more complete, synthesized report will be "
        "produced once every material has been submitted."
    )


def build_preliminary_prompt(
    stage: str,
    features: UnifiedFeatureModel,
    scores: ScoreBreakdown,
    language: str = "vi",
) -> str:
    """
    Build a preliminary, single-material review prompt.

    Args:
        stage: One of "slide", "resume", "video", "practice" -- which
            material this preliminary pass covers. `features` should only
            contain the fields relevant to that material (see
            `db.models.EvaluationStage` and `services/workflow_manager.py`'s
            preliminary-evaluation methods, which build a narrowed
            `UnifiedFeatureModel` per stage; "practice" is built by
            `services/practice_session_manager.py` instead).
        scores: The `ScoreBreakdown` computed by `ScoringEngine` from just
            this material's features (other sub-scores will be `None`).
        language: Output language code ("vi" or "en").

    Returns:
        The finished prompt string.
    """
    if stage not in _STAGE_LABELS:
        raise ValueError(f"Unknown preliminary stage: {stage!r}")

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

    stage_label = _STAGE_LABELS[stage]
    language_label = language_name(language)

    feedback_field = "presentation_feedback" if stage in ("slide", "video", "practice") else "interview_feedback"
    context_note = _context_note(stage)

    return f"""{PERSONA_INTRO}

{SCORE_GUARDRAIL}

You are giving a QUICK, PRELIMINARY review of ONLY the {stage_label} the
candidate has submitted so far. {context_note}

{materials_block}

## Your Task

Using ONLY the structured data above, produce a brief preliminary review:
- `strengths`: 2-4 concrete strengths, each grounded in the data above.
- `weaknesses`: 2-4 concrete weaknesses, each grounded in the data above.
- `improvement_plan`: 2-4 concrete next steps specific to this material.
- `{feedback_field}`: 2-4 sentence preliminary assessment. Leave the OTHER
  feedback field (of `presentation_feedback`/`interview_feedback`) as an
  empty string -- it does not apply to this material.
- `interview_questions`: leave as an empty list (not applicable at this stage).
- `suggestions`: 1-3 quick, actionable tips.

Respond entirely in {language_label}.

{build_json_only_instruction(_PRELIMINARY_SCHEMA)}
"""
