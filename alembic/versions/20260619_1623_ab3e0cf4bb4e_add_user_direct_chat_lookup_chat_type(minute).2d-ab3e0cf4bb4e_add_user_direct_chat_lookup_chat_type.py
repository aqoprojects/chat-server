"""add user direct chat lookup (chat_type)

Revision ID: ab3e0cf4bb4e
Revises: 8b11fc296a87
Create Date: 2026-06-19 16:23:23.764249+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ab3e0cf4bb4e'
down_revision: Union[str, Sequence[str], None] = '8b11fc296a87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_chats_direct_active
        ON chats (chat_type)
        WHERE deleted_at IS NULL;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        DROP INDEX CONCURRENTLY IF EXISTS ix_chats_direct_active;
    """)
