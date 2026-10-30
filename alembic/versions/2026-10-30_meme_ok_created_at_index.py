"""Index fresh ok memes by created_at for explore_budget_v1 feed queries.

low_sent_pool (labeling budget, < 7d) and fresh_viral (< 72h) filter on
meme.created_at; without this index they bitmap-scan every ok meme of the
user's languages (~400ms per heavy user on prod).

Revision ID: b2d4f6a8c0e1
Revises: a7c9e2f5b8d1
Create Date: 2026-10-30
"""

from alembic import op

revision = "b2d4f6a8c0e1"
down_revision = "a7c9e2f5b8d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # A failed CONCURRENTLY build leaves an INVALID index; drop it so reruns rebuild.
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_meme_ok_created_at")
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_meme_ok_created_at "
            "ON meme (created_at) WHERE status = 'ok'"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_meme_ok_created_at")
