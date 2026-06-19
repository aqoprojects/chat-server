"""add deferred FK

Revision ID: 4f3fcc7d540f
Revises:     c7a51b60dd5f
Create date: 2026-06-19 21:31:13.624860+00:00

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
revision: str = '4f3fcc7d540f'
down_revision: Union[str, None] = 'c7a51b60dd5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None



def upgrade() -> None:
    op.get_bind().commit()

    # 2. Open an autocommit block to run the concurrent statement isolated
    with op.get_context().autocommit_block():
        op.execute("""
            ALTER TABLE chats
            ADD CONSTRAINT fk_chats_last_message_id
            FOREIGN KEY (last_message_id)
            REFERENCES messages (id)
            ON DELETE SET NULL
            DEFERRABLE INITIALLY DEFERRED
        """)


def downgrade() -> None:
    pass