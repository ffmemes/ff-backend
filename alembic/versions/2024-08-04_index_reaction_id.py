"""index_reaction_id

Revision ID: 5e6843001af4
Revises: 4637e7d45ece
Create Date: 2024-08-04 19:43:33.102226

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '5e6843001af4'
down_revision = '4637e7d45ece'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_index(op.f('user_meme_reaction_reaction_id_idx'), 'user_meme_reaction', ['reaction_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_index(op.f('user_meme_reaction_reaction_id_idx'), table_name='user_meme_reaction')
    # ### end Alembic commands ###