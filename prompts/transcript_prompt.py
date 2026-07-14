"""
prompts/transcript_prompt.py

Builds the transcript section of the master evaluation prompt: the
deterministic linguistic analysis of the speech transcript (word/sentence
stats, structure, filler words, topic consistency, CEFR estimate) and the
already-computed Transcript Score.
"""

from __future__ import annotations

from models.features import TranscriptFeature
from prompts.base_prompt import to_json_block


def build_transcript_section(
    transcript: TranscriptFeature | None,
    transcript_score: int | None,
) -> str:
    """
    Build the transcript section of the evaluation prompt.

    Returns an empty string if no transcript analysis is available.
    """
    if transcript is None:
        return ""

    payload = {**transcript.model_dump(), "transcript_score": transcript_score}

    return f"""## Speech Transcript Analysis

Deterministic linguistic analysis of the spoken transcript (no LLM was used
to produce these statistics) and the pre-computed Transcript Score:

```json
{to_json_block(payload)}
```
"""
