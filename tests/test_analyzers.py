"""
Unit tests for Layer 2 deterministic analyzers (no LLM, no heavy optional
dependencies): ResumeAnalyzer, SlideAnalyzer, TranscriptAnalyzer.
"""

from __future__ import annotations

from analyzers.cv_analyzer import ResumeAnalyzer
from analyzers.slide_analyzer import SlideAnalyzer
from analyzers.transcript_analyzer import TranscriptAnalyzer
from models.features import ResumeFeature, SlideFeature


class TestResumeAnalyzer:
    def test_full_resume_scores_well_rounded(self, sample_resume_feature: ResumeFeature) -> None:
        result = ResumeAnalyzer().analyze(sample_resume_feature)
        assert result.section_completeness == 1.0  # all 4 sections present
        assert result.contact_info_present is True
        assert result.quantified_achievement_count >= 2  # "20%", "35%"
        assert 0.0 <= result.keyword_density <= 1.0
        assert 0.0 <= result.action_verb_ratio <= 1.0

    def test_empty_resume_returns_zeroed_analysis(self) -> None:
        empty = ResumeFeature(text="", page_count=0, word_count=0, avg_words_per_page=0.0)
        result = ResumeAnalyzer().analyze(empty)
        assert result.section_completeness == 0.0
        assert result.contact_info_present is False
        assert result.quantified_achievement_count == 0

    def test_length_appropriateness_band(self) -> None:
        analyzer = ResumeAnalyzer()
        ideal = ResumeFeature(text="x", page_count=1, word_count=500, avg_words_per_page=500.0)
        too_short = ResumeFeature(text="x", page_count=1, word_count=10, avg_words_per_page=10.0)
        assert analyzer._length_appropriateness(ideal.word_count) == 1.0
        assert analyzer._length_appropriateness(too_short.word_count) < 1.0


class TestSlideAnalyzer:
    def test_full_deck_analysis_in_bounds(self, sample_slide_feature: SlideFeature) -> None:
        result = SlideAnalyzer().analyze(sample_slide_feature)
        for value in (
            result.text_density_score,
            result.visual_richness_score,
            result.consistency_score,
            result.notes_usage_ratio,
            result.title_presence_ratio,
            result.structure_balance_score,
        ):
            assert 0.0 <= value <= 1.0
        # 3/3 slides have titles, 2/3 have notes in the fixture.
        assert result.title_presence_ratio == 1.0
        assert round(result.notes_usage_ratio, 3) == round(2 / 3, 3)

    def test_empty_deck_returns_default(self) -> None:
        empty = SlideFeature(slide_count=0)
        result = SlideAnalyzer().analyze(empty)
        assert result.text_density_score == 0.0
        assert result.visual_richness_score == 0.0


class TestTranscriptAnalyzer:
    def test_structured_transcript_detects_all_parts(self, sample_transcript_text: str) -> None:
        result = TranscriptAnalyzer().analyze(sample_transcript_text)
        assert result.has_opening is True
        assert result.has_conclusion is True
        assert result.has_call_to_action is True
        assert result.has_body is True
        assert result.word_count > 0
        assert result.sentence_count > 0
        assert 0.0 <= result.vocabulary_diversity <= 1.0
        assert 0.0 <= result.topic_consistency <= 1.0
        assert result.estimated_cefr in {"A1", "A2", "B1", "B2", "C1", "C2"}

    def test_empty_transcript_returns_default(self) -> None:
        result = TranscriptAnalyzer().analyze("")
        assert result.word_count == 0
        assert result.sentence_count == 0
        assert result.estimated_cefr == "A1"

    def test_filler_words_are_counted(self) -> None:
        transcript = "So, um, I think, uh, this is like, you know, a good idea."
        result = TranscriptAnalyzer().analyze(transcript)
        assert result.filler_word_count > 0
        assert result.filler_word_ratio > 0.0
