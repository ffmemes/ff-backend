"""engagement_score and median_session_length

Revision ID: a1b2c3d4e5f6
Revises: 00de08abdabe
Create Date: 2026-03-15 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "fbccd3f03fef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meme_stats",
        sa.Column(
            "engagement_score",
            sa.Float(),
            nullable=False,
            server_default="0",
        ),
    )

    op.add_column(
        "user_stats",
        sa.Column(
            "median_session_length",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_index(
        "ix_user_meme_reaction_user_id_sent_at",
        "user_meme_reaction",
        ["user_id", "sent_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_user_meme_reaction_user_id_sent_at",
        table_name="user_meme_reaction",
    )
    op.drop_column("user_stats", "median_session_length")
    op.drop_column("meme_stats", "engagement_score")
