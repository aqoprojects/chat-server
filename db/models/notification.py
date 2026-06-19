from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base

if TYPE_CHECKING:
    from db.models.user import User


# ══════════════════════════════════════════════════════════════════════════════
#  Notification type enum
# ══════════════════════════════════════════════════════════════════════════════


class NotificationType(str, enum.Enum):
    """
    Canonical set of notification types.

    mention         — user was @mentioned in a chat message
    reply           — someone replied to user's post or reply
    follow          — someone followed the user
    like            — someone liked user's post or reply
    chat_message    — new message in a direct chat (for push only —
                      in-app notifications don't show per-message alerts,
                      only unread counts. This type is used exclusively
                      by the Celery push task for offline users.)
    group_added     — user was added to a group chat
    group_removed   — user was removed from a group chat
    group_muted     — user was muted in a group chat
    group_banned    — user was banned from a group chat
    admin_promoted  — user was promoted to admin in a group
    system          — server-generated system message (no actor)
    """

    mention = "mention"
    reply = "reply"
    follow = "follow"
    like = "like"
    chat_message = "chat_message"
    group_added = "group_added"
    group_removed = "group_removed"
    group_muted = "group_muted"
    group_banned = "group_banned"
    admin_promoted = "admin_promoted"
    system = "system"


# ══════════════════════════════════════════════════════════════════════════════
#  Notification delivery channel enum
# ══════════════════════════════════════════════════════════════════════════════


class DeliveryChannel(str, enum.Enum):
    """
    How this notification was or should be delivered.

    in_app   — delivered via WebSocket to the online user's session.
               Stored in DB regardless of delivery success.
    push     — queued in Celery for FCM/APNs delivery to an offline user.
               Only created when the user has no active WebSocket connection.
    both     — both in-app and push (used for high-priority notifications
               like being banned from a group).
    """

    in_app = "in_app"
    push = "push"
    both = "both"


# ══════════════════════════════════════════════════════════════════════════════
#  Notification
# ══════════════════════════════════════════════════════════════════════════════


