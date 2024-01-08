"""user_stats

Revision ID: e49c184f5f54
Revises: bc43e9755fd6
Create Date: 2024-01-08 19:12:41.894196

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e49c184f5f54'
down_revision = 'bc43e9755fd6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user_stats',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('nlikes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ndislikes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('nmemes_sent', sa.Integer(), server_default='0', nullable=False),
    sa.Column('nsessions', sa.Integer(), server_default='0', nullable=False),
    sa.Column('active_days_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('user_stats_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', name=op.f('user_stats_pkey'))
    )
    op.create_table('user_meme_source_stats',
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('meme_source_id', sa.Integer(), nullable=False),
    sa.Column('nlikes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('ndislikes', sa.Integer(), server_default='0', nullable=False),
    sa.Column('updated_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['meme_source_id'], ['meme_source.id'], name=op.f('user_meme_source_stats_meme_source_id_fkey'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('user_meme_source_stats_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'meme_source_id', name=op.f('user_meme_source_stats_pkey'))
    )
    op.create_index(op.f('meme_type_idx'), 'meme', ['type'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('meme_type_idx'), table_name='meme')
    op.drop_table('user_meme_source_stats')
    op.drop_table('user_stats')
    # ### end Alembic commands ###