from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey,
    Index, Integer, SmallInteger, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User
    from db.models.chat import Chat


# ── Enums ─────────────────────────────────────────────────────────────────────

class MessageType(str, enum.Enum):
    """
    text       — plain text message
    image      — image attachment (path in attachment_path)
    file       — generic file attachment
    voice      — voice message (duration + waveform in metadata JSONB)
    system     — system-generated event (member joined, left, muted, etc.)
                 These are never sent by users — only by the server.
    """
    text   = "text"
    image  = "image"
    file   = "file"
    voice  = "voice"
    system = "system"


class DeliveryStatus(str, enum.Enum):
    """
    sent      — written to DB and Redis Stream; not yet delivered to any socket
    delivered — at least one recipient's WebSocket has ACK'd receipt
    read      — at least one recipient has called mark-as-read
    """
    sent      = "sent"
    delivered = "delivered"
    read      = "read"


# ══════════════════════════════════════════════════════════════════════════════
#  Message
# ══════════════════════════════════════════════════════════════════════════════

class Message(Base):
    """
    A single message inside a Chat.

    All message types (text, image, file, voice, system) share this table.
    Type-specific fields are:
        content         → text messages
        attachment_path → image / file messages
        attachment_name → original filename for file messages
        attachment_size → bytes, for file messages
        metadata JSONB  → voice (duration_seconds, waveform array),
                          system (event_type, actor_id, target_id),
                          E2E (key_id, encrypted_payload_hash)

    Quoted / threaded replies:
        quoted_message_id → the message being quoted (shown inline above)
        thread_root_id    → NULL for top-level, or the root message of a thread

    E2E encryption:
        is_encrypted flag signals that `content` holds ciphertext.
        The `metadata` JSONB holds key exchange identifiers.
        Key material itself is never stored server-side.

    Edit tracking:
        edited_at is set on first edit and updated on each subsequent edit.
        Full edit history is stored in MessageEdit (below) for audit trail.

    Soft delete:
        deleted_at is set; content and attachment_path are NULLed.
        The row is retained for read-receipt integrity and reply references.
    """
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sender_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,        # NULL if sender's account was deleted
        index=True,
    )
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type_enum"),
        nullable=False,
        server_default="text",
        index=True,
    )

    # ── Content fields ────────────────────────────────────────────────────────
    content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,        # NULL for non-text types and deleted messages
    )

    # ── Attachment fields (NULL for text and system messages) ─────────────────
    attachment_path: Mapped[Optional[str]] = mapped_column(
        String(500),          # relative to MEDIA_ROOT
        nullable=True,
    )
    attachment_name: Mapped[Optional[str]] = mapped_column(
        String(255),          # original filename shown to users
        nullable=True,
    )
    attachment_mime: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    attachment_size: Mapped[Optional[int]] = mapped_column(
        Integer,              # bytes
        nullable=True,
    )

    # ── Type-specific metadata (JSONB) ────────────────────────────────────────
    # Voice:  {"duration_seconds": 12, "waveform": [0.1, 0.4, ...]}
    # System: {"event_type": "member_joined", "actor_id": "uuid", "target_id": "uuid"}
    # E2E:    {"key_id": "...", "algorithm": "AES-GCM"}
    metadata: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )

    # ── Threading / quoting ───────────────────────────────────────────────────
    # quoted_message_id: shown as an inline preview above this message
    quoted_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # thread_root_id: groups messages into a thread.
    # NULL = this is a top-level chat message (not part of a thread).
    # Non-NULL = this is a threaded reply under thread_root_id.
    thread_root_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Encryption flag ───────────────────────────────────────────────────────
    is_encrypted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    # ── Delivery status ───────────────────────────────────────────────────────
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="delivery_status_enum"),
        nullable=False,
        server_default="sent",
        index=True,
    )

    # ── Redis Stream reference ────────────────────────────────────────────────
    # The Redis Stream entry ID for this message.
    # Stored so that offline catch-up can use XRANGE with this ID.
    # Format: "1234567890123-0" (Redis Stream ID string)
    stream_id: Mapped[Optional[str]] = mapped_column(
        String(30),
        nullable=True,
    )

    # ── Edit tracking ─────────────────────────────────────────────────────────
    edited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,        # NULL = never edited
    )

    # ── Idempotency ───────────────────────────────────────────────────────────
    # Client-supplied idempotency key — prevents duplicate messages
    # if the client retries after a network timeout.
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(36),           # UUID format
        nullable=True,
        index=True,
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
    chat: Mapped["Chat"] = relationship(
        "Chat",
        back_populates="messages",
    )
    sender: Mapped[Optional["User"]] = relationship("User")
    reactions: Mapped[list["MessageReaction"]] = relationship(
        "MessageReaction",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="select",
    )
    reads: Mapped[list["MessageRead"]] = relationship(
        "MessageRead",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="select",
    )
    edits: Mapped[list["MessageEdit"]] = relationship(
        "MessageEdit",
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="select",
    )
    quoted_message: Mapped[Optional["Message"]] = relationship(
        "Message",
        foreign_keys=[quoted_message_id],
        remote_side="Message.id",
        lazy="select",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Primary message history query: all messages in a chat, newest first
        Index(
            "ix_messages_chat_created",
            "chat_id",
            "created_at",
        ),
        # Active messages only (exclude soft-deleted)
        Index(
            "ix_messages_chat_active",
            "chat_id",
            "created_at",
            postgresql_where="deleted_at IS NULL",
        ),
        # Thread fetch: all messages in a thread
        Index(
            "ix_messages_thread_root",
            "thread_root_id",
            "created_at",
            postgresql_where="thread_root_id IS NOT NULL",
        ),
        # Idempotency key lookup (short TTL in Redis; DB is fallback)
        Index(
            "ix_messages_idempotency",
            "chat_id",
            "idempotency_key",
            postgresql_where="idempotency_key IS NOT NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Message id={self.id} chat_id={self.chat_id} "
            f"type={self.message_type.value}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  MessageEdit
# ══════════════════════════════════════════════════════════════════════════════

class MessageEdit(Base):
    """
    Append-only edit history log for messages.

    One row per edit event. The current content is always in messages.content.
    This table stores what the content WAS before each edit, enabling an
    "edit history" feature and audit trail.

    Only created when FEATURE_MESSAGE_EDIT_HISTORY is True in settings.
    The message service checks this flag before inserting.
    """
    __tablename__ = "message_edits"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Content BEFORE this edit was applied
    previous_content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    edited_by_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    edited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="edits",
    )

    def __repr__(self) -> str:
        return f"<MessageEdit message_id={self.message_id} at={self.edited_at}>"


# ══════════════════════════════════════════════════════════════════════════════
#  MessageReaction
# ══════════════════════════════════════════════════════════════════════════════

class MessageReaction(Base):
    """
    An emoji reaction on a message.

    Each (user, message, emoji) triplet is unique — a user can react
    with the same emoji only once per message. A user CAN react with
    multiple different emojis to the same message (multiple rows, different emoji).

    emoji column:
        Stores the Unicode emoji character(s), e.g. "❤️", "👍", "😂".
        Max 10 characters covers compound emoji sequences (skin tone modifiers,
        ZWJ sequences).

    Aggregation:
        The API aggregates reactions by emoji:
        SELECT emoji, COUNT(*) as count, array_agg(user_id) as reactors
        FROM message_reactions
        WHERE message_id = $id
        GROUP BY emoji
        ORDER BY count DESC
    """
    __tablename__ = "message_reactions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    emoji: Mapped[str] = mapped_column(
        String(10),           # Unicode emoji, max 10 chars for compound sequences
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="reactions",
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        # One reaction per (user, message, emoji) triplet
        UniqueConstraint(
            "message_id", "user_id", "emoji",
            name="uq_message_reactions_message_user_emoji",
        ),
        # Aggregation query: all reactions for a message
        Index(
            "ix_message_reactions_message_id",
            "message_id",
        ),
        # "Has user X reacted with Y to message Z?" — idempotency check
        Index(
            "ix_message_reactions_user_message",
            "user_id",
            "message_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MessageReaction message_id={self.message_id} "
            f"user_id={self.user_id} emoji={self.emoji!r}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  MessageRead
# ══════════════════════════════════════════════════════════════════════════════

class MessageRead(Base):
    """
    Per-user read receipt for a specific message.

    One row per (user, message) pair. Created when the mark-as-read
    endpoint is called or when the WebSocket client sends a read event.

    Relationship to unread counts:
        Redis holds the authoritative unread count (fast increment/decrement).
        This table is the durable source of truth — consulted on:
            1. Redis cache miss (cold start, Redis restart).
            2. The "seen by" feature (who has read this message?).
            3. Offline catch-up: XRANGE from the user's last-read stream ID.

    Performance note:
        This is a very high-write table in an active chat. The indexes
        are carefully chosen to cover the two hottest queries:
            a) "Has user X read message Y?" (idempotency before insert)
            b) "What is the last message user X read in chat Y?"
               (answered by chat_participants.last_read_message_id, not here)
    """
    __tablename__ = "message_reads"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("messages.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        # Denormalised from Message.chat_id for query efficiency.
        # Avoids a JOIN to messages when computing "unread count in chat X".
    )
    read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    message: Mapped["Message"] = relationship(
        "Message",
        back_populates="reads",
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        # One read receipt per (user, message) pair
        UniqueConstraint(
            "message_id", "user_id",
            name="uq_message_reads_message_user",
        ),
        # "Seen by" query: who has read message X?
        Index(
            "ix_message_reads_message_id",
            "message_id",
        ),
        # "Has user X read anything in chat Y after timestamp T?"
        # Used for unread count recalculation on DB fallback.
        Index(
            "ix_message_reads_user_chat",
            "user_id",
            "chat_id",
            "read_at",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<MessageRead message_id={self.message_id} "
            f"user_id={self.user_id} at={self.read_at}>"
        )