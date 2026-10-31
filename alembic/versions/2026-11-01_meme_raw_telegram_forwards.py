"""Add meme_raw_telegram.forwards + stats_fetched_at (Telethon read of source posts).

Filled once per post at ~20-48h by the channel stats flow; feeds the crosspost
src_fwd_pct shadow signal. NULL = not fetched yet / post gone.

Revision ID: e5a7c9b1d3f4
Revises: d4f6a8c0e2b3
Create Date: 2026-11-01
"""

from alembic import op

revision = "e5a7c9b1d3f4"
down_revision = "d4f6a8c0e2b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute("ALTER TABLE meme_raw_telegram ADD COLUMN IF NOT EXISTS forwards INTEGER")
    op.execute("ALTER TABLE meme_raw_telegram ADD COLUMN IF NOT EXISTS stats_fetched_at TIMESTAMP")


def downgrade() -> None:
    op.drop_column("meme_raw_telegram", "stats_fetched_at")
    op.drop_column("meme_raw_telegram", "forwards")
