from sqlalchemy import text

from src.database import execute


async def calculate_meme_reactions_and_engagement(
    min_user_reactions: int = 10,
    min_meme_reactions: int = 3,
    lookback_hours: int = 3,
) -> None:
    """Combined lr_smoothed + engagement_score + basic counts — incremental mode.

    Only recomputes stats for memes that received reactions in the last
    `lookback_hours` hours. Memes with no recent activity keep their existing
    meme_stats rows unchanged (ON CONFLICT DO UPDATE only fires for included rows).

    lr_smoothed algorithm:
        1. like_symmetrical: reaction_id=1 → +1, else → -1
        2. user_like_rate = running avg(like_symmetrical) per user
        3. like_smoothed = like_symmetrical - user_like_rate
        4. lr_smoothed = avg(like_smoothed) per meme

    engagement_score algorithm:
        Like → +1.0, Slow dislike (>3s) → -1.0, Fast dislike (≤3s) → -0.5,
        Skip (sent, no reaction, user continued) → -0.3
        Same running-average user-bias correction as lr_smoothed.

    Both metrics are computed from one pass over user_meme_reaction.
    """

    query = """
        INSERT INTO meme_stats (
            meme_id, nlikes, ndislikes, nmemes_sent,
            age_days, sec_to_react, updated_at,
            lr_smoothed, engagement_score
        )

        WITH RECENT_MEME_IDS AS (
            SELECT DISTINCT meme_id
            FROM user_meme_reaction
            WHERE reacted_at > NOW() - :lookback_hours * INTERVAL '1 hour'
               OR sent_at > NOW() - :lookback_hours * INTERVAL '1 hour'
        ),

        BASE_REACTIONS AS (
            SELECT
                R.user_id, R.meme_id, R.reaction_id,
                R.sent_at, R.reacted_at,
                CASE WHEN R.reaction_id = 1 THEN 1
                     WHEN R.reaction_id IS NOT NULL THEN -1
                END AS like_sym,
                EXTRACT(EPOCH FROM R.reacted_at - R.sent_at) AS sec_to_react,
                MAX(CASE WHEN R.reaction_id IS NOT NULL THEN R.sent_at END)
                    OVER (PARTITION BY R.user_id) AS user_last_reaction_sent_at
            FROM user_meme_reaction R
            JOIN meme ON R.meme_id = meme.id
            WHERE R.meme_id IN (SELECT meme_id FROM RECENT_MEME_IDS)
        ),

        WITH_USER_AVGS AS (
            SELECT *,
                -- lr_smoothed: running avg of like_sym per user
                AVG(like_sym) OVER (
                    PARTITION BY user_id ORDER BY sent_at
                ) AS lr_avg,
                COUNT(like_sym) OVER (
                    PARTITION BY user_id ORDER BY sent_at
                ) AS n_user_lr_reactions,
                -- engagement: value assignment
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
            FROM BASE_REACTIONS
        ),

        SMOOTHED AS (
            SELECT
                user_id, meme_id,
                -- lr_smoothed per reaction
                CASE WHEN n_user_lr_reactions >= :min_user_reactions
                    THEN like_sym - lr_avg
                    ELSE NULL
                END AS lr_smoothed_val,
                -- engagement smoothed per reaction
                CASE WHEN engagement_value IS NOT NULL THEN
                    engagement_value - AVG(engagement_value) OVER (
                        PARTITION BY user_id ORDER BY sent_at
                    )
                    ELSE NULL
                END AS es_smoothed_val,
                n_user_lr_reactions
            FROM WITH_USER_AVGS
        ),

        MEME_SCORES AS (
            SELECT
                meme_id,
                AVG(lr_smoothed_val) AS lr_smoothed,
                AVG(es_smoothed_val) AS engagement_score,
                COUNT(lr_smoothed_val) AS n_lr_reactions,
                COUNT(es_smoothed_val) AS n_es_reactions
            FROM SMOOTHED
            GROUP BY meme_id
        ),

        BASIC_COUNTS AS (
            SELECT
                meme_id
                , COUNT(*) FILTER (WHERE reaction_id = 1) AS nlikes
                , COUNT(*) FILTER (WHERE reaction_id = 2) AS ndislikes
                , COUNT(*) AS nmemes_sent
                , MAX(EXTRACT('DAYS' FROM NOW() - M.published_at)) AS age_days
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
            INNER JOIN meme M ON M.id = E.meme_id
            GROUP BY 1
        )

        SELECT
            BC.meme_id, BC.nlikes, BC.ndislikes, BC.nmemes_sent,
            BC.age_days, BC.sec_to_react, BC.updated_at,
            COALESCE(
                CASE WHEN MS.n_lr_reactions >= :min_meme_reactions
                    THEN MS.lr_smoothed ELSE NULL END,
                0
            ) AS lr_smoothed,
            COALESCE(
                CASE WHEN MS.n_es_reactions >= :min_meme_reactions
                    THEN MS.engagement_score ELSE NULL END,
                0
            ) AS engagement_score
        FROM BASIC_COUNTS BC
        LEFT JOIN MEME_SCORES MS ON MS.meme_id = BC.meme_id

        ON CONFLICT (meme_id) DO
        UPDATE SET
            nlikes = EXCLUDED.nlikes,
            ndislikes = EXCLUDED.ndislikes,
            nmemes_sent = EXCLUDED.nmemes_sent,
            age_days = EXCLUDED.age_days,
            sec_to_react = EXCLUDED.sec_to_react,
            updated_at = EXCLUDED.updated_at,
            lr_smoothed = EXCLUDED.lr_smoothed,
            engagement_score = EXCLUDED.engagement_score
    """
    await execute(
        text(query),
        {
            "min_user_reactions": min_user_reactions,
            "min_meme_reactions": min_meme_reactions,
            "lookback_hours": lookback_hours,
        },
    )


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
