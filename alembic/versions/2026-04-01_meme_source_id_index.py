"""Add index on meme.meme_source_id for raw impressions stats performance

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-01 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    op.execute("COMMIT")

    # meme.meme_source_id is the PARTITION BY key in calculate_meme_raw_impressions_stats.
    # Without an index the planner does a full sequential sort on every 15-min stats run,
    # causing the 300s timeout.  CONCURRENTLY avoids table lock on the large meme table.
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_meme_meme_source_id "
        "ON meme (meme_source_id)"
    )


def downgrade() -> None:
    op.execute("COMMIT")

    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_meme_meme_source_id"
    )
