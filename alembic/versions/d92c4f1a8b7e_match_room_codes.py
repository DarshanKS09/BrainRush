"""match room codes for manual join-by-code

Revision ID: d92c4f1a8b7e
Revises: c41f2b9e7d3a

Adds matches.room_code: a short human-readable code for manual entry.
The opaque invite_token stays the only authorization secret in links;
the room code is never accepted as a link token and vice versa.
Backward-compatible: nullable first, backfill, then NOT NULL + UNIQUE.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd92c4f1a8b7e'
down_revision: Union[str, None] = 'c41f2b9e7d3a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "matches",
        sa.Column("room_code", sa.String(length=12), nullable=True),
    )
    # Backfill any pre-existing rows (production has none at the time of
    # writing) with random 8-char codes derived per row.
    op.execute(
        sa.text(
            "UPDATE matches SET room_code = "
            "upper(substr(md5(random()::text || id::text), 1, 8)) "
            "WHERE room_code IS NULL"
        )
    )
    op.alter_column("matches", "room_code", existing_type=sa.String(12), nullable=False)
    op.create_unique_constraint(
        op.f("uq_matches_room_code"), "matches", ["room_code"]
    )


def downgrade() -> None:
    op.drop_constraint(op.f("uq_matches_room_code"), "matches", type_="unique")
    op.drop_column("matches", "room_code")
