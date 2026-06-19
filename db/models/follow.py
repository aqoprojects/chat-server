from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime, ForeignKey, Index,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User


class Follow(Base):
    """
    Directed follower/following relationship between two users.

    Terminology:
        follower  — the user who is doing the following (initiated the action)
        following — the user being followed (the target)

    Reading: "follower_id follows following_id"

    Mutual detection:
        A mutual follow exists when both (A→B) and (B→A) rows exist.
        The mutual detection utility in services/follow_service.py checks
        for this with a self-join or EXISTS subquery.

    No soft delete:
        Unfollowing deletes the row. There is no history requirement for
        follow events. If history is needed later, add an event log table.
    """
    __tablename__ = "follows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    # The user doing the following
    follower_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The user being followed
    following_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    follower: Mapped["User"] = relationship(
        "User",
        foreign_keys=[follower_id],
        back_populates="following",
    )
    following: Mapped["User"] = relationship(
        "User",
        foreign_keys=[following_id],
        back_populates="followers",
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        # Prevent duplicate follow rows
        UniqueConstraint(
            "follower_id", "following_id",
            name="uq_follows_follower_following",
        ),
        # Prevent self-follows at DB level
        # CHECK (follower_id <> following_id)
        # Added as a raw DDL check constraint via Alembic in the migration.

        # Fast lookup: "who does user X follow?"
        Index("ix_follows_follower_id", "follower_id"),

        # Fast lookup: "who follows user X?"
        Index("ix_follows_following_id", "following_id"),

        # Composite index for mutual detection query:
        # SELECT 1 FROM follows
        # WHERE follower_id=$A AND following_id=$B
        Index(
            "ix_follows_mutual_check",
            "follower_id",
            "following_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Follow follower_id={self.follower_id} "
            f"following_id={self.following_id}>"
        )