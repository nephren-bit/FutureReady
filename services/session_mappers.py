"""
services/session_mappers.py

Two-way conversion between the persistence layer (`db/models.py` ORM rows)
and the pipeline's strongly-typed Pydantic feature models
(`models/features.py`). Kept in its own module, separate from
`EvaluationWorkflowManager`, so the orchestration logic never has to know
column-level details and the mapping can be unit-tested in isolation.

Convention: `*_to_orm` builds (but does not `add`/`commit`) an ORM row from
one or more Pydantic models; `orm_to_*` rebuilds the Pydantic model(s) from
a persisted row. Round-tripping through these functions must be lossless
for every field the pipeline actually uses.
"""

from __future__ import annotations

import uuid

from db.models import (
    EmotionFeatureORM,
    FaceMeshFeatureORM,
    ResumeFeatureORM,
    SlideFeatureORM,
    SpeechFeatureORM,
    TranscriptFeatureORM,
    VideoFeatureORM,
)
from models.features import (
    EmotionFeature,
    FaceMeshFeature,
    ResumeAnalysisFeature,
    ResumeFeature,
    SlideAnalysisFeature,
    SlideFeature,
    SpeechIntelligenceFeature,
    TranscriptFeature,
    VideoFeature,
)

# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------


def resume_to_orm(
    session_id: uuid.UUID, feature: ResumeFeature, analysis: ResumeAnalysisFeature
) -> ResumeFeatureORM:
    return ResumeFeatureORM(session_id=session_id, **feature.model_dump(), **analysis.model_dump())


def orm_to_resume(row: ResumeFeatureORM) -> tuple[ResumeFeature, ResumeAnalysisFeature]:
    feature = ResumeFeature(
        text=row.text,
        page_count=row.page_count,
        headings=row.headings,
        skills=row.skills,
        education=row.education,
        experience=row.experience,
        projects=row.projects,
        word_count=row.word_count,
        avg_words_per_page=row.avg_words_per_page,
        font_size_min=row.font_size_min,
        font_size_max=row.font_size_max,
        font_size_avg=row.font_size_avg,
        distinct_fonts=row.distinct_fonts,
    )
    analysis = ResumeAnalysisFeature(
        keyword_density=row.keyword_density,
        action_verb_ratio=row.action_verb_ratio,
        quantified_achievement_count=row.quantified_achievement_count,
        section_completeness=row.section_completeness,
        contact_info_present=row.contact_info_present,
        length_appropriateness=row.length_appropriateness,
    )
    return feature, analysis


# ---------------------------------------------------------------------------
# Slide
# ---------------------------------------------------------------------------


def slide_to_orm(
    session_id: uuid.UUID, feature: SlideFeature, analysis: SlideAnalysisFeature
) -> SlideFeatureORM:
    data = feature.model_dump()  # nested SlideInfo list becomes plain dicts, JSON-serializable as-is
    return SlideFeatureORM(session_id=session_id, **data, **analysis.model_dump())


def orm_to_slide(row: SlideFeatureORM) -> tuple[SlideFeature, SlideAnalysisFeature]:
    feature = SlideFeature(
        slide_count=row.slide_count,
        slides=row.slides,
        image_count=row.image_count,
        chart_count=row.chart_count,
        table_count=row.table_count,
        fonts=row.fonts,
        colors=row.colors,
        average_text_length=row.average_text_length,
    )
    analysis = SlideAnalysisFeature(
        text_density_score=row.text_density_score,
        visual_richness_score=row.visual_richness_score,
        consistency_score=row.consistency_score,
        notes_usage_ratio=row.notes_usage_ratio,
        title_presence_ratio=row.title_presence_ratio,
        structure_balance_score=row.structure_balance_score,
    )
    return feature, analysis


# ---------------------------------------------------------------------------
# Video (raw OpenCV metrics only — see VideoFeatureORM docstring)
# ---------------------------------------------------------------------------


def video_to_orm(session_id: uuid.UUID, feature: VideoFeature) -> VideoFeatureORM:
    return VideoFeatureORM(session_id=session_id, **feature.model_dump())


def orm_to_video(row: VideoFeatureORM) -> VideoFeature:
    return VideoFeature(
        fps=row.fps,
        frame_count=row.frame_count,
        duration_sec=row.duration_sec,
        width=row.width,
        height=row.height,
        sampled_frame_count=row.sampled_frame_count,
        brightness_mean=row.brightness_mean,
        brightness_std=row.brightness_std,
        contrast_mean=row.contrast_mean,
        motion_score_mean=row.motion_score_mean,
        motion_score_std=row.motion_score_std,
        scene_cut_count=row.scene_cut_count,
        blur_score_mean=row.blur_score_mean,
    )


# ---------------------------------------------------------------------------
# Speech (Librosa acoustic + Whisper speech-intelligence, merged)
# ---------------------------------------------------------------------------


