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
            , EXTRACT(
                EPOCH FROM
                percentile_cont(0.5) WITHIN GROUP (ORDER BY reacted_at - sent_at)
            ) AS sec_to_react
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
            sec_to_react = EXCLUDED.sec_to_react,
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


async def calculate_meme_invited_count():
    insert_query = """
        WITH MEME_IDS_IN_DEEP_LINKS AS (
            SELECT
                deep_link,
                CASE
                    WHEN deep_link ~ '^s_[0-9]+_[0-9]+$'
                        THEN SUBSTRING(deep_link FROM '_([0-9]+)$')::INT
                    WHEN deep_link ~ '^sc_[0-9]+$'
                        THEN SUBSTRING(deep_link FROM '_([0-9]+)$')::INT
                    ELSE NULL
                END AS meme_id
            FROM user_tg
        )

        INSERT INTO meme_stats (
            meme_id,
            invited_count
        )
        SELECT
            meme_id,
            COUNT(*)
        FROM MEME_IDS_IN_DEEP_LINKS
        INNER JOIN meme M
            ON M.id = MEME_IDS_IN_DEEP_LINKS.meme_id
        WHERE meme_id IS NOT NULL
        GROUP BY 1
        ON CONFLICT (meme_id) DO
        UPDATE SET
            invited_count = EXCLUDED.invited_count
    """
    await execute(text(insert_query))
