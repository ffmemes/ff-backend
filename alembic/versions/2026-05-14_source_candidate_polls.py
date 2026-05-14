"""add source candidate poll tables

Revision ID: 4f6e8a1b2c3d
Revises: 3d9b4f6a2c10
Create Date: 2026-05-14 10:00:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "4f6e8a1b2c3d"
down_revision = "3d9b4f6a2c10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meme_source_candidate_poll",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("chat_id", sa.BigInteger(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=True),
        sa.Column("prepared_meme_source_id", sa.Integer(), nullable=True),
        sa.Column(
            "status",
            sa.String(),
            server_default="draft",
            nullable=False,
        ),
        sa.Column("opened_at", sa.DateTime(), nullable=True),
        sa.Column("closes_at", sa.DateTime(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("result_meme_source_id", sa.Integer(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["meme_source_candidate.id"],
            name=op.f("meme_source_candidate_poll_candidate_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["prepared_meme_source_id"],
            ["meme_source.id"],
            name=op.f("meme_source_candidate_poll_prepared_meme_source_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["result_meme_source_id"],
            ["meme_source.id"],
            name=op.f("meme_source_candidate_poll_result_meme_source_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("meme_source_candidate_poll_pkey")),
    )
    op.create_index(
        op.f("ix_meme_source_candidate_poll_candidate_id"),
        "meme_source_candidate_poll",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        "ix_meme_source_candidate_poll_status_closes_at",
        "meme_source_candidate_poll",
        ["status", "closes_at"],
        unique=False,
    )
    op.create_index(
        "uq_meme_source_candidate_poll_message",
        "meme_source_candidate_poll",
        ["chat_id", "message_id"],
        unique=True,
        postgresql_where=sa.text("message_id IS NOT NULL"),
    )
    op.create_index(
        "uq_meme_source_candidate_poll_active_global",
        "meme_source_candidate_poll",
        [sa.text("(true)")],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'open')"),
    )
    op.create_index(
        "uq_meme_source_candidate_poll_active_candidate",
        "meme_source_candidate_poll",
        ["candidate_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('draft', 'open')"),
    )

    op.create_table(
        "meme_source_candidate_vote",
        sa.Column("poll_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("vote", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["poll_id"],
            ["meme_source_candidate_poll.id"],
            name=op.f("meme_source_candidate_vote_poll_id_fkey"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "poll_id",
            "user_id",
            name=op.f("meme_source_candidate_vote_pkey"),
        ),
    )


def downgrade() -> None:
    op.drop_table("meme_source_candidate_vote")
    op.drop_index(
        "uq_meme_source_candidate_poll_active_candidate",
        table_name="meme_source_candidate_poll",
    )
    op.drop_index(
        "uq_meme_source_candidate_poll_active_global",
        table_name="meme_source_candidate_poll",
    )
    op.drop_index(
        "uq_meme_source_candidate_poll_message",
        table_name="meme_source_candidate_poll",
    )
    op.drop_index(
        "ix_meme_source_candidate_poll_status_closes_at",
        table_name="meme_source_candidate_poll",
    )
    op.drop_index(
        op.f("ix_meme_source_candidate_poll_candidate_id"),
        table_name="meme_source_candidate_poll",
    )
    op.drop_table("meme_source_candidate_poll")
