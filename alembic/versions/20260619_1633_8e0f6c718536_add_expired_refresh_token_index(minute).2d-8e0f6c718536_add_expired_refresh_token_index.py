"""add expired refresh token index

Revision ID: 8e0f6c718536
Revises: 104000d422b2
Create Date: 2026-06-19 16:33:53.498192+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e0f6c718536'
down_revision: Union[str, Sequence[str], None] = '104000d422b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_refresh_tokens_expired_revoked
        ON refresh_tokens (expires_at)
        WHERE is_revoked = true;
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
