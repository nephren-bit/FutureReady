"""
End-to-end tests for routers/practice.py using FastAPI's TestClient,
including its WebSocket support (`client.websocket_connect`). Exercises the
full Live Practice wire protocol (connect -> stream audio chunks ->
end_session -> final_evaluation) against an in-memory SQLite database, with
every Layer 1/2/6 AI call mocked -- same approach as test_sessions_api.py.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.session import get_db
from models.features import AudioFeature, SpeechIntelligenceFeature, TranscriptFeature
from models.responses import ReasoningPayload


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import app as app_module
    import routers.practice as practice_router

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=pool.StaticPool
    )
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app_module.app.dependency_overrides[get_db] = override_get_db
    # The WebSocket handler opens its own DB session directly (`SessionLocal()`,
    # not via Depends -- a WS connection outlives any single request scope),
    # so it must be redirected to the same test engine.
    monkeypatch.setattr(practice_router, "SessionLocal", TestSessionLocal)

    from config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads_practice")

    orchestrator = practice_router.ai_orchestrator
    monkeypatch.setattr(
        orchestrator,
        "extract_audio",
        lambda path: AudioFeature(
            sample_rate=16000, duration_sec=6.0, pitch_mean_hz=170.0, pitch_std_hz=40.0,
            voiced_ratio=0.6, silence_ratio=0.1,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "analyze_speech",
        lambda path: SpeechIntelligenceFeature(
            transcript="Hello everyone, thanks for listening to this quick practice run.",
            language="en", average_confidence=0.9, duration_sec=6.0, words_per_minute=115.0, word_count=11,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "analyze_transcript",
        lambda text: TranscriptFeature(
            word_count=11, sentence_count=1, vocabulary_diversity=0.85, has_opening=True, has_conclusion=True
        ),
    )
    monkeypatch.setattr(
        "services.lmstudio_service.lmstudio_service.generate_structured",
        AsyncMock(
            return_value=ReasoningPayload(
                strengths=["Confident opening"], presentation_feedback="Nice and steady pace throughout."
            )
        ),
    )

    with TestClient(app_module.app) as test_client:
        yield test_client

    app_module.app.dependency_overrides.clear()


def _poll_until_state(client: TestClient, session_id: str, target_states: set[str], timeout_sec: float = 5.0) -> str:
    """Poll GET /practice/{id} until it reaches one of `target_states`. finalize() completing relative to the
    WebSocket disconnect event can be racy right after the socket closes, so this mirrors the polling pattern
    already used in test_sessions_api.py rather than asserting immediately."""
    deadline = time.monotonic() + timeout_sec
    state = None
    while time.monotonic() < deadline:
        resp = client.get(f"/practice/{session_id}")
        state = resp.json()["state"]
        if state in target_states:
            return state
        time.sleep(0.05)
    return state


class TestPracticeWebSocketFlow:
    def test_full_practice_flow_via_websocket(self, client: TestClient) -> None:
        with client.websocket_connect("/practice/stream?language=vi&audio_format=wav") as ws:
            started = ws.receive_json()
            assert started["type"] == "session_started"
            session_id = started["session_id"]

            # Send a handful of "audio" chunks -- content is irrelevant since
            # extract_audio/analyze_speech are mocked.
            for _ in range(3):
                ws.send_bytes(b"\x00" * 512)

            ws.send_text('{"type": "end_session"}')

            final = ws.receive_json()
            assert final["type"] == "final_evaluation"
            assert final["session_id"] == session_id
            assert final["reasoning"]["presentation_feedback"] == "Nice and steady pace throughout."
            assert 0 <= final["scores"]["overall_score"] <= 100

        # Retrievable afterward via the REST endpoints too.
        status_resp = client.get(f"/practice/{session_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["state"] == "completed"

        eval_resp = client.get(f"/practice/{session_id}/evaluation")
        assert eval_resp.status_code == 200
        assert eval_resp.json()["reasoning"]["presentation_feedback"] == "Nice and steady pace throughout."

    def test_disconnect_without_end_session_does_not_crash_and_stays_queryable(self, client: TestClient) -> None:
        """
        Covers the "client vanished without end_session" path in
        `_stream_audio`/`practice_stream` (the `websocket.disconnect`
        branch). Note: Starlette's `TestClient` cancels the server-side ASGI
        task almost immediately after `close()` (see
        `WebSocketTestSession.__exit__`), which is far more aggressive than
        a real disconnect (uvicorn lets the handler keep running at its own
        pace) -- so best-effort `finalize()` may or may not win the race to
        commit "completed"/"failed" before cancellation. What this test
        actually guarantees is what matters in production: the handler
        never raises, and the session row it already created stays
        queryable in whatever state it reached. Real-world finalize-on-
        disconnect behavior is covered directly at the unit level in
        test_practice_session_manager.py.
        """
        with client.websocket_connect("/practice/stream?audio_format=wav") as ws:
            started = ws.receive_json()
            session_id = started["session_id"]
            ws.send_bytes(b"\x00" * 512)
            # Drop the connection without sending end_session.

        status_resp = client.get(f"/practice/{session_id}")
        assert status_resp.status_code == 200
        assert status_resp.json()["state"] in {"streaming", "finalizing", "completed", "failed"}

    def test_rejects_unsupported_audio_format(self, client: TestClient) -> None:
        with pytest.raises(Exception):
            with client.websocket_connect("/practice/stream?audio_format=flac") as ws:
                ws.receive_json()


class TestPracticeRestEndpoints:
    def test_get_unknown_session_is_404(self, client: TestClient) -> None:
        resp = client.get("/practice/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_get_evaluation_before_ready_is_409(self, client: TestClient) -> None:
        with client.websocket_connect("/practice/stream?audio_format=wav") as ws:
            started = ws.receive_json()
            session_id = started["session_id"]
            # No chunks sent, no end_session yet -- check status mid-stream.
            resp = client.get(f"/practice/{session_id}/evaluation")
            assert resp.status_code == 409
            ws.send_text('{"type": "end_session"}')
            ws.receive_json()

    def test_get_evaluation_unknown_session_is_404(self, client: TestClient) -> None:
        resp = client.get("/practice/00000000-0000-0000-0000-000000000000/evaluation")
        assert resp.status_code == 404
