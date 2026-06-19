from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    DateTime, ForeignKey, Index,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User


class Interest(Base):
    """
    Global interest/category taxonomy.
    Seeded by scripts/seed_categories.py — not created by users.
    Examples: "Technology", "Sports", "Music", "Gaming".
    """
    __tablename__ = "interests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    name: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    slug: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
        index=True,           # used in URL paths: /interests/technology
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    icon_name: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,        # icon identifier for the frontend
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user_interests: Mapped[list["UserInterest"]] = relationship(
        "UserInterest",
        back_populates="interest",
        cascade="all, delete-orphan",
        lazy="select",
    )

    def __repr__(self) -> str:
        return f"<Interest slug={self.slug!r}>"


class UserInterest(Base):
    """
    Many-to-many join between users and interests.
    One row per (user, interest) pair.
    Used to personalise content feeds and user search ranking.
    """
    __tablename__ = "user_interests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    interest_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interests.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        back_populates="interests",
    )
    interest: Mapped["Interest"] = relationship(
        "Interest",
        back_populates="user_interests",
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        UniqueConstraint(
            "user_id", "interest_id",
            name="uq_user_interests_user_interest",
        ),
        Index("ix_user_interests_user_id", "user_id"),
        Index("ix_user_interests_interest_id", "interest_id"),
    )

    def __repr__(self) -> str:
        return f"<UserInterest user_id={self.user_id} interest_id={self.interest_id}>"