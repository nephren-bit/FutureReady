"""
analyzers/emotion_analyzer.py

Facial emotion analyzer (Layer 2C), built on HSEmotion (ONNX build,
`hsemotion-onnx`) for emotion classification and OpenCV's Haar cascade for
face detection. Runs per sampled video frame and produces an emotion
timeline, distribution, dominant emotion, and consistency/confidence
statistics. No LLM is involved — HSEmotion's own classifier produces the
labels; Gemini never sees a frame.

Recognized taxonomy (per project spec): happy, neutral, sad, fear, disgust,
surprise, angry. HSEmotion's default 8-class models also predict
"contempt", which is folded into "disgust" to match this taxonomy.
"""

from __future__ import annotations

import statistics
from collections import Counter
from typing import Any

import numpy as np

from analyzers.base import BaseAnalyzer
from models.features import EmotionFeature, EmotionTimelinePoint
from utils.logger import get_logger

logger = get_logger(__name__)

_EMOTION_TAXONOMY = {"happy", "neutral", "sad", "fear", "disgust", "surprise", "angry"}

_LABEL_MAP = {
    "anger": "angry",
    "angry": "angry",
    "contempt": "disgust",
    "disgust": "disgust",
    "fear": "fear",
    "happiness": "happy",
    "happy": "happy",
    "neutral": "neutral",
    "sadness": "sad",
    "sad": "sad",
    "surprise": "surprise",
}

_HSEMOTION_MODEL_NAME = "enet_b0_8_best_afew"

_recognizer_cache: dict[str, Any] = {}
_face_cascade_cache: dict[str, Any] = {}


def _load_recognizer(model_name: str) -> Any:
    if model_name not in _recognizer_cache:
        from hsemotion_onnx.facial_emotions import HSEmotionRecognizer  # local, optional dependency

        logger.info("Loading HSEmotion model '%s' (first use)...", model_name)
        _recognizer_cache[model_name] = HSEmotionRecognizer(model_name=model_name)
    return _recognizer_cache[model_name]


def _load_face_cascade(cv2_module: Any) -> Any:
    if "default" not in _face_cascade_cache:
        cascade_path = cv2_module.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade_cache["default"] = cv2_module.CascadeClassifier(cascade_path)
    return _face_cascade_cache["default"]


class EmotionAnalyzer(BaseAnalyzer[list[tuple[np.ndarray, float]], EmotionFeature]):
    """HSEmotion-based facial emotion analyzer over sampled video frames (Layer 2C)."""

    def __init__(self, model_name: str = _HSEMOTION_MODEL_NAME) -> None:
        self._model_name = model_name

    def analyze(self, data: list[tuple[np.ndarray, float]]) -> EmotionFeature:
        """
        Args:
            data: List of (BGR frame, timestamp_sec) tuples, as produced by
                `VideoExtractor.extract_with_frames`.

        Returns:
            An `EmotionFeature` summarizing emotion over the clip. Returns a
            neutral, zero-confidence result if no face is detected in any
            sampled frame.
        """
        if not data:
            return EmotionFeature()

        import cv2  # local import: keep optional dependency lazy

        recognizer = _load_recognizer(self._model_name)
        cascade = _load_face_cascade(cv2)

        timeline: list[EmotionTimelinePoint] = []
        raw_scores: list[dict[str, float]] = []

        for frame, timestamp in data:
            face_crop = self._detect_largest_face(frame, cascade)
            if face_crop is None:
                continue

            rgb_face = cv2.cvtColor(face_crop, cv2.COLOR_BGR2RGB)
            try:
                label, scores = recognizer.predict_emotions(rgb_face, logits=False)
            except Exception:  # noqa: BLE001
                logger.warning("HSEmotion inference failed on a frame; skipping.")
                continue

            mapped_scores = self._map_scores(recognizer.idx_to_class, scores)
            dominant_label = max(mapped_scores, key=mapped_scores.get)
            timeline.append(
                EmotionTimelinePoint(
                    timestamp_sec=round(timestamp, 2),
                    emotion=dominant_label,
                    confidence=round(mapped_scores[dominant_label], 3),
                )
            )
            raw_scores.append(mapped_scores)

        if not timeline:
            return EmotionFeature()

        return self._aggregate(timeline, raw_scores)

    @staticmethod
    def _detect_largest_face(frame: np.ndarray, cascade: Any) -> np.ndarray | None:
        """Detect the largest face in a frame and return the cropped region, or None."""
        import cv2

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(48, 48))
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda box: box[2] * box[3])
        return frame[y : y + h, x : x + w]

    @staticmethod
    def _map_scores(idx_to_class: dict[int, str], scores: np.ndarray) -> dict[str, float]:
        """Map HSEmotion's native class scores onto the project's 7-emotion taxonomy."""
        aggregated: dict[str, float] = {label: 0.0 for label in _EMOTION_TAXONOMY}
        for index, raw_label in idx_to_class.items():
            mapped = _LABEL_MAP.get(str(raw_label).lower())
            if mapped is None:
                continue
            aggregated[mapped] += float(scores[index])
        total = sum(aggregated.values())
        if total > 0:
            aggregated = {label: value / total for label, value in aggregated.items()}
        return aggregated

    @staticmethod
    def _aggregate(
        timeline: list[EmotionTimelinePoint], raw_scores: list[dict[str, float]]
    ) -> EmotionFeature:
        """Aggregate per-frame emotion predictions into distribution/consistency stats."""
        emotion_counts = Counter(point.emotion for point in timeline)
        total_frames = len(timeline)
        dominant_emotion = emotion_counts.most_common(1)[0][0]

        distribution: dict[str, float] = {}
        for emotion in _EMOTION_TAXONOMY:
            mean_score = statistics.mean(scores.get(emotion, 0.0) for scores in raw_scores)
            distribution[emotion] = round(mean_score, 3)

        emotion_consistency = round(emotion_counts[dominant_emotion] / total_frames, 3)
        emotion_confidence_mean = round(
            statistics.mean(point.confidence for point in timeline), 3
        )
        positive_frames = sum(1 for point in timeline if point.emotion in {"happy", "surprise"})
        positive_emotion_ratio = round(positive_frames / total_frames, 3)

        return EmotionFeature(
            emotion_timeline=timeline,
            emotion_distribution=distribution,
            dominant_emotion=dominant_emotion,
            emotion_consistency=emotion_consistency,
            emotion_confidence_mean=emotion_confidence_mean,
            positive_emotion_ratio=positive_emotion_ratio,
        )
