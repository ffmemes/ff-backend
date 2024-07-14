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


async def get_users_to_broadcast_meme_from_tgchannelru(
    meme_id: int,
):
    # select users
    # 1. with language ru
    # 2. who hadn't followed the channel
    # 3. who didn't watch the meme

    select_query = f"""
        SELECT DISTINCT UL.user_id
        FROM user_language UL
        LEFT JOIN user_meme_reaction UMR
            ON UMR.user_id = UL.user_id
            AND UMR.meme_id = {meme_id}
        LEFT JOIN user_tg_chat_membership UTCM
            ON UTCM.user_tg_id = UL.user_id
        WHERE 1=1
            AND UL.language_code = 'ru'
            AND UMR.user_id IS NULL
            AND UTCM.user_tg_id IS NULL
    """

    return await fetch_all(text(select_query))


async def get_users_with_language(
    language_code: str,
):
    select_query = f"""
        SELECT user_id
        FROM user_language
        WHERE language_code = '{language_code}'
    """
    return await fetch_all(text(select_query))


async def get_users_active_more_than_days_ago(
    days_ago: int,
):
    select_query = f"""
        SELECT id
        FROM "user"
        WHERE last_active_at < NOW() - INTERVAL '{days_ago} DAYS'
        AND type != 'blocked_bot'
    """
    return await fetch_all(text(select_query))
