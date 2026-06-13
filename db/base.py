from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Naming convention for all constraints.
# This makes Alembic-generated migration names predictable and ensures
# constraint names are consistent across databases.
# Required for Alembic's --autogenerate to produce ALTER TABLE statements
# that can be reversed cleanly.
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """
        Shared declarative base for all ORM models.

        All model files do:
    from db.base import Base
    class User(Base): ...

    Alembic's env.py imports Base.metadata to discover all tables
    for autogenerate.
    """


metadata = MetaData(naming_convention=NAMING_CONVENTION)
