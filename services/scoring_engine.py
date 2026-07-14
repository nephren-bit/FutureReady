"""
services/scoring_engine.py

Layer 4 — Deterministic Scoring Engine.

Computes every score the API returns (resume, slide, speech, transcript,
emotion, eye contact, voice confidence, presentation, communication,
overall) from `UnifiedFeatureModel` + `DerivedFeatures`. Every formula is
fixed, documented, and reproducible: the same inputs always produce the
same scores. Gemini (Layer 6) never sees this logic and never calculates a
score — it only reasons over the finished numbers.

A sub-score is `None` when its underlying material was not supplied (e.g.
no resume was uploaded). `overall_score` is always populated: it is a
weighted average over whichever material-level scores ARE available,
renormalized so the weights still sum to 1.0.
"""

from __future__ import annotations

from models.features import DerivedFeatures, ScoreBreakdown, UnifiedFeatureModel
from utils.logger import get_logger
from utils.scoring_math import band_score, clamp_score, weighted_average

logger = get_logger(__name__)

_IDEAL_PITCH_VARIATION = (0.15, 0.45)
_PITCH_VARIATION_BOUNDS = (0.0, 0.8)
_IDEAL_SILENCE_RATIO = (0.05, 0.25)
_SILENCE_RATIO_BOUNDS = (0.0, 0.6)
_IDEAL_EMOTION_CONSISTENCY = (0.40, 0.75)
_EMOTION_CONSISTENCY_BOUNDS = (0.10, 1.0)
_IDEAL_BLINK_RATE = (12.0, 25.0)
_BLINK_RATE_BOUNDS = (0.0, 45.0)

# Weights for the final `overall_score`, applied only to the material-level
# scores (resume/slide/speech/transcript/emotion/eye_contact) so the
# composite communication/presentation scores are not double-counted.
_OVERALL_WEIGHTS = {
    "resume_score": 0.20,
    "slide_score": 0.15,
    "speech_score": 0.15,
    "transcript_score": 0.20,
    "emotion_score": 0.10,
    "eye_contact_score": 0.20,
}


