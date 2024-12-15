from typing import Any

from sqlalchemy import select, text

from src.database import fetch_all, fetch_one, user_stats


async def get_user_stats(
    user_id: int,
) -> dict[str, Any] | None:
    select_statement = select(user_stats).where(user_stats.c.user_id == user_id)
    return await fetch_one(select_statement)


async def get_most_liked_meme_source_urls(
    user_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    select_statement = f"""
        SELECT MS.id, MS.url
        FROM user_meme_source_stats UMSS
        LEFT JOIN meme_source MS
            ON MS.id = UMSS.meme_source_id
        WHERE user_id = {user_id}
        ORDER BY nlikes / (nlikes + ndislikes) DESC, nlikes DESC
        LIMIT {limit}
    """
    return await fetch_all(text(select_statement))


async def get_shared_memes(user_id: int, limit: int) -> list[dict[str, Any]]:
    select_statement = f"""
        SELECT
            TRIM(SPLIT_PART(deep_link, '_', 3))::INT AS meme_id,
            COUNT(*) invited_users
        FROM user_tg
        WHERE
            deep_link LIKE 's_{user_id}_%'
            -- AND pg_input_is_valid(TRIM(SPLIT_PART(deep_link, '_', 3)), 'INT')
        GROUP BY 1
        ORDER BY 2 DESC
        LIMIT {limit}
    """
    return await fetch_all(text(select_statement))


async def get_ocr_text_of_liked_memes_for_llm(user_id: int) -> list:
    select_statement = """
        SELECT
            MEME.ocr_result->>'text' AS ocr_text
        FROM
            user_meme_reaction UMR
        LEFT JOIN
            meme MEME ON MEME.id = UMR.meme_id
        WHERE
            user_id = :user_id
            AND reaction_id = 1
            AND MEME.type = 'image'
            AND MEME.status = 'ok'
            AND MEME.language_code = 'ru'
            AND (
                LENGTH(
                    REGEXP_REPLACE(
                        MEME.ocr_result->>'text',
                        '[^\u0410-\u044f]',
                        '',
                        'g'
                    )
                )::float /
                NULLIF(
                    LENGTH(MEME.ocr_result->>'text'),
                    0
                )
            ) > 0.5
            AND LENGTH(MEME.ocr_result->>'text') > 8
            AND LENGTH(MEME.ocr_result->>'text') < 100
        ORDER BY
            reacted_at DESC
        LIMIT 20;
    """
    return await fetch_all(text(select_statement), {"user_id": user_id})
