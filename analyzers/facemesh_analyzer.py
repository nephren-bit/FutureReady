"""
analyzers/facemesh_analyzer.py

Face Mesh analyzer (Layer 2D), built on MediaPipe Face Mesh (468 landmarks +
iris refinement). Estimates head pose, blink frequency, eye openness, gaze
direction, and head movement/stability across sampled video frames, and
derives raw (still deterministic, non-LLM) eye-contact, attention, and
face-stability ratios that the Scoring Engine (Layer 4) later normalizes
into the final Eye Contact Score.
"""

from __future__ import annotations

import statistics
from typing import Any

import numpy as np

from analyzers.base import BaseAnalyzer
from models.features import FaceMeshFeature
from utils.logger import get_logger

logger = get_logger(__name__)

# MediaPipe Face Mesh landmark indices for eye-aspect-ratio (EAR) computation.
_LEFT_EYE_EAR_IDX = (362, 385, 387, 263, 373, 380)
_RIGHT_EYE_EAR_IDX = (33, 160, 158, 133, 153, 144)

# Landmark indices used for the 6-point solvePnP head-pose model.
_POSE_LANDMARK_IDX = {
    "nose_tip": 1,
    "chin": 152,
    "left_eye_corner": 263,
    "right_eye_corner": 33,
    "mouth_left": 291,
    "mouth_right": 61,
}

# Generic 3D face model points (mm), in the same order as `_POSE_LANDMARK_IDX`.
_MODEL_POINTS_3D = np.array(
    [
        (0.0, 0.0, 0.0),  # nose tip
        (0.0, -330.0, -65.0),  # chin
        (-225.0, 170.0, -135.0),  # left eye corner
        (225.0, 170.0, -135.0),  # right eye corner
        (150.0, -150.0, -125.0),  # mouth left
        (-150.0, -150.0, -125.0),  # mouth right
    ],
    dtype=np.float64,
)

# Iris landmark indices, only present when `refine_landmarks=True`.
_LEFT_IRIS_IDX = (468, 469, 470, 471, 472)
_RIGHT_IRIS_IDX = (473, 474, 475, 476, 477)

_BLINK_EAR_THRESHOLD = 0.21
_EYE_CONTACT_YAW_PITCH_THRESHOLD_DEG = 15.0
_EYE_OPENNESS_NORMALIZATION = 0.35


