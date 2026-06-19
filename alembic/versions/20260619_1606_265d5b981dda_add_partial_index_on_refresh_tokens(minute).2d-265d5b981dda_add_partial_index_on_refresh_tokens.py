"""add partial index on refresh_tokens

Revision ID: 265d5b981dda
Revises: 
Create Date: 2026-06-19 16:06:43.133918+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '265d5b981dda'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_refresh_tokens_hash_active
        ON refresh_tokens (token_hash)
        WHERE is_revoked = false AND expires_at > now();
    """)

    # op.create_index(
    #     "ix_refresh_tokens_hash_active",
    #     "refresh_tokens",
    #     ["token_hash"],
    #     postgresql_where="is_revoked = false AND expires_at > now()",
    #     postgresql_concurrently=True,
    # )



def downgrade() -> None:
    """Downgrade schema."""
    pass
