"""
analyzers/cv_analyzer.py

Deterministic, non-LLM analysis of an already-extracted resume
(`ResumeFeature`). Computes structural/content signals — keyword density,
action-verb usage, quantified achievements, section completeness, contact
info presence, and length appropriateness — that the Scoring Engine (Layer
4) later turns into the Resume Score. Gemini never sees this logic; it only
ever sees the finished numbers.
"""

from __future__ import annotations

import re

from analyzers.base import BaseAnalyzer
from models.features import ResumeAnalysisFeature, ResumeFeature
from utils.logger import get_logger

logger = get_logger(__name__)

# A representative (not exhaustive) set of resume/job-market keywords used to
# approximate topical relevance. Kept intentionally generic and bilingual so
# the heuristic degrades gracefully across domains and languages.
_KEYWORDS: set[str] = {
    "python", "java", "javascript", "sql", "aws", "cloud", "docker", "kubernetes",
    "leadership", "team", "project", "manage", "managed", "develop", "developed",
    "design", "designed", "analysis", "analyzed", "research", "communication",
    "agile", "scrum", "data", "machine learning", "ai", "product", "customer",
    "kỹ năng", "quản lý", "phát triển", "dự án", "phân tích", "giao tiếp",
}

# Action verbs commonly used to open resume bullet points (English + Vietnamese).
_ACTION_VERBS: set[str] = {
    "led", "built", "created", "developed", "designed", "managed", "improved",
    "launched", "implemented", "analyzed", "reduced", "increased", "delivered",
    "optimized", "automated", "coordinated", "achieved", "organized",
    "phát triển", "xây dựng", "quản lý", "thiết kế", "tối ưu", "triển khai",
}

_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{2,4}\)?[ .-]?){2,4}\d{2,4}")
_NUMBER_PATTERN = re.compile(r"\d+[%+]?|\$\s?\d+")

# Ideal resume length band, in words, used for `length_appropriateness`.
_IDEAL_MIN_WORDS = 250
_IDEAL_MAX_WORDS = 900


class ResumeAnalyzer(BaseAnalyzer[ResumeFeature, ResumeAnalysisFeature]):
    """Deterministic structural/content analysis of a resume (Layer 2)."""

    def analyze(self, data: ResumeFeature) -> ResumeAnalysisFeature:
        """Analyze a `ResumeFeature` and return a `ResumeAnalysisFeature`."""
        bullet_lines = data.experience + data.projects
        keyword_density = self._keyword_density(data.text)
        action_verb_ratio = self._action_verb_ratio(bullet_lines)
        quantified_count = self._count_quantified_achievements(bullet_lines)
        section_completeness = self._section_completeness(data)
        contact_present = bool(_EMAIL_PATTERN.search(data.text)) or bool(
            _PHONE_PATTERN.search(data.text)
        )
        length_score = self._length_appropriateness(data.word_count)

        return ResumeAnalysisFeature(
            keyword_density=keyword_density,
            action_verb_ratio=action_verb_ratio,
            quantified_achievement_count=quantified_count,
            section_completeness=section_completeness,
            contact_info_present=contact_present,
            length_appropriateness=length_score,
        )

    @staticmethod
    def _keyword_density(text: str) -> float:
        """Fraction of the reference keyword set found (case-insensitive) in the text."""
        if not _KEYWORDS:
            return 0.0
        text_lower = text.lower()
        hits = sum(1 for keyword in _KEYWORDS if keyword in text_lower)
        return round(min(hits / len(_KEYWORDS), 1.0), 3)

    @staticmethod
    def _action_verb_ratio(bullet_lines: list[str]) -> float:
        """Fraction of bullet lines that open with a recognized action verb."""
        if not bullet_lines:
            return 0.0
        matches = 0
        for line in bullet_lines:
            first_word = line.strip().split(" ", 1)[0].lower().strip(".,;:")
            if first_word in _ACTION_VERBS:
                matches += 1
        return round(matches / len(bullet_lines), 3)

    @staticmethod
    def _count_quantified_achievements(bullet_lines: list[str]) -> int:
        """Count bullet lines that contain a number, percentage, or currency amount."""
        return sum(1 for line in bullet_lines if _NUMBER_PATTERN.search(line))

    @staticmethod
    def _section_completeness(data: ResumeFeature) -> float:
        """Fraction of the four core sections (skills/education/experience/projects) present."""
        sections = [data.skills, data.education, data.experience, data.projects]
        present = sum(1 for section in sections if section)
        return round(present / len(sections), 3)

    @staticmethod
    def _length_appropriateness(word_count: int) -> float:
        """
        Score how close the resume's word count is to an ideal band.

        Returns 1.0 inside the ideal band [_IDEAL_MIN_WORDS, _IDEAL_MAX_WORDS],
        decaying linearly to 0.0 as the word count moves to half (too short)
        or double (too long) the band's edges.
        """
        if word_count <= 0:
            return 0.0
        if _IDEAL_MIN_WORDS <= word_count <= _IDEAL_MAX_WORDS:
            return 1.0
        if word_count < _IDEAL_MIN_WORDS:
            floor = _IDEAL_MIN_WORDS / 2
            return round(max((word_count - floor) / (_IDEAL_MIN_WORDS - floor), 0.0), 3)
        ceiling = _IDEAL_MAX_WORDS * 2
        return round(max((ceiling - word_count) / (ceiling - _IDEAL_MAX_WORDS), 0.0), 3)
