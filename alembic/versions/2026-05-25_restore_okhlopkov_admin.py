"""restore okhlopkov admin role

Revision ID: a9f0d6c2b1e3
Revises: 8c2f4a6d9e10
Create Date: 2026-05-25 12:45:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "a9f0d6c2b1e3"
down_revision = "8c2f4a6d9e10"
branch_labels = None
depends_on = None

OKHLOPKOV_USER_ID = 49820636
TELEGRAM_MODERATOR_CHAT_ID = -1001305866294


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO "user" (id, type, created_at, last_active_at, blocked_bot_at)
            VALUES (:user_id, 'admin', now(), now(), NULL)
            ON CONFLICT (id)
            DO UPDATE SET
                type = 'admin',
                blocked_bot_at = NULL
            """
        ),
        {"user_id": OKHLOPKOV_USER_ID},
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
        {"user_id": OKHLOPKOV_USER_ID, "chat_id": TELEGRAM_MODERATOR_CHAT_ID},
    )


def downgrade() -> None:
    pass
