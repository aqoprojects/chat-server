# # Import all model modules so SQLAlchemy registers their Table objects
# # into Base.metadata before Alembic inspects it.
# #
# # When you add a new model file, add its import here.
# # Alembic's env.py imports this module, which triggers all model
# # registrations as a side effect.

# from db.models.chat import Chat, ChatParticipant  # noqa: F401
# from db.models.follow import Follow  # noqa: F401
# from db.models.interest import Interest, UserInterest  # noqa: F401
# from db.models.message import Message, MessageReaction, MessageRead  # noqa: F401
# from db.models.notification import Notification  # noqa: F401
# from db.models.post import Post  # noqa: F401
# from db.models.token import BlacklistedToken, RefreshToken  # noqa: F401
# from db.models.user import User  # noqa: F401

# __all__ = [
#     "User",
#     "RefreshToken",
#     "BlacklistedToken",
#     "Interest",
#     "UserInterest",
#     "Follow",
#     "Post",
#     "Chat",
#     "ChatParticipant",
#     "Message",
#     "MessageReaction",
#     "MessageRead",
#     "Notification",
# ]