class Notification(Base):
    """
    A single notification event for a specific user.

    Lifecycle:
        1. Service creates a Notification row and increments the Redis
           unread counter for the recipient.
        2. If the recipient has an active WebSocket connection, the
           notification is immediately pushed via the connection manager.
           delivery_channel = "in_app", delivered_at = now().
        3. If the recipient is offline, a Celery push task is queued.
           delivery_channel = "push" or "both".
        4. When the recipient calls GET /notifications or opens the app,
           notifications are fetched from DB (paginated).
        5. Mark-as-read sets is_read=True, read_at=now(), and decrements
           the Redis unread counter.
        6. Celery beat deletes notifications older than 90 days.

    Idempotency:
        The (recipient_id, notification_type, entity_id, actor_id) combination
        is not unique — the same actor can trigger the same notification type
        on the same entity multiple times (e.g., like → unlike → like again).
        Idempotency is enforced at the service layer with a time-window check:
        if an identical notification was created in the last 60 seconds,
        it is suppressed (prevents notification spam on rapid actions).
        The idempotency_key column stores a hash of the deduplicated fields
        for this check.
    """

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )

    # ── Recipient ─────────────────────────────────────────────────────────────
    recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Actor (who triggered this notification) ───────────────────────────────
    # NULL for system notifications
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ── Notification type ─────────────────────────────────────────────────────
    notification_type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, name="notification_type_enum"),
        nullable=False,
        index=True,
    )

    # ── Polymorphic entity reference ──────────────────────────────────────────
    # The entity that the notification is about.
    # entity_type: "message" | "post" | "reply" | "chat" | "user" | "system"
    # entity_id:   UUID of the entity (NULL for system notifications)
    entity_type: Mapped[Optional[str]] = mapped_column(
        String(20),
        nullable=True,
    )
    entity_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        # No FK — polymorphic reference across multiple tables.
        # The service validates entity existence before creating the notification.
    )

    # ── Human-readable title and body ─────────────────────────────────────────
    # Pre-rendered on the server so the client can display the notification
    # without any additional logic or API calls.
    # Also used as the push notification title/body.
    title: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    body: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        # Short preview text. e.g. first 100 chars of a message.
        # NULL for notifications with no body text (follow, like).
    )

    # ── Type-specific payload (JSONB) ─────────────────────────────────────────
    # Contains all the data the frontend needs to render the notification
    # and navigate to the correct screen.
    #
    # mention:        {"chat_id": "...", "message_id": "...",
    #                  "chat_name": "Dev Team", "preview": "Hey @alice"}
    # reply:          {"post_id": "...", "reply_id": "...",
    #                  "preview": "Great insight!"}
    # follow:         {"follower_id": "...", "follower_username": "bob",
    #                  "follower_avatar_path": "avatars/..."}
    # like:           {"post_id": "...", "liker_username": "carol"}
    # group_added:    {"chat_id": "...", "chat_name": "...",
    #                  "added_by": "admin_username"}
    # group_removed:  {"chat_id": "...", "chat_name": "...",
    #                  "removed_by": "admin_username", "reason": "..."}
    # group_muted:    {"chat_id": "...", "chat_name": "...",
    #                  "muted_until": "2025-01-01T12:00:00Z"}
    # group_banned:   {"chat_id": "...", "chat_name": "..."}
    # admin_promoted: {"chat_id": "...", "chat_name": "..."}
    # system:         {"message": "...", "action_url": "..."}
    data: Mapped[Optional[dict]] = mapped_column(
        JSONB,
        nullable=True,
    )

    # ── Delivery ──────────────────────────────────────────────────────────────
    delivery_channel: Mapped[DeliveryChannel] = mapped_column(
        Enum(DeliveryChannel, name="delivery_channel_enum"),
        nullable=False,
        server_default="in_app",
    )
    # Set when the WebSocket delivery was confirmed or push was queued
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    # True if the Celery push task successfully sent to FCM/APNs
    push_sent: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
    )

    # ── Read state ────────────────────────────────────────────────────────────
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default="false",
        index=True,
    )
    read_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # ── Idempotency ───────────────────────────────────────────────────────────
    # SHA-256 hash of (recipient_id + notification_type + entity_id + actor_id).
    # The service checks for an existing row with this hash created in the
    # last 60 seconds before inserting — prevents duplicate notifications
    # from rapid repeated actions.
    idempotency_key: Mapped[Optional[str]] = mapped_column(
        String(64),
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

    # ── Relationships ─────────────────────────────────────────────────────────
    recipient: Mapped["User"] = relationship(
        "User",
        foreign_keys=[recipient_id],
        back_populates="notifications",
    )
    actor: Mapped[Optional["User"]] = relationship(
        "User",
        foreign_keys=[actor_id],
        lazy="select",
    )

    # ── Indexes ───────────────────────────────────────────────────────────────
    __table_args__ = (
        # Primary notification list query:
        # "All unread notifications for user X, newest first"
        # This is the notification bell endpoint — must be fast.
        Index(
            "ix_notifications_recipient_unread",
            "recipient_id",
            "created_at",
            postgresql_where="is_read = false",
        ),
        # Full notification history query (includes read):
        # "All notifications for user X, newest first" (paginated)
        Index(
            "ix_notifications_recipient_created",
            "recipient_id",
            "created_at",
        ),
        # Type filter: "All mention notifications for user X"
        # Used by the notification filter tabs in the frontend.
        Index(
            "ix_notifications_recipient_type",
            "recipient_id",
            "notification_type",
            "created_at",
        ),
        # Idempotency window check:
        # "Did we already create a notification with this key recently?"
        # Combined with a WHERE created_at > now() - interval '60 seconds'
        # in the service layer.
        Index(
            "ix_notifications_idempotency",
            "idempotency_key",
            "created_at",
            postgresql_where="idempotency_key IS NOT NULL",
        ),
        # Entity-based lookup:
        # "All notifications about entity X" — used when an entity is
        # deleted to bulk-mark related notifications as stale.
        Index(
            "ix_notifications_entity",
            "entity_type",
            "entity_id",
            postgresql_where="entity_id IS NOT NULL",
        ),
        # Push delivery queue:
        # "All undelivered push notifications" — polled by the Celery
        # retry task for notifications whose push delivery failed.
        Index(
            "ix_notifications_push_pending",
            "created_at",
            postgresql_where=(
                "delivery_channel IN ('push', 'both') "
                "AND push_sent = false "
                "AND is_read = false"
            ),
        ),
        # Cleanup index:
        # Celery beat: DELETE FROM notifications WHERE created_at < now() - interval '90 days'
        # This partial index covers old unread notifications specifically —
        # the most expensive to scan without it.
        Index(
            "ix_notifications_cleanup",
            "created_at",
            postgresql_where="is_read = false",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} "
            f"type={self.notification_type.value} "
            f"recipient_id={self.recipient_id} "
            f"read={self.is_read}>"
        )
