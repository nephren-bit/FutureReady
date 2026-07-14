"""Unit tests for services/session_state_machine.py (pure transition logic)."""

from __future__ import annotations

import pytest

from db.models import EvaluationMode, SessionState
from services.session_state_machine import (
    InvalidTransitionError,
    can_apply,
    legal_events,
    next_state,
)


class TestPresentationBranch:
    def test_full_happy_path(self) -> None:
        mode = EvaluationMode.PRESENTATION
        state = SessionState.EMPTY
        for event, expected in [
            ("upload_slide", SessionState.SLIDE_UPLOADED),
            ("start_slide_analysis", SessionState.SLIDE_ANALYZING),
            ("slide_analysis_done", SessionState.SLIDE_ANALYZED),
            ("start_slide_scoring", SessionState.SLIDE_SCORING),
            ("slide_scoring_done", SessionState.SLIDE_REASONING),
            ("slide_reasoning_done", SessionState.SLIDE_EVALUATED),
            ("await_video", SessionState.WAITING_FOR_VIDEO),
            ("upload_video", SessionState.VIDEO_UPLOADED),
            ("start_video_analysis", SessionState.VIDEO_ANALYZING),
            ("video_analysis_done", SessionState.VIDEO_ANALYZED),
            ("start_video_scoring", SessionState.VIDEO_SCORING),
            ("video_scoring_done", SessionState.VIDEO_REASONING),
            ("video_reasoning_done", SessionState.VIDEO_EVALUATED),
            ("start_fusion", SessionState.FEATURE_FUSION),
            ("fusion_done", SessionState.SCORING),
            ("scoring_done", SessionState.PROMPT_BUILDING),
            ("prompt_built", SessionState.REASONING),
            ("reasoning_done", SessionState.REPORT_GENERATED),
            ("finalize", SessionState.COMPLETED),
        ]:
            state = next_state(mode, state, event)
            assert state == expected

    def test_cannot_upload_resume_in_presentation_mode(self) -> None:
        with pytest.raises(InvalidTransitionError):
            next_state(EvaluationMode.PRESENTATION, SessionState.EMPTY, "upload_resume")


class TestInterviewBranch:
    def test_full_happy_path(self) -> None:
        mode = EvaluationMode.INTERVIEW
        state = SessionState.EMPTY
        for event, expected in [
            ("upload_resume", SessionState.RESUME_UPLOADED),
            ("start_resume_analysis", SessionState.RESUME_ANALYZING),
            ("resume_analysis_done", SessionState.RESUME_ANALYZED),
            ("start_resume_scoring", SessionState.RESUME_SCORING),
            ("resume_scoring_done", SessionState.RESUME_REASONING),
            ("resume_reasoning_done", SessionState.RESUME_EVALUATED),
            ("await_video", SessionState.WAITING_FOR_VIDEO),
        ]:
            state = next_state(mode, state, event)
            assert state == expected

    def test_cannot_upload_slide_in_interview_mode(self) -> None:
        with pytest.raises(InvalidTransitionError):
            next_state(EvaluationMode.INTERVIEW, SessionState.EMPTY, "upload_slide")


class TestTerminalStates:
    def test_completed_has_no_legal_events(self) -> None:
        assert legal_events(EvaluationMode.PRESENTATION, SessionState.COMPLETED) == []

    def test_failed_has_no_legal_events(self) -> None:
        assert legal_events(EvaluationMode.INTERVIEW, SessionState.FAILED) == []

    def test_can_apply_is_non_raising(self) -> None:
        assert can_apply(EvaluationMode.PRESENTATION, SessionState.EMPTY, "upload_slide") is True
        assert can_apply(EvaluationMode.PRESENTATION, SessionState.EMPTY, "upload_resume") is False


class TestLegalEvents:
    def test_waiting_for_video_lists_upload_video(self) -> None:
        events = legal_events(EvaluationMode.PRESENTATION, SessionState.WAITING_FOR_VIDEO)
        assert events == ["upload_video"]
