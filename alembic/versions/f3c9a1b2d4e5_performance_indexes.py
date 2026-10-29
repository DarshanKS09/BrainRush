"""add performance indexes for leaderboard, history, and match queries

Revision ID: f3c9a1b2d4e5
Revises: e7a1c9d4f2b6
Create Date: 2026-10-29 00:00:00.000000

Adds additive indexes only — no data changes, no table alterations.
Safe to apply on a live database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f3c9a1b2d4e5'
down_revision: Union[str, None] = 'e7a1c9d4f2b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for leaderboard ORDER BY total_xp DESC, user_id ASC.
    op.create_index(
        'ix_player_profiles_total_xp_desc_user_id',
        'player_profiles',
        [sa.text('total_xp DESC'), sa.text('user_id ASC')],
        unique=False,
    )
    # Composite index for user history ORDER BY started_at DESC.
    op.create_index(
        'ix_game_sessions_user_id_started_at_desc',
        'game_sessions',
        [sa.text('user_id'), sa.text('started_at DESC')],
        unique=False,
    )
    # Index for daily cap sum query: WHERE user_id = ? AND awarded_at >= ?.
    op.create_index(
        'ix_match_rewards_user_id_awarded_at',
        'match_rewards',
        ['user_id', 'awarded_at'],
        unique=False,
    )
    # Index for match finalization: WHERE match_id = ? AND finished_at IS NOT NULL.
    op.create_index(
        'ix_match_participants_match_id_finished_at',
        'match_participants',
        ['match_id', 'finished_at'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_match_participants_match_id_finished_at', table_name='match_participants')
    op.drop_index('ix_match_rewards_user_id_awarded_at', table_name='match_rewards')
    op.drop_index('ix_game_sessions_user_id_started_at_desc', table_name='game_sessions')
    op.drop_index('ix_player_profiles_total_xp_desc_user_id', table_name='player_profiles')
