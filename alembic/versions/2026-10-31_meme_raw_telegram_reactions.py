"""Add meme_raw_telegram.reactions (total reaction count from the public channel page).

NULL = post had no reactions block (no reactions yet, or reactions disabled).

Revision ID: d4f6a8c0e2b3
Revises: c3e5a7b9d1f2
Create Date: 2026-10-31
"""

from alembic import op

revision = "d4f6a8c0e2b3"
down_revision = "c3e5a7b9d1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("ALTER TABLE meme_raw_telegram ADD COLUMN IF NOT EXISTS reactions INTEGER")


def downgrade() -> None:
    op.drop_column("meme_raw_telegram", "reactions")
