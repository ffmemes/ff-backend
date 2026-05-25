"""grant mearsm source moderation

Revision ID: 8c2f4a6d9e10
Revises: 7b2c9f1e4a6d
Create Date: 2026-05-25 11:10:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8c2f4a6d9e10"
down_revision = "7b2c9f1e4a6d"
branch_labels = None
depends_on = None

MEARSM_USER_ID = 1007266539
TELEGRAM_MODERATOR_CHAT_ID = -1001305866294


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO "user" (id, type, created_at, last_active_at, blocked_bot_at)
            VALUES (:user_id, 'moderator', now(), now(), NULL)
            ON CONFLICT (id)
            DO UPDATE SET
                type = 'moderator',
                blocked_bot_at = NULL
            """
        ),
        {"user_id": MEARSM_USER_ID},
    )
    conn.execute(
        sa.text(
            """
            INSERT INTO user_tg_chat_membership (user_tg_id, chat_id, last_seen_at)
            SELECT id, :chat_id, now()
            FROM user_tg
            WHERE id = :user_id
            ON CONFLICT (user_tg_id, chat_id)
            DO UPDATE SET last_seen_at = now()
            """
        ),
        {"user_id": MEARSM_USER_ID, "chat_id": TELEGRAM_MODERATOR_CHAT_ID},
    )


def downgrade() -> None:
    pass
