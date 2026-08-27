"""
Unit tests for services/quality_tracking.py (Nhom B Task 14 / Nhom C Task
18): the detection-quality dashboard's actual number-crunching, exercised
directly against an in-memory SQLite DB and hand-built rows -- no need to
run the real pose pipeline to test whether the overlap math and the
`created_before_reveal`/invite-status filters are correct.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, pool
from sqlalchemy.orm import sessionmaker

from db.base import Base
from db.models import (
    PeerNoteORM,
    PeerReviewInviteORM,
    PeerReviewStatus,
    PresentationEventORM,
    SelfPracticeSessionORM,
    SelfPracticeState,
    UserORM,
)
from services.quality_tracking import compute_quality_report
from utils.security import hash_password


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=pool.StaticPool
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = SessionLocal()
    yield session
    session.close()


def _make_user(db, email="owner@example.com") -> UserORM:
    user = UserORM(email=email, password_hash=hash_password("matkhau-du-dai"), full_name="U")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _make_session(db, owner: UserORM, profile="presentation_solo") -> SelfPracticeSessionORM:
    session = SelfPracticeSessionORM(
        profile=profile,
        video_file_path="/tmp/x.mp4",
        state=SelfPracticeState.COMPLETED,
        user_id=owner.id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _make_event(db, session: SelfPracticeSessionORM, event_type: str, start_sec: float, duration_sec: float = 2.0):
    event = PresentationEventORM(
        session_id=session.id,
        profile=session.profile,
        type=event_type,
        start_sec=start_sec,
        duration_sec=duration_sec,
        measured_value=1.0,
        unit="giây",
        label="x",
        rule_version="0.1.0",
    )
    db.add(event)
    db.commit()
    return event


def _make_invite(db, session: SelfPracticeSessionORM, inviter: UserORM, status=PeerReviewStatus.COMPLETED):
    invite = PeerReviewInviteORM(
        session_id=session.id,
        inviter_user_id=inviter.id,
        token=str(uuid.uuid4()),
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
    )
    db.add(invite)
    db.commit()
    db.refresh(invite)
    return invite


def _make_mark(db, session, invite, rater, mark_sec, created_before_reveal=True):
    note = PeerNoteORM(
        session_id=session.id,
        rater_user_id=rater.id,
        invite_id=invite.id,
        mark_sec=mark_sec,
        created_before_reveal=created_before_reveal,
        rubric_scores={},
    )
    db.add(note)
    db.commit()
    return note


class TestPrecisionByEventType:
    def test_a_mark_near_an_event_counts_as_matched(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0, duration_sec=4.0)
        invite = _make_invite(db, session, owner)
        _make_mark(db, session, invite, rater, mark_sec=12.0)  # inside [10, 14]

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert len(report.by_event_type) == 1
        tally = report.by_event_type[0]
        assert tally.event_type == "E_HEAD_DOWN"
        assert tally.system_events == 1
        assert tally.system_matched == 1
        assert tally.precision == 1.0

    def test_a_mark_far_from_any_event_leaves_it_unmatched(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0, duration_sec=4.0)
        invite = _make_invite(db, session, owner)
        _make_mark(db, session, invite, rater, mark_sec=100.0)  # nowhere near

        report = compute_quality_report(db, tolerance_sec=5.0)
        tally = report.by_event_type[0]
        assert tally.system_events == 1
        assert tally.system_matched == 0
        assert tally.precision == 0.0

    def test_tolerance_window_is_respected_at_the_edge(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0, duration_sec=4.0)  # window [10, 14]
        invite = _make_invite(db, session, owner)
        _make_mark(db, session, invite, rater, mark_sec=16.0)  # 2s past the end, tolerance=2 -> just inside

        report = compute_quality_report(db, tolerance_sec=2.0)
        assert report.by_event_type[0].system_matched == 1

    def test_types_and_profiles_are_tallied_separately(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")

        session_a = _make_session(db, owner, profile="presentation_solo")
        _make_event(db, session_a, "E_HEAD_DOWN", start_sec=10.0)
        invite_a = _make_invite(db, session_a, owner)
        _make_mark(db, session_a, invite_a, rater, mark_sec=10.0)

        session_b = _make_session(db, owner, profile="interview_solo")
        _make_event(db, session_b, "E_STATIC", start_sec=20.0)
        invite_b = _make_invite(db, session_b, owner)
        _make_mark(db, session_b, invite_b, rater, mark_sec=20.0)

        report = compute_quality_report(db, tolerance_sec=5.0)
        keys = {(t.profile, t.event_type) for t in report.by_event_type}
        assert keys == {("presentation_solo", "E_HEAD_DOWN"), ("interview_solo", "E_STATIC")}


class TestMissRate:
    def test_a_mark_with_no_nearby_event_is_a_miss(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        invite = _make_invite(db, session, owner)
        _make_mark(db, session, invite, rater, mark_sec=50.0)  # no events at all this session

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert report.peer_marks_total == 1
        assert report.peer_marks_missed == 1
        assert report.miss_rate == 1.0

    def test_a_mark_near_an_event_is_not_a_miss(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0, duration_sec=4.0)
        invite = _make_invite(db, session, owner)
        _make_mark(db, session, invite, rater, mark_sec=11.0)

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert report.peer_marks_missed == 0
        assert report.miss_rate == 0.0

    def test_no_peer_marks_at_all_is_none_not_zero(self, db):
        """A `0%` miss rate would falsely claim perfect recall; there's simply nothing measured yet."""
        report = compute_quality_report(db)
        assert report.peer_marks_total == 0
        assert report.miss_rate is None


