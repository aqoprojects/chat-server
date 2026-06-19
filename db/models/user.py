from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey,
    Index, Integer, String, Text, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.token import RefreshToken, BlacklistedToken
    from db.models.interest import UserInterest
    from db.models.follow import Follow
    from db.models.post import Post
    from db.models.chat import ChatParticipant
    from db.models.notification import Notification


class User(Base):
    """
    Core user account record.

    One row per registered user. Contains only authentication-relevant
    fields. Display and social fields live in UserProfile (below).

    Soft-delete pattern:
        deleted_at IS NULL  → active account
        deleted_at IS NOT NULL → deleted account (hidden from all queries)
    """
    __tablename__ = "users"

    # ── Identity ──────────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    email: Mapped[str] = mapped_column(
        String(320),       # RFC 5321 max email length
        unique=True,
        nullable=False,
        index=True,
    )
    username: Mapped[str] = mapped_column(
        String(30),
        unique=True,
        nullable=False,
        index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # ── Verification & status ─────────────────────────────────────────────────
    is_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
    )
    is_superuser: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    # ── IP / registration metadata ────────────────────────────────────────────
    registered_ip: Mapped[Optional[str]] = mapped_column(
        String(45),        # IPv6 max length
        nullable=True,
    )
    registered_country: Mapped[Optional[str]] = mapped_column(
        String(2),         # ISO 3166-1 alpha-2
        nullable=True,
    )
    registered_city: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,        # partial index below filters IS NULL quickly
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Username change cooldown ──────────────────────────────────────────────
    username_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    profile: Mapped[Optional["UserProfile"]] = relationship(
        "UserProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
        lazy="select",
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    interests: Mapped[list["UserInterest"]] = relationship(
        "UserInterest",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    posts: Mapped[list["Post"]] = relationship(
        "Post",
        back_populates="author",
        cascade="all, delete-orphan",
        lazy="select",
    )
    followers: Mapped[list["Follow"]] = relationship(
        "Follow",
        foreign_keys="Follow.following_id",
        back_populates="following",
        cascade="all, delete-orphan",
        lazy="select",
    )
    following: Mapped[list["Follow"]] = relationship(
        "Follow",
        foreign_keys="Follow.follower_id",
        back_populates="follower",
        cascade="all, delete-orphan",
        lazy="select",
    )
    chat_memberships: Mapped[list["ChatParticipant"]] = relationship(
        "ChatParticipant",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="select",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="recipient",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Partial index: active users only — the vast majority of queries
        # filter on deleted_at IS NULL. This index is far smaller and
        # faster than a full index on (email) across all rows.
        Index(
            "ix_users_email_active",
            "email",
            postgresql_where="deleted_at IS NULL",
        ),
        Index(
            "ix_users_username_active",
            "username",
            postgresql_where="deleted_at IS NULL",
        ),
        # Full-text search index on username for the user search endpoint.
        # Using GIN with to_tsvector for fast prefix and full-word matching.
        Index(
            "ix_users_username_fts",
            "username",
            postgresql_using="gin",
            postgresql_ops={"username": "gin_trgm_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} username={self.username!r}>"


class UserProfile(Base):
    """
    User-visible display fields — bio, avatar, display name, social links.
    Separated from User so the auth table stays lean and cache-friendly.
    One UserProfile row per User row (1:1, created at registration).
    """
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # ── Display fields ────────────────────────────────────────────────────────
    display_name: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
    )
    bio: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    location: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    website_url: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    # ── Avatar ────────────────────────────────────────────────────────────────
    # Stores the relative path from MEDIA_ROOT, not a full URL.
    # The API constructs full URLs using APP_BASE_URL + this path.
    # Example: "avatars/user-uuid/original.webp"
    avatar_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    # Stores the blurred placeholder as a base64-encoded string (tiny JPEG,
    # ~200–400 bytes). Sent inline in the API response so the client can
    # show a blurred preview before the full avatar loads.
    avatar_blurhash: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )

    # ── Counters (denormalised for fast profile reads) ────────────────────────
    # These are incremented/decremented in Redis and periodically synced
    # back to PostgreSQL by a Celery beat task. Serve from Redis in hot
    # path; fall back to these columns on cache miss.
    follower_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    following_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    post_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    user: Mapped["User"] = relationship(
        "User",
        back_populates="profile",
    )

    def __repr__(self) -> str:
        return f"<UserProfile user_id={self.user_id}>"


class VerificationToken(Base):
    """
    Email verification codes.

    One row per pending verification. The code is stored as a SHA-256
    hash — never plaintext. The raw code is emailed to the user and
    never stored anywhere persistent.

    TTL is enforced in Redis (faster check) and in this table
    (expires_at column for DB-level cleanup via Celery beat).

    A new row replaces the previous one on resend — enforced by the
    unique constraint on user_id.
    """
    __tablename__ = "verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,          # one pending token per user at a time
        nullable=False,
        index=True,
    )
    # SHA-256 hash of the 6-digit code emailed to the user
    code_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,           # Celery cleanup job: DELETE WHERE expires_at < now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,        # set when the user successfully verifies
    )

    def __repr__(self) -> str:
        return f"<VerificationToken user_id={self.user_id} expires_at={self.expires_at}>"