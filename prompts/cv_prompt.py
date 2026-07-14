"""
prompts/cv_prompt.py

Builds the resume/CV section of the master evaluation prompt: the
structured resume features, the deterministic resume analysis, and the
already-computed Resume Score. Gemini reasons over this section; it never
sees the raw PDF and never assigns the score itself.
"""

from __future__ import annotations

from models.features import ResumeAnalysisFeature, ResumeFeature
from prompts.base_prompt import to_json_block


def build_resume_section(
    resume: ResumeFeature | None,
    resume_analysis: ResumeAnalysisFeature | None,
    resume_score: int | None,
) -> str:
    """
    Build the resume section of the evaluation prompt.

    Returns an empty string if no resume was supplied, so the section is
    cleanly omitted from the final prompt.
    """
    if resume is None:
        return ""

    payload = {
        "headings": resume.headings,
        "skills": resume.skills,
        "education": resume.education,
        "experience": resume.experience,
        "projects": resume.projects,
        "word_count": resume.word_count,
        "page_count": resume.page_count,
        "distinct_fonts": resume.distinct_fonts,
        "analysis": resume_analysis.model_dump() if resume_analysis else None,
        "resume_score": resume_score,
    }

    return f"""## Resume / CV

Structured resume data, deterministic analysis, and the pre-computed Resume Score:

```json
{to_json_block(payload)}
```
"""