class TestOnlyBlindCompletedNotesCount:
    def test_marks_from_a_still_pending_invite_are_excluded(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0)
        invite = _make_invite(db, session, owner, status=PeerReviewStatus.PENDING)
        _make_mark(db, session, invite, rater, mark_sec=10.0)

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert report.by_event_type == []
        assert report.peer_marks_total == 0

    def test_notes_created_after_reveal_are_excluded(self, db):
        """The DoD's explicit exclusion check: created_before_reveal=False must never count."""
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0)
        invite = _make_invite(db, session, owner, status=PeerReviewStatus.COMPLETED)
        _make_mark(db, session, invite, rater, mark_sec=10.0, created_before_reveal=False)

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert report.by_event_type == []
        assert report.peer_marks_total == 0

    def test_the_rubric_row_itself_mark_sec_none_is_never_treated_as_a_mark(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0)
        invite = _make_invite(db, session, owner)
        _make_mark(db, session, invite, rater, mark_sec=None)

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert report.peer_marks_total == 0

    def test_self_notes_never_influence_the_report(self, db):
        """SelfNote is not independent judgment (plan.md) -- it must never be a data source here at all."""
        from models.notes import SelfNote
        from db.models import SelfNoteORM

        owner = _make_user(db, "a@example.com")
        session = _make_session(db, owner)
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0)
        note = SelfNote(session_id=str(session.id), mark_sec=10.0, text="tu ghi chu")
        db.add(SelfNoteORM(id=uuid.UUID(note.note_id), session_id=session.id, mark_sec=note.mark_sec, text=note.text))
        db.commit()

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert report.by_event_type == []
        assert report.peer_marks_total == 0


class TestInviteCompletionRate:
    def test_completion_rate_across_all_invites(self, db):
        owner = _make_user(db, "a@example.com")
        session = _make_session(db, owner)
        _make_invite(db, session, owner, status=PeerReviewStatus.COMPLETED)
        _make_invite(db, session, owner, status=PeerReviewStatus.COMPLETED)
        _make_invite(db, session, owner, status=PeerReviewStatus.PENDING)
        _make_invite(db, session, owner, status=PeerReviewStatus.EXPIRED)

        report = compute_quality_report(db)
        assert report.invites_total == 4
        assert report.invites_completed == 2
        assert report.invite_completion_rate == 0.5

    def test_no_invites_at_all_is_none_not_zero(self, db):
        report = compute_quality_report(db)
        assert report.invites_total == 0
        assert report.invite_completion_rate is None


class TestProcessingSessionsAreIgnored:
    def test_a_session_still_processing_contributes_nothing(self, db):
        owner = _make_user(db, "a@example.com")
        rater = _make_user(db, "b@example.com")
        session = _make_session(db, owner)
        session.state = SelfPracticeState.PROCESSING
        db.commit()
        _make_event(db, session, "E_HEAD_DOWN", start_sec=10.0)
        invite = _make_invite(db, session, owner)
        _make_mark(db, session, invite, rater, mark_sec=10.0)

        report = compute_quality_report(db, tolerance_sec=5.0)
        assert report.by_event_type == []
