"""add partial index on refresh tokens

Revision ID: f7096b32c7b8
Revises:     4f1f566eed87
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
revision: str = 'f7096b32c7b8'
down_revision: Union[str, None] = '4f1f566eed87'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pgcrypto;")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm;")