"""add partial index on refresh tokens

Revision ID: f7096b32c7b9
Revises:     593699f69e19
Create date: 2026-06-19 18:55:30.393002+00:00

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
revision: str = 'f7096b32c7b9'
down_revision: Union[str, None] = 'f7096b32c7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
        CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_refresh_tokens_hash_active
        ON refresh_tokens (token_hash)
        WHERE is_revoked = false;
        """)


def downgrade() -> None:
    op.get_bind().commit()

    # 2. Drop the index inside an autocommit block
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_refresh_tokens_hash_active;")