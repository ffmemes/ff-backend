"""Stats performance: add reacted_at index, drop unused reaction_id index, tune autovacuum

Revision ID: b7c8d9e0f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-03-18 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "b7c8d9e0f1a2"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CREATE/DROP INDEX CONCURRENTLY cannot run inside a transaction.
    # We must use non-transactional DDL for these operations.
    op.execute("COMMIT")

    # Add index on reacted_at for Tier 2 incremental stats.
    # Enables fast lookup of "which memes got new reactions since last run?"
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_user_meme_reaction_reacted_at "
        "ON user_meme_reaction (reacted_at)"
    )

    # Drop the reaction_id index (306 MB, zero scans in 3 months).
    # reaction_id has only 2 values (1=like, 2=dislike) — too low selectivity
    # for an index. All queries that filter on reaction_id either:
    # - Filter within a per-user subset (uses PK)
    # - Filter globally (WHERE reaction_id = 1 matches 50%, seq scan is faster)
    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS "
        "user_meme_reaction_reaction_id_idx"
    )

    # Tune autovacuum for user_meme_reaction (22M rows).
    # Default scale_factor=0.2 means vacuum triggers at 4.4M dead tuples.
    # With 0.01, it triggers at ~220K dead tuples — much more responsive.
    # Last autovacuum was Jan 5 (73 days ago). This fixes that.
    op.execute(
        "ALTER TABLE user_meme_reaction SET ("
        "autovacuum_vacuum_scale_factor = 0.01, "
        "autovacuum_analyze_scale_factor = 0.01"
        ")"
    )


def downgrade() -> None:
    op.execute("COMMIT")

    op.execute(
        "ALTER TABLE user_meme_reaction RESET ("
        "autovacuum_vacuum_scale_factor, "
        "autovacuum_analyze_scale_factor"
        ")"
    )

    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "user_meme_reaction_reaction_id_idx "
        "ON user_meme_reaction (reaction_id)"
    )

    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS "
        "ix_user_meme_reaction_reacted_at"
    )
