"""
End-to-end tests for routers/self_practice.py using FastAPI's TestClient,
against an in-memory SQLite database -- same DB-override approach as
test_practice_api.py / test_sessions_api.py.

Every route requires a valid token (Nhóm B, Task 13 / Plans.md B4) and
enforces ownership: a session belongs to whoever created it, and a session
with no owner (`user_id IS NULL` -- recorded before accounts existed) is
reachable only by an admin. `TestSelfPracticeOwnership` covers that
boundary; the other classes just log in before doing what they did before
accounts existed.

`VideoExtractor`/`PoseAnalyzer` are mocked (no real webcam footage in the
test suite); `EventDetector` runs for real against the synthetic
`presentation_solo` `PoseFeature` below, so this exercises the actual
persistence path (`pose_to_orm`/`presentation_event_to_orm`) end to end,
not just a mocked response shape.
"""

from __future__ import annotations

import time
import uuid as uuid_module
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


def _register(client: TestClient, email="an@example.com", password="matkhau-du-dai", full_name="An") -> str:
    resp = client.post("/auth/register", json={"email": email, "password": password, "full_name": full_name})
    assert resp.status_code == 201
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _db_session(client: TestClient):
    import app as app_module

    override = app_module.app.dependency_overrides[get_db]
    return next(override())


def _make_admin(client: TestClient, email: str) -> None:
    from db.models import UserORM

    db = _db_session(client)
    user = db.query(UserORM).filter(UserORM.email == email).one()
    user.is_admin = True
    db.commit()


def _poll_until_state(
    client: TestClient, token: str, session_id: str, target_states: set[str], timeout_sec: float = 5.0
) -> str:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        resp = client.get(f"/self-practice/{session_id}", headers=_auth(token))
        assert resp.status_code == 200
        state = resp.json()["state"]
        if state in target_states:
            return state
        time.sleep(0.05)
    pytest.fail(f"session {session_id} never reached {target_states}")


def _create_session(client: TestClient, token: str, tmp_path, profile: str = "presentation_solo"):
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"not a real video, VideoExtractor is mocked")
    with open(video_path, "rb") as handle:
        return client.post(
            "/self-practice",
            data={"profile": profile},
            files={"video": ("clip.mp4", handle, "video/mp4")},
            headers=_auth(token),
        )


class TestSelfPracticeSessionLifecycle:
    def test_create_session_runs_pipeline_and_persists_events(self, client, tmp_path):
        token = _register(client)
        resp = _create_session(client, token, tmp_path)
        assert resp.status_code == 202
        session_id = resp.json()["id"]

        state = _poll_until_state(client, token, session_id, {"completed", "failed"})
        assert state == "completed"

        final = client.get(f"/self-practice/{session_id}", headers=_auth(token)).json()
        assert final["pose_feature"] is not None
        assert any(event["type"] == "E_HEAD_DOWN" for event in final["events"])

    def test_a_profile_outside_the_self_practice_set_is_rejected(self, client, tmp_path):
        token = _register(client)
        resp = _create_session(client, token, tmp_path, profile="presentation_class")
        assert resp.status_code == 400

    def test_creating_a_session_without_a_token_is_401(self, client, tmp_path):
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"x")
        with open(video_path, "rb") as handle:
            resp = client.post(
                "/self-practice",
                data={"profile": "presentation_solo"},
                files={"video": ("clip.mp4", handle, "video/mp4")},
            )
        assert resp.status_code == 401

    def test_unknown_session_is_404(self, client):
        token = _register(client)
        resp = client.get("/self-practice/00000000-0000-0000-0000-000000000000", headers=_auth(token))
        assert resp.status_code == 404

    def test_list_sessions_only_includes_the_caller_s_own(self, client, tmp_path):
        token_a = _register(client, email="a@example.com")
        token_b = _register(client, email="b@example.com")
        mine = _create_session(client, token_a, tmp_path).json()["id"]
        theirs = _create_session(client, token_b, tmp_path).json()["id"]

        ids = [row["id"] for row in client.get("/self-practice", headers=_auth(token_a)).json()]
        assert mine in ids
        assert theirs not in ids

    def test_delete_session_removes_it(self, client, tmp_path):
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]
        _poll_until_state(client, token, session_id, {"completed", "failed"})

        delete_resp = client.delete(f"/self-practice/{session_id}", headers=_auth(token))
        assert delete_resp.status_code == 204
        assert client.get(f"/self-practice/{session_id}", headers=_auth(token)).status_code == 404

    def test_deleting_an_unknown_session_is_404(self, client):
        token = _register(client)
        resp = client.delete("/self-practice/00000000-0000-0000-0000-000000000000", headers=_auth(token))
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

        token = _register(client)
        video_path = tmp_path / "clip.mp4"
        video_path.write_bytes(b"x" * 1_000)  # over the doc limit, under the video limit
        with open(video_path, "rb") as handle:
            resp = client.post(
                "/self-practice",
                data={"profile": "presentation_solo"},
                files={"video": ("clip.mp4", handle, "video/mp4")},
                headers=_auth(token),
            )
        assert resp.status_code == 202