class ScoringEngine:
    """Computes the full `ScoreBreakdown` for a `UnifiedFeatureModel` (Layer 4)."""

    def score(self, features: UnifiedFeatureModel, derived: DerivedFeatures) -> ScoreBreakdown:
        """Run deterministic scoring and return every score field."""
        resume_score = self._resume_score(features)
        slide_score = self._slide_score(features)
        speech_score = self._speech_score(features)
        transcript_score = self._transcript_score(features)
        emotion_score = self._emotion_score(features)
        eye_contact_score = self._eye_contact_score(features)
        voice_confidence_score = self._voice_confidence_score(features, derived)

        presentation_score = self._presentation_score(slide_score, eye_contact_score, derived)
        communication_score = self._communication_score(
            transcript_score, speech_score, emotion_score, voice_confidence_score
        )
        overall_score = self._overall_score(
            resume_score, slide_score, speech_score, transcript_score, emotion_score, eye_contact_score
        )

        return ScoreBreakdown(
            resume_score=resume_score,
            slide_score=slide_score,
            speech_score=speech_score,
            transcript_score=transcript_score,
            emotion_score=emotion_score,
            eye_contact_score=eye_contact_score,
            voice_confidence_score=voice_confidence_score,
            presentation_score=presentation_score,
            communication_score=communication_score,
            overall_score=overall_score,
        )

    def _resume_score(self, features: UnifiedFeatureModel) -> int | None:
        """Resume Score = same weighted blend as Professionalism (Layer 3), scaled 0-100."""
        analysis = features.resume_analysis
        if analysis is None:
            return None
        value = 100.0 * weighted_average(
            {
                "section_completeness": (analysis.section_completeness, 0.30),
                "keyword_density": (analysis.keyword_density, 0.25),
                "action_verb_ratio": (analysis.action_verb_ratio, 0.25),
                "length_appropriateness": (analysis.length_appropriateness, 0.10),
                "contact_info_present": (1.0 if analysis.contact_info_present else 0.0, 0.10),
            }
        )
        return clamp_score(value)

    def _slide_score(self, features: UnifiedFeatureModel) -> int | None:
        """
        Slide Score = text density (30%) + visual richness (20%) + structural
        balance (20%) + font/color consistency (15%) + notes usage (7.5%) +
        title presence (7.5%).
        """
        analysis = features.slide_analysis
        if analysis is None:
            return None
        value = 100.0 * weighted_average(
            {
                "text_density": (analysis.text_density_score, 0.30),
                "visual_richness": (analysis.visual_richness_score, 0.20),
                "structure_balance": (analysis.structure_balance_score, 0.20),
                "consistency": (analysis.consistency_score, 0.15),
                "notes_usage": (analysis.notes_usage_ratio, 0.075),
                "title_presence": (analysis.title_presence_ratio, 0.075),
            }
        )
        return clamp_score(value)

    def _speech_score(self, features: UnifiedFeatureModel) -> int | None:
        """
        Speech (vocal delivery) Score = pitch-variation band score (40%) +
        silence-ratio band score (30%) + voiced-speech ratio (30%), all from
        raw acoustic features (Librosa).
        """
        audio = features.audio
        if audio is None:
            return None

        pitch_variation_ratio = (
            audio.pitch_std_hz / audio.pitch_mean_hz if audio.pitch_mean_hz > 0 else 0.0
        )
        pitch_score = band_score(
            pitch_variation_ratio, *_IDEAL_PITCH_VARIATION, *_PITCH_VARIATION_BOUNDS
        )
        silence_score = band_score(audio.silence_ratio, *_IDEAL_SILENCE_RATIO, *_SILENCE_RATIO_BOUNDS)
        voiced_score = min(audio.voiced_ratio, 1.0)

        value = 100.0 * weighted_average(
            {
                "pitch_score": (pitch_score, 0.40),
                "silence_score": (silence_score, 0.30),
                "voiced_score": (voiced_score, 0.30),
            }
        )
        return clamp_score(value)

    def _transcript_score(self, features: UnifiedFeatureModel) -> int | None:
        """
        Transcript Score = vocabulary diversity (25%) + structure coverage
        (opening/body/conclusion/CTA average, 20%) + inverse filler ratio
        (15%) + topic consistency (15%) + inverse grammar-issue rate (15%) +
        keyword coverage (10%).
        """
        transcript = features.transcript
        if transcript is None:
            return None

        structure_flags = [
            transcript.has_opening,
            transcript.has_body,
            transcript.has_conclusion,
            transcript.has_call_to_action,
        ]
        structure_score = sum(1.0 for flag in structure_flags if flag) / len(structure_flags)
        filler_inverse = max(0.0, 1.0 - min(transcript.filler_word_ratio * 10, 1.0))
        grammar_inverse = max(
            0.0, 1.0 - min(transcript.grammar_issue_estimate / max(transcript.sentence_count, 1), 1.0)
        )

        value = 100.0 * weighted_average(
            {
                "vocabulary_diversity": (transcript.vocabulary_diversity, 0.25),
                "structure_score": (structure_score, 0.20),
                "filler_inverse": (filler_inverse, 0.15),
                "topic_consistency": (transcript.topic_consistency, 0.15),
                "grammar_inverse": (grammar_inverse, 0.15),
                "keyword_coverage": (transcript.keyword_coverage, 0.10),
            }
        )
        return clamp_score(value)

    def _emotion_score(self, features: UnifiedFeatureModel) -> int | None:
        """
        Emotion Score = positive-emotion ratio (50%) + healthy emotion-
        consistency band score (30%, penalizing both flat and erratic affect)
        + mean detection confidence (20%).
        """
        emotion = features.emotion
        if emotion is None:
            return None

        consistency_score = band_score(
            emotion.emotion_consistency, *_IDEAL_EMOTION_CONSISTENCY, *_EMOTION_CONSISTENCY_BOUNDS
        )
        value = 100.0 * weighted_average(
            {
                "positive_emotion_ratio": (emotion.positive_emotion_ratio, 0.50),
                "consistency_score": (consistency_score, 0.30),
                "confidence_mean": (emotion.emotion_confidence_mean, 0.20),
            }
        )
        return clamp_score(value)

    def _eye_contact_score(self, features: UnifiedFeatureModel) -> int | None:
        """
        Eye Contact Score = eye-contact ratio (50%) + healthy blink-rate band
        score (25%) + inverse head movement (15%) + face stability (10%).
        """
        facemesh = features.facemesh
        if facemesh is None:
            return None

        blink_score = band_score(facemesh.blink_rate_per_min, *_IDEAL_BLINK_RATE, *_BLINK_RATE_BOUNDS)
        movement_inverse = 1.0 - facemesh.head_movement_score

        value = 100.0 * weighted_average(
            {
                "eye_contact_ratio": (facemesh.eye_contact_ratio, 0.50),
                "blink_score": (blink_score, 0.25),
                "movement_inverse": (movement_inverse, 0.15),
                "face_stability": (facemesh.face_stability_ratio, 0.10),
            }
        )
        return clamp_score(value)

    def _voice_confidence_score(
        self, features: UnifiedFeatureModel, derived: DerivedFeatures
    ) -> int | None:
        """Voice Confidence Score is the Layer 3 `voice_confidence` derived feature, rounded."""
        if features.audio is None and features.speech_intelligence is None:
            return None
        return clamp_score(derived.voice_confidence)

    def _presentation_score(
        self, slide_score: int | None, eye_contact_score: int | None, derived: DerivedFeatures
    ) -> int | None:
        """
        Presentation Score = slide quality (50%) + visual engagement (30%,
        from Layer 3) + eye contact (20%). `None` only if no presentation
        material (slides or video) was supplied at all.
        """
        if slide_score is None and eye_contact_score is None:
            return None
        value = 100.0 * weighted_average(
            {
                "slide_score": (slide_score / 100.0 if slide_score is not None else None, 0.50),
                "visual_engagement": (derived.visual_engagement / 100.0, 0.30),
                "eye_contact_score": (
                    eye_contact_score / 100.0 if eye_contact_score is not None else None, 0.20
                ),
            }
        )
        return clamp_score(value)

    def _communication_score(
        self,
        transcript_score: int | None,
        speech_score: int | None,
        emotion_score: int | None,
        voice_confidence_score: int | None,
    ) -> int | None:
        """
        Communication Score = transcript quality (30%) + vocal delivery
        (25%) + emotional engagement (20%) + voice confidence (25%). `None`
        only if none of these are available.
        """
        if all(s is None for s in (transcript_score, speech_score, emotion_score, voice_confidence_score)):
            return None
        value = 100.0 * weighted_average(
            {
                "transcript": (transcript_score / 100.0 if transcript_score is not None else None, 0.30),
                "speech": (speech_score / 100.0 if speech_score is not None else None, 0.25),
                "emotion": (emotion_score / 100.0 if emotion_score is not None else None, 0.20),
                "voice_confidence": (
                    voice_confidence_score / 100.0 if voice_confidence_score is not None else None, 0.25
                ),
            }
        )
        return clamp_score(value)

    def _overall_score(
        self,
        resume_score: int | None,
        slide_score: int | None,
        speech_score: int | None,
        transcript_score: int | None,
        emotion_score: int | None,
        eye_contact_score: int | None,
    ) -> int:
        """
        Overall Score = weighted average over whichever material-level
        scores are available (see `_OVERALL_WEIGHTS`), renormalized. Returns
        0 only if literally no material was supplied.
        """
        scores = {
            "resume_score": resume_score,
            "slide_score": slide_score,
            "speech_score": speech_score,
            "transcript_score": transcript_score,
            "emotion_score": emotion_score,
            "eye_contact_score": eye_contact_score,
        }
        components = {
            name: (float(value) if value is not None else None, _OVERALL_WEIGHTS[name])
            for name, value in scores.items()
        }
        return clamp_score(weighted_average(components))
