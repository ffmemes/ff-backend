"""Add reaction stats performance indexes

Revision ID: f2a5c8e1b4d7
Revises: c1e2f3a4b5d6
Create Date: 2026-06-26 16:10:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f2a5c8e1b4d7"
down_revision = "c1e2f3a4b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_user_meme_reaction_liked_sent_at_meme_id "
            "ON user_meme_reaction (sent_at DESC, meme_id) "
            "WHERE reaction_id = 1"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_user_meme_reaction_sent_at_meme_id_user_id "
            "ON user_meme_reaction (sent_at, meme_id, user_id) "
            "INCLUDE (reaction_id, reacted_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_user_meme_reaction_meme_id_sent_at_user_id "
            "ON user_meme_reaction (meme_id, sent_at, user_id) "
            "INCLUDE (reaction_id, reacted_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_user_meme_reaction_user_id_reacted_at "
            "ON user_meme_reaction (user_id, reacted_at) "
            "INCLUDE (reaction_id, meme_id, sent_at)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_user_meme_reaction_user_id_reacted_at")
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_user_meme_reaction_meme_id_sent_at_user_id"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_user_meme_reaction_sent_at_meme_id_user_id"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_user_meme_reaction_liked_sent_at_meme_id")
