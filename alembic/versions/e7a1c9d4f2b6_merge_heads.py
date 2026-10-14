"""merge match room codes + reward ledger branches

Revision ID: e7a1c9d4f2b6
Revises: 54102bd6c817, d92c4f1a8b7e

Merge-only revision: joins the room-code branch (d92c4f1a8b7e) with the
reward-ledger branch (54102bd6c817). No schema changes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7a1c9d4f2b6'
down_revision: Union[str, Sequence[str], None] = ('54102bd6c817', 'd92c4f1a8b7e')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
