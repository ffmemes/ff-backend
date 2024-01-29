"""meme_stats_raw_impr_rank

Revision ID: b845d8e244f5
Revises: ba7a67652ac6
Create Date: 2024-01-28 16:53:56.642112

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b845d8e244f5'
down_revision = 'ba7a67652ac6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('meme_stats', sa.Column('raw_impr_rank', sa.Integer(), server_default='99999', nullable=False))
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column('meme_stats', 'raw_impr_rank')
    # ### end Alembic commands ###