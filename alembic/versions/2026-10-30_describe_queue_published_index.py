"""Widen the Describe Memes pending index to channel-published memes.

The queue now describes 'published' memes too and serves them first in the
backlog tier, so the index leads with that flag and keeps created_at order.

Revision ID: e7a1c3f5b9d2
Revises: d4e6f8a1b3c5
Create Date: 2026-10-30
"""

from alembic import op

revision = "e7a1c3f5b9d2"
down_revision = "d4e6f8a1b3c5"
branch_labels = None
depends_on = None

_PENDING = (
    "type = 'image' AND telegram_file_id IS NOT NULL "
    "AND (ocr_result IS NULL OR ocr_result->>'description' IS NULL) "
    "AND COALESCE((ocr_result->>'describe_failures')::int, 0) < 3"
)


def upgrade() -> None:
    # Build without blocking meme writes on the large production table.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_meme_describe_pending_published_created_at "
            "ON meme ((status = 'published') DESC, created_at) "
            f"WHERE status IN ('ok', 'published') AND {_PENDING}"
        )
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_meme_describe_pending_created_at")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_meme_describe_pending_created_at "
            f"ON meme (created_at) WHERE status = 'ok' AND {_PENDING}"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_meme_describe_pending_published_created_at"
        )
