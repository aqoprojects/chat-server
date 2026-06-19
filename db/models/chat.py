from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import (
    Boolean, DateTime, Enum, ForeignKey,
    Index, Integer, SmallInteger, String,
    Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
import enum

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User
    from db.models.message import Message


# ── Enums ─────────────────────────────────────────────────────────────────────

class ChatType(str, enum.Enum):
    """
    direct — 1:1 chat between exactly two users.
               Deduplicated on creation: only one direct chat can exist
               between any two users at any time.
    group  — chat with 2 or more participants, a name, and admin controls.
    """
    direct = "direct"
    group  = "group"


class ParticipantRole(str, enum.Enum):
    """
    member — standard participant. Can send and read messages.
    admin  — can add/remove members, update group name/description,
             mute and ban participants.
    owner  — the user who created the group. Cannot be removed by admins.
             Has all admin permissions plus can delete the group.
    """
    member = "member"
    admin  = "admin"
    owner  = "owner"


# ══════════════════════════════════════════════════════════════════════════════
#  Chat
# ══════════════════════════════════════════════════════════════════════════════

class Chat(Base):
    """
    A conversation container — either a 1:1 direct chat or a group chat.

    Direct chats:
        name and description are NULL.
        Exactly two ChatParticipant rows exist.
        Creation is deduplicated: before inserting, the service checks
        for an existing Chat.id via a sorted pair lookup on participants.

    Group chats:
        name and description are set by the creator.
        Any number of ChatParticipant rows (≥ 2).
        Controlled by admin/owner participants.

    last_message_id:
        Denormalised pointer to the most recent message in this chat.
        Used by the chat list endpoint to show a preview without loading
        the full message history. Updated atomically on every message send.

    Soft delete:
        Groups can be "archived" by setting deleted_at. Direct chats are
        never deleted — they persist even if both users delete their accounts
        (content is redacted by the user delete cascade, not the chat).
    """
    __tablename__ = "chats"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    chat_type: Mapped[ChatType] = mapped_column(
        Enum(ChatType, name="chat_type_enum"),
        nullable=False,
        index=True,
    )

    # ── Group-only fields (NULL for direct chats) ─────────────────────────────
    name: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
    )
    # Path to group avatar image (relative to MEDIA_ROOT)
    avatar_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
    )

    # ── Last message pointer (denormalised) ───────────────────────────────────
    last_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        # FK added as deferred to avoid circular dependency with messages table.
        # Set in the migration with DEFERRABLE INITIALLY DEFERRED.
        nullable=True,
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,   # used to sort chat list by most recent activity
    )

    # ── Participant count (denormalised) ──────────────────────────────────────
    participant_count: Mapped[int] = mapped_column(
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
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    participants: Mapped[list["ChatParticipant"]] = relationship(
        "ChatParticipant",
        back_populates="chat",
        cascade="all, delete-orphan",
        lazy="select",
    )
    messages: Mapped[list["Message"]] = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan",
        lazy="select",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Sort active chats by most recent message (chat list endpoint)
        Index(
            "ix_chats_last_message_at",
            "last_message_at",
            postgresql_where="deleted_at IS NULL",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Chat id={self.id} type={self.chat_type.value} "
            f"name={self.name!r}>"
        )


# ══════════════════════════════════════════════════════════════════════════════
#  ChatParticipant
# ══════════════════════════════════════════════════════════════════════════════

class ChatParticipant(Base):
    """
    Membership record linking a User to a Chat.

    This table is the ACL (access control list) for the chat system.
    Every message send, read, and WebSocket subscription checks here
    before touching the messages table.

    is_active = False:
        The user was removed or left. They can no longer send messages
        or receive new ones. Their historical messages remain visible.
        They cannot rejoin unless re-added by an admin (groups only).

    is_muted:
        The user's messages are hidden from other participants.
        The muted user can still read the chat but their messages
        show as muted to others. Admin action.

    is_banned:
        The user is permanently excluded. is_active is also set False.
        The user cannot be re-added to this chat.

    notification_muted:
        The user has muted notifications for this chat (personal preference,
        not an admin action). They still receive messages but no push alerts.

    Direct chat deduplication:
        For direct chats, the service performs a sorted pair lookup:
        SELECT c.id FROM chats c
        JOIN chat_participants cp1 ON cp1.chat_id = c.id AND cp1.user_id = $user_a
        JOIN chat_participants cp2 ON cp2.chat_id = c.id AND cp2.user_id = $user_b
        WHERE c.chat_type = 'direct'
        This is covered by the composite index below.
    """
    __tablename__ = "chat_participants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[ParticipantRole] = mapped_column(
        Enum(ParticipantRole, name="participant_role_enum"),
        nullable=False,
        server_default="member",
    )

    # ── Status flags ──────────────────────────────────────────────────────────
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="true",
    )
    is_muted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    muted_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,        # NULL = muted indefinitely when is_muted=True
    )
    is_banned: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )
    notification_muted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    # ── Read tracking ─────────────────────────────────────────────────────────
    # last_read_message_id: The most recent message this participant has
    # confirmed as read. Used to compute unread count on DB fallback
    # (Redis is the primary counter). Updated by the mark-as-read endpoint.
    last_read_message_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
    )
    last_read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Timestamps ────────────────────────────────────────────────────────────
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    left_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,        # set when is_active → False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    chat: Mapped["Chat"] = relationship(
        "Chat",
        back_populates="participants",
    )
    user: Mapped["User"] = relationship(
        "User",
        back_populates="chat_memberships",
    )

    # ── Constraints & indexes ─────────────────────────────────────────────────
    __table_args__ = (
        # A user can only have one membership row per chat
        UniqueConstraint(
            "chat_id", "user_id",
            name="uq_chat_participants_chat_user",
        ),
        # ACL check: "is user X an active member of chat Y?"
        # This is the hottest query in the system — every WS message
        # and every REST endpoint hits this index.
        Index(
            "ix_chat_participants_chat_user_active",
            "chat_id",
            "user_id",
            postgresql_where="is_active = true",
        ),
        # "All active chats for user X" — WS connect subscription
        Index(
            "ix_chat_participants_user_active",
            "user_id",
            postgresql_where="is_active = true",
        ),
        # Direct chat deduplication self-join
        Index(
            "ix_chat_participants_user_chat",
            "user_id",
            "chat_id",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ChatParticipant chat_id={self.chat_id} "
            f"user_id={self.user_id} role={self.role.value}>"
        )