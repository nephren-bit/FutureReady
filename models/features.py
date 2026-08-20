"""
models/features.py

Central, strongly-typed feature schema for the entire FutureReady pipeline.

Design rule (see project README, "Design Principle"): every stage of the
pipeline communicates through these models — never through raw dicts and
never through raw file bytes. This module is the single source of truth for
what a "feature" looks like at every layer:

* Layer 1 (extractors/) — raw, deterministic features pulled straight out of
  a file (PDF/PPTX/MP3/MP4). No AI reasoning happens here.
* Layer 2 (analyzers/) — AI Vision & Speech Intelligence and deterministic
  text/structure analysis, still with **no LLM involvement**.
* Layer 3 (services/feature_fusion.py) — `DerivedFeatures`, computed by
  combining Layer 1 + Layer 2 features.
* Layer 4 (services/scoring_engine.py) — `ScoreBreakdown`, computed
  deterministically from everything above.

Gemini (Layer 6) only ever receives the models defined here (already
extracted, analyzed, fused, and scored) — it never sees a raw file and never
produces a score.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from models.profiles import LandmarkGroup

# ---------------------------------------------------------------------------
# Layer 1 — Extractor features (extractors/)
# ---------------------------------------------------------------------------


class ResumeFeature(BaseModel):
    """Raw structured features extracted from a CV/resume PDF (PyMuPDF)."""

    text: str = Field(..., description="Full extracted text of the resume.")
    page_count: int = Field(..., ge=0)
    headings: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    word_count: int = Field(..., ge=0)
    avg_words_per_page: float = Field(..., ge=0)
    font_size_min: float = 0.0
    font_size_max: float = 0.0
    font_size_avg: float = 0.0
    distinct_fonts: list[str] = Field(default_factory=list)


class SlideInfo(BaseModel):
    """Per-slide structured data extracted from a presentation."""

    slide_number: int = Field(..., ge=1)
    title: str = ""
    bullets: list[str] = Field(default_factory=list)
    notes: str = ""
    image_count: int = 0
    chart_count: int = 0
    table_count: int = 0
    fonts: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    text_length: int = 0


class SlideFeature(BaseModel):
    """Raw structured features extracted from a presentation (python-pptx)."""

    slide_count: int = Field(..., ge=0)
    slides: list[SlideInfo] = Field(default_factory=list)
    image_count: int = 0
    chart_count: int = 0
    table_count: int = 0
    fonts: list[str] = Field(default_factory=list)
    colors: list[str] = Field(default_factory=list)
    average_text_length: float = 0.0


class AudioFeature(BaseModel):
    """Raw acoustic features extracted from a speech recording (Librosa)."""

    sample_rate: int = Field(..., ge=0)
    duration_sec: float = Field(..., ge=0)
    channels: int = 1
    pitch_mean_hz: float = 0.0
    pitch_std_hz: float = 0.0
    pitch_min_hz: float = 0.0
    pitch_max_hz: float = 0.0
    voiced_ratio: float = 0.0
    tempo_bpm: float = 0.0
    rms_mean: float = 0.0
    rms_std: float = 0.0
    mfcc_mean: list[float] = Field(default_factory=list)
    mfcc_std: list[float] = Field(default_factory=list)
    chroma_mean: list[float] = Field(default_factory=list)
    spectral_centroid_mean: float = 0.0
    spectral_bandwidth_mean: float = 0.0
    spectral_rolloff_mean: float = 0.0
    zcr_mean: float = 0.0
    zcr_std: float = 0.0
    silence_ratio: float = 0.0
    total_silence_sec: float = 0.0
    silent_region_count: int = 0


class VideoFeature(BaseModel):
    """Raw structured features extracted from a presentation video (OpenCV)."""

    fps: float = Field(..., ge=0)
    frame_count: int = Field(..., ge=0)
    duration_sec: float = Field(..., ge=0)
    width: int = 0
    height: int = 0
    sampled_frame_count: int = Field(
        ..., ge=0, description="Number of frames sampled for downstream vision analyzers."
    )
    brightness_mean: float = 0.0
    brightness_std: float = 0.0
    contrast_mean: float = 0.0
    motion_score_mean: float = Field(
        0.0, description="Mean inter-frame pixel difference, a proxy for overall movement."
    )
    motion_score_std: float = 0.0
    scene_cut_count: int = Field(
        0, description="Number of abrupt frame-to-frame changes above threshold."
    )
    blur_score_mean: float = Field(
        0.0, description="Mean variance-of-Laplacian; lower means blurrier footage."
    )


# ---------------------------------------------------------------------------
# Layer 2 — AI Vision & Speech Intelligence / deterministic analyzers (analyzers/)
# ---------------------------------------------------------------------------


class TranscriptSegment(BaseModel):
    """A single timestamped segment produced by the speech-to-text model."""

    start_sec: float = 0.0
    end_sec: float = 0.0
    text: str = ""
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class SpeechIntelligenceFeature(BaseModel):
    """Output of the Whisper-based speech analyzer (analyzers/speech_analyzer.py)."""

    transcript: str = ""
    language: str = ""
    segments: list[TranscriptSegment] = Field(default_factory=list)
    average_confidence: float = Field(0.0, ge=0.0, le=1.0)
    duration_sec: float = 0.0
    words_per_minute: float = 0.0
    word_count: int = 0


class TranscriptFeature(BaseModel):
    """Deterministic (non-LLM) linguistic analysis of a transcript."""

    word_count: int = 0
    sentence_count: int = 0
    vocabulary_diversity: float = Field(0.0, ge=0.0, le=1.0, description="Type-token ratio.")
    repeated_words: dict[str, int] = Field(default_factory=dict)
    filler_word_count: int = 0
    filler_word_ratio: float = Field(0.0, ge=0.0)
    grammar_issue_estimate: int = Field(
        0, description="Heuristic count of likely grammar issues (e.g. run-on sentences)."
    )
    has_opening: bool = False
    has_body: bool = False
    has_conclusion: bool = False
    has_call_to_action: bool = False
    topic_consistency: float = Field(0.0, ge=0.0, le=1.0)
    estimated_cefr: str = Field("A1", description="Estimated CEFR band, A1-C2.")
    keyword_coverage: float = Field(0.0, ge=0.0, le=1.0)


class EmotionTimelinePoint(BaseModel):
    """A single sampled point on the emotion timeline."""

    timestamp_sec: float = 0.0
    emotion: str = "neutral"
    confidence: float = Field(0.0, ge=0.0, le=1.0)


class EmotionFeature(BaseModel):
    """Output of the HSEmotion-based facial emotion analyzer."""

    emotion_timeline: list[EmotionTimelinePoint] = Field(default_factory=list)
    emotion_distribution: dict[str, float] = Field(default_factory=dict)
    dominant_emotion: str = "neutral"
    emotion_consistency: float = Field(0.0, ge=0.0, le=1.0)
    emotion_confidence_mean: float = Field(0.0, ge=0.0, le=1.0)
    positive_emotion_ratio: float = Field(0.0, ge=0.0, le=1.0)


class FaceMeshFeature(BaseModel):
    """Output of the MediaPipe Face Mesh analyzer."""

    frames_analyzed: int = 0
    faces_detected_ratio: float = Field(0.0, ge=0.0, le=1.0)
    blink_rate_per_min: float = 0.0
    eye_openness_mean: float = Field(0.0, ge=0.0, le=1.0)
    eye_contact_ratio: float = Field(
        0.0, ge=0.0, le=1.0, description="Fraction of analyzed frames where gaze is toward camera."
    )
    head_up_ratio: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Fallback head-up signal for `PoseFeature.head_up_ratio`, from the nose's "
            "position between the eye line and the chin. None when no face was found."
        ),
    )
    head_pose_pitch_std: float = 0.0
    head_pose_yaw_std: float = 0.0
    head_pose_roll_std: float = 0.0
    head_movement_score: float = Field(0.0, ge=0.0, le=1.0)
    face_stability_ratio: float = Field(0.0, ge=0.0, le=1.0)


class PoseMetric(BaseModel):
    """
    One body-movement metric, carrying its own `measured` flag.

    A metric is only ever `measured=True` when every landmark group it
    declared in the context profile was stably visible. Otherwise `value`
    stays `None` and `reason` says why — **never 0.0**. A zero is a legitimate
    measurement ("did not move at all"); returning one for "could not see the
    hips" is the exact failure this flag exists to make impossible.
    """

    value: float | None = None
    measured: bool = False
    unit: str = ""
    reason: str | None = Field(
        None, description="Vietnamese explanation of why the metric is not measurable."
    )

    @classmethod
    def not_measured(cls, unit: str, reason: str) -> "PoseMetric":
        """Build a `không đo được` metric carrying its reason."""
        return cls(value=None, measured=False, unit=unit, reason=reason)

    @classmethod
    def measure(cls, value: float, unit: str) -> "PoseMetric":
        """Build a measured metric, rounded to the pipeline's 4-decimal contract."""
        return cls(value=round(float(value), 4), measured=True, unit=unit, reason=None)


