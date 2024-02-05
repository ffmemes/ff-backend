from sqlalchemy import text

from src.database import execute


async def calculate_meme_reactions_stats() -> None:
    insert_query = """
        INSERT INTO meme_stats (
            meme_id,
            nlikes,
            ndislikes,
            nmemes_sent,
            age_days,
            updated_at
        )
        SELECT
            meme_id
            , COUNT(*) FILTER (WHERE reaction_id = 1) nlikes
            , COUNT(*) FILTER (WHERE reaction_id = 2) ndislikes
            , COUNT(*) nmemes_sent
            , MAX(EXTRACT('DAYS' FROM NOW() - M.published_at)) age_days
            , NOW() AS updated_at
        FROM user_meme_reaction E
        INNER JOIN meme M
            ON M.id = E.meme_id
        GROUP BY 1

        ON CONFLICT (meme_id) DO
        UPDATE SET
            nlikes = EXCLUDED.nlikes,
            ndislikes = EXCLUDED.ndislikes,
            nmemes_sent = EXCLUDED.nmemes_sent,
            age_days = EXCLUDED.age_days,
            updated_at = EXCLUDED.updated_at
    """
    await execute(text(insert_query))


async def calculate_meme_raw_impressions_stats() -> None:
    insert_query = """
        WITH MEME_RAW_IMPRESSIONS AS (
            SELECT
                M.id AS meme_id,
                M.meme_source_id,
                COUNT(*) OVER (PARTITION BY M.meme_source_id),
                COALESCE(MRT.views, MRV.views) impressions,
                ROW_NUMBER() OVER (
                    PARTITION BY M.meme_source_id
                    ORDER BY COALESCE(MRT.views, MRV.views) DESC
                ) impr_rank
            FROM meme M
            LEFT JOIN meme_source MS
                ON MS.id = M.meme_source_id
            LEFT JOIN meme_raw_telegram MRT
                ON MRT.id = M.raw_meme_id AND MS.type = 'telegram'
            LEFT JOIN meme_raw_vk MRV
                ON MRV.id = M.raw_meme_id AND MS.type = 'vk'
        )

        INSERT INTO meme_stats (
            meme_id,
            raw_impr_rank
        )
        SELECT
            meme_id,
            FLOOR(4.0 * impr_rank / count) AS raw_impr_rank
        FROM MEME_RAW_IMPRESSIONS
        ON CONFLICT (meme_id) DO
        UPDATE SET
            raw_impr_rank = EXCLUDED.raw_impr_rank;
    """
    await execute(text(insert_query))
