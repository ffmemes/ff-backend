"""Add low_sent_pool skip alert index

Revision ID: 9f0a1b2c3d4e
Revises: 1a2b3c4d5e6f
Create Date: 2026-05-12 16:30:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "9f0a1b2c3d4e"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    op.execute("COMMIT")

    # Supports the daily low_sent_pool skip-rate alert, which scans recent
    # deliveries for one recommendation engine on a production-sized table.
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_user_meme_reaction_low_sent_pool_sent_at_meme_id "
        "ON user_meme_reaction (sent_at, meme_id) "
        "INCLUDE (reaction_id) "
        "WHERE recommended_by = 'low_sent_pool'"
    )


def downgrade() -> None:
    op.execute("COMMIT")

    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_user_meme_reaction_low_sent_pool_sent_at_meme_id"
    )
