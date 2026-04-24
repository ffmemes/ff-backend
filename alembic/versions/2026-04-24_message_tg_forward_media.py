"""Extend message_tg with forward source and media metadata

Adds columns needed to detect moderator-chat meme forwards (forward_from_*),
capture media context for the chat agent (media_type, file_id, media_group_id),
and indexes for fast lookup.

Revision ID: a7b8c9d0e1f2
Revises: 5a9d22dbecb6
Create Date: 2026-04-24 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "5a9d22dbecb6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("message_tg", sa.Column("media_type", sa.String(), nullable=True))
    op.add_column("message_tg", sa.Column("file_id", sa.String(), nullable=True))
    op.add_column("message_tg", sa.Column("media_group_id", sa.String(), nullable=True))
    op.add_column("message_tg", sa.Column("forward_from_chat_id", sa.BigInteger(), nullable=True))
    op.add_column(
        "message_tg", sa.Column("forward_from_message_id", sa.BigInteger(), nullable=True)
    )
    op.add_column("message_tg", sa.Column("forward_from_user_id", sa.BigInteger(), nullable=True))

    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    op.execute("COMMIT")
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_message_tg_chat_id_date "
        "ON message_tg (chat_id, date DESC)"
    )
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_message_tg_forward_source "
        "ON message_tg (forward_from_chat_id, forward_from_message_id)"
    )


def downgrade() -> None:
    op.execute("COMMIT")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_message_tg_forward_source")
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_message_tg_chat_id_date")

    op.drop_column("message_tg", "forward_from_user_id")
    op.drop_column("message_tg", "forward_from_message_id")
    op.drop_column("message_tg", "forward_from_chat_id")
    op.drop_column("message_tg", "media_group_id")
    op.drop_column("message_tg", "file_id")
    op.drop_column("message_tg", "media_type")
