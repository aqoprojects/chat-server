"""add user chat lookup chat type

Revision ID: 609eea68d09c
Revises:     c98813a46592
Create date: 2026-06-19 19:30:48.046273+00:00

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
revision: str = '609eea68d09c'
down_revision: Union[str, None] = 'c98813a46592'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
            CREATE INDEX CONCURRENTLY ix_chats_type_active
            ON chats (chat_type)
            WHERE deleted_at IS NULL;
        """)


def downgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_chats_type_active;")