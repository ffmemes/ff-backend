from sqlalchemy import text

from src.database import fetch_all


async def get_users_which_were_active_hours_ago(hours: int) -> list[dict]:
    insert_query = f"""
        SELECT
            id
        FROM "user"
        WHERE 1=1
            AND type NOT IN ('waitlist', 'blocked_bot')
            AND last_active_at BETWEEN
                NOW() - INTERVAL '{hours} HOURS'
                AND
                NOW() - INTERVAL '{hours-1} HOURS'
    """
    return await fetch_all(text(insert_query))


async def get_recently_active_users() -> list[dict]:
    insert_query = """
        SELECT
            id
        FROM "user"
        WHERE 1=1
            AND type NOT IN ('waitlist', 'blocked_bot')
            AND last_active_at BETWEEN
                NOW() - INTERVAL '30 MINUTES'
                AND
                NOW() - INTERVAL '15 MINUTES'
    """
    return await fetch_all(text(insert_query))
