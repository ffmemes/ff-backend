from sqlalchemy import text

from src.database import execute


async def calculate_meme_reactions_stats(
    min_user_reactions=10, min_meme_reactions=3
) -> None:
    """
    lr_smoothed algorithm

    Smoothing is needed to handle the cases when users have very diverse like rates

    Step 1. Change target to the symmetrical form:

        like_symmetrical: (0, 1) -> (-1, 1)

    Step 2. Calculate symmetrical like rate for each user

        user_like_rate = avg(like_symmetrical)

    Step 3. Calculate smoothed likes

        like_smoothed = like_symmetrical - user_like_rate
        like_smoothed in (-2, 2)

    Step 4. Calculate meme smoothed like rate

        lr_smoothed = avg(like_smoothed)
        lr_smoothed in (-2, 2)
    """

    insert_query = f"""
        INSERT INTO meme_stats (
            meme_id,
            nlikes,
            ndislikes,
            nmemes_sent,
            age_days,
            sec_to_react,
            updated_at,
            lr_smoothed
        )

        WITH LR AS (
        SELECT *
        FROM (
        SELECT meme_id, AVG(lr_smoothed) lr_smoothed, COUNT(user_id) n_reactions
        FROM (
        SELECT *, (like_ - lr_avg) lr_smoothed
        FROM (
        SELECT
            user_id,
            meme_id,
            like_,
            sent_at,
            AVG(like_) OVER (PARTITION BY user_id ORDER BY sent_at) lr_avg,
            COUNT(like_) over (PARTITION BY user_id ORDER BY sent_at) n_reactions
        FROM (
            SELECT *, CASE WHEN reaction_id = 1 THEN 1 ELSE -1 END like_
            FROM user_meme_reaction r
            JOIN meme
            ON r.meme_id = meme.id
            WHERE reaction_id IS NOT NULL
        ) t
        ) t
        WHERE n_reactions >= {min_user_reactions}
        ) t
        GROUP BY meme_id
        ) t
        WHERE n_reactions >= {min_meme_reactions}
        )
        SELECT
            MS.*,
            COALESCE(LR.lr_smoothed, 0) lr_smoothed
        FROM (
            SELECT
                meme_id
                , COUNT(*) FILTER (WHERE reaction_id = 1) nlikes
                , COUNT(*) FILTER (WHERE reaction_id = 2) ndislikes
                , COUNT(*) nmemes_sent
                , MAX(EXTRACT('DAYS' FROM NOW() - M.published_at)) age_days
                , COALESCE(EXTRACT(
                    EPOCH FROM
                    percentile_cont(0.5)
                        WITHIN GROUP (ORDER BY reacted_at - sent_at)
                        FILTER (
                            WHERE reacted_at - sent_at
                            BETWEEN '0.5 second'
                            AND '1 minute'
                        )
                ), 99999) AS sec_to_react
                , NOW() AS updated_at
            FROM user_meme_reaction E
            INNER JOIN meme M
                ON M.id = E.meme_id
            GROUP BY 1
        ) MS
        LEFT JOIN LR
            ON MS.meme_id = LR.meme_id

        ON CONFLICT (meme_id) DO
        UPDATE SET
            nlikes = EXCLUDED.nlikes,
            ndislikes = EXCLUDED.ndislikes,
            nmemes_sent = EXCLUDED.nmemes_sent,
            age_days = EXCLUDED.age_days,
            sec_to_react = EXCLUDED.sec_to_react,
            updated_at = EXCLUDED.updated_at,
            lr_smoothed = EXCLUDED.lr_smoothed
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
