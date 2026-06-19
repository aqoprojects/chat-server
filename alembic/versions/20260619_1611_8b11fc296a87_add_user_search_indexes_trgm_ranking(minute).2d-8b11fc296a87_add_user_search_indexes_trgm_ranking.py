"""add user search indexes (trgm + ranking)

Revision ID: 8b11fc296a87
Revises: 265d5b981dda
Create Date: 2026-06-19 16:11:58.143276+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b11fc296a87'
down_revision: Union[str, Sequence[str], None] = '265d5b981dda'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Needed for similarity() + trigram indexes
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm;")

    # USERS: username trigram index (ILIKE + similarity)
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_users_username_trgm
        ON users USING gin (username gin_trgm_ops)
        WHERE deleted_at IS NULL;
    """)

    # PROFILES: display_name trigram index
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_user_profiles_display_name_trgm
        ON user_profiles USING gin (display_name gin_trgm_ops);
    """)

    # follower_count ordering optimization
    op.execute("""
        CREATE INDEX CONCURRENTLY ix_user_profiles_follower_count_desc
        ON user_profiles (follower_count DESC);
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_users_username_trgm;")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_user_profiles_display_name_trgm;")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_user_profiles_follower_count_desc;")
