from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Index,
    Integer, SmallInteger, String, Text,
    UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User


class Post(Base):
    """
    A top-level user post.

    Posts are the root of the content tree. Replies reference posts
    via root_post_id. Posts themselves have no parent.

    Soft delete:
        deleted_at IS NOT NULL → post is soft-deleted.
        Content is replaced with NULL; a placeholder is shown to clients
        if FEATURE_SHOW_DELETED_PLACEHOLDER is enabled.
    """
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,        # NULL after soft delete
    )
    # Optional media attachment (image/video path relative to MEDIA_ROOT)
    media_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )
    media_type: Mapped[Optional[str]] = mapped_column(
        String(20),           # "image" | "video" | None
        nullable=True,
    )

    # ── Denormalised counters ─────────────────────────────────────────────────
    # Maintained in Redis and periodically synced here by Celery beat.
    like_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )
    reply_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    # ── Full-text search ──────────────────────────────────────────────────────
    # Generated tsvector column — maintained automatically by PostgreSQL.
    # Used by the user search endpoint for post content search.
    content_tsv: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        nullable=True,
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
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
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    author: Mapped["User"] = relationship(
        "User",
        back_populates="posts",
    )
    replies: Mapped[list["Reply"]] = relationship(
        "Reply",
        back_populates="root_post",
        cascade="all, delete-orphan",
        lazy="select",
    )
    likes: Mapped[list["PostLike"]] = relationship(
        "PostLike",
        back_populates="post",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Feed query: fetch user's posts, newest first
        Index(
            "ix_posts_author_created",
            "author_id",
            "created_at",
            postgresql_ops={"created_at": "DESC"},
        ),
        # Active posts only
        Index(
            "ix_posts_active",
            "created_at",
            postgresql_where="deleted_at IS NULL",
        ),
        # Full-text search using GIN index on tsvector
        Index(
            "ix_posts_content_fts",
            "content_tsv",
            postgresql_using="gin",
        ),
    )

    def __repr__(self) -> str:
        return f"<Post id={self.id} author_id={self.author_id}>"


class Reply(Base):
    """
    A threaded reply to a Post or another Reply.

    Tree structure:
        root_post_id  → always points to the top-level Post
        parent_id     → points to the direct parent (Post or Reply)
        depth         → 0 = direct reply to a post, 1 = reply to a reply, etc.
        path          → materialized path: "post_uuid.reply_uuid.reply_uuid"

    Fetching strategies:
        All replies for a post  : WHERE root_post_id = $id ORDER BY created_at
        Direct children         : WHERE parent_id = $id
        Full subtree (recursive): WITH RECURSIVE CTE on parent_id
        Subtree via path        : WHERE path LIKE 'root_uuid.target_uuid%'
    """
    __tablename__ = "replies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    root_post_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # parent_id can reference either a post (depth=0) or another reply.
    # We do NOT add a FK to both tables — the parent is resolved in the
    # service layer. The root_post_id FK ensures cascade delete.
    parent_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,        # NULL only for direct replies to the post
        index=True,
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,        # NULL after soft delete
    )
    depth: Mapped[int] = mapped_column(
        SmallInteger,
        nullable=False,
        server_default="0",
    )
    # Materialized path for efficient subtree queries.
    # Format: "<root_post_id>.<reply_id>.<reply_id>"
    # Each segment is a UUID without hyphens to keep the string compact.
    path: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        index=True,
    )

    # ── Denormalised counter ──────────────────────────────────────────────────
    reply_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
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
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    root_post: Mapped["Post"] = relationship(
        "Post",
        back_populates="replies",
    )
    author: Mapped["User"] = relationship("User")
    likes: Mapped[list["PostLike"]] = relationship(
        "PostLike",
        foreign_keys="PostLike.reply_id",
        back_populates="reply",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # All replies for a post, chronological
        Index(
            "ix_replies_root_post_created",
            "root_post_id",
            "created_at",
        ),
        # Direct children of a node — used for incremental tree loading
        Index(
            "ix_replies_parent_id",
            "parent_id",
            "created_at",
        ),
        # Subtree queries via materialized path prefix match
        Index(
            "ix_replies_path",
            "path",
            postgresql_using="btree",
        ),
        # Active replies only
        Index(
            "ix_replies_active",
            "root_post_id",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Reply id={self.id} root_post_id={self.root_post_id} "
            f"depth={self.depth}>"
        )


class PostLike(Base):
    """
    A like on a Post or a Reply.

    Supports liking both posts and replies — exactly one of
    (post_id, reply_id) is non-NULL per row. This is enforced by a
    CHECK constraint added in the Alembic migration.

    Idempotency:
        The unique constraints below prevent double-likes at the DB level.
        Redis also guards against double-likes before the DB write.
    """
    __tablename__ = "post_likes"

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
    # Exactly one of these is non-NULL
    post_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("posts.id", ondelete="CASCADE"),
        nullable=True,
    )
    reply_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("replies.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    post: Mapped[Optional["Post"]] = relationship(
        "Post",
        foreign_keys=[post_id],
        back_populates="likes",
    )
    reply: Mapped[Optional["Reply"]] = relationship(
        "Reply",
        foreign_keys=[reply_id],
        back_populates="likes",
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        # A user can like a specific post only once
        UniqueConstraint(
            "user_id", "post_id",
            name="uq_post_likes_user_post",
        ),
        # A user can like a specific reply only once
        UniqueConstraint(
            "user_id", "reply_id",
            name="uq_post_likes_user_reply",
        ),
        Index("ix_post_likes_post_id", "post_id"),
        Index("ix_post_likes_reply_id", "reply_id"),
        Index("ix_post_likes_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<PostLike user_id={self.user_id} "
            f"post_id={self.post_id} reply_id={self.reply_id}>"
        )