def speech_to_orm(
    session_id: uuid.UUID,
    speech_intelligence: SpeechIntelligenceFeature,
    *,
    sample_rate: int = 0,
    pitch_mean_hz: float = 0.0,
    pitch_std_hz: float = 0.0,
    pitch_min_hz: float = 0.0,
    pitch_max_hz: float = 0.0,
    voiced_ratio: float = 0.0,
    tempo_bpm: float = 0.0,
    rms_mean: float = 0.0,
    rms_std: float = 0.0,
    mfcc_mean: list[float] | None = None,
    mfcc_std: list[float] | None = None,
    chroma_mean: list[float] | None = None,
    spectral_centroid_mean: float = 0.0,
    spectral_bandwidth_mean: float = 0.0,
    spectral_rolloff_mean: float = 0.0,
    zcr_mean: float = 0.0,
    zcr_std: float = 0.0,
    silence_ratio: float = 0.0,
    total_silence_sec: float = 0.0,
    silent_region_count: int = 0,
) -> SpeechFeatureORM:
    """
    Build the merged `SpeechFeatureORM` row. Acoustic (Librosa) fields are
    keyword-only with neutral defaults because the video pipeline does not
    always run a standalone Librosa pass (see `AudioFeature` vs.
    `SpeechIntelligenceFeature` in `models/features.py`) — callers that have
    an `AudioFeature` should pass its fields through via
    `**audio_feature.model_dump(exclude={"duration_sec", "channels"})`.
    """
    return SpeechFeatureORM(
        session_id=session_id,
        sample_rate=sample_rate,
        duration_sec=speech_intelligence.duration_sec,
        pitch_mean_hz=pitch_mean_hz,
        pitch_std_hz=pitch_std_hz,
        pitch_min_hz=pitch_min_hz,
        pitch_max_hz=pitch_max_hz,
        voiced_ratio=voiced_ratio,
        tempo_bpm=tempo_bpm,
        rms_mean=rms_mean,
        rms_std=rms_std,
        mfcc_mean=mfcc_mean or [],
        mfcc_std=mfcc_std or [],
        chroma_mean=chroma_mean or [],
        spectral_centroid_mean=spectral_centroid_mean,
        spectral_bandwidth_mean=spectral_bandwidth_mean,
        spectral_rolloff_mean=spectral_rolloff_mean,
        zcr_mean=zcr_mean,
        zcr_std=zcr_std,
        silence_ratio=silence_ratio,
        total_silence_sec=total_silence_sec,
        silent_region_count=silent_region_count,
        transcript_text=speech_intelligence.transcript,
        language=speech_intelligence.language,
        segments=[seg.model_dump() for seg in speech_intelligence.segments],
        average_confidence=speech_intelligence.average_confidence,
        words_per_minute=speech_intelligence.words_per_minute,
        word_count=speech_intelligence.word_count,
    )


def orm_to_speech_intelligence(row: SpeechFeatureORM) -> SpeechIntelligenceFeature:
    return SpeechIntelligenceFeature(
        transcript=row.transcript_text,
        language=row.language,
        segments=row.segments,
        average_confidence=row.average_confidence,
        duration_sec=row.duration_sec,
        words_per_minute=row.words_per_minute,
        word_count=row.word_count,
    )


# ---------------------------------------------------------------------------
# Transcript
# ---------------------------------------------------------------------------


def transcript_to_orm(
    session_id: uuid.UUID, feature: TranscriptFeature, speech_feature_id: uuid.UUID | None = None
) -> TranscriptFeatureORM:
    return TranscriptFeatureORM(
        session_id=session_id, speech_feature_id=speech_feature_id, **feature.model_dump()
    )


def orm_to_transcript(row: TranscriptFeatureORM) -> TranscriptFeature:
    return TranscriptFeature(
        word_count=row.word_count,
        sentence_count=row.sentence_count,
        vocabulary_diversity=row.vocabulary_diversity,
        repeated_words=row.repeated_words,
        filler_word_count=row.filler_word_count,
        filler_word_ratio=row.filler_word_ratio,
        grammar_issue_estimate=row.grammar_issue_estimate,
        has_opening=row.has_opening,
        has_body=row.has_body,
        has_conclusion=row.has_conclusion,
        has_call_to_action=row.has_call_to_action,
        topic_consistency=row.topic_consistency,
        estimated_cefr=row.estimated_cefr,
        keyword_coverage=row.keyword_coverage,
    )


# ---------------------------------------------------------------------------
# Emotion
# ---------------------------------------------------------------------------


def emotion_to_orm(session_id: uuid.UUID, feature: EmotionFeature) -> EmotionFeatureORM:
    return EmotionFeatureORM(session_id=session_id, **feature.model_dump())


def orm_to_emotion(row: EmotionFeatureORM) -> EmotionFeature:
    return EmotionFeature(
        emotion_timeline=row.emotion_timeline,
        emotion_distribution=row.emotion_distribution,
        dominant_emotion=row.dominant_emotion,
        emotion_consistency=row.emotion_consistency,
        emotion_confidence_mean=row.emotion_confidence_mean,
        positive_emotion_ratio=row.positive_emotion_ratio,
    )


# ---------------------------------------------------------------------------
# Face mesh
# ---------------------------------------------------------------------------


def facemesh_to_orm(session_id: uuid.UUID, feature: FaceMeshFeature) -> FaceMeshFeatureORM:
    return FaceMeshFeatureORM(session_id=session_id, **feature.model_dump())


def orm_to_facemesh(row: FaceMeshFeatureORM) -> FaceMeshFeature:
    return FaceMeshFeature(
        frames_analyzed=row.frames_analyzed,
        faces_detected_ratio=row.faces_detected_ratio,
        blink_rate_per_min=row.blink_rate_per_min,
        eye_openness_mean=row.eye_openness_mean,
        eye_contact_ratio=row.eye_contact_ratio,
        head_pose_pitch_std=row.head_pose_pitch_std,
        head_pose_yaw_std=row.head_pose_yaw_std,
        head_pose_roll_std=row.head_pose_roll_std,
        head_movement_score=row.head_movement_score,
        face_stability_ratio=row.face_stability_ratio,
    )
