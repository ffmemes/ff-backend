"""Add telegram_chat table, sender_chat_id to message_tg, user_wrapped table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-03-23 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "telegram_chat",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("type", sa.String(20)),
        sa.Column("title", sa.String(256)),
        sa.Column("username", sa.String(128)),
        sa.Column("members_count", sa.Integer()),
        sa.Column("bot_status", sa.String(20)),
        sa.Column("bot_joined_at", sa.DateTime()),
        sa.Column("bot_left_at", sa.DateTime()),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.func.now()
        ),
    )

    op.add_column(
        "message_tg",
        sa.Column("sender_chat_id", sa.BigInteger()),
    )

    op.create_table(
        "user_wrapped",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("user.id"),
            nullable=False,
        ),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("card_telegram_file_id", sa.String()),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now()
        ),
    )


def downgrade() -> None:
    op.drop_table("user_wrapped")
    op.drop_column("message_tg", "sender_chat_id")
    op.drop_table("telegram_chat")
