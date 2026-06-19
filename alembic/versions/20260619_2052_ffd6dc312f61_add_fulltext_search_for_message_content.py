"""add fulltext search for message content

Revision ID: ffd6dc312f61
Revises:     609eea68d09c
Create date: 2026-06-19 19:38:11.182926+00:00

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
revision: str = 'ffd6dc312f61'
down_revision: Union[str, None] = '609eea68d09c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY ix_messages_content_fts
            ON messages USING gin (to_tsvector('english', content))
            WHERE deleted_at IS NULL AND content IS NOT NULL;
        """)


def downgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_messages_content_fts;")