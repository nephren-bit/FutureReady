"""
Tests for the learning-resource catalog (permission matrix row 12).

The behaviours worth pinning down are the ones that protect history: hiding
rather than deleting, refusing duplicate URLs, and surfacing how many
recommendations point at a resource before someone retires it.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app as app_module
import db.models as dbm
from db.base import Base
from db.session import get_db
from utils.security import create_access_token, hash_password


@pytest.fixture()
def db_session():
    """An isolated in-memory database per test."""
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with maker() as session:
        yield session
    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session):
    """A TestClient sharing the test's database session."""
    app_module.app.dependency_overrides[get_db] = lambda: db_session
    with TestClient(app_module.app) as test_client:
        yield test_client
    app_module.app.dependency_overrides.clear()


@pytest.fixture()
def admin_headers(db_session):
    """Bearer header for an administrator, created the only way the system allows."""
    admin = dbm.UserORM(
        email="admin@truong.edu.vn",
        password_hash=hash_password("quantri12345"),
        full_name="Quan tri",
        role=dbm.UserRole.LECTURER,
        is_admin=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    token = create_access_token(admin.id, role="lecturer", is_admin=True)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def learner_headers(db_session):
    """Bearer header for an ordinary learner."""
    learner = dbm.UserORM(
        email="hoc@truong.edu.vn",
        password_hash=hash_password("sinhvien12345"),
        full_name="Nguoi hoc",
        role=dbm.UserRole.LEARNER,
    )
    db_session.add(learner)
    db_session.commit()
    db_session.refresh(learner)
    token = create_access_token(learner.id, role="learner", is_admin=False)
    return {"Authorization": f"Bearer {token}"}


def sample_payload(**overrides) -> dict:
    """A valid create payload, with overrides applied."""
    return {
        "title": "Nói trước đám đông không run",
        "url": "https://www.youtube.com/watch?v=abc123",
        "resource_type": "video",
        "platform": "Youtube",
        "language": "vi",
        "speaker": "Trần Văn B",
        "source": "TEDx",
        "skill_tags": ["confidence", "speaking"],
        **overrides,
    }


class TestAccess:
    """Row 12 belongs to administrators alone."""

    def test_no_token_is_401(self, client) -> None:
        assert client.get("/admin/resources").status_code == 401

    def test_learner_is_403(self, client, learner_headers) -> None:
        assert client.get("/admin/resources", headers=learner_headers).status_code == 403

    def test_learner_cannot_create(self, client, learner_headers) -> None:
        response = client.post("/admin/resources", json=sample_payload(), headers=learner_headers)
        assert response.status_code == 403

    def test_admin_reaches_it(self, client, admin_headers) -> None:
        assert client.get("/admin/resources", headers=admin_headers).status_code == 200


class TestCreate:
    def test_creates_a_resource(self, client, admin_headers) -> None:
        response = client.post("/admin/resources", json=sample_payload(), headers=admin_headers)
        assert response.status_code == 201, response.text

        body = response.json()
        assert body["title"] == "Nói trước đám đông không run"
        assert body["skill_tags"] == ["confidence", "speaking"]
        assert body["is_active"] is True
        assert body["recommendation_count"] == 0

    def test_duplicate_url_is_refused(self, client, admin_headers) -> None:
        """The same talk must not be catalogued twice and recommended twice."""
        client.post("/admin/resources", json=sample_payload(), headers=admin_headers)
        again = client.post(
            "/admin/resources", json=sample_payload(title="Tiêu đề khác"), headers=admin_headers
        )
        assert again.status_code == 409

    def test_url_must_be_http(self, client, admin_headers) -> None:
        response = client.post(
            "/admin/resources", json=sample_payload(url="youtube.com/abc"), headers=admin_headers
        )
        assert response.status_code == 422

    def test_unknown_skill_tag_is_refused(self, client, admin_headers) -> None:
        """
        A tag the engine cannot match on would catalogue a resource that is
        never recommendable, which looks like success and is not.
        """
        response = client.post(
            "/admin/resources", json=sample_payload(skill_tags=["khong-co-that"]), headers=admin_headers
        )
        assert response.status_code == 422

    def test_a_resource_with_no_tag_is_allowed_but_counted(self, client, admin_headers) -> None:
        client.post("/admin/resources", json=sample_payload(skill_tags=[]), headers=admin_headers)
        stats = client.get("/admin/resources/stats", headers=admin_headers).json()
        assert stats["untagged"] == 1


class TestUpdateAndHide:
    def test_partial_update_leaves_other_fields_alone(self, client, admin_headers) -> None:
        created = client.post("/admin/resources", json=sample_payload(), headers=admin_headers).json()

        updated = client.patch(
            f"/admin/resources/{created['id']}", json={"title": "Tiêu đề mới"}, headers=admin_headers
        )
        assert updated.status_code == 200
        body = updated.json()
        assert body["title"] == "Tiêu đề mới"
        assert body["speaker"] == "Trần Văn B"  # untouched
        assert body["skill_tags"] == ["confidence", "speaking"]  # untouched

    def test_retagging_replaces_the_tag_list(self, client, admin_headers) -> None:
        created = client.post("/admin/resources", json=sample_payload(), headers=admin_headers).json()
        updated = client.patch(
            f"/admin/resources/{created['id']}", json={"skill_tags": ["interview"]}, headers=admin_headers
        ).json()
        assert updated["skill_tags"] == ["interview"]

    def test_hiding_keeps_the_row(self, client, admin_headers, db_session) -> None:
        """The catalog hides; it never deletes."""
        created = client.post("/admin/resources", json=sample_payload(), headers=admin_headers).json()
        resource_id = uuid.UUID(created["id"])

        hidden = client.patch(
            f"/admin/resources/{resource_id}", json={"is_active": False}, headers=admin_headers
        )
        assert hidden.status_code == 200
        assert hidden.json()["is_active"] is False
        assert db_session.get(dbm.LearningResourceORM, resource_id) is not None

    def test_there_is_no_delete_endpoint(self, client, admin_headers) -> None:
        """
        Deleting would strand `RecommendationORM` rows that record what a
        learner was once told to study.
        """
        created = client.post("/admin/resources", json=sample_payload(), headers=admin_headers).json()
        response = client.delete(f"/admin/resources/{created['id']}", headers=admin_headers)
        assert response.status_code == 405

    def test_url_clash_on_update_is_refused(self, client, admin_headers) -> None:
        first = client.post("/admin/resources", json=sample_payload(), headers=admin_headers).json()
        second = client.post(
            "/admin/resources",
            json=sample_payload(url="https://example.com/khac"),
            headers=admin_headers,
        ).json()

        response = client.patch(
            f"/admin/resources/{second['id']}", json={"url": first["url"]}, headers=admin_headers
        )
        assert response.status_code == 409

    def test_unknown_resource_is_404(self, client, admin_headers) -> None:
        response = client.patch(
            f"/admin/resources/{uuid.uuid4()}", json={"title": "x"}, headers=admin_headers
        )
        assert response.status_code == 404


class TestListingAndFilters:
    @staticmethod
    def _seed(client, admin_headers) -> None:
        client.post("/admin/resources", json=sample_payload(
            title="Tự tin nói chuyện", url="https://a.com/1",
            skill_tags=["confidence"], language="vi", resource_type="video"), headers=admin_headers)
        client.post("/admin/resources", json=sample_payload(
            title="Interview prep guide", url="https://a.com/2",
            skill_tags=["interview"], language="en", resource_type="article"), headers=admin_headers)
        client.post("/admin/resources", json=sample_payload(
            title="Bài tập luyện giọng", url="https://a.com/3",
            skill_tags=["speaking"], language="vi", resource_type="exercise",
            is_active=False), headers=admin_headers)

    def test_lists_everything_by_default(self, client, admin_headers) -> None:
        self._seed(client, admin_headers)
        body = client.get("/admin/resources", headers=admin_headers).json()
        assert body["total"] == 3

    def test_filter_by_type(self, client, admin_headers) -> None:
        self._seed(client, admin_headers)
        body = client.get(
            "/admin/resources", params={"resource_type": "article"}, headers=admin_headers
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "Interview prep guide"

    def test_filter_by_skill_tag(self, client, admin_headers) -> None:
        self._seed(client, admin_headers)
        body = client.get(
            "/admin/resources", params={"skill_tag": "interview"}, headers=admin_headers
        ).json()
        assert body["total"] == 1

    def test_filter_by_hidden(self, client, admin_headers) -> None:
        self._seed(client, admin_headers)
        body = client.get(
            "/admin/resources", params={"is_active": False}, headers=admin_headers
        ).json()
        assert body["total"] == 1
        assert body["items"][0]["title"] == "Bài tập luyện giọng"

    def test_search_covers_title_and_speaker(self, client, admin_headers) -> None:
        self._seed(client, admin_headers)
        assert client.get(
            "/admin/resources", params={"search": "luyện giọng"}, headers=admin_headers
        ).json()["total"] == 1
        assert client.get(
            "/admin/resources", params={"search": "trần văn"}, headers=admin_headers
        ).json()["total"] == 3

    def test_total_counts_before_paging(self, client, admin_headers) -> None:
        self._seed(client, admin_headers)
        body = client.get("/admin/resources", params={"limit": 1}, headers=admin_headers).json()
        assert body["total"] == 3
        assert len(body["items"]) == 1


class TestRecommendationCount:
    def test_count_shows_how_much_history_hangs_off_a_resource(
        self, client, admin_headers, db_session
    ) -> None:
        """What an administrator needs to see before retiring something."""
        created = client.post("/admin/resources", json=sample_payload(), headers=admin_headers).json()
        resource_id = uuid.UUID(created["id"])

        session = dbm.AnalysisSession(mode=dbm.EvaluationMode.PRESENTATION)
        db_session.add(session)
        db_session.flush()
        for rank in (1, 2):
            db_session.add(
                dbm.RecommendationORM(
                    session_id=session.id,
                    resource_id=resource_id,
                    rank=rank,
                    rationale="vi du",
                )
            )
        db_session.commit()

        body = client.get(f"/admin/resources/{resource_id}", headers=admin_headers).json()
        assert body["recommendation_count"] == 2

    def test_hiding_does_not_touch_existing_recommendations(
        self, client, admin_headers, db_session
    ) -> None:
        created = client.post("/admin/resources", json=sample_payload(), headers=admin_headers).json()
        resource_id = uuid.UUID(created["id"])

        session = dbm.AnalysisSession(mode=dbm.EvaluationMode.PRESENTATION)
        db_session.add(session)
        db_session.flush()
        db_session.add(
            dbm.RecommendationORM(
                session_id=session.id, resource_id=resource_id, rank=1, rationale="vi du"
            )
        )
        db_session.commit()

        client.patch(
            f"/admin/resources/{resource_id}", json={"is_active": False}, headers=admin_headers
        )

        remaining = db_session.scalars(
            select(dbm.RecommendationORM).where(dbm.RecommendationORM.resource_id == resource_id)
        ).all()
        assert len(remaining) == 1


class TestStats:
    def test_stats_partition_the_catalog(self, client, admin_headers) -> None:
        TestListingAndFilters._seed(client, admin_headers)
        stats = client.get("/admin/resources/stats", headers=admin_headers).json()

        assert stats["total"] == 3
        assert stats["active"] + stats["hidden"] == stats["total"]
        assert stats["hidden"] == 1
        assert sum(stats["by_type"].values()) == 3
        assert stats["by_skill_tag"] == {"confidence": 1, "interview": 1, "speaking": 1}
        assert stats["untagged"] == 0
