"""deep_link_log

Revision ID: 9da466e57138
Revises: 5e6843001af4
Create Date: 2024-09-30 21:25:49.970165

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '9da466e57138'
down_revision = '5e6843001af4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('user_deep_link_log',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('deep_link', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('user_deep_link_log_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('user_deep_link_log_pkey'))
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('user_deep_link_log')
    # ### end Alembic commands ###
