"""add refresh tokens expired revoked

Revision ID: 683cf6ccb920
Revises:     ffd6dc312f61
Create date: 2026-06-19 19:40:40.274523+00:00

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
revision: str = '683cf6ccb920'
down_revision: Union[str, None] = 'ffd6dc312f61'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY ix_refresh_tokens_expired_revoked
            ON refresh_tokens (expires_at)
            WHERE is_revoked = true;
        """)


def downgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_refresh_tokens_expired_revoked;")