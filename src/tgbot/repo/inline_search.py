from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.database import execute, fetch_all, inline_search_chosen_result_logs, inline_search_logs
from src.storage.constants import MemeStatus, MemeType


def _escape_like_pattern(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


async def search_memes_for_inline_query(search_query: str, limit: int) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 50))
    search_pattern = f"%{_escape_like_pattern(search_query)}%"
    select_query = """
        SELECT
            M.*,
            GREATEST(
                CASE
                    WHEN M.ocr_result ->> 'text' ILIKE :search_pattern ESCAPE '\\'
                    THEN 1.0
                    ELSE 0.0
                END,
                CASE
                    WHEN M.ocr_result -> 'raw_result' ->> 'ocr_text'
                        ILIKE :search_pattern ESCAPE '\\'
                    THEN 1.0
                    ELSE 0.0
                END,
                CASE
                    WHEN M.ocr_result ->> 'description' ILIKE :search_pattern ESCAPE '\\'
                    THEN 0.9
                    ELSE 0.0
                END,
                word_similarity(:search_query, COALESCE(M.ocr_result ->> 'text', '')),
                word_similarity(
                    :search_query,
                    COALESCE(M.ocr_result -> 'raw_result' ->> 'ocr_text', '')
                ),
                word_similarity(:search_query, COALESCE(M.ocr_result ->> 'description', '')) * 0.9
            ) AS inline_search_score,
            (COALESCE(MS.nlikes, 0) + 1.)
            / (COALESCE(MS.nlikes, 0) + COALESCE(MS.ndislikes, 0) + 2)
            * CASE WHEN COALESCE(MS.raw_impr_rank, 99999) <= 1 THEN 1 ELSE 0.8 END
            * CASE WHEN COALESCE(MS.age_days, 99999) < 90 THEN 1 ELSE 0.8 END
            * CASE
                WHEN COALESCE(MS.nmemes_sent, 0) <= 1 THEN 1
                ELSE (MS.nlikes + MS.ndislikes) * 1. / NULLIF(MS.nmemes_sent, 0)
              END
            * (1.0 + LEAST(COALESCE(MS.invited_count, 0), 10) * 0.1)
            * (1.0 + GREATEST(COALESCE(MS.engagement_score, 0), 0))
            AS inline_quality_score
        FROM meme M
        LEFT JOIN meme_stats MS
            ON MS.meme_id = M.id
        WHERE M.status = :status
            AND M.type = :type
            AND M.telegram_file_id IS NOT NULL
            AND (
                M.ocr_result ->> 'text' ILIKE :search_pattern ESCAPE '\\'
                OR M.ocr_result -> 'raw_result' ->> 'ocr_text'
                    ILIKE :search_pattern ESCAPE '\\'
                OR M.ocr_result ->> 'description' ILIKE :search_pattern ESCAPE '\\'
                OR (M.ocr_result ->> 'text') % :search_query
                OR (M.ocr_result -> 'raw_result' ->> 'ocr_text') % :search_query
                OR (M.ocr_result ->> 'description') % :search_query
            )
        ORDER BY inline_search_score DESC, inline_quality_score DESC, M.published_at DESC
        LIMIT :limit;
    """
    select_statement = text(select_query)

    return await fetch_all(
        select_statement,
        {
            "search_query": search_query,
            "search_pattern": search_pattern,
            "status": MemeStatus.OK.value,
            "type": MemeType.IMAGE.value,
            "limit": limit,
        },
    )


async def create_inline_search_log(
    user_id: int,
    query: str,
    chat_type: str | None,
) -> None:
    insert_query = insert(inline_search_logs).values(
        user_id=user_id,
        query=query,
        chat_type=chat_type,
    )
    await execute(insert_query)


async def create_inline_chosen_result_log(
    user_id: int,
    result_id: str,
    query: str,
) -> None:
    insert_query = insert(inline_search_chosen_result_logs).values(
        user_id=user_id,
        result_id=result_id,
        query=query,
    )
    await execute(insert_query)
