"""
services/feature_fusion.py

Layer 3 — Feature Fusion Engine.

Combines the raw (Layer 1) and analyzed (Layer 2) features held in a
`UnifiedFeatureModel` into a small set of cross-modal "derived features":
Professionalism, Presentation Density, Communication Confidence, Visual
Engagement, Voice Confidence, and Presentation Readiness. Every formula
below is fixed, documented, and reproducible — no LLM involvement.

Each derived feature degrades gracefully: if the inputs it needs were not
supplied (e.g. no video was uploaded), it falls back to a neutral midpoint
(50.0) rather than crashing, so the pipeline still produces a usable report
for partial submissions.
"""

from __future__ import annotations

from models.features import DerivedFeatures, UnifiedFeatureModel
from utils.logger import get_logger
from utils.scoring_math import band_score, weighted_average

logger = get_logger(__name__)

_NEUTRAL_SCORE = 50.0

# "Healthy" band constants used by the band_score() formulas below. Kept as
# named constants (rather than magic numbers) so the documented rationale is
# visible next to each score and easy to tune from one place.
_IDEAL_PITCH_VARIATION = (0.15, 0.45)
_PITCH_VARIATION_BOUNDS = (0.0, 0.8)
_IDEAL_SILENCE_RATIO = (0.05, 0.25)
_SILENCE_RATIO_BOUNDS = (0.0, 0.6)
_IDEAL_BLINK_RATE = (12.0, 25.0)
_BLINK_RATE_BOUNDS = (0.0, 45.0)


class FeatureFusionEngine:
    """Computes `DerivedFeatures` from a `UnifiedFeatureModel` (Layer 3)."""

    def fuse(self, features: UnifiedFeatureModel) -> DerivedFeatures:
        """Run feature fusion and return the derived, cross-modal features."""
        professionalism = self._professionalism(features)
        presentation_density = self._presentation_density(features)
        communication_confidence = self._communication_confidence(features)
        visual_engagement = self._visual_engagement(features)
        voice_confidence = self._voice_confidence(features)

        presentation_readiness = weighted_average(
            {
                "professionalism": (professionalism, 0.2),
                "presentation_density": (presentation_density, 0.2),
                "communication_confidence": (communication_confidence, 0.2),
                "visual_engagement": (visual_engagement, 0.2),
                "voice_confidence": (voice_confidence, 0.2),
            }
        )

        return DerivedFeatures(
            professionalism=round(professionalism, 2),
            presentation_density=round(presentation_density, 2),
            communication_confidence=round(communication_confidence, 2),
            visual_engagement=round(visual_engagement, 2),
            voice_confidence=round(voice_confidence, 2),
            presentation_readiness=round(presentation_readiness, 2),
        )

    def _professionalism(self, features: UnifiedFeatureModel) -> float:
        """
        Professionalism = weighted blend of resume structure/content signals:
        section completeness (30%), keyword density (25%), action-verb usage
        (25%), length appropriateness (10%), contact info present (10%).
        """
        analysis = features.resume_analysis
        if analysis is None:
            return _NEUTRAL_SCORE

        return 100.0 * weighted_average(
            {
                "section_completeness": (analysis.section_completeness, 0.30),
                "keyword_density": (analysis.keyword_density, 0.25),
                "action_verb_ratio": (analysis.action_verb_ratio, 0.25),
                "length_appropriateness": (analysis.length_appropriateness, 0.10),
                "contact_info_present": (1.0 if analysis.contact_info_present else 0.0, 0.10),
            }
        )

    def _presentation_density(self, features: UnifiedFeatureModel) -> float:
        """
        Presentation Density = weighted blend of slide-deck structure:
        text density (40%), visual richness (30%), structural balance (30%).
        """
        analysis = features.slide_analysis
        if analysis is None:
            return _NEUTRAL_SCORE

        return 100.0 * weighted_average(
            {
                "text_density": (analysis.text_density_score, 0.40),
                "visual_richness": (analysis.visual_richness_score, 0.30),
                "structure_balance": (analysis.structure_balance_score, 0.30),
            }
        )

    def _communication_confidence(self, features: UnifiedFeatureModel) -> float:
        """
        Communication Confidence = weighted blend of transcript vocabulary
        diversity (30%), inverse filler-word usage (30%), voiced-speech
        ratio from acoustic features (20%), and positive-emotion ratio (20%).
        """
        transcript = features.transcript
        audio = features.audio
        emotion = features.emotion

        vocabulary_diversity = transcript.vocabulary_diversity if transcript else None
        filler_inverse = (
            max(0.0, 1.0 - min(transcript.filler_word_ratio * 10, 1.0)) if transcript else None
        )
        voiced_ratio = audio.voiced_ratio if audio else None
        positive_emotion_ratio = emotion.positive_emotion_ratio if emotion else None

        if all(v is None for v in (vocabulary_diversity, filler_inverse, voiced_ratio, positive_emotion_ratio)):
            return _NEUTRAL_SCORE

        return 100.0 * weighted_average(
            {
                "vocabulary_diversity": (vocabulary_diversity, 0.30),
                "filler_inverse": (filler_inverse, 0.30),
                "voiced_ratio": (voiced_ratio, 0.20),
                "positive_emotion_ratio": (positive_emotion_ratio, 0.20),
            }
        )

    def _visual_engagement(self, features: UnifiedFeatureModel) -> float:
        """
        Visual Engagement = weighted blend of eye-contact ratio (50%), face
        framing stability (30%), and a healthy-blink-rate band score (20%).
        """
        facemesh = features.facemesh
        if facemesh is None:
            return _NEUTRAL_SCORE

        blink_score = band_score(
            facemesh.blink_rate_per_min, *_IDEAL_BLINK_RATE, *_BLINK_RATE_BOUNDS
        )

        return 100.0 * weighted_average(
            {
                "eye_contact_ratio": (facemesh.eye_contact_ratio, 0.50),
                "face_stability_ratio": (facemesh.face_stability_ratio, 0.30),
                "blink_score": (blink_score, 0.20),
            }
        )

    def _voice_confidence(self, features: UnifiedFeatureModel) -> float:
        """
        Voice Confidence = weighted blend of words-per-minute band score
        (40%, from Speech Intelligence), pitch-variation band score (30%,
        neither monotone nor erratic), and silence-ratio band score (30%,
        enough pausing without excessive dead air).
        """
        audio = features.audio
        speech = features.speech_intelligence
        if audio is None and speech is None:
            return _NEUTRAL_SCORE

        wpm_score = None
        if speech is not None and speech.words_per_minute > 0:
            wpm_score = band_score(speech.words_per_minute, 110.0, 160.0, 60.0, 220.0)

        pitch_score = None
        silence_score = None
        if audio is not None:
            pitch_variation_ratio = (
                audio.pitch_std_hz / audio.pitch_mean_hz if audio.pitch_mean_hz > 0 else 0.0
            )
            pitch_score = band_score(
                pitch_variation_ratio, *_IDEAL_PITCH_VARIATION, *_PITCH_VARIATION_BOUNDS
            )
            silence_score = band_score(
                audio.silence_ratio, *_IDEAL_SILENCE_RATIO, *_SILENCE_RATIO_BOUNDS
            )

        return 100.0 * weighted_average(
            {
                "wpm_score": (wpm_score, 0.40),
                "pitch_score": (pitch_score, 0.30),
                "silence_score": (silence_score, 0.30),
            }
        )
