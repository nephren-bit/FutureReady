"""
tests/test_practice_session_manager.py

Unit tests for services/practice_session_manager.py -- the Live Practice
orchestrator (Layer 1/2 -> Fusion -> Scoring -> Prompt -> Reasoning on a
single, standalone audio recording, with no session state machine
involved). Layer 1/2 calls (extract_audio/analyze_speech/analyze_transcript)
and the Gemini reasoning call are mocked, same approach as
test_workflow_manager.py -- this suite verifies orchestration and
persistence, not the AI models themselves.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import PracticeSessionState
from models.features import AudioFeature, SpeechIntelligenceFeature, TranscriptFeature
from models.responses import ReasoningPayload
from services.practice_session_manager import (
    PracticeEvaluationNotReadyError,
    PracticeSessionManager,
    PracticeSessionNotFoundError,
)


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=pool.StaticPool
    )
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def manager(monkeypatch) -> PracticeSessionManager:
    from services.ai_orchestrator import ai_orchestrator

    monkeypatch.setattr(
        ai_orchestrator,
        "extract_audio",
        lambda path: AudioFeature(
            sample_rate=16000,
            duration_sec=12.0,
            pitch_mean_hz=170.0,
            pitch_std_hz=40.0,
            voiced_ratio=0.6,
            silence_ratio=0.1,
        ),
    )
    monkeypatch.setattr(
        ai_orchestrator,
        "analyze_speech",
        lambda path: SpeechIntelligenceFeature(
            transcript="This is a short practice recording about my public speaking skills today.",
            language="en",
            average_confidence=0.85,
            duration_sec=12.0,
            words_per_minute=110.0,
            word_count=13,
        ),
    )
    monkeypatch.setattr(
        ai_orchestrator,
        "analyze_transcript",
        lambda text: TranscriptFeature(
            word_count=13,
            sentence_count=1,
            vocabulary_diversity=0.8,
            has_opening=True,
            has_conclusion=False,
        ),
    )
    monkeypatch.setattr(
        "services.lmstudio_service.lmstudio_service.generate_structured",
        AsyncMock(
            return_value=ReasoningPayload(
                strengths=["Clear pacing"], presentation_feedback="Solid delivery overall."
            )
        ),
    )
    return PracticeSessionManager()


def _write_dummy_audio(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"RIFF....WAVEfmt ")  # content is irrelevant -- extract_audio/analyze_speech are mocked


class TestPracticeSessionLifecycle:
    def test_create_and_get_session(self, db_session, manager: PracticeSessionManager) -> None:
        session = manager.create_session(db_session, language="vi")
        assert session.state == PracticeSessionState.CONNECTING
        assert session.language == "vi"

        fetched = manager.get_session(db_session, session.id)
        assert fetched.id == session.id

    def test_get_unknown_session_raises(self, db_session, manager: PracticeSessionManager) -> None:
        with pytest.raises(PracticeSessionNotFoundError):
            manager.get_session(db_session, uuid.uuid4())

    def test_start_streaming_records_audio_path(
        self, db_session, manager: PracticeSessionManager, tmp_path: Path
    ) -> None:
        session = manager.create_session(db_session)
        audio_path = tmp_path / "practice.wav"
        updated = manager.start_streaming(db_session, session.id, audio_path)
        assert updated.state == PracticeSessionState.STREAMING
        assert updated.audio_file_path == str(audio_path)
        assert updated.started_at is not None

    def test_evaluation_not_ready_before_finalize(self, db_session, manager: PracticeSessionManager) -> None:
        session = manager.create_session(db_session)
        with pytest.raises(PracticeEvaluationNotReadyError):
            manager.get_evaluation(db_session, session.id)


class TestPracticeFinalize:
    async def test_finalize_with_no_audio_fails_gracefully(
        self, db_session, manager: PracticeSessionManager
    ) -> None:
        session = manager.create_session(db_session)
        result = await manager.finalize(db_session, session.id)
        assert result.state == PracticeSessionState.FAILED
        assert "No audio" in result.error_message

    async def test_finalize_with_empty_audio_file_fails_gracefully(
        self, db_session, manager: PracticeSessionManager, tmp_path: Path
    ) -> None:
        session = manager.create_session(db_session)
        audio_path = tmp_path / "empty.wav"
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.touch()  # exists, zero bytes
        manager.start_streaming(db_session, session.id, audio_path)

        result = await manager.finalize(db_session, session.id)
        assert result.state == PracticeSessionState.FAILED

    async def test_finalize_success_persists_evaluation(
        self, db_session, manager: PracticeSessionManager, tmp_path: Path
    ) -> None:
        session = manager.create_session(db_session)
        audio_path = tmp_path / "practice.wav"
        _write_dummy_audio(audio_path)
        manager.start_streaming(db_session, session.id, audio_path)

        result = await manager.finalize(db_session, session.id)
        assert result.state == PracticeSessionState.COMPLETED
        assert result.ended_at is not None
        assert "public speaking" in result.transcript_so_far

        evaluation = manager.get_evaluation(db_session, session.id)
        assert 0 <= evaluation.overall_score <= 100
        assert evaluation.reasoning_engine_name == "lmstudio"
        assert evaluation.presentation_feedback == "Solid delivery overall."
        # Audio-only material: resume/slide sub-scores are never populated.
        assert evaluation.resume_score is None
        assert evaluation.slide_score is None

    async def test_finalize_records_failure_on_reasoning_error(
        self, db_session, manager: PracticeSessionManager, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(
            "services.lmstudio_service.lmstudio_service.generate_structured",
            AsyncMock(side_effect=RuntimeError("Gemini is down")),
        )
        session = manager.create_session(db_session)
        audio_path = tmp_path / "practice.wav"
        _write_dummy_audio(audio_path)
        manager.start_streaming(db_session, session.id, audio_path)

        result = await manager.finalize(db_session, session.id)
        assert result.state == PracticeSessionState.FAILED
        assert "Gemini is down" in result.error_message


class TestLiveTip:
    def test_tip_none_when_transcript_too_short(self, manager: PracticeSessionManager) -> None:
        assert manager.partial_transcript_tip("um so") is None

    def test_tip_flags_filler_words(self, manager: PracticeSessionManager) -> None:
        text = "um uh um so basically um like uh yeah um totally um right um"
        tip = manager.partial_transcript_tip(text)
        assert tip is not None

    def test_tip_present_for_healthy_transcript(self, manager: PracticeSessionManager) -> None:
        text = (
            "Good morning everyone, today I want to walk you through our roadmap "
            "for the next quarter and explain why these priorities matter."
        )
        tip = manager.partial_transcript_tip(text)
        assert tip is not None
