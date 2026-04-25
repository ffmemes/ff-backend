"""Add editorial_posts + editorial_post_snapshots tables

Revision ID: a1b4c7d0e3f6
Revises: 5a9d22dbecb6
Create Date: 2026-04-24 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a1b4c7d0e3f6"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "editorial_posts",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("draft_hash", sa.String(), nullable=False),
        sa.Column("category", sa.String()),
        sa.Column("entity_id", sa.String()),
        sa.Column("topic_slug", sa.String()),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("has_media", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("validation_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("views", sa.Integer()),
        sa.Column("forwards", sa.Integer()),
        sa.Column("reactions", sa.Integer()),
        sa.Column("comments", sa.Integer()),
        sa.Column("reactions_detail", JSONB),
        sa.Column("stats_updated_at", sa.DateTime()),
        sa.UniqueConstraint("draft_hash", name="uq_editorial_posts_draft_hash"),
        sa.UniqueConstraint(
            "channel",
            "telegram_message_id",
            name="uq_editorial_posts_channel_msg",
        ),
    )
    op.create_index(
        "ix_editorial_posts_telegram_message_id",
        "editorial_posts",
        ["telegram_message_id"],
    )
    op.create_index(
        "ix_editorial_posts_created_at",
        "editorial_posts",
        ["created_at"],
    )

    op.create_table(
        "editorial_post_snapshots",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column(
            "editorial_post_id",
            sa.Integer(),
            sa.ForeignKey("editorial_posts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("views", sa.Integer()),
        sa.Column("forwards", sa.Integer()),
        sa.Column("reactions", sa.Integer()),
        sa.Column("comments", sa.Integer()),
        sa.Column("reactions_detail", JSONB),
        sa.Column(
            "snapshot_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_editorial_post_snapshots_channel_msg",
        "editorial_post_snapshots",
        ["channel", "telegram_message_id"],
    )
    op.create_index(
        "ix_editorial_post_snapshots_editorial_post_id",
        "editorial_post_snapshots",
        ["editorial_post_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_editorial_post_snapshots_editorial_post_id")
    op.drop_index("ix_editorial_post_snapshots_channel_msg")
    op.drop_table("editorial_post_snapshots")
    op.drop_index("ix_editorial_posts_created_at")
    op.drop_index("ix_editorial_posts_telegram_message_id")
    op.drop_table("editorial_posts")
