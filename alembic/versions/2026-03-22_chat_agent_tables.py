"""Add chat_meme_reaction and chat_agent_usage tables for chat agent

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2026-03-22 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "c3d4e5f6a7b8"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_meme_reaction",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "meme_id",
            sa.Integer(),
            sa.ForeignKey("meme.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("reaction", sa.SmallInteger(), nullable=False),
        sa.Column(
            "reacted_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "chat_id", "meme_id", "user_id", name="uq_chat_meme_reaction"
        ),
    )

    op.create_table(
        "chat_agent_usage",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "prompt_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "completion_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "tool_calls", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("response_time_ms", sa.Integer()),
        sa.Column("trigger_type", sa.String()),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("chat_agent_usage")
    op.drop_table("chat_meme_reaction")
