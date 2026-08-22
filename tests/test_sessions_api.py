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

Every route under /sessions requires a token, so the `client` fixture
registers an account and signs in as it for the whole test. `TestOwnership`
at the bottom of this file is where the account boundary itself is tested:
that a second account sees none of the first one's work, cannot open it by
id, and cannot delete it.
"""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

import app as app_module
import db.models as dbm
from db.base import Base
from db.session import get_db
from utils.security import create_access_token, hash_password
from models.features import (
    EmotionFeature,
    FaceMeshFeature,
    SlideAnalysisFeature,
    SpeechIntelligenceFeature,
    TranscriptFeature,
    VideoFeature,
)
from models.responses import RecommendationPayload, ReasoningPayload


async def _fake_generate_structured(prompt: str, response_model: type):
    """Dispatches by `response_model` since a session's pipeline requests both
    `ReasoningPayload` (preliminary + final) and `RecommendationPayload` schemas."""
    if response_model is RecommendationPayload:
        return RecommendationPayload()  # no learning_resources seeded in these tests -> never actually called
    return ReasoningPayload(strengths=["Clear structure"], presentation_feedback="Solid overall delivery.")


@pytest.fixture()
def client(monkeypatch, sample_slide_feature, stub_reasoning_engine):
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
    stub_reasoning_engine.generate_structured = _fake_generate_structured

    with TestClient(app_module.app) as test_client:
        # Sign in for the whole test. Set as a default header rather than
        # passed per call so a route added later is covered by default; a test
        # that wants a *different* account passes `headers=` explicitly.
        test_client.headers["Authorization"] = f"Bearer {_register(test_client, 'owner@truong.edu.vn')}"
        yield test_client

    app_module.app.dependency_overrides.clear()


def _register(client: TestClient, email: str, password: str = "matkhau123") -> str:
    """Create an account through the public route and return its bearer token."""
    resp = client.post("/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()["access_token"]


def _auth(token: str) -> dict[str, str]:
    """Authorization header for a token."""
    return {"Authorization": f"Bearer {token}"}


def _complete_a_session(client: TestClient) -> str:
    """Run one presentation session through to COMPLETED and return its id."""
    session_id = client.post("/sessions", json={"mode": "presentation", "language": "vi"}).json()["id"]
    client.post(
        f"/sessions/{session_id}/slide",
        files={"file": ("deck.pptx", b"fake-pptx-bytes", "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    _poll_until_state(client, session_id, {"waiting_for_video", "failed"})
    client.post(
        f"/sessions/{session_id}/video",
        files={"file": ("talk.mp4", b"fake-mp4-bytes", "video/mp4")},
    )
    _poll_until_state(client, session_id, {"completed", "failed"})
    return session_id


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


class TestRecommendationsEndpoint:
    """
    Covers `GET /sessions/{id}/recommendations` — automatically populated
    once the final report exists (the `RECOMMENDING` stage runs right after
    `REASONING`). These tests run against an unseeded `learning_resources`
    catalog (see test_workflow_manager.py::TestRecommendationEngine for
    coverage of actual resource matching/ranking), so the expected shape is
    a 200 with an empty list -- confirming completion is never blocked by a
    missing catalog, and that the endpoint itself is wired up correctly.
    """

    def test_recommendations_available_after_completion(self, client: TestClient) -> None:
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

        resp = client.get(f"/sessions/{session_id}/recommendations")
        assert resp.status_code == 200
        body = resp.json()
        assert body["session_id"] == session_id
        assert body["recommendations"] == []  # no learning_resources seeded in this test DB

    def test_recommendations_before_completion_is_409(self, client: TestClient) -> None:
        create_resp = client.post("/sessions", json={"mode": "presentation", "language": "vi"})
        session_id = create_resp.json()["id"]
        resp = client.get(f"/sessions/{session_id}/recommendations")
        assert resp.status_code == 409

    def test_recommendations_unknown_session_is_404(self, client: TestClient) -> None:
        resp = client.get("/sessions/00000000-0000-0000-0000-000000000000/recommendations")
        assert resp.status_code == 404


class TestOwnership:
    """
    A session belongs to the account that created it.

    These are the tests that would fail if someone dropped the WHERE clause in
    `list_sessions` or the `assert_can_*_session` call in a route -- the kind
    of regression that leaves every endpoint returning 200 and every existing
    test green while quietly showing one account another account's work.
    """

    def test_created_session_is_stamped_with_its_creator(self, client: TestClient) -> None:
        me = client.get("/auth/me").json()
        session_id = client.post("/sessions", json={"mode": "presentation", "language": "vi"}).json()["id"]

        db = next(app_module.app.dependency_overrides[get_db]())
        try:
            row = db.get(dbm.AnalysisSession, uuid.UUID(session_id))
            assert str(row.user_id) == me["id"]
        finally:
            db.close()

    def test_a_new_account_sees_none_of_an_existing_accounts_sessions(
        self, client: TestClient
    ) -> None:
        """The headline guarantee: registering does not inherit anyone's history."""
        _complete_a_session(client)
        assert len(client.get("/sessions").json()) == 1

        newcomer = _register(client, "newcomer@truong.edu.vn")
        assert client.get("/sessions", headers=_auth(newcomer)).json() == []

    def test_each_account_lists_only_its_own_sessions(self, client: TestClient) -> None:
        mine = client.post("/sessions", json={"mode": "presentation", "language": "vi"}).json()["id"]

        other = _register(client, "other@truong.edu.vn")
        theirs = client.post(
            "/sessions", json={"mode": "interview", "language": "vi"}, headers=_auth(other)
        ).json()["id"]

        assert [s["id"] for s in client.get("/sessions").json()] == [mine]
        assert [s["id"] for s in client.get("/sessions", headers=_auth(other)).json()] == [theirs]

    def test_another_account_cannot_read_a_session_it_does_not_own(
        self, client: TestClient
    ) -> None:
        """Knowing the id is not authorization -- ids leak through URLs and logs."""
        session_id = _complete_a_session(client)
        stranger = _auth(_register(client, "stranger@truong.edu.vn"))

        for path in (
            f"/sessions/{session_id}",
            f"/sessions/{session_id}/report",
            f"/sessions/{session_id}/recommendations",
            f"/sessions/{session_id}/preliminary/slide",
        ):
            assert client.get(path, headers=stranger).status_code == 403, path

    def test_another_account_cannot_delete_or_upload_to_a_session_it_does_not_own(
        self, client: TestClient
    ) -> None:
        session_id = client.post("/sessions", json={"mode": "presentation", "language": "vi"}).json()["id"]
        stranger = _auth(_register(client, "vandal@truong.edu.vn"))

        assert client.delete(f"/sessions/{session_id}", headers=stranger).status_code == 403
        upload = client.post(
            f"/sessions/{session_id}/slide",
            files={"file": ("deck.pptx", b"fake-pptx-bytes", "application/octet-stream")},
            headers=stranger,
        )
        assert upload.status_code == 403
        assert client.post(f"/sessions/{session_id}/retry", headers=stranger).status_code == 403

        # And the session is still there, untouched, for its owner.
        assert client.get(f"/sessions/{session_id}").status_code == 200

    def test_a_lecturer_may_read_another_learners_session_but_not_delete_it(
        self, client: TestClient
    ) -> None:
        """
        Permission matrix row 9 grants viewing, not editing. This is the split
        between `assert_can_access_session` and `assert_can_modify_session`.
        """
        session_id = _complete_a_session(client)

        lecturer = _auth(_register(client, "giangvien@truong.edu.vn"))
        assert client.patch("/auth/me/role", json={"role": "lecturer"}, headers=lecturer).status_code == 200

        assert client.get(f"/sessions/{session_id}", headers=lecturer).status_code == 200
        assert client.get(f"/sessions/{session_id}/report", headers=lecturer).status_code == 200
        assert client.delete(f"/sessions/{session_id}", headers=lecturer).status_code == 403

    def test_a_lecturers_dashboard_still_shows_only_their_own_sessions(
        self, client: TestClient
    ) -> None:
        """Being allowed to open a learner's report does not put it on your dashboard."""
        _complete_a_session(client)

        lecturer = _auth(_register(client, "giangvien2@truong.edu.vn"))
        client.patch("/auth/me/role", json={"role": "lecturer"}, headers=lecturer)
        assert client.get("/sessions", headers=lecturer).json() == []

    def test_an_administrator_may_delete_any_session(self, client: TestClient) -> None:
        session_id = client.post("/sessions", json={"mode": "presentation", "language": "vi"}).json()["id"]

        db = next(app_module.app.dependency_overrides[get_db]())
        try:
            admin = dbm.UserORM(
                email="quantri@truong.edu.vn",
                password_hash=hash_password("matkhau123"),
                full_name="Quan tri",
                role=dbm.UserRole.LECTURER,
                is_admin=True,
            )
            db.add(admin)
            db.commit()
            token = create_access_token(admin.id, role=admin.role.value, is_admin=True)
        finally:
            db.close()

        assert client.delete(f"/sessions/{session_id}", headers=_auth(token)).status_code == 204

    def test_every_session_route_requires_a_token(self, client: TestClient) -> None:
        """NFR-08: no token, no business route -- 401, not an empty 200."""
        session_id = client.post("/sessions", json={"mode": "presentation", "language": "vi"}).json()["id"]
        anonymous = {"Authorization": ""}

        assert client.get("/sessions", headers=anonymous).status_code == 401
        assert client.get(f"/sessions/{session_id}", headers=anonymous).status_code == 401
        assert client.get(f"/sessions/{session_id}/report", headers=anonymous).status_code == 401
        assert client.delete(f"/sessions/{session_id}", headers=anonymous).status_code == 401
        assert client.post(
            "/sessions", json={"mode": "presentation", "language": "vi"}, headers=anonymous
        ).status_code == 401

    def test_an_unowned_legacy_session_is_listed_for_nobody(self, client: TestClient) -> None:
        """
        Rows from before accounts existed have `user_id = NULL`. They belong to
        nobody, so they appear on nobody's dashboard until
        `scripts/assign_orphan_sessions.py` gives them an owner -- which is
        exactly why that script exists.
        """
        session_id = client.post("/sessions", json={"mode": "presentation", "language": "vi"}).json()["id"]

        db = next(app_module.app.dependency_overrides[get_db]())
        try:
            db.get(dbm.AnalysisSession, uuid.UUID(session_id)).user_id = None
            db.commit()
        finally:
            db.close()

        assert client.get("/sessions").json() == []
