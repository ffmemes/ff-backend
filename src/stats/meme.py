from sqlalchemy import text

from src.database import execute


async def calculate_meme_reactions_stats(min_user_reactions=10, min_meme_reactions=3) -> None:
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


async def calculate_engagement_score(
    min_user_reactions: int = 10,
    min_meme_reactions: int = 3,
) -> None:
    """
    Engagement score: a composite per-meme quality metric that replaces
    binary like rate with timing-weighted reaction values and skip detection.

    Reaction values:
        Like                          → +1.0
        Dislike, slow (>3s)           → -1.0  (genuine rejection)
        Dislike, fast (≤3s)           → -0.5  (uncertain: lazy or bad?)
        Dislike, timing unknown       → -1.0  (default conservative)
        Skip (sent, no reaction,
              but user continued)     → -0.3  (didn't even engage)
        Last meme in session          → NULL  (excluded, unknowable)

    Smoothing: same running-average user-bias correction as lr_smoothed.
        smoothed = engagement_value - running_avg(engagement_value per user)
        engagement_score = avg(smoothed) per meme

    Performance: ~80s full scan of 22M rows (same as lr_smoothed at 75s).
    Incremental would need a meme_id index on user_meme_reaction to fetch
    all reactions per meme efficiently. Without it, any approach that needs
    "all reactions to meme X" falls back to a full table scan. Acceptable
    for now since this runs alongside lr_smoothed in the same flow.
    """

    query = f"""
        INSERT INTO meme_stats (meme_id, engagement_score)

        WITH REACTIONS_WITH_CONTEXT AS (
            SELECT
                R.user_id,
                R.meme_id,
                R.reaction_id,
                R.sent_at,
                R.reacted_at,
                EXTRACT(EPOCH FROM R.reacted_at - R.sent_at) AS sec_to_react,
                MAX(CASE WHEN R.reaction_id IS NOT NULL THEN R.sent_at END)
                    OVER (PARTITION BY R.user_id) AS user_last_reaction_sent_at
            FROM user_meme_reaction R
        ),

        ENGAGEMENT_VALUES AS (
            SELECT
                user_id, meme_id, sent_at,
                CASE
                    WHEN reaction_id = 1 THEN 1.0
                    WHEN reaction_id = 2
                        AND sec_to_react BETWEEN 0.5 AND 60
                        AND sec_to_react > 3 THEN -1.0
                    WHEN reaction_id = 2
                        AND sec_to_react BETWEEN 0.5 AND 60
                        AND sec_to_react <= 3 THEN -0.5
                    WHEN reaction_id = 2 THEN -1.0
                    WHEN reaction_id IS NULL
                        AND sent_at < user_last_reaction_sent_at THEN -0.3
                    ELSE NULL
                END AS engagement_value
            FROM REACTIONS_WITH_CONTEXT
        ),

        USER_SMOOTHED AS (
            SELECT
                user_id,
                meme_id,
                engagement_value,
                engagement_value
                    - AVG(engagement_value)
                        OVER (PARTITION BY user_id ORDER BY sent_at)
                    AS smoothed_value,
                COUNT(engagement_value)
                    OVER (PARTITION BY user_id ORDER BY sent_at)
                    AS n_user_reactions
            FROM ENGAGEMENT_VALUES
            WHERE engagement_value IS NOT NULL
        )

        SELECT
            meme_id,
            AVG(smoothed_value) AS engagement_score
        FROM USER_SMOOTHED
        WHERE n_user_reactions >= {min_user_reactions}
        GROUP BY meme_id
        HAVING COUNT(*) >= {min_meme_reactions}

        ON CONFLICT (meme_id) DO UPDATE SET
            engagement_score = EXCLUDED.engagement_score
    """
    await execute(text(query))


async def calculate_meme_invited_count():
    # ruff: noqa: W605
    insert_query = """
        WITH MEME_IDS_IN_DEEP_LINKS AS (
            SELECT
                CAST(SPLIT_PART(deep_link, '_', 3) AS INTEGER) AS meme_id,
                user_id
            FROM
                user_deep_link_log
            WHERE
                deep_link IS NOT NULL
                AND deep_link LIKE 's\\_%\\_%'
        )

        INSERT INTO meme_stats (
            meme_id,
            invited_count
        )
        SELECT
            meme_id,
            COUNT(DISTINCT user_id) AS invited_count
        FROM MEME_IDS_IN_DEEP_LINKS
        INNER JOIN meme M
            ON M.id = MEME_IDS_IN_DEEP_LINKS.meme_id
        GROUP BY meme_id
        ON CONFLICT (meme_id) DO
        UPDATE SET
            invited_count = EXCLUDED.invited_count
    """
    await execute(text(insert_query))
