"""Friend challenge: fixed five-meme packs, participations and first answers.

Revision ID: a7c9e2f5b8d1
Revises: e7a1c3f5b9d2
Create Date: 2026-10-30
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c9e2f5b8d1"
down_revision = "e7a1c3f5b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "friend_challenge_pack",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column(
            "owner_id",
            sa.BigInteger(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime()),
        sa.UniqueConstraint("owner_id"),
        sa.UniqueConstraint("token"),
    )
    op.create_table(
        "friend_challenge_item",
        sa.Column(
            "pack_id",
            sa.Integer(),
            sa.ForeignKey("friend_challenge_pack.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column("meme_id", sa.Integer(), sa.ForeignKey("meme.id", ondelete="SET NULL")),
        sa.CheckConstraint("position BETWEEN 1 AND 5", name="position"),
        sa.UniqueConstraint("pack_id", "meme_id", name="friend_challenge_item_pack_meme_key"),
    )
    op.create_table(
        "friend_challenge_participation",
        sa.Column(
            "pack_id",
            sa.Integer(),
            sa.ForeignKey("friend_challenge_pack.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("started_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
    )
    op.create_table(
        "friend_challenge_answer",
        sa.Column("pack_id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("position", sa.SmallInteger(), primary_key=True),
        sa.Column("liked", sa.Boolean(), nullable=False),
        sa.Column("answered_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["pack_id", "user_id"],
            ["friend_challenge_participation.pack_id", "friend_challenge_participation.user_id"],
            name="friend_challenge_answer_participation_fkey",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["pack_id", "position"],
            ["friend_challenge_item.pack_id", "friend_challenge_item.position"],
            name="friend_challenge_answer_item_fkey",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("friend_challenge_answer")
    op.drop_table("friend_challenge_participation")
    op.drop_table("friend_challenge_item")
    op.drop_table("friend_challenge_pack")
