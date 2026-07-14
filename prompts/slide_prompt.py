"""
prompts/slide_prompt.py

Builds the presentation/slide-deck section of the master evaluation
prompt: the full per-slide CONTENT (title, bullets, speaker notes) so
Gemini can judge the actual message -- clarity, relevance, narrative flow,
jargon, whether claims are well-supported -- not just the deterministic
design/structure analysis and the already-computed Slide Score, which only
capture layout-level signals (text density, image/chart counts, font
consistency, etc.) and say nothing about what the slides actually say.
"""

from __future__ import annotations

from models.features import SlideAnalysisFeature, SlideFeature
from prompts.base_prompt import to_json_block


def build_slide_section(
    slide: SlideFeature | None,
    slide_analysis: SlideAnalysisFeature | None,
    slide_score: int | None,
) -> str:
    """
    Build the slide-deck section of the evaluation prompt.

    Returns an empty string if no presentation was supplied.
    """
    if slide is None:
        return ""

    payload = {
        "slide_count": slide.slide_count,
        "slides": [
            {
                "slide_number": s.slide_number,
                "title": s.title,
                "bullets": s.bullets,
                "notes": s.notes,
            }
            for s in slide.slides
        ],
        "image_count": slide.image_count,
        "chart_count": slide.chart_count,
        "table_count": slide.table_count,
        "fonts": slide.fonts,
        "colors": slide.colors,
        "average_text_length": slide.average_text_length,
        "analysis": slide_analysis.model_dump() if slide_analysis else None,
        "slide_score": slide_score,
    }

    return f"""## Presentation Slides

Full per-slide content (title, bullet points, and speaker notes for every
slide) plus deterministic design/structure analysis and the pre-computed
Slide Score. Judge the CONTENT itself -- is the message on each slide
clear, relevant, well-organized, and appropriately detailed for its
audience? Are claims specific/credible rather than vague filler? Does the
notes text add real substance or is it empty/boilerplate? -- in addition to
the structural metrics below:

```json
{to_json_block(payload)}
```
"""
