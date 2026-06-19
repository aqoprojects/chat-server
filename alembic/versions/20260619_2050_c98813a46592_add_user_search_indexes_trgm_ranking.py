"""add user search indexes trgm ranking

Revision ID: c98813a46592
Revises:     f7096b32c7b9
Create date: 2026-06-19 18:57:44.867645+00:00

Description:
    <fill in what this migration does and why>

Affected tables:
    <list tables created, altered, or dropped>
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# ── Revision identifiers ──────────────────────────────────────────────────────
revision: str = "c98813a46592"
down_revision: Union[str, None] = "f7096b32c7b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY ix_users_username_trgm
            ON users USING gin (username gin_trgm_ops)
            WHERE deleted_at IS NULL;
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY ix_user_profiles_display_name_trgm
            ON user_profiles USING gin (display_name gin_trgm_ops);
        """)

        op.execute("""
            CREATE INDEX CONCURRENTLY ix_user_profiles_follower_count_desc
    ON user_profiles (follower_count DESC);
        """)


def downgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_users_username_trgm;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_user_profiles_display_name_trgm;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_user_profiles_follower_count_desc;")

