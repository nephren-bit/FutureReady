"""
prompts/speech_prompt.py

Builds the vocal-delivery and on-camera-presence section of the master
evaluation prompt: acoustic features (Librosa), Whisper speech intelligence
metadata, facial emotion analysis (HSEmotion), face mesh / eye contact
analysis (MediaPipe), and their already-computed scores (Speech, Emotion,
Eye Contact, Voice Confidence).
"""

from __future__ import annotations

from models.features import AudioFeature, EmotionFeature, FaceMeshFeature, SpeechIntelligenceFeature
from prompts.base_prompt import to_json_block


def build_speech_section(
    audio: AudioFeature | None,
    speech_intelligence: SpeechIntelligenceFeature | None,
    emotion: EmotionFeature | None,
    facemesh: FaceMeshFeature | None,
    speech_score: int | None,
    emotion_score: int | None,
    eye_contact_score: int | None,
    voice_confidence_score: int | None,
) -> str:
    """
    Build the vocal-delivery / on-camera-presence section of the evaluation
    prompt. Returns an empty string if none of the underlying inputs were
    supplied.
    """
    if all(v is None for v in (audio, speech_intelligence, emotion, facemesh)):
        return ""

    payload = {
        "acoustic_features": audio.model_dump() if audio else None,
        "speech_intelligence": (
            {
                "language": speech_intelligence.language,
                "duration_sec": speech_intelligence.duration_sec,
                "words_per_minute": speech_intelligence.words_per_minute,
                "word_count": speech_intelligence.word_count,
                "average_confidence": speech_intelligence.average_confidence,
            }
            if speech_intelligence
            else None
        ),
        "emotion_analysis": emotion.model_dump() if emotion else None,
        "face_mesh_analysis": facemesh.model_dump() if facemesh else None,
        "speech_score": speech_score,
        "emotion_score": emotion_score,
        "eye_contact_score": eye_contact_score,
        "voice_confidence_score": voice_confidence_score,
    }

    return f"""## Vocal Delivery & On-Camera Presence

Acoustic features, speech-intelligence metadata, facial emotion analysis, and
face-mesh/eye-contact analysis (all produced by traditional signal processing
and computer vision — no LLM), plus their pre-computed scores:

```json
{to_json_block(payload)}
```
"""
