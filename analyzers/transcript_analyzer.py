"""
analyzers/transcript_analyzer.py

Deterministic, non-LLM linguistic analysis of a speech transcript (produced
by the Whisper-based `analyzers/speech_analyzer.py`). Computes word/sentence
statistics, vocabulary diversity, filler-word usage, a rough grammar-issue
estimate, opening/body/conclusion/call-to-action detection, topic
consistency, an estimated CEFR band, and keyword coverage. No LLM is
involved — everything here is regex/statistics based and fully reproducible.
"""

from __future__ import annotations

import re
import statistics
from collections import Counter

from analyzers.base import BaseAnalyzer
from models.features import TranscriptFeature
from utils.logger import get_logger

logger = get_logger(__name__)

_WORD_PATTERN = re.compile(r"[A-Za-zÀ-ỹ]+(?:'[A-Za-z]+)?", re.UNICODE)
_SENTENCE_SPLIT_PATTERN = re.compile(r"[.!?]+")

_STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "and", "or", "but", "of",
    "to", "in", "on", "for", "with", "it", "this", "that", "i", "you", "we",
    "they", "so", "as", "at", "be", "have", "has", "do", "does", "la", "va",
    "va", "la", "cua", "va", "va", "la",
}

_FILLER_WORDS: set[str] = {
    "um", "uh", "erm", "like", "actually", "basically", "literally",
    "you know", "kind of", "sort of", "i mean",
    "à", "ừ", "thì", "kiểu", "đại loại", "kiểu như",
}

_OPENING_KEYWORDS: list[str] = [
    "hello", "hi everyone", "good morning", "good afternoon", "today i will",
    "today i'm going to", "let me introduce", "xin chào", "hôm nay tôi sẽ",
    "kính chào",
]
_CONCLUSION_KEYWORDS: list[str] = [
    "in conclusion", "to conclude", "to summarize", "in summary",
    "thank you", "thanks for", "tóm lại", "kết luận", "cảm ơn",
]
_CTA_KEYWORDS: list[str] = [
    "please", "let's", "feel free to", "reach out", "contact", "sign up",
    "get started", "hãy", "liên hệ", "đăng ký",
]

# Discourse/transition markers used to approximate topical/logical coherence
# signaling (a proxy for "keyword coverage" of well-structured speech).
_DISCOURSE_MARKERS: set[str] = {
    "first", "second", "third", "next", "then", "however", "therefore",
    "for example", "in addition", "moreover", "furthermore", "finally",
    "as a result", "on the other hand", "thứ nhất", "thứ hai", "tiếp theo",
    "tuy nhiên", "vì vậy", "ví dụ", "cuối cùng",
}

_MIN_BODY_WORD_COUNT = 50
_RUN_ON_SENTENCE_WORD_THRESHOLD = 40
_MIN_SENTENCE_WORD_COUNT = 2


