"""Add channel growth measurement tables and crossposting columns

Revision ID: 5a9d22dbecb6
Revises: f6a7b8c9d0e1
Create Date: 2026-04-13 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "5a9d22dbecb6"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend crossposting table
    op.add_column("crossposting", sa.Column("telegram_message_id", sa.BigInteger()))
    op.add_column("crossposting", sa.Column("caption_text", sa.String()))
    op.add_column("crossposting", sa.Column("score_version", sa.Integer(), server_default="1"))
    op.add_column("crossposting", sa.Column("views", sa.Integer()))
    op.add_column("crossposting", sa.Column("forwards", sa.Integer()))
    op.add_column("crossposting", sa.Column("reactions", sa.Integer()))
    op.add_column("crossposting", sa.Column("comments", sa.Integer()))
    op.add_column("crossposting", sa.Column("reactions_detail", JSONB))
    op.add_column("crossposting", sa.Column("stats_updated_at", sa.DateTime()))

    # Index for stats collector lookups
    op.create_index(
        "ix_crossposting_telegram_message_id",
        "crossposting",
        ["telegram_message_id"],
    )

    # Time-series snapshots table
    op.create_table(
        "crossposting_snapshots",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column(
            "meme_id",
            sa.Integer(),
            sa.ForeignKey("meme.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("telegram_message_id", sa.BigInteger(), nullable=False),
        sa.Column("views", sa.Integer()),
        sa.Column("forwards", sa.Integer()),
        sa.Column("reactions", sa.Integer()),
        sa.Column("comments", sa.Integer()),
        sa.Column("reactions_detail", JSONB),
        sa.Column("message_text", sa.String()),
        sa.Column(
            "snapshot_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index(
        "ix_crossposting_snapshots_channel_msg",
        "crossposting_snapshots",
        ["channel", "telegram_message_id"],
    )

    # Daily channel stats table
    op.create_table(
        "channel_daily_stats",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("subscriber_count", sa.Integer()),
        sa.Column("posts_count", sa.Integer()),
        sa.Column("total_forwards", sa.Integer()),
        sa.Column("total_views", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("channel", "date"),
    )


def downgrade() -> None:
    op.drop_table("channel_daily_stats")
    op.drop_index("ix_crossposting_snapshots_channel_msg")
    op.drop_table("crossposting_snapshots")
    op.drop_index("ix_crossposting_telegram_message_id")
    op.drop_column("crossposting", "stats_updated_at")
    op.drop_column("crossposting", "reactions_detail")
    op.drop_column("crossposting", "comments")
    op.drop_column("crossposting", "reactions")
    op.drop_column("crossposting", "forwards")
    op.drop_column("crossposting", "views")
    op.drop_column("crossposting", "score_version")
    op.drop_column("crossposting", "caption_text")
    op.drop_column("crossposting", "telegram_message_id")
