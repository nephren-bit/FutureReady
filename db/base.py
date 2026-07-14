"""
db/base.py

Declarative base for every SQLAlchemy ORM model in the persistence layer.
Kept in its own module (rather than inside db/models.py) so Alembic's
`env.py` can import just the metadata without pulling in the full model
module graph, and so there is exactly one `Base` shared by every table.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models in `db/models.py`."""