class TestSelfPracticeVideoStreaming:
    """
    Regression: a plain `<video src>` is a browser-issued GET that can never
    carry a custom `Authorization` header, so the video route must also
    accept the token as a `?token=` query param (routers/deps.py's
    get_current_user_from_header_or_query) -- header-only auth would make
    every recording unwatchable the moment B4 required a token on this
    route too.
    """

    def test_owner_can_stream_via_the_authorization_header(self, client, tmp_path):
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]

        resp = client.get(f"/self-practice/{session_id}/video", headers=_auth(token))
        assert resp.status_code == 200

    def test_owner_can_stream_via_a_query_token_with_no_header_at_all(self, client, tmp_path):
        """This is exactly what a real <video src="...?token=..."> sends."""
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]

        resp = client.get(f"/self-practice/{session_id}/video?token={token}")
        assert resp.status_code == 200

    def test_streaming_with_neither_header_nor_query_token_is_401(self, client, tmp_path):
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]

        resp = client.get(f"/self-practice/{session_id}/video")
        assert resp.status_code == 401


class TestSelfNoteCrud:
    def test_create_and_list_notes(self, client, tmp_path):
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]

        resp = client.post(
            f"/self-practice/{session_id}/notes", json={"mark_sec": 3.5, "text": "hay"}, headers=_auth(token)
        )
        assert resp.status_code == 201
        note = resp.json()
        assert note["mark_sec"] == 3.5
        assert note["text"] == "hay"

        notes = client.get(f"/self-practice/{session_id}", headers=_auth(token)).json()["notes"]
        assert [n["note_id"] for n in notes] == [note["note_id"]]

    def test_editing_a_note_updates_the_same_row_rather_than_creating_one(self, client, tmp_path):
        """Task 4's acceptance check: an edit must not add a second row."""
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]
        note = client.post(
            f"/self-practice/{session_id}/notes", json={"mark_sec": 3.5, "text": "ban dau"}, headers=_auth(token)
        ).json()

        resp = client.patch(
            f"/self-practice/{session_id}/notes/{note['note_id']}", json={"text": "da sua"}, headers=_auth(token)
        )
        assert resp.status_code == 200
        assert resp.json()["note_id"] == note["note_id"]
        assert resp.json()["text"] == "da sua"
        assert resp.json()["mark_sec"] == 3.5  # untouched field survives a partial edit

        notes = client.get(f"/self-practice/{session_id}", headers=_auth(token)).json()["notes"]
        assert len(notes) == 1
        assert notes[0]["text"] == "da sua"

    def test_deleting_a_note_removes_it(self, client, tmp_path):
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]
        note = client.post(
            f"/self-practice/{session_id}/notes", json={"mark_sec": 1.0}, headers=_auth(token)
        ).json()

        resp = client.delete(f"/self-practice/{session_id}/notes/{note['note_id']}", headers=_auth(token))
        assert resp.status_code == 204

        notes = client.get(f"/self-practice/{session_id}", headers=_auth(token)).json()["notes"]
        assert notes == []

    def test_editing_an_unknown_note_is_404(self, client, tmp_path):
        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]
        resp = client.patch(
            f"/self-practice/{session_id}/notes/00000000-0000-0000-0000-000000000000",
            json={"text": "x"},
            headers=_auth(token),
        )
        assert resp.status_code == 404


