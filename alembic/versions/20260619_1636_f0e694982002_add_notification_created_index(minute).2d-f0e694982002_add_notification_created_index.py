"""add notification created index

Revision ID: f0e694982002
Revises: 8e0f6c718536
Create Date: 2026-06-19 16:36:58.686158+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f0e694982002'
down_revision: Union[str, Sequence[str], None] = '8e0f6c718536'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_notifications_created_at
        ON notifications (created_at);
    """)


def downgrade() -> None:
    """Downgrade schema."""
    pass
