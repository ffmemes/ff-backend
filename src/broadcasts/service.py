from sqlalchemy import text

from src.database import fetch_all


async def get_users_active_minutes_ago(
    from_minutes_ago: int,
    to_minutes_ago: int,
) -> list[dict]:
    assert from_minutes_ago < to_minutes_ago
    insert_query = f"""
        SELECT
            id
        FROM "user"
        WHERE 1=1
            AND type NOT IN ('waitlist', 'blocked_bot')
            AND last_active_at BETWEEN
                NOW() - INTERVAL '{to_minutes_ago} MINUTES'
                AND
                NOW() - INTERVAL '{from_minutes_ago} MINUTES'
    """
    return await fetch_all(text(insert_query))
