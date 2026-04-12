"""Add index on user_deep_link_log.deep_link to fix calculate_meme_invited_count timeout

The LIKE 's\\_\\_%' filter in calculate_meme_invited_count was doing a full
sequential scan of user_deep_link_log on every stats run (hourly). The pattern
has a constant prefix 's_' so a B-tree index is sufficient for the planner to
use an index scan.

Revision ID: 6c67d32f7db5
Revises: f6a7b8c9d0e1
Create Date: 2026-04-01 00:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "6c67d32f7db5"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CREATE INDEX CONCURRENTLY cannot run inside a transaction.
    op.execute("COMMIT")

    # user_deep_link_log.deep_link has no index. The hourly meme_heavy stats flow
    # queries WHERE deep_link LIKE 's\_%\_%' which causes a full sequential scan,
    # leading to 300s+ query time and FlowRunTimeoutError. CONCURRENTLY avoids
    # locking the table during index build.
    op.execute(
        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
        "ix_user_deep_link_log_deep_link "
        "ON user_deep_link_log (deep_link)"
    )


def downgrade() -> None:
    op.execute("COMMIT")

    op.execute(
        "DROP INDEX CONCURRENTLY IF EXISTS ix_user_deep_link_log_deep_link"
    )
