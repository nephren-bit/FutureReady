"""
End-to-end tests for routers/peer_review.py (Nhom C, Task 15-16 / "nhờ bạn
chấm hộ"), against an in-memory SQLite database -- same approach as
test_self_practice_api.py, including its VideoExtractor/PoseAnalyzer
fakes so a session actually reaches COMPLETED to invite a review on.

Written before routers/peer_review.py existed (TDD Red).
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
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


def _neutral_pose() -> PoseFeature:
    series = [
        PoseFrameSample(timestamp_sec=float(i), pose_detected=True, signals=dict(_NEUTRAL_SIGNALS))
        for i in range(10)
    ]
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
        return _neutral_pose()


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
    monkeypatch.setattr(self_practice_router, "SessionLocal", TestSessionLocal)

    from config import settings

    monkeypatch.setattr(settings, "UPLOAD_DIR", tmp_path / "uploads_peer_review")
    monkeypatch.setattr(manager_module, "VideoExtractor", _FakeVideoExtractor)
    monkeypatch.setattr(manager_module, "PoseAnalyzer", _FakePoseAnalyzer)

    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


def _register(client: TestClient, email="a@example.com", password="matkhau-du-dai", full_name="A") -> str:
    resp = client.post("/auth/register", json={"email": email, "password": password, "full_name": full_name})
    assert resp.status_code == 201
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _db_session(client: TestClient):
    import app as app_module

    override = app_module.app.dependency_overrides[get_db]
    return next(override())


def _completed_session(client: TestClient, token: str, tmp_path) -> str:
    video_path = tmp_path / "clip.mp4"
    video_path.write_bytes(b"not a real video, VideoExtractor is mocked")
    with open(video_path, "rb") as handle:
        resp = client.post(
            "/self-practice",
            data={"profile": "presentation_solo"},
            files={"video": ("clip.mp4", handle, "video/mp4")},
            headers=_auth(token),
        )
    session_id = resp.json()["id"]

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        state = client.get(f"/self-practice/{session_id}", headers=_auth(token)).json()["state"]
        if state in {"completed", "failed"}:
            assert state == "completed"
            return session_id
        time.sleep(0.05)
    pytest.fail("session never reached completed")


_RUBRIC = {"clarity": 4, "confidence": 5, "engagement": 3}


class TestCreateListRevokeInvite:
    def test_owner_can_create_an_invite(self, client, tmp_path):
        token = _register(client)
        session_id = _completed_session(client, token, tmp_path)

        resp = client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(token))
        assert resp.status_code == 201
        body = resp.json()
        assert body["status"] == "pending"
        assert len(body["token"]) > 20

    def test_no_token_is_401(self, client, tmp_path):
        token = _register(client)
        session_id = _completed_session(client, token, tmp_path)

        resp = client.post(f"/self-practice/{session_id}/peer-invites")
        assert resp.status_code == 401

    def test_cannot_invite_on_a_session_still_processing(self, client, tmp_path):
        from db.models import SelfPracticeSessionORM, SelfPracticeState

        token = _register(client)
        session_id = _completed_session(client, token, tmp_path)

        # Force it back to PROCESSING -- deterministic instead of racing
        # the background pipeline for a freshly-created session.
        db = _db_session(client)
        import uuid as uuid_module

        row = db.get(SelfPracticeSessionORM, uuid_module.UUID(session_id))
        row.state = SelfPracticeState.PROCESSING
        db.commit()

        resp = client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(token))
        assert resp.status_code == 409

    def test_non_owner_cannot_create_an_invite(self, client, tmp_path):
        owner_token = _register(client, email="a@example.com")
        session_id = _completed_session(client, owner_token, tmp_path)
        other_token = _register(client, email="b@example.com")

        resp = client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(other_token))
        assert resp.status_code == 403

    def test_creating_on_an_unknown_session_is_404(self, client):
        token = _register(client)
        resp = client.post(
            "/self-practice/00000000-0000-0000-0000-000000000000/peer-invites", headers=_auth(token)
        )
        assert resp.status_code == 404

    def test_owner_can_list_invites(self, client, tmp_path):
        token = _register(client)
        session_id = _completed_session(client, token, tmp_path)
        client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(token))
        client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(token))

        resp = client.get(f"/self-practice/{session_id}/peer-invites", headers=_auth(token))
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_non_owner_cannot_list_invites(self, client, tmp_path):
        owner_token = _register(client, email="a@example.com")
        session_id = _completed_session(client, owner_token, tmp_path)
        other_token = _register(client, email="b@example.com")

        resp = client.get(f"/self-practice/{session_id}/peer-invites", headers=_auth(other_token))
        assert resp.status_code == 403

    def test_owner_can_revoke_a_pending_invite(self, client, tmp_path):
        token = _register(client)
        session_id = _completed_session(client, token, tmp_path)
        invite = client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(token)).json()

        resp = client.delete(
            f"/self-practice/{session_id}/peer-invites/{invite['invite_id']}", headers=_auth(token)
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "revoked"

    def test_a_revoked_invite_link_is_410(self, client, tmp_path):
        token = _register(client)
        session_id = _completed_session(client, token, tmp_path)
        invite = client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(token)).json()
        client.delete(f"/self-practice/{session_id}/peer-invites/{invite['invite_id']}", headers=_auth(token))

        other_token = _register(client, email="b@example.com")
        resp = client.get(f"/peer-review/invites/{invite['token']}", headers=_auth(other_token))
        assert resp.status_code == 410

    def test_revoking_an_unknown_invite_is_404(self, client, tmp_path):
        token = _register(client)
        session_id = _completed_session(client, token, tmp_path)

        resp = client.delete(
            f"/self-practice/{session_id}/peer-invites/00000000-0000-0000-0000-000000000000",
            headers=_auth(token),
        )
        assert resp.status_code == 404


class TestBlindReview:
    def _invite(self, client, tmp_path, owner_email="a@example.com"):
        owner_token = _register(client, email=owner_email)
        session_id = _completed_session(client, owner_token, tmp_path)
        invite = client.post(f"/self-practice/{session_id}/peer-invites", headers=_auth(owner_token)).json()
        return owner_token, session_id, invite["token"]

    def test_unknown_token_is_404(self, client):
        token = _register(client)
        resp = client.get("/peer-review/invites/does-not-exist", headers=_auth(token))
        assert resp.status_code == 404

    def test_no_auth_is_401(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        resp = client.get(f"/peer-review/invites/{invite_token}")
        assert resp.status_code == 401

    def test_pending_invite_withholds_events_and_pose_feature(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")

        resp = client.get(f"/peer-review/invites/{invite_token}", headers=_auth(rater_token))
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert body["events"] == []
        assert body["pose_feature"] is None

    def test_rater_can_stream_the_video_while_pending(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")

        resp = client.get(f"/peer-review/invites/{invite_token}/video", headers=_auth(rater_token))
        assert resp.status_code == 200

    def test_rater_can_stream_via_a_query_token_with_no_header_at_all(self, client, tmp_path):
        """
        Regression: this is exactly what a real <video src="...?access_token=...">
        sends -- a plain browser GET with no Authorization header. See the
        identical bug and fix for routers/self_practice.py's video route.
        """
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")

        resp = client.get(f"/peer-review/invites/{invite_token}/video?access_token={rater_token}")
        assert resp.status_code == 200

    def test_streaming_with_neither_header_nor_query_token_is_401(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        resp = client.get(f"/peer-review/invites/{invite_token}/video")
        assert resp.status_code == 401

    def test_owner_cannot_peer_review_their_own_session(self, client, tmp_path):
        owner_token, _, invite_token = self._invite(client, tmp_path)

        mark = client.post(
            f"/peer-review/invites/{invite_token}/marks",
            json={"mark_sec": 1.0},
            headers=_auth(owner_token),
        )
        assert mark.status_code == 403

        submit = client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(owner_token),
        )
        assert submit.status_code == 403

    def test_rater_can_add_marks_while_pending_and_see_them_on_refresh(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")

        mark = client.post(
            f"/peer-review/invites/{invite_token}/marks",
            json={"mark_sec": 2.5, "text": "chỗ này hay"},
            headers=_auth(rater_token),
        )
        assert mark.status_code == 201

        refreshed = client.get(f"/peer-review/invites/{invite_token}", headers=_auth(rater_token)).json()
        assert len(refreshed["own_marks"]) == 1
        assert refreshed["own_marks"][0]["mark_sec"] == 2.5

    def test_submitting_rubric_with_wrong_keys_is_422(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")

        resp = client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": {"only_one": 3}},
            headers=_auth(rater_token),
        )
        assert resp.status_code == 422

    def test_submitting_rubric_with_out_of_range_score_is_422(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")

        bad_rubric = {**_RUBRIC, "clarity": 6}
        resp = client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": bad_rubric},
            headers=_auth(rater_token),
        )
        assert resp.status_code == 422

    def test_submitting_reveals_machine_results_immediately(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")

        resp = client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(rater_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "completed"
        assert body["pose_feature"] is not None
        assert any(mark["rubric_scores"] == _RUBRIC for mark in body["own_marks"])

    def test_re_opening_a_completed_invite_still_shows_the_reveal(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")
        client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(rater_token),
        )

        resp = client.get(f"/peer-review/invites/{invite_token}", headers=_auth(rater_token))
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    def test_adding_a_mark_after_completion_is_409(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")
        client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(rater_token),
        )

        resp = client.post(
            f"/peer-review/invites/{invite_token}/marks",
            json={"mark_sec": 9.0},
            headers=_auth(rater_token),
        )
        assert resp.status_code == 409

    def test_submitting_twice_is_409(self, client, tmp_path):
        _, _, invite_token = self._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")
        client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(rater_token),
        )

        resp = client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(rater_token),
        )
        assert resp.status_code == 409

    def test_an_expired_invite_link_is_410(self, client, tmp_path):
        from db.models import PeerReviewInviteORM

        _, _, invite_token = self._invite(client, tmp_path)
        db = _db_session(client)
        invite_row = db.query(PeerReviewInviteORM).filter(PeerReviewInviteORM.token == invite_token).one()
        invite_row.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
        db.commit()

        rater_token = _register(client, email="b@example.com")
        resp = client.get(f"/peer-review/invites/{invite_token}", headers=_auth(rater_token))
        assert resp.status_code == 410


class TestOwnerSeesRevealedPeerNotes:
    def test_a_pending_rater_s_marks_never_appear_on_the_owner_s_view(self, client, tmp_path):
        owner_token, session_id, invite_token = TestBlindReview()._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")
        client.post(
            f"/peer-review/invites/{invite_token}/marks",
            json={"mark_sec": 3.0},
            headers=_auth(rater_token),
        )

        owner_view = client.get(f"/self-practice/{session_id}", headers=_auth(owner_token)).json()
        assert owner_view["peer_notes"] == []

    def test_the_owner_sees_peer_notes_once_the_review_is_submitted(self, client, tmp_path):
        owner_token, session_id, invite_token = TestBlindReview()._invite(client, tmp_path)
        rater_token = _register(client, email="b@example.com")
        client.post(
            f"/peer-review/invites/{invite_token}/marks",
            json={"mark_sec": 3.0},
            headers=_auth(rater_token),
        )
        client.post(
            f"/peer-review/invites/{invite_token}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(rater_token),
        )

        owner_view = client.get(f"/self-practice/{session_id}", headers=_auth(owner_token)).json()
        # The moment-mark plus the rubric row.
        assert len(owner_view["peer_notes"]) == 2
        assert any(note["rubric_scores"] == _RUBRIC for note in owner_view["peer_notes"])

    def test_peer_notes_never_appear_alongside_the_wrong_session(self, client, tmp_path):
        owner_a, session_a, invite_a = TestBlindReview()._invite(client, tmp_path, owner_email="a@example.com")
        rater_token = _register(client, email="b@example.com")
        client.post(
            f"/peer-review/invites/{invite_a}/submit",
            json={"rubric_scores": _RUBRIC},
            headers=_auth(rater_token),
        )

        owner_c, session_c, _ = TestBlindReview()._invite(client, tmp_path, owner_email="c@example.com")
        other_view = client.get(f"/self-practice/{session_c}", headers=_auth(owner_c)).json()
        assert other_view["peer_notes"] == []
