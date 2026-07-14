"""
db/session.py

SQLAlchemy engine, session factory, and FastAPI dependency for the
session-persistence database (PostgreSQL in production; any SQLAlchemy-
supported dialect works for local smoke tests, e.g. SQLite).

Usage in a router:

    from fastapi import Depends
    from sqlalchemy.orm import Session
    from db.session import get_db

    @router.get("/sessions/{session_id}")
    def read_session(session_id: str, db: Session = Depends(get_db)):
        ...
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config import settings

# `pool_pre_ping` avoids handing out dead connections after the DB restarts
# or an idle connection is dropped by a proxy/firewall — cheap insurance for
# a long-lived FastAPI process talking to a long-lived Postgres instance.
engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a `Session` scoped to a single request and
    guarantees it is closed afterwards, regardless of whether the request
    succeeded or raised.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """
    Create all tables that don't yet exist.

    Convenience for local development / first run. In any environment where
    schema history matters, use Alembic (`alembic upgrade head`) instead —
    this function does not know about migrations and will not alter existing
    tables.
    """
    from db.base import Base
    import db.models  # noqa: F401  (ensures every model is registered on Base.metadata)

    Base.metadata.create_all(bind=engine)
