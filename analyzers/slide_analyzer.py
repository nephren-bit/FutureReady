"""
analyzers/slide_analyzer.py

Deterministic, non-LLM analysis of an already-extracted presentation
(`SlideFeature`). Computes structural/design signals — text density, visual
richness, font/color consistency, notes usage, title presence, and
structural balance across slides — that the Scoring Engine (Layer 4) later
turns into the Slide Score.
"""

from __future__ import annotations

import statistics

from analyzers.base import BaseAnalyzer
from models.features import SlideAnalysisFeature, SlideFeature
from utils.logger import get_logger

logger = get_logger(__name__)

# Ideal per-slide text length band (characters) used for `text_density_score`.
# Slides with too little text look empty; slides with too much are hard to
# present from and tend to be read verbatim rather than delivered.
_IDEAL_MIN_CHARS = 40
_IDEAL_MAX_CHARS = 220


class SlideAnalyzer(BaseAnalyzer[SlideFeature, SlideAnalysisFeature]):
    """Deterministic structural/design analysis of a slide deck (Layer 2)."""

    def analyze(self, data: SlideFeature) -> SlideAnalysisFeature:
        """Analyze a `SlideFeature` and return a `SlideAnalysisFeature`."""
        if data.slide_count == 0:
            return SlideAnalysisFeature()

        return SlideAnalysisFeature(
            text_density_score=self._text_density_score(data.average_text_length),
            visual_richness_score=self._visual_richness_score(data),
            consistency_score=self._consistency_score(data),
            notes_usage_ratio=self._ratio(
                sum(1 for slide in data.slides if slide.notes.strip()), data.slide_count
            ),
            title_presence_ratio=self._ratio(
                sum(1 for slide in data.slides if slide.title.strip()), data.slide_count
            ),
            structure_balance_score=self._structure_balance_score(data),
        )

    @staticmethod
    def _ratio(count: int, total: int) -> float:
        return round(count / total, 3) if total else 0.0

    @staticmethod
    def _text_density_score(average_text_length: float) -> float:
        """
        Score how close average per-slide text length is to the ideal band.

        Returns 1.0 inside [_IDEAL_MIN_CHARS, _IDEAL_MAX_CHARS], decaying
        linearly to 0.0 as it approaches zero (too sparse) or triple the
        upper bound (wall-of-text slides).
        """
        if _IDEAL_MIN_CHARS <= average_text_length <= _IDEAL_MAX_CHARS:
            return 1.0
        if average_text_length < _IDEAL_MIN_CHARS:
            return round(max(average_text_length / _IDEAL_MIN_CHARS, 0.0), 3)
        ceiling = _IDEAL_MAX_CHARS * 3
        return round(max((ceiling - average_text_length) / (ceiling - _IDEAL_MAX_CHARS), 0.0), 3)

    @staticmethod
    def _visual_richness_score(data: SlideFeature) -> float:
        """Ratio of visual elements (images+charts+tables) to slide count, capped at 1.0."""
        visual_elements = data.image_count + data.chart_count + data.table_count
        return round(min(visual_elements / data.slide_count, 1.0), 3)

    @staticmethod
    def _consistency_score(data: SlideFeature) -> float:
        """
        Font/color consistency: fewer distinct fonts and colors relative to
        the number of slides indicates a more consistent visual identity.
        """
        diversity = len(data.fonts) + len(data.colors)
        penalty = min(diversity / (data.slide_count * 2), 1.0)
        return round(1.0 - penalty, 3)

    @staticmethod
    def _structure_balance_score(data: SlideFeature) -> float:
        """
        Structural balance: lower relative variance in per-slide text length
        (coefficient of variation) means content is spread more evenly
        across the deck rather than concentrated on a few dense slides.
        """
        lengths = [slide.text_length for slide in data.slides]
        if len(lengths) < 2 or sum(lengths) == 0:
            return 1.0 if sum(lengths) == 0 else 0.5
        mean_length = statistics.mean(lengths)
        if mean_length == 0:
            return 0.5
        stdev = statistics.pstdev(lengths)
        coefficient_of_variation = stdev / mean_length
        return round(max(1.0 - min(coefficient_of_variation, 1.0), 0.0), 3)
