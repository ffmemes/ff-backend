"""add crossposting_decision_log table

Revision ID: 78054f923898
Revises: a1b4c7d0e3f6
Create Date: 2026-04-28 19:54:51.333661

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "78054f923898"
down_revision = "a1b4c7d0e3f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "crossposting_decision_log",
        sa.Column("id", sa.Integer(), sa.Identity(always=False), nullable=False),
        sa.Column(
            "decided_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(), nullable=False),
        sa.Column("picked_meme_id", sa.Integer(), nullable=True),
        sa.Column("score_version", sa.Integer(), nullable=False),
        sa.Column("median_signal", sa.Float(), nullable=True),
        sa.Column("candidate_pool_size", sa.Integer(), nullable=True),
        sa.Column(
            "candidates",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["picked_meme_id"],
            ["meme.id"],
            name=op.f("crossposting_decision_log_picked_meme_id_fkey"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("crossposting_decision_log_pkey")),
    )
    op.create_index(
        "ix_crossposting_decision_log_channel_time",
        "crossposting_decision_log",
        ["channel", "decided_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_crossposting_decision_log_channel_time",
        table_name="crossposting_decision_log",
    )
    op.drop_table("crossposting_decision_log")
