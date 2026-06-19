from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, ForeignKey,
    Index, String, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User


class RefreshToken(Base):
    """
    Persistent refresh tokens for the sliding-session auth system.

    Each login event creates one row. On every token rotation:
        1. The old row's is_revoked is set to True.
        2. A new row is inserted with the new token_hash and same family_id.

    Stolen token detection:
        If a token with is_revoked=True is presented, the entire family_id
        group is revoked (all rows with that family_id get is_revoked=True).
        The user must log in again.

    family_id groups all refresh tokens from one login session.
    """
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # family_id groups all tokens from one login event.
    # When any token in the family is reused after rotation → revoke all.
    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,
        index=True,
    )
    # SHA-256 hash of the raw refresh token JWT string.
    # Never store the raw token — hash it before persisting.
    token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
    )
    is_revoked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        index=True,
    )
    # Device/client metadata — optional, for session management UI
    user_agent: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    ip_address: Mapped[Optional[str]] = mapped_column(
        String(45),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        back_populates="refresh_tokens",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Composite index for stolen-token family revocation query:
        # UPDATE refresh_tokens SET is_revoked=true
        # WHERE family_id = $1 AND is_revoked = false
        Index(
            "ix_refresh_tokens_family_active",
            "family_id",
            "is_revoked",
        ),
        # Cleanup index: Celery beat deletes expired rows periodically.
        # Partial index on non-revoked, non-expired rows for fast lookups.
        Index(
            "ix_refresh_tokens_user_active",
            "user_id",
            "is_revoked",
            postgresql_where="is_revoked = false",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<RefreshToken id={self.id} user_id={self.user_id} "
            f"revoked={self.is_revoked}>"
        )


class BlacklistedToken(Base):
    """
    Blacklisted JWT access tokens.

    When a user logs out or a token is explicitly revoked, the access
    token's JTI (JWT ID) is stored here so the auth middleware can
    reject it even before it expires.

    Redis is the primary blacklist store (fast O(1) lookup). This table
    is the durable backup — it is consulted only on Redis cache miss and
    is used to repopulate Redis after a Redis restart.

    Rows are automatically cleaned up by a Celery beat task that deletes
    rows WHERE expires_at < now() — keeping the table small.
    """
    __tablename__ = "blacklisted_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    # jti = JWT ID claim — unique identifier per access token.
    jti: Mapped[str] = mapped_column(
        String(36),           # UUID string length
        unique=True,
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # When the access token would have naturally expired.
    # After this time the token is invalid anyway — the blacklist
    # entry can be safely deleted.
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    blacklisted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    def __repr__(self) -> str:
        return f"<BlacklistedToken jti={self.jti} user_id={self.user_id}>"