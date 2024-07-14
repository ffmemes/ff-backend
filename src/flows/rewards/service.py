from typing import Any

from sqlalchemy import text

from src.database import fetch_all


async def get_all_uploaded_memes_weekly_ru() -> list[dict[str, Any]]:
    select_statement = """
        SELECT
            M.id meme_id,
            M.status,
            M.telegram_file_id,
            S.added_by AS author_id,
            U.nickname,
            MS.nmemes_sent,
            MS.nlikes,
            MS.ndislikes
        FROM meme M
        LEFT JOIN meme_source S
            ON M.meme_source_id = S.id
        LEFT JOIN meme_stats MS
            ON M.id = MS.meme_id
        LEFT JOIN "user" U
            ON U.id = S.added_by
        WHERE 1=1
            AND S.type = 'user upload'
            AND M.status IN ('ok', 'published')
            AND M.created_at >= NOW() - INTERVAL '7 days'
            AND M.language_code = 'ru'
            AND MS.nmemes_sent >= 10
    """
    return await fetch_all(text(select_statement))


async def get_all_uploaded_memes_weekly_en() -> list[dict[str, Any]]:
    select_statement = """
        SELECT
            M.id meme_id,
            M.status,
            M.telegram_file_id,
            S.added_by AS author_id,
            U.nickname,
            MS.nmemes_sent,
            MS.nlikes,
            MS.ndislikes
        FROM meme M
        LEFT JOIN meme_source S
            ON M.meme_source_id = S.id
        LEFT JOIN meme_stats MS
            ON M.id = MS.meme_id
        LEFT JOIN "user" U
            ON U.id = S.added_by
        WHERE 1=1
            AND S.type = 'user upload'
            AND M.status IN ('ok', 'published')
            AND M.created_at >= NOW() - INTERVAL '7 days'
            AND M.language_code = 'en'
            AND MS.nmemes_sent >= 10
    """
    return await fetch_all(text(select_statement))
