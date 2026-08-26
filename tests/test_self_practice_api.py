"""
End-to-end tests for routers/self_practice.py using FastAPI's TestClient,
against an in-memory SQLite database -- same DB-override approach as
test_practice_api.py / test_sessions_api.py.

`VideoExtractor`/`PoseAnalyzer` are mocked (no real webcam footage in the
test suite); `EventDetector` runs for real against the synthetic
`presentation_solo` `PoseFeature` below, so this exercises the actual
persistence path (`pose_to_orm`/`presentation_event_to_orm`) end to end,
not just a mocked response shape.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.session import get_db
from models.features import PoseFeature, PoseFrameSample, PoseMetric
from services.profile_loader import load_profile

_NEUTRAL_SIGNALS = {
    "head_up": 1.0,
    "motion_rate": 0.2,
    "horizontal_rate": 0.1,
    "turned_away": 0.0,
    "closed_posture": 0.0,
    "shoulder_tilt_deg": 3.0,
    "shoulder_width_ratio": 1.0,
}


def _head_down_pose() -> PoseFeature:
    """A `presentation_solo` PoseFeature whose series triggers E_HEAD_DOWN (>=4s head-down)."""
    series = []
    for i in range(20):
        signals = dict(_NEUTRAL_SIGNALS)
        if 5 <= i < 15:  # 10 seconds head-down, well over the 4s minimum
            signals["head_up"] = 0.0
        series.append(PoseFrameSample(timestamp_sec=float(i), pose_detected=True, signals=signals))

    measured = PoseMetric.measure(0.5, "x")
    return PoseFeature(
        profile="presentation_solo",
        profile_version=load_profile("presentation_solo").version,
        frames_analyzed=len(series),
        pose_detected_ratio=1.0,
        series=series,
        head_up_ratio=measured,
        postural_sway=measured,
        movement_range=measured,
        gesture_rate=measured,
        closed_posture_ratio=measured,
        shoulder_tilt=measured,
        turned_away_ratio=measured,
    )


class _FakeVideoExtractor:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def extract_with_frames(self, path):
        return SimpleNamespace(fps=30.0), [], []


class _FakePoseAnalyzer:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def analyze(self, frames_with_timestamps, source_fps=0.0):
        return _head_down_pose()


@pytest.fixture()
def client(monkeypatch, tmp_path):
    import app as app_module
    import routers.self_practice as self_practice_router
    import services.self_practice_manager as manager_module

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
    # The pipeline's background task opens its own SessionLocal (not via
    # Depends -- the request-scoped session is closed before it runs), so it
    # must be redirected to the same in-memory test engine.
    monkeypatch.setattr(self_practice_router, "SessionLocal", TestSessionLocal)

    from config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads_self_practice")
    monkeypatch.setattr(manager_module, "VideoExtractor", _FakeVideoExtractor)
    monkeypatch.setattr(manager_module, "PoseAnalyzer", _FakePoseAnalyzer)

    with TestClient(app_module.app) as test_client:
        yield test_client

    app_module.app.dependency_overrides.clear()


def _poll_until_state(client: TestClient, session_id: str, target_states: set[str], timeout_sec: float = 5.0) -> str:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        resp = client.get(f"/self-practice/{session_id}")
        assert resp.status_code == 200
        state = resp.json()["state"]
        if state in target_states:
            return state
        time.sleep(0.05)
    pytest.fail(f"session {session_id} never reached {target_states}")


def _create_session(client: TestClient, tmp_path, profile: str = "presentation_solo"):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"not a real video, VideoExtractor is mocked")
    with open(video_path, "rb") as handle:
        return client.post(
            "/self-practice",
            data={"profile": profile},
            files={"video": ("clip.mp4", handle, "video/mp4")},
        )


class TestSelfPracticeSessionLifecycle:
    def test_create_session_runs_pipeline_and_persists_events(self, client, tmp_path):
        resp = _create_session(client, tmp_path)
        assert resp.status_code == 202
        session_id = resp.json()["id"]

        state = _poll_until_state(client, session_id, {"completed", "failed"})
        assert state == "completed"

        final = client.get(f"/self-practice/{session_id}").json()
        assert final["pose_feature"] is not None
        assert any(event["type"] == "E_HEAD_DOWN" for event in final["events"])

    def test_a_profile_outside_the_self_practice_set_is_rejected(self, client, tmp_path):
        # presentation_class is the retired teacher-facing profile -- valid
        # for the old scoring flow, not for this one.
        resp = _create_session(client, tmp_path, profile="presentation_class")
        assert resp.status_code == 400

    def test_unknown_session_is_404(self, client):
        resp = client.get("/self-practice/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_list_sessions_includes_every_session(self, client, tmp_path):
        first = _create_session(client, tmp_path).json()["id"]
        second = _create_session(client, tmp_path).json()["id"]

        ids = [row["id"] for row in client.get("/self-practice").json()]
        assert {first, second} <= set(ids)

    def test_delete_session_removes_it(self, client, tmp_path):
        session_id = _create_session(client, tmp_path).json()["id"]
        _poll_until_state(client, session_id, {"completed", "failed"})

        delete_resp = client.delete(f"/self-practice/{session_id}")
        assert delete_resp.status_code == 204
        assert client.get(f"/self-practice/{session_id}").status_code == 404

    def test_deleting_an_unknown_session_is_404(self, client):
        resp = client.delete("/self-practice/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404

    def test_upload_uses_the_video_size_limit_not_the_document_one(self, client, tmp_path, monkeypatch):
        """
        Regression: a practice recording is a video, not a small PDF/pptx --
        save_upload_file's default limit is sized for documents and rejects
        real recordings with 413 if the router forgets to override it (see
        routers/sessions.py's own /video upload for the same override).
        """
        from config import settings

        monkeypatch.setattr(settings, "MAX_FILE_SIZE_BYTES", 10)
        monkeypatch.setattr(settings, "MAX_VIDEO_SIZE_BYTES", 10_000)

        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"x" * 1_000)  # over the doc limit, under the video limit
        with open(video_path, "rb") as handle:
            resp = client.post(
                "/self-practice",
                data={"profile": "presentation_solo"},
                files={"video": ("clip.mp4", handle, "video/mp4")},
            )
        assert resp.status_code == 202


class TestSelfNoteCrud:
    def test_create_and_list_notes(self, client, tmp_path):
        session_id = _create_session(client, tmp_path).json()["id"]

        resp = client.post(f"/self-practice/{session_id}/notes", json={"mark_sec": 3.5, "text": "hay"})
        assert resp.status_code == 201
        note = resp.json()
        assert note["mark_sec"] == 3.5
        assert note["text"] == "hay"

        notes = client.get(f"/self-practice/{session_id}").json()["notes"]
        assert [n["note_id"] for n in notes] == [note["note_id"]]

    def test_editing_a_note_updates_the_same_row_rather_than_creating_one(self, client, tmp_path):
        """Task 4's acceptance check: an edit must not add a second row."""
        session_id = _create_session(client, tmp_path).json()["id"]
        note = client.post(f"/self-practice/{session_id}/notes", json={"mark_sec": 3.5, "text": "ban dau"}).json()

        resp = client.patch(f"/self-practice/{session_id}/notes/{note['note_id']}", json={"text": "da sua"})
        assert resp.status_code == 200
        assert resp.json()["note_id"] == note["note_id"]
        assert resp.json()["text"] == "da sua"
        assert resp.json()["mark_sec"] == 3.5  # untouched field survives a partial edit

        notes = client.get(f"/self-practice/{session_id}").json()["notes"]
        assert len(notes) == 1
        assert notes[0]["text"] == "da sua"

    def test_deleting_a_note_removes_it(self, client, tmp_path):
        session_id = _create_session(client, tmp_path).json()["id"]
        note = client.post(f"/self-practice/{session_id}/notes", json={"mark_sec": 1.0}).json()

        resp = client.delete(f"/self-practice/{session_id}/notes/{note['note_id']}")
        assert resp.status_code == 204

        notes = client.get(f"/self-practice/{session_id}").json()["notes"]
        assert notes == []

    def test_editing_an_unknown_note_is_404(self, client, tmp_path):
        session_id = _create_session(client, tmp_path).json()["id"]
        resp = client.patch(
            f"/self-practice/{session_id}/notes/00000000-0000-0000-0000-000000000000",
            json={"text": "x"},
        )
        assert resp.status_code == 404
