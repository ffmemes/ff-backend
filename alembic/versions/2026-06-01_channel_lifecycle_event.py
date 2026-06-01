"""add channel lifecycle event table

Revision ID: c1e2f3a4b5d6
Revises: a9f0d6c2b1e3
Create Date: 2026-06-01 07:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "c1e2f3a4b5d6"
down_revision = "a9f0d6c2b1e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_lifecycle_event",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("telegram_event_id", sa.BigInteger(), nullable=False),
        sa.Column("telegram_user_id", sa.BigInteger(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("event_at", sa.DateTime(), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("channel_lifecycle_event_pkey")),
        sa.UniqueConstraint(
            "channel",
            "telegram_event_id",
            name=op.f("uq_channel_lifecycle_event_channel_event"),
        ),
    )
    op.create_index(
        "ix_channel_lifecycle_event_channel_time",
        "channel_lifecycle_event",
        ["channel", "event_at"],
        unique=False,
    )
    op.create_index(
        "ix_channel_lifecycle_event_user_time",
        "channel_lifecycle_event",
        ["telegram_user_id", "event_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_channel_lifecycle_event_user_time",
        table_name="channel_lifecycle_event",
    )
    op.drop_index(
        "ix_channel_lifecycle_event_channel_time",
        table_name="channel_lifecycle_event",
    )
    op.drop_table("channel_lifecycle_event")