class FaceMeshAnalyzer(BaseAnalyzer[list[tuple[np.ndarray, float]], FaceMeshFeature]):
    """MediaPipe-based face mesh / head pose analyzer over sampled video frames (Layer 2D)."""

    def analyze(self, data: list[tuple[np.ndarray, float]]) -> FaceMeshFeature:
        """
        Args:
            data: List of (BGR frame, timestamp_sec) tuples, as produced by
                `VideoExtractor.extract_with_frames`.

        Returns:
            A `FaceMeshFeature` summarizing head pose, blinking, gaze, and
            stability across the clip.
        """
        if not data:
            return FaceMeshFeature()

        import mediapipe as mp  # local import: keep optional dependency lazy

        ear_values: list[float] = []
        yaw_values: list[float] = []
        pitch_values: list[float] = []
        roll_values: list[float] = []
        gaze_offsets: list[float] = []
        face_centers: list[tuple[float, float]] = []
        frames_with_face = 0

        mp_face_mesh = mp.solutions.face_mesh
        with mp_face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        ) as face_mesh:
            for frame, _timestamp in data:
                import cv2  # local import: keep optional dependency lazy

                height, width = frame.shape[:2]
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb_frame)

                if not results.multi_face_landmarks:
                    continue

                frames_with_face += 1
                landmarks = results.multi_face_landmarks[0].landmark

                ear_values.append(self._eye_aspect_ratio(landmarks, width, height))
                face_centers.append(self._face_center(landmarks, width, height))

                pose = self._estimate_head_pose(landmarks, width, height)
                if pose is not None:
                    pitch, yaw, roll = pose
                    pitch_values.append(pitch)
                    yaw_values.append(yaw)
                    roll_values.append(roll)

                gaze_offsets.append(self._gaze_offset(landmarks))

        total_frames = len(data)
        if frames_with_face == 0:
            return FaceMeshFeature(frames_analyzed=total_frames, faces_detected_ratio=0.0)

        blink_rate = self._estimate_blink_rate(ear_values, data)
        eye_openness_mean = round(
            min(statistics.mean(ear_values) / _EYE_OPENNESS_NORMALIZATION, 1.0), 3
        ) if ear_values else 0.0

        eye_contact_ratio = self._eye_contact_ratio(yaw_values, pitch_values, gaze_offsets)
        head_movement_score = self._head_movement_score(yaw_values, pitch_values, roll_values)
        face_stability_ratio = self._face_stability_ratio(face_centers, width_height=(1.0, 1.0))

        return FaceMeshFeature(
            frames_analyzed=total_frames,
            faces_detected_ratio=round(frames_with_face / total_frames, 3),
            blink_rate_per_min=blink_rate,
            eye_openness_mean=eye_openness_mean,
            eye_contact_ratio=eye_contact_ratio,
            head_pose_pitch_std=round(statistics.pstdev(pitch_values), 2) if len(pitch_values) > 1 else 0.0,
            head_pose_yaw_std=round(statistics.pstdev(yaw_values), 2) if len(yaw_values) > 1 else 0.0,
            head_pose_roll_std=round(statistics.pstdev(roll_values), 2) if len(roll_values) > 1 else 0.0,
            head_movement_score=head_movement_score,
            face_stability_ratio=face_stability_ratio,
        )

    @staticmethod
    def _landmark_xy(landmark: Any, width: int, height: int) -> tuple[float, float]:
        return landmark.x * width, landmark.y * height

    def _eye_aspect_ratio(self, landmarks: Any, width: int, height: int) -> float:
        """Average eye-aspect-ratio (EAR) across both eyes for one frame."""
        left = self._single_eye_ear(landmarks, _LEFT_EYE_EAR_IDX, width, height)
        right = self._single_eye_ear(landmarks, _RIGHT_EYE_EAR_IDX, width, height)
        return (left + right) / 2.0

    def _single_eye_ear(
        self, landmarks: Any, idx: tuple[int, int, int, int, int, int], width: int, height: int
    ) -> float:
        points = [np.array(self._landmark_xy(landmarks[i], width, height)) for i in idx]
        p1, p2, p3, p4, p5, p6 = points
        vertical = np.linalg.norm(p2 - p6) + np.linalg.norm(p3 - p5)
        horizontal = 2.0 * np.linalg.norm(p1 - p4)
        if horizontal == 0:
            return 0.0
        return float(vertical / horizontal)

    def _estimate_head_pose(
        self, landmarks: Any, width: int, height: int
    ) -> tuple[float, float, float] | None:
        """Estimate (pitch, yaw, roll) in degrees via solvePnP, or None if it fails."""
        import cv2

        image_points = np.array(
            [self._landmark_xy(landmarks[idx], width, height) for idx in _POSE_LANDMARK_IDX.values()],
            dtype=np.float64,
        )

        focal_length = width
        center = (width / 2.0, height / 2.0)
        camera_matrix = np.array(
            [[focal_length, 0, center[0]], [0, focal_length, center[1]], [0, 0, 1]],
            dtype=np.float64,
        )
        dist_coeffs = np.zeros((4, 1))

        success, rotation_vec, _translation_vec = cv2.solvePnP(
            _MODEL_POINTS_3D, image_points, camera_matrix, dist_coeffs, flags=cv2.SOLVEPNP_ITERATIVE
        )
        if not success:
            return None

        rotation_matrix, _ = cv2.Rodrigues(rotation_vec)
        pitch, yaw, roll = self._rotation_matrix_to_euler(rotation_matrix)
        return pitch, yaw, roll

    @staticmethod
    def _rotation_matrix_to_euler(rotation_matrix: np.ndarray) -> tuple[float, float, float]:
        """Convert a rotation matrix to (pitch, yaw, roll) Euler angles in degrees."""
        sy = np.sqrt(rotation_matrix[0, 0] ** 2 + rotation_matrix[1, 0] ** 2)
        singular = sy < 1e-6

        if not singular:
            pitch = np.arctan2(rotation_matrix[2, 1], rotation_matrix[2, 2])
            yaw = np.arctan2(-rotation_matrix[2, 0], sy)
            roll = np.arctan2(rotation_matrix[1, 0], rotation_matrix[0, 0])
        else:
            pitch = np.arctan2(-rotation_matrix[1, 2], rotation_matrix[1, 1])
            yaw = np.arctan2(-rotation_matrix[2, 0], sy)
            roll = 0.0

        return (
            float(np.degrees(pitch)),
            float(np.degrees(yaw)),
            float(np.degrees(roll)),
        )

    @staticmethod
    def _gaze_offset(landmarks: Any) -> float:
        """
        Approximate horizontal gaze offset: how far the iris centers sit from
        the midpoint of their eye corners, normalized by eye width. ~0 means
        looking straight ahead (toward the eye's own center).
        """
        try:
            left_iris = np.mean(
                [[landmarks[i].x, landmarks[i].y] for i in _LEFT_IRIS_IDX], axis=0
            )
            right_iris = np.mean(
                [[landmarks[i].x, landmarks[i].y] for i in _RIGHT_IRIS_IDX], axis=0
            )
        except IndexError:
            return 0.0

        left_corner = np.array([landmarks[362].x, landmarks[362].y])
        left_outer = np.array([landmarks[263].x, landmarks[263].y])
        right_corner = np.array([landmarks[33].x, landmarks[33].y])
        right_outer = np.array([landmarks[133].x, landmarks[133].y])

        left_mid = (left_corner + left_outer) / 2.0
        right_mid = (right_corner + right_outer) / 2.0
        left_width = np.linalg.norm(left_corner - left_outer) or 1.0
        right_width = np.linalg.norm(right_corner - right_outer) or 1.0

        left_offset = np.linalg.norm(left_iris - left_mid) / left_width
        right_offset = np.linalg.norm(right_iris - right_mid) / right_width
        return float((left_offset + right_offset) / 2.0)

    @staticmethod
    def _face_center(landmarks: Any, width: int, height: int) -> tuple[float, float]:
        """Approximate face center (normalized 0-1) via the nose-tip landmark."""
        nose = landmarks[_POSE_LANDMARK_IDX["nose_tip"]]
        return nose.x, nose.y

    @staticmethod
    def _estimate_blink_rate(
        ear_values: list[float], data: list[tuple[np.ndarray, float]]
    ) -> float:
        """Count EAR-threshold blink events and normalize to blinks-per-minute."""
        if len(ear_values) < 2:
            return 0.0

        blink_events = 0
        was_closed = False
        for ear in ear_values:
            is_closed = ear < _BLINK_EAR_THRESHOLD
            if is_closed and not was_closed:
                blink_events += 1
            was_closed = is_closed

        timestamps = [t for _frame, t in data]
        span_sec = max(timestamps) - min(timestamps) if timestamps else 0.0
        if span_sec <= 0:
            return 0.0
        return round(blink_events / (span_sec / 60.0), 2)

    @staticmethod
    def _eye_contact_ratio(
        yaw_values: list[float], pitch_values: list[float], gaze_offsets: list[float]
    ) -> float:
        """
        Fraction of frames where head yaw/pitch are within a small threshold
        of forward-facing AND gaze offset is low, i.e. plausibly looking at
        the camera.
        """
        if not yaw_values or not pitch_values:
            return 0.0

        gaze_threshold = statistics.median(gaze_offsets) * 1.5 if gaze_offsets else 0.15
        count = 0
        total = min(len(yaw_values), len(pitch_values))
        for i in range(total):
            forward_facing = (
                abs(yaw_values[i]) <= _EYE_CONTACT_YAW_PITCH_THRESHOLD_DEG
                and abs(pitch_values[i]) <= _EYE_CONTACT_YAW_PITCH_THRESHOLD_DEG
            )
            low_gaze_offset = gaze_offsets[i] <= gaze_threshold if i < len(gaze_offsets) else True
            if forward_facing and low_gaze_offset:
                count += 1
        return round(count / total, 3) if total else 0.0

    @staticmethod
    def _head_movement_score(
        yaw_values: list[float], pitch_values: list[float], roll_values: list[float]
    ) -> float:
        """Normalize combined rotational variance into a 0-1 'movement' score."""
        if len(yaw_values) < 2:
            return 0.0
        combined_std = statistics.pstdev(yaw_values) + statistics.pstdev(pitch_values) + statistics.pstdev(roll_values)
        return round(min(combined_std / 45.0, 1.0), 3)

    @staticmethod
    def _face_stability_ratio(
        face_centers: list[tuple[float, float]], width_height: tuple[float, float]
    ) -> float:
        """
        1 minus normalized positional jitter of the face center across
        frames — i.e. how steady the subject's framing is (not rotation,
        which is captured separately by `head_movement_score`).
        """
        if len(face_centers) < 2:
            return 1.0
        xs = [c[0] for c in face_centers]
        ys = [c[1] for c in face_centers]
        jitter = statistics.pstdev(xs) + statistics.pstdev(ys)
        return round(max(1.0 - min(jitter / 0.3, 1.0), 0.0), 3)