class TranscriptAnalyzer(BaseAnalyzer[str, TranscriptFeature]):
    """Deterministic linguistic analysis of a transcript string (Layer 2)."""

    def analyze(self, data: str) -> TranscriptFeature:
        """Analyze a raw transcript string and return a `TranscriptFeature`."""
        transcript = (data or "").strip()
        if not transcript:
            return TranscriptFeature()

        words = [w.lower() for w in _WORD_PATTERN.findall(transcript)]
        sentences = [s.strip() for s in _SENTENCE_SPLIT_PATTERN.split(transcript) if s.strip()]

        word_count = len(words)
        sentence_count = len(sentences)
        vocabulary_diversity = round(len(set(words)) / word_count, 3) if word_count else 0.0

        repeated_words = self._repeated_words(words)
        filler_count, filler_ratio = self._filler_word_stats(transcript, word_count)
        grammar_issue_estimate = self._grammar_issue_estimate(sentences)

        lower_transcript = transcript.lower()
        has_opening = self._contains_any(lower_transcript[: max(len(lower_transcript) // 4, 1)], _OPENING_KEYWORDS)
        has_conclusion = self._contains_any(lower_transcript[-max(len(lower_transcript) // 4, 1):], _CONCLUSION_KEYWORDS)
        has_cta = self._contains_any(lower_transcript, _CTA_KEYWORDS)
        has_body = word_count >= _MIN_BODY_WORD_COUNT

        topic_consistency = self._topic_consistency(words)
        estimated_cefr = self._estimate_cefr(words, sentences, vocabulary_diversity)
        keyword_coverage = self._keyword_coverage(lower_transcript)

        return TranscriptFeature(
            word_count=word_count,
            sentence_count=sentence_count,
            vocabulary_diversity=vocabulary_diversity,
            repeated_words=repeated_words,
            filler_word_count=filler_count,
            filler_word_ratio=filler_ratio,
            grammar_issue_estimate=grammar_issue_estimate,
            has_opening=has_opening,
            has_body=has_body,
            has_conclusion=has_conclusion,
            has_call_to_action=has_cta,
            topic_consistency=topic_consistency,
            estimated_cefr=estimated_cefr,
            keyword_coverage=keyword_coverage,
        )

    @staticmethod
    def _contains_any(text: str, keywords: list[str]) -> bool:
        return any(keyword in text for keyword in keywords)

    @staticmethod
    def _repeated_words(words: list[str], top_n: int = 10, min_count: int = 3) -> dict[str, int]:
        """Return the most frequently repeated non-stopword words (potential crutch words)."""
        counts = Counter(w for w in words if w not in _STOPWORDS and len(w) > 2)
        return {word: count for word, count in counts.most_common(top_n) if count >= min_count}

    @staticmethod
    def _filler_word_stats(transcript: str, word_count: int) -> tuple[int, float]:
        """Count filler-word occurrences (including multi-word fillers) and their ratio."""
        lower = transcript.lower()
        count = sum(len(re.findall(rf"\b{re.escape(filler)}\b", lower)) for filler in _FILLER_WORDS)
        ratio = round(count / word_count, 4) if word_count else 0.0
        return count, ratio

    @staticmethod
    def _grammar_issue_estimate(sentences: list[str]) -> int:
        """
        Heuristic grammar-issue count: sentences that are likely run-ons
        (too many words with no punctuation break) or fragments (too few
        words to form a complete thought).
        """
        issues = 0
        for sentence in sentences:
            word_count = len(_WORD_PATTERN.findall(sentence))
            if word_count > _RUN_ON_SENTENCE_WORD_THRESHOLD:
                issues += 1
            elif 0 < word_count < _MIN_SENTENCE_WORD_COUNT:
                issues += 1
        return issues

    @staticmethod
    def _topic_consistency(words: list[str]) -> float:
        """
        Approximate topical coherence by splitting the transcript into four
        equal chunks, building a bag-of-words vector per chunk, and averaging
        pairwise cosine similarity between adjacent chunks. A speech that
        stays on-topic will use overlapping vocabulary across chunks.
        """
        content_words = [w for w in words if w not in _STOPWORDS and len(w) > 2]
        if len(content_words) < 8:
            return 0.0

        chunk_count = 4
        chunk_size = max(len(content_words) // chunk_count, 1)
        chunks = [
            content_words[i * chunk_size : (i + 1) * chunk_size] for i in range(chunk_count)
        ]
        chunks = [chunk for chunk in chunks if chunk]
        if len(chunks) < 2:
            return 0.0

        vectors = [Counter(chunk) for chunk in chunks]
        similarities = []
        for i in range(len(vectors) - 1):
            similarities.append(TranscriptAnalyzer._cosine_similarity(vectors[i], vectors[i + 1]))

        return round(statistics.mean(similarities), 3) if similarities else 0.0

    @staticmethod
    def _cosine_similarity(a: Counter, b: Counter) -> float:
        """Cosine similarity between two sparse bag-of-words vectors."""
        shared_keys = set(a) & set(b)
        numerator = sum(a[k] * b[k] for k in shared_keys)
        norm_a = statistics.sqrt(sum(v * v for v in a.values()))
        norm_b = statistics.sqrt(sum(v * v for v in b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return numerator / (norm_a * norm_b)

    @staticmethod
    def _estimate_cefr(words: list[str], sentences: list[str], vocabulary_diversity: float) -> str:
        """
        Heuristic CEFR (A1-C2) estimate based on average word length, average
        sentence length, and vocabulary diversity. This is a coarse proxy,
        not a calibrated linguistic assessment.
        """
        if not words or not sentences:
            return "A1"

        avg_word_len = statistics.mean(len(w) for w in words)
        avg_sentence_len = len(words) / len(sentences)

        # Composite score combining sentence complexity, word complexity, and
        # vocabulary range. Weights are documented and fixed for reproducibility.
        composite = (
            0.4 * min(avg_sentence_len / 20, 1.0)
            + 0.3 * min(avg_word_len / 7, 1.0)
            + 0.3 * vocabulary_diversity
        )

        if composite < 0.2:
            return "A1"
        if composite < 0.4:
            return "A2"
        if composite < 0.55:
            return "B1"
        if composite < 0.7:
            return "B2"
        if composite < 0.85:
            return "C1"
        return "C2"

    @staticmethod
    def _keyword_coverage(lower_transcript: str) -> float:
        """Fraction of known discourse/transition markers found in the transcript."""
        if not _DISCOURSE_MARKERS:
            return 0.0
        hits = sum(1 for marker in _DISCOURSE_MARKERS if marker in lower_transcript)
        return round(min(hits / len(_DISCOURSE_MARKERS), 1.0), 3)