class TestSelfPracticeOwnership:
    """
    B4: every route requires a valid token and enforces ownership --
    `session.user_id != token.user_id` is 403 unless the caller is an
    admin, and a NULL-owner session (recorded before accounts existed) is
    reachable only by an admin, never silently claimed by whoever knows
    the id.
    """

    def _owned_session(self, client, tmp_path, owner_email="a@example.com"):
        token = _register(client, email=owner_email)
        session_id = _create_session(client, token, tmp_path).json()["id"]
        _poll_until_state(client, token, session_id, {"completed", "failed"})
        return token, session_id

    def test_the_owner_can_still_access_their_own_session(self, client, tmp_path):
        token, session_id = self._owned_session(client, tmp_path)
        assert client.get(f"/self-practice/{session_id}", headers=_auth(token)).status_code == 200

    def test_reading_someone_else_s_session_is_403(self, client, tmp_path):
        _, session_id = self._owned_session(client, tmp_path)
        other_token = _register(client, email="b@example.com")

        resp = client.get(f"/self-practice/{session_id}", headers=_auth(other_token))
        assert resp.status_code == 403

    def test_reading_someone_else_s_video_is_403(self, client, tmp_path):
        _, session_id = self._owned_session(client, tmp_path)
        other_token = _register(client, email="b@example.com")

        resp = client.get(f"/self-practice/{session_id}/video", headers=_auth(other_token))
        assert resp.status_code == 403

    def test_reading_someone_else_s_video_via_query_token_is_403(self, client, tmp_path):
        """The query-token fallback (for <video src>) enforces ownership too, not just the header path."""
        _, session_id = self._owned_session(client, tmp_path)
        other_token = _register(client, email="b@example.com")

        resp = client.get(f"/self-practice/{session_id}/video?token={other_token}")
        assert resp.status_code == 403

    def test_deleting_someone_else_s_session_is_403(self, client, tmp_path):
        _, session_id = self._owned_session(client, tmp_path)
        other_token = _register(client, email="b@example.com")

        resp = client.delete(f"/self-practice/{session_id}", headers=_auth(other_token))
        assert resp.status_code == 403

    def test_adding_a_note_to_someone_else_s_session_is_403(self, client, tmp_path):
        _, session_id = self._owned_session(client, tmp_path)
        other_token = _register(client, email="b@example.com")

        resp = client.post(
            f"/self-practice/{session_id}/notes", json={"mark_sec": 1.0}, headers=_auth(other_token)
        )
        assert resp.status_code == 403

    def test_editing_someone_else_s_note_is_403(self, client, tmp_path):
        token, session_id = self._owned_session(client, tmp_path)
        note = client.post(
            f"/self-practice/{session_id}/notes", json={"mark_sec": 1.0}, headers=_auth(token)
        ).json()
        other_token = _register(client, email="b@example.com")

        resp = client.patch(
            f"/self-practice/{session_id}/notes/{note['note_id']}",
            json={"text": "x"},
            headers=_auth(other_token),
        )
        assert resp.status_code == 403

    def test_deleting_someone_else_s_note_is_403(self, client, tmp_path):
        token, session_id = self._owned_session(client, tmp_path)
        note = client.post(
            f"/self-practice/{session_id}/notes", json={"mark_sec": 1.0}, headers=_auth(token)
        ).json()
        other_token = _register(client, email="b@example.com")

        resp = client.delete(f"/self-practice/{session_id}/notes/{note['note_id']}", headers=_auth(other_token))
        assert resp.status_code == 403

    def test_admin_can_access_any_session(self, client, tmp_path):
        _, session_id = self._owned_session(client, tmp_path)
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")

        resp = client.get(f"/self-practice/{session_id}", headers=_auth(admin_token))
        assert resp.status_code == 200

    def test_admin_sees_every_session_in_the_list(self, client, tmp_path):
        _, session_a = self._owned_session(client, tmp_path, owner_email="a@example.com")
        _, session_b = self._owned_session(client, tmp_path, owner_email="c@example.com")
        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")

        ids = [row["id"] for row in client.get("/self-practice", headers=_auth(admin_token)).json()]
        assert session_a in ids
        assert session_b in ids

    def test_a_session_with_no_owner_is_reachable_only_by_an_admin(self, client, tmp_path):
        """Sessions recorded before accounts existed have user_id=NULL."""
        from db.models import SelfPracticeSessionORM

        token = _register(client)
        session_id = _create_session(client, token, tmp_path).json()["id"]

        db = _db_session(client)
        row = db.get(SelfPracticeSessionORM, uuid_module.UUID(session_id))
        row.user_id = None
        db.commit()

        # The original creator no longer "owns" it once user_id is cleared.
        assert client.get(f"/self-practice/{session_id}", headers=_auth(token)).status_code == 403

        admin_token = _register(client, email="admin@example.com")
        _make_admin(client, "admin@example.com")
        assert client.get(f"/self-practice/{session_id}", headers=_auth(admin_token)).status_code == 200