class LandmarkGroupAvailability(BaseModel):
    """How reliably one landmark group was visible across the sampled frames."""

    group: LandmarkGroup
    visible_frame_ratio: float = Field(0.0, ge=0.0, le=1.0)
    available: bool = False


class PoseFrameSample(BaseModel):
    """
    One sampled frame's worth of per-frame signals, in profile-independent
    units (everything distance-based is already divided by shoulder width, so
    the same person filmed from 2 m and from 5 m produces the same numbers).

    `signals` is a flat name -> value map rather than fixed fields because
    `config/profiles/*.yaml` addresses signals by name; adding a signal is
    then an analyzer change plus a YAML change, with no schema migration.
    Missing signals are absent from the map, not zero.
    """

    timestamp_sec: float = 0.0
    pose_detected: bool = False
    visible_groups: list[LandmarkGroup] = Field(default_factory=list)
    signals: dict[str, float] = Field(default_factory=dict)


class PoseFeature(BaseModel):
    """
    Output of the MediaPipe Pose analyzer (`analyzers/pose_analyzer.py`).

    This is the body-movement replacement for the eye-contact signal: in a
    classroom the presenter should be looking at the audience, not at the
    lens, so measuring gaze-into-camera measures the wrong thing entirely.
    """

    profile: str = Field("", description="Context profile code used to compute these metrics.")
    profile_version: str = Field("0.0.0", description="Version of that profile's threshold set.")

    frames_analyzed: int = 0
    pose_detected_ratio: float = Field(0.0, ge=0.0, le=1.0)
    available_landmark_groups: list[LandmarkGroup] = Field(default_factory=list)
    landmark_group_availability: list[LandmarkGroupAvailability] = Field(default_factory=list)

    sampling_rate_hz: float = Field(
        0.0, description="Sampled frames per second of source video, for event-detection reliability."
    )
    sampling_warning: str | None = Field(
        None, description="Set when sampling is too sparse for the profile's event rules."
    )

    head_up_ratio: PoseMetric = Field(default_factory=PoseMetric)
    postural_sway: PoseMetric = Field(default_factory=PoseMetric)
    movement_range: PoseMetric = Field(default_factory=PoseMetric)
    gesture_rate: PoseMetric = Field(default_factory=PoseMetric)
    closed_posture_ratio: PoseMetric = Field(default_factory=PoseMetric)
    shoulder_tilt: PoseMetric = Field(default_factory=PoseMetric)
    turned_away_ratio: PoseMetric = Field(default_factory=PoseMetric)

    series: list[PoseFrameSample] = Field(
        default_factory=list,
        description="Per-frame time series, consumed by events/detector.py.",
    )

    def metric(self, name: str) -> PoseMetric | None:
        """Look a metric up by its profile name, or `None` if there is no such metric."""
        value = getattr(self, name, None)
        return value if isinstance(value, PoseMetric) else None

    def measured_metrics(self) -> list[str]:
        """Names of every metric that actually came back with a value."""
        return [
            name
            for name in (
                "head_up_ratio",
                "postural_sway",
                "movement_range",
                "gesture_rate",
                "closed_posture_ratio",
                "shoulder_tilt",
                "turned_away_ratio",
            )
            if getattr(self, name).measured
        ]


