"""meme_raw_upload

Revision ID: 5313c3b2301e
Revises: b2e46e6fed7f
Create Date: 2024-05-06 17:34:39.289802

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '5313c3b2301e'
down_revision = 'b2e46e6fed7f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table('meme_raw_upload',
    sa.Column('id', sa.Integer(), sa.Identity(always=False), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('date', sa.DateTime(), nullable=False),
    sa.Column('forward_origin', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('media', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('language_code', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['user.id'], name=op.f('meme_raw_upload_user_id_fkey'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('meme_raw_upload_pkey'))
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('meme_raw_upload')
    # ### end Alembic commands ###