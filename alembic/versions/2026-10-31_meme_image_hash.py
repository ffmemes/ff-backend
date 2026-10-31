"""Add meme.image_hash (64-bit dHash) for perceptual duplicate detection.

Shadow mode: hashes are stored and same-hash live memes are logged, not merged.

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
Create Date: 2026-10-31
"""

from alembic import op

revision = "c3e5a7b9d1f2"
down_revision = "b2d4f6a8c0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS: a failed index build below commits the column without stamping.
    # Don't queue every meme read behind ACCESS EXCLUSIVE if a long scan holds meme.
    op.execute("SET lock_timeout = '5s'")
    op.execute("ALTER TABLE meme ADD COLUMN IF NOT EXISTS image_hash BIGINT")
    # Build without blocking meme writes on the large production table.
    with op.get_context().autocommit_block():
        # A failed CONCURRENTLY build leaves an INVALID index; drop it so reruns rebuild.
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_meme_image_hash")
        op.execute(
            "CREATE INDEX CONCURRENTLY ix_meme_image_hash "
            "ON meme (image_hash) WHERE image_hash IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_meme_image_hash")
    op.drop_column("meme", "image_hash")
