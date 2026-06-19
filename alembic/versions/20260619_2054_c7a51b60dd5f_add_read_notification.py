"""add read notification

Revision ID: c7a51b60dd5f
Revises:     683cf6ccb920
Create date: 2026-06-19 19:42:24.052845+00:00

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
revision: str = 'c7a51b60dd5f'
down_revision: Union[str, None] = '683cf6ccb920'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_notifications_created_at
            ON notifications (created_at);
        """)


def downgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_notifications_created_at;")