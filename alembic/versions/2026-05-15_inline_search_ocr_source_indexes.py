"""add inline search indexes for OpenRouter OCR fields

Revision ID: 7b2c9f1e4a6d
Revises: 4f6e8a1b2c3d
Create Date: 2026-05-15 12:00:00.000000

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "7b2c9f1e4a6d"
down_revision = "4f6e8a1b2c3d"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_meme_ocr_description_gin
            ON meme
            USING gin ((ocr_result ->> 'description') gin_trgm_ops)
            """
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_meme_ocr_raw_ocr_text_gin
            ON meme
            USING gin (((ocr_result -> 'raw_result') ->> 'ocr_text') gin_trgm_ops)
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_meme_ocr_raw_ocr_text_gin")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_meme_ocr_description_gin")