class ResumeAnalysisFeature(BaseModel):
    """Deterministic structural/content analysis of a resume (analyzers/cv_analyzer.py)."""

    keyword_density: float = Field(0.0, ge=0.0, le=1.0)
    action_verb_ratio: float = Field(0.0, ge=0.0, le=1.0)
    quantified_achievement_count: int = 0
    section_completeness: float = Field(0.0, ge=0.0, le=1.0)
    contact_info_present: bool = False
    length_appropriateness: float = Field(0.0, ge=0.0, le=1.0)


class SlideAnalysisFeature(BaseModel):
    """Deterministic structural/design analysis of a slide deck (analyzers/slide_analyzer.py)."""

    text_density_score: float = Field(0.0, ge=0.0, le=1.0)
    visual_richness_score: float = Field(0.0, ge=0.0, le=1.0)
    consistency_score: float = Field(0.0, ge=0.0, le=1.0)
    notes_usage_ratio: float = Field(0.0, ge=0.0, le=1.0)
    title_presence_ratio: float = Field(0.0, ge=0.0, le=1.0)
    structure_balance_score: float = Field(0.0, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Unified Feature Model — the single object every service communicates through
# ---------------------------------------------------------------------------


class UnifiedFeatureModel(BaseModel):
    """
    The one central model that every AI service in the pipeline communicates
    through, from Feature Fusion onward. Every field is optional because a
    given evaluation may only include a subset of materials (e.g. resume only,
    or resume + video without a separate speech file).
    """

    model_config = ConfigDict(title="UnifiedFeatureModel")

    resume: ResumeFeature | None = None
    slide: SlideFeature | None = None
    audio: AudioFeature | None = None
    video: VideoFeature | None = None

    speech_intelligence: SpeechIntelligenceFeature | None = None
    transcript: TranscriptFeature | None = None
    emotion: EmotionFeature | None = None
    facemesh: FaceMeshFeature | None = None
    pose: PoseFeature | None = None

    resume_analysis: ResumeAnalysisFeature | None = None
    slide_analysis: SlideAnalysisFeature | None = None


# ---------------------------------------------------------------------------
# Layer 3 / 4 outputs
# ---------------------------------------------------------------------------


class DerivedFeatures(BaseModel):
    """Cross-modal derived signals computed by the Feature Fusion Engine."""

    professionalism: float = Field(0.0, ge=0.0, le=100.0)
    presentation_density: float = Field(0.0, ge=0.0, le=100.0)
    communication_confidence: float = Field(0.0, ge=0.0, le=100.0)
    visual_engagement: float = Field(0.0, ge=0.0, le=100.0)
    voice_confidence: float = Field(0.0, ge=0.0, le=100.0)
    presentation_readiness: float = Field(0.0, ge=0.0, le=100.0)


class ScoreBreakdown(BaseModel):
    """
    Every deterministic score produced by the Scoring Engine. Individual
    sub-scores are `None` when the corresponding input material was not
    supplied; `overall_score` is always populated (renormalized over the
    sub-scores that are available).
    """

    resume_score: int | None = Field(None, ge=0, le=100)
    slide_score: int | None = Field(None, ge=0, le=100)
    speech_score: int | None = Field(None, ge=0, le=100)
    transcript_score: int | None = Field(None, ge=0, le=100)
    emotion_score: int | None = Field(None, ge=0, le=100)
    eye_contact_score: int | None = Field(None, ge=0, le=100)
    voice_confidence_score: int | None = Field(None, ge=0, le=100)
    presentation_score: int | None = Field(None, ge=0, le=100)
    communication_score: int | None = Field(None, ge=0, le=100)
    overall_score: int = Field(0, ge=0, le=100)
