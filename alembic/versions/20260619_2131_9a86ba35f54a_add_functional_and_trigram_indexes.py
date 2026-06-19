"""add Functional and trigram indexes

Revision ID: 9a86ba35f54a
Revises:     4f3fcc7d540f
Create date: 2026-06-19 21:31:52.274507+00:00

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
revision: str = '9a86ba35f54a'
down_revision: Union[str, None] = '4f3fcc7d540f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS ix_users_email_lower
            ON users (lower(email))
            WHERE deleted_at IS NULL
        """)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_users_username_trgm
            ON users USING gin (username gin_trgm_ops)
            WHERE deleted_at IS NULL
        """)
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_user_profiles_display_name_trgm
            ON user_profiles USING gin (display_name gin_trgm_ops)
        """)


def downgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_users_email_lower;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_users_username_trgm;")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_user_profiles_display_name_trgm;")