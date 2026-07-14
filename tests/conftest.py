"""
tests/conftest.py

Shared pytest fixtures for the FutureReady test suite.

Sets a dummy `GEMINI_API_KEY` before any application module is imported
(config.py reads it at import time), so the test suite never needs a real
API key or network access. Gemini itself is always mocked in endpoint
tests — no test in this suite makes a real network call.
"""

from __future__ import annotations

import os

os.environ.setdefault("GEMINI_API_KEY", "test-key-not-a-real-secret")
os.environ.setdefault("UPLOAD_DIR", "uploads_test")

import pytest

from models.features import (
    AudioFeature,
    EmotionFeature,
    FaceMeshFeature,
    ResumeAnalysisFeature,
    ResumeFeature,
    SlideAnalysisFeature,
    SlideFeature,
    SlideInfo,
    SpeechIntelligenceFeature,
    TranscriptFeature,
    UnifiedFeatureModel,
)


@pytest.fixture()
def sample_resume_feature() -> ResumeFeature:
    """A realistic, hand-built `ResumeFeature` for analyzer/scoring tests."""
    return ResumeFeature(
        text=(
            "John Doe\njohn.doe@example.com\n+1 555-123-4567\n"
            "Skills\nPython, SQL, AWS, Leadership, Communication\n"
            "Education\nB.Sc. Computer Science, State University\n"
            "Experience\nLed a team of 5 engineers to deliver a project 20% ahead of schedule.\n"
            "Developed an internal tool that reduced processing time by 35%.\n"
            "Projects\nBuilt a personal finance dashboard using Python and SQL.\n"
        ),
        page_count=1,
        headings=["Skills", "Education", "Experience", "Projects"],
        skills=["Python, SQL, AWS, Leadership, Communication"],
        education=["B.Sc. Computer Science, State University"],
        experience=[
            "Led a team of 5 engineers to deliver a project 20% ahead of schedule.",
            "Developed an internal tool that reduced processing time by 35%.",
        ],
        projects=["Built a personal finance dashboard using Python and SQL."],
        word_count=400,
        avg_words_per_page=400.0,
        font_size_min=9.0,
        font_size_max=14.0,
        font_size_avg=10.5,
        distinct_fonts=["Arial", "Arial-Bold"],
    )


@pytest.fixture()
def sample_slide_feature() -> SlideFeature:
    """A realistic, hand-built `SlideFeature` for analyzer/scoring tests."""
    slides = [
        SlideInfo(
            slide_number=1,
            title="Introduction",
            bullets=["Welcome to the presentation"],
            notes="Say hello and introduce the topic.",
            image_count=1,
            chart_count=0,
            table_count=0,
            fonts=["Calibri"],
            colors=["000000"],
            text_length=60,
        ),
        SlideInfo(
            slide_number=2,
            title="Data Overview",
            bullets=["Point one", "Point two", "Point three"],
            notes="",
            image_count=0,
            chart_count=1,
            table_count=0,
            fonts=["Calibri"],
            colors=["000000"],
            text_length=140,
        ),
        SlideInfo(
            slide_number=3,
            title="Conclusion",
            bullets=["Thank you"],
            notes="Wrap up and thank the audience.",
            image_count=0,
            chart_count=0,
            table_count=0,
            fonts=["Calibri"],
            colors=["000000"],
            text_length=50,
        ),
    ]
    return SlideFeature(
        slide_count=3,
        slides=slides,
        image_count=1,
        chart_count=1,
        table_count=0,
        fonts=["Calibri"],
        colors=["000000"],
        average_text_length=round((60 + 140 + 50) / 3, 2),
    )


@pytest.fixture()
def sample_transcript_text() -> str:
    """A short but structurally complete sample transcript."""
    return (
        "Hello everyone, good morning. Today I will present our quarterly results. "
        "First, revenue grew by twelve percent this quarter. Next, we expanded into two new markets. "
        "However, operating costs also increased. For example, hiring costs rose sharply. "
        "In addition, marketing spend increased as well. Finally, let's look at next steps. "
        "In conclusion, the quarter was strong overall. Please reach out if you have any questions. "
        "Thank you very much for your time."
    )


@pytest.fixture()
def sample_unified_features(
    sample_resume_feature: ResumeFeature, sample_slide_feature: SlideFeature
) -> UnifiedFeatureModel:
    """A fully populated `UnifiedFeatureModel` covering every modality."""
    from analyzers.cv_analyzer import ResumeAnalyzer
    from analyzers.slide_analyzer import SlideAnalyzer
    from analyzers.transcript_analyzer import TranscriptAnalyzer

    transcript_text = (
        "Hello everyone, good morning. Today I will present our quarterly results. "
        "First, revenue grew by twelve percent this quarter. However, costs also increased. "
        "In conclusion, the quarter was strong overall. Thank you very much."
    )

    resume_analysis: ResumeAnalysisFeature = ResumeAnalyzer().analyze(sample_resume_feature)
    slide_analysis: SlideAnalysisFeature = SlideAnalyzer().analyze(sample_slide_feature)
    transcript: TranscriptFeature = TranscriptAnalyzer().analyze(transcript_text)

    audio = AudioFeature(
        sample_rate=22050,
        duration_sec=60.0,
        channels=1,
        pitch_mean_hz=180.0,
        pitch_std_hz=45.0,
        pitch_min_hz=90.0,
        pitch_max_hz=260.0,
        voiced_ratio=0.7,
        tempo_bpm=110.0,
        rms_mean=0.05,
        rms_std=0.01,
        mfcc_mean=[0.0] * 13,
        mfcc_std=[0.0] * 13,
        chroma_mean=[0.0] * 12,
        spectral_centroid_mean=2000.0,
        spectral_bandwidth_mean=1500.0,
        spectral_rolloff_mean=3500.0,
        zcr_mean=0.05,
        zcr_std=0.01,
        silence_ratio=0.12,
        total_silence_sec=7.2,
        silent_region_count=5,
    )

    speech_intelligence = SpeechIntelligenceFeature(
        transcript=transcript_text,
        language="en",
        segments=[],
        average_confidence=0.9,
        duration_sec=60.0,
        words_per_minute=130.0,
        word_count=int(60.0 * 130.0 / 60.0),
    )

    emotion = EmotionFeature(
        emotion_timeline=[],
        emotion_distribution={
            "happy": 0.4,
            "neutral": 0.4,
            "sad": 0.05,
            "fear": 0.05,
            "disgust": 0.02,
            "surprise": 0.05,
            "angry": 0.03,
        },
        dominant_emotion="neutral",
        emotion_consistency=0.55,
        emotion_confidence_mean=0.8,
        positive_emotion_ratio=0.45,
    )

    facemesh = FaceMeshFeature(
        frames_analyzed=60,
        faces_detected_ratio=0.95,
        blink_rate_per_min=17.0,
        eye_openness_mean=0.8,
        eye_contact_ratio=0.75,
        head_pose_pitch_std=4.0,
        head_pose_yaw_std=6.0,
        head_pose_roll_std=3.0,
        head_movement_score=0.2,
        face_stability_ratio=0.85,
    )

    return UnifiedFeatureModel(
        resume=sample_resume_feature,
        slide=sample_slide_feature,
        audio=audio,
        video=None,
        speech_intelligence=speech_intelligence,
        transcript=transcript,
        emotion=emotion,
        facemesh=facemesh,
        resume_analysis=resume_analysis,
        slide_analysis=slide_analysis,
    )
