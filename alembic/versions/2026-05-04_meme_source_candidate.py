"""add meme_source_candidate table

Revision ID: 24cd1a8bd9b8
Revises: 78054f923898
Create Date: 2026-05-04 04:05:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "24cd1a8bd9b8"
down_revision = "78054f923898"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meme_source_candidate",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("url", sa.String(), nullable=False),
        sa.Column(
            "status",
            sa.String(),
            server_default="discovered",
            nullable=False,
        ),
        sa.Column(
            "times_forwarded",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("sample_meme_source_id", sa.Integer(), nullable=True),
        sa.Column("sample_meme_raw_telegram_post_id", sa.Integer(), nullable=True),
        sa.Column("promoted_meme_source_id", sa.Integer(), nullable=True),
        sa.Column("dismissed_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["promoted_meme_source_id"],
            ["meme_source.id"],
            name=op.f("meme_source_candidate_promoted_meme_source_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("meme_source_candidate_pkey")),
        sa.UniqueConstraint("url", name=op.f("meme_source_candidate_url_key")),
    )
    op.create_index(
        op.f("ix_meme_source_candidate_status"),
        "meme_source_candidate",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_meme_source_candidate_status_times",
        "meme_source_candidate",
        ["status", sa.text("times_forwarded DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_meme_source_candidate_status_times",
        table_name="meme_source_candidate",
    )
    op.drop_index(
        op.f("ix_meme_source_candidate_status"),
        table_name="meme_source_candidate",
    )
    op.drop_table("meme_source_candidate")
