"""Index pending Describe Memes candidates by ingestion time.

Revision ID: d4e6f8a1b3c5
Revises: c9e3a7b1d5f2
Create Date: 2026-09-14
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e6f8a1b3c5"
down_revision = "c9e3a7b1d5f2"
branch_labels = None
depends_on = None


_PENDING_DESCRIBE_WHERE = sa.text(
    "type = 'image' AND status = 'ok' AND telegram_file_id IS NOT NULL "
    "AND (ocr_result IS NULL OR ocr_result->>'description' IS NULL) "
    "AND COALESCE((ocr_result->>'describe_failures')::int, 0) < 3"
)


def upgrade() -> None:
    # This is a 636k-row production table.  Build without blocking meme writes.
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_meme_describe_pending_created_at",
            "meme",
            ["created_at"],
            postgresql_where=_PENDING_DESCRIBE_WHERE,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_meme_describe_pending_created_at",
            table_name="meme",
            postgresql_concurrently=True,
        )
