"""add message content for full-text search inside chat

Revision ID: 104000d422b2
Revises: ab3e0cf4bb4e
Create Date: 2026-06-19 16:30:08.111392+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '104000d422b2'
down_revision: Union[str, Sequence[str], None] = 'ab3e0cf4bb4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_messages_content_fts
        ON messages USING gin (to_tsvector('english', content))
        WHERE deleted_at IS NULL AND content IS NOT NULL;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("""
        DROP INDEX CONCURRENTLY IF EXISTS ix_messages_content_fts;
    """)
