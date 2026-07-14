"""
End-to-end tests for routers/sessions.py using FastAPI's TestClient.

Exercises the full HTTP surface (create -> upload -> poll -> report ->
delete) against an in-memory SQLite database, with every Layer 1/2/6 AI
call mocked (same approach as test_workflow_manager.py). Upload endpoints
return as soon as the fast, synchronous half of the pipeline completes;
the actual AI analysis runs as a `BackgroundTasks` job, so tests poll
`GET /sessions/{id}` afterward rather than asserting on the immediate
upload response body — this mirrors how a real frontend is expected to
observe progress.
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
from models.features import (
    EmotionFeature,
    FaceMeshFeature,
    SlideAnalysisFeature,
    SpeechIntelligenceFeature,
    TranscriptFeature,
    VideoFeature,
)
from models.responses import ReasoningPayload


@pytest.fixture()
def client(monkeypatch, sample_slide_feature):
    import app as app_module
    import routers.sessions as sessions_router

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
    # Background tasks in routers/sessions.py call `SessionLocal()` directly
    # (not via Depends), so they must be redirected to the same test engine.
    monkeypatch.setattr(sessions_router, "SessionLocal", TestSessionLocal)

    orchestrator = sessions_router.workflow_manager._orchestrator
    monkeypatch.setattr(orchestrator, "extract_slide", lambda path: sample_slide_feature)
    monkeypatch.setattr(
        orchestrator,
        "analyze_slide",
        lambda feature: SlideAnalysisFeature(
            text_density_score=0.5,
            visual_richness_score=0.6,
            consistency_score=0.7,
            notes_usage_ratio=0.4,
            title_presence_ratio=1.0,
            structure_balance_score=0.8,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "analyze_video_vision",
        lambda path: (
            VideoFeature(
                fps=30.0, frame_count=900, duration_sec=30.0, sampled_frame_count=60,
                brightness_mean=120.0, contrast_mean=40.0,
            ),
            EmotionFeature(dominant_emotion="neutral", emotion_consistency=0.6),
            FaceMeshFeature(frames_analyzed=60, faces_detected_ratio=0.9, eye_contact_ratio=0.7),
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "analyze_speech",
        lambda path: SpeechIntelligenceFeature(
            transcript="Hello and welcome to this presentation about our results.",
            language="en",
            average_confidence=0.9,
            duration_sec=30.0,
            words_per_minute=120.0,
            word_count=10,
        ),
    )
    monkeypatch.setattr(
        orchestrator,
        "analyze_transcript",
        lambda text: TranscriptFeature(
            word_count=10, sentence_count=1, vocabulary_diversity=0.8, has_opening=True, has_conclusion=True
        ),
    )
    monkeypatch.setattr(
        "services.gemini_service.gemini_service.generate_structured",
        AsyncMock(
            return_value=ReasoningPayload(
                strengths=["Clear structure"], presentation_feedback="Solid overall delivery."
            )
        ),
    )

    with TestClient(app_module.app) as test_client:
        yield test_client

    app_module.app.dependency_overrides.clear()


def _poll_until_state(client: TestClient, session_id: str, target_states: set[str], timeout_sec: float = 5.0) -> str:
    """Poll GET /sessions/{id} until it reaches one of `target_states` (mirrors real client polling)."""
    deadline = time.monotonic() + timeout_sec
    state = None
    while time.monotonic() < deadline:
        resp = client.get(f"/sessions/{session_id}")
        state = resp.json()["state"]
        if state in target_states:
            return state
        time.sleep(0.05)
    return state


class TestSessionLifecycle:
    def test_create_session(self, client: TestClient) -> None:
        resp = client.post("/sessions", json={"mode": "presentation", "language": "vi"})
        assert resp.status_code == 201
        body = resp.json()
        assert body["mode"] == "presentation"
        assert body["state"] == "empty"
        assert body["legal_next_events"] == ["upload_slide"]

    def test_full_presentation_flow_via_http(self, client: TestClient) -> None:
        create_resp = client.post("/sessions", json={"mode": "presentation", "language": "vi"})
        session_id = create_resp.json()["id"]

        slide_resp = client.post(
            f"/sessions/{session_id}/slide",
            files={"file": ("deck.pptx", b"fake-pptx-bytes", "application/octet-stream")},
        )
        assert slide_resp.status_code == 200
        # The background task (Layer 1/2 slide analysis + its preliminary
        # score/reasoning pass) may not have finished by the time the upload
        # response is sent — that is precisely the "return immediately, poll
        # for progress" contract this endpoint promises, so we poll rather
        # than asserting on the immediate body.
        state = _poll_until_state(client, session_id, {"waiting_for_video", "failed"})
        assert state == "waiting_for_video"

        video_resp = client.post(
            f"/sessions/{session_id}/video",
            files={"file": ("clip.mp4", b"fake-mp4-bytes", "application/octet-stream")},
        )
        assert video_resp.status_code == 200
        state = _poll_until_state(client, session_id, {"completed", "failed"})
        assert state == "completed"

        report_resp = client.get(f"/sessions/{session_id}/report")
        assert report_resp.status_code == 200
        report = report_resp.json()
        assert report["reasoning"]["presentation_feedback"] == "Solid overall delivery."
        assert 0 <= report["scores"]["overall_score"] <= 100

        get_resp = client.get(f"/sessions/{session_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["state"] == "completed"

        delete_resp = client.delete(f"/sessions/{session_id}")
        assert delete_resp.status_code == 204
        assert client.get(f"/sessions/{session_id}").status_code == 404

    def test_report_before_completion_is_409(self, client: TestClient) -> None:
        create_resp = client.post("/sessions", json={"mode": "presentation", "language": "vi"})
        session_id = create_resp.json()["id"]
        resp = client.get(f"/sessions/{session_id}/report")
        assert resp.status_code == 409

    def test_wrong_mode_upload_is_409(self, client: TestClient) -> None:
        create_resp = client.post("/sessions", json={"mode": "interview", "language": "vi"})
        session_id = create_resp.json()["id"]
        resp = client.post(
            f"/sessions/{session_id}/slide",
            files={"file": ("deck.pptx", b"fake-pptx-bytes", "application/octet-stream")},
        )
        assert resp.status_code == 409

    def test_unknown_session_is_404(self, client: TestClient) -> None:
        resp = client.get("/sessions/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestPreliminaryEvaluationEndpoint:
    """
    Covers `GET /sessions/{id}/preliminary/{stage}` — the dedicated endpoint
    (per the product decision) for the slide/resume/video "quick review"
    that appears as soon as that single material finishes analysis, well
    before the rest of the session's materials are uploaded or the final
    report is ready.
    """

    def test_slide_preliminary_available_before_video_is_uploaded(self, client: TestClient) -> None:
        create_resp = client.post("/sessions", json={"mode": "presentation", "language": "vi"})
        session_id = create_resp.json()["id"]

        client.post(
            f"/sessions/{session_id}/slide",
            files={"file": ("deck.pptx", b"fake-pptx-bytes", "application/octet-stream")},
        )
        state = _poll_until_state(client, session_id, {"waiting_for_video", "failed"})
        assert state == "waiting_for_video"

        prelim_resp = client.get(f"/sessions/{session_id}/preliminary/slide")
        assert prelim_resp.status_code == 200
        body = prelim_resp.json()
        assert body["stage"] == "slide"
        assert body["reasoning"]["presentation_feedback"] == "Solid overall delivery."
        assert 0 <= body["scores"]["overall_score"] <= 100

        # The video hasn't been uploaded yet, so its preliminary evaluation isn't ready.
        video_prelim_resp = client.get(f"/sessions/{session_id}/preliminary/video")
        assert video_prelim_resp.status_code == 409

    def test_both_preliminary_evaluations_available_after_completion(self, client: TestClient) -> None:
        create_resp = client.post("/sessions", json={"mode": "presentation", "language": "vi"})
        session_id = create_resp.json()["id"]

        client.post(
            f"/sessions/{session_id}/slide",
            files={"file": ("deck.pptx", b"fake-pptx-bytes", "application/octet-stream")},
        )
        _poll_until_state(client, session_id, {"waiting_for_video", "failed"})

        client.post(
            f"/sessions/{session_id}/video",
            files={"file": ("clip.mp4", b"fake-mp4-bytes", "application/octet-stream")},
        )
        state = _poll_until_state(client, session_id, {"completed", "failed"})
        assert state == "completed"

        slide_resp = client.get(f"/sessions/{session_id}/preliminary/slide")
        video_resp = client.get(f"/sessions/{session_id}/preliminary/video")
        assert slide_resp.status_code == 200
        assert video_resp.status_code == 200
        assert slide_resp.json()["stage"] == "slide"
        assert video_resp.json()["stage"] == "video"

    def test_preliminary_evaluation_unknown_session_is_404(self, client: TestClient) -> None:
        resp = client.get("/sessions/00000000-0000-0000-0000-000000000000/preliminary/slide")
        assert resp.status_code == 404

    def test_preliminary_evaluation_before_any_upload_is_409(self, client: TestClient) -> None:
        create_resp = client.post("/sessions", json={"mode": "presentation", "language": "vi"})
        session_id = create_resp.json()["id"]
        resp = client.get(f"/sessions/{session_id}/preliminary/slide")
        assert resp.status_code == 409
