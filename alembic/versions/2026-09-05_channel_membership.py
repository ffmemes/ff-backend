"""Current owned-channel membership, separate from historical positive sightings.

Revision ID: b8d2f6a9c1e4
Revises: f2a5c8e1b4d7
"""

import sqlalchemy as sa
from alembic import op

revision = "b8d2f6a9c1e4"
down_revision = "f2a5c8e1b4d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_channel_membership",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("chat_id", sa.BigInteger(), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="unknown"),
        sa.Column("observed_at", sa.DateTime()),
        sa.Column("source", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("last_event_update_id", sa.BigInteger()),
        sa.Column("last_event_received_at", sa.DateTime()),
        sa.Column("ever_member", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_member_at", sa.DateTime()),
        sa.Column("checked_at", sa.DateTime()),
        sa.Column("next_check_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("last_error", sa.String(40)),
        sa.CheckConstraint(
            "status IN ('unknown', 'member', 'nonmember')", name="user_channel_membership_status"
        ),
        sa.CheckConstraint(
            "source IN ('queued', 'event', 'snapshot', 'access_lost')",
            name="user_channel_membership_source",
        ),
    )
    op.create_index(
        "ix_user_channel_membership_next_check",
        "user_channel_membership",
        ["next_check_at", "user_id"],
    )
    # No bulk population in migrations: the bounded background worker discovers
    # known users and incorporates their existing positive sightings lazily.


def downgrade() -> None:
    op.drop_table("user_channel_membership")
