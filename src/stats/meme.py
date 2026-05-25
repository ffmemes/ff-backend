import logging
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import execute, fetch_all

logger = logging.getLogger(__name__)

LOW_SENT_POOL_SKIP_RATE_ALERT_THRESHOLD = 0.5
LOW_SENT_POOL_SKIP_RATE_ALERT_MIN_SENDS = 10
LOW_SENT_POOL_SKIP_RATE_ALERT_LOOKBACK_DAYS = 7
LOW_SENT_POOL_SKIP_RATE_ALERT_LIMIT = 20


async def calculate_meme_reactions_and_engagement(
    min_user_reactions: int = 10,
    min_meme_reactions: int = 3,
    lookback_hours: int = 3,
    meme_ids: list[int] | None = None,
    include_user_history: bool = False,
) -> None:
    await _execute_meme_reactions_and_engagement(
        execute,
        min_user_reactions=min_user_reactions,
        min_meme_reactions=min_meme_reactions,
        lookback_hours=lookback_hours,
        meme_ids=meme_ids,
        include_user_history=include_user_history,
    )


async def calculate_meme_reactions_and_engagement_on_connection(
    conn: AsyncConnection,
    *,
    min_user_reactions: int = 10,
    min_meme_reactions: int = 3,
    lookback_hours: int = 3,
    meme_ids: list[int] | None = None,
    include_user_history: bool = False,
) -> None:
    await _execute_meme_reactions_and_engagement(
        conn.execute,
        min_user_reactions=min_user_reactions,
        min_meme_reactions=min_meme_reactions,
        lookback_hours=lookback_hours,
        meme_ids=meme_ids,
        include_user_history=include_user_history,
    )


async def _execute_meme_reactions_and_engagement(
    execute_query: Callable[[Any, dict[str, Any]], Awaitable[Any]],
    *,
    min_user_reactions: int,
    min_meme_reactions: int,
    lookback_hours: int,
    meme_ids: list[int] | None,
    include_user_history: bool,
) -> None:
    """Combined lr_smoothed + engagement_score + basic counts — incremental mode.

    Only recomputes stats for memes that received reactions in the last
    `lookback_hours` hours. Memes with no recent activity keep their existing
    meme_stats rows unchanged unless explicitly included in `meme_ids`.
    When `include_user_history` is true, user baselines are built from all
    reactions by users who touched the target memes; this is used after moving
    historical reactions during deduplication.

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
            WHERE COALESCE(reacted_at, sent_at) > NOW() - :lookback_hours * INTERVAL '1 hour'
        ),

        FORCED_MEME_IDS AS (
            SELECT M.id AS meme_id
            FROM meme M
            WHERE :has_forced_meme_ids
              AND M.id = ANY(:meme_ids)
        ),

        TARGET_MEME_IDS AS (
            SELECT meme_id FROM RECENT_MEME_IDS
            UNION
            SELECT meme_id FROM FORCED_MEME_IDS
        ),

        AFFECTED_USERS AS (
            SELECT DISTINCT user_id
            FROM user_meme_reaction
            WHERE meme_id IN (SELECT meme_id FROM TARGET_MEME_IDS)
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
            WHERE (
                (:include_user_history AND R.user_id IN (SELECT user_id FROM AFFECTED_USERS))
                OR (
                    NOT :include_user_history
                    AND R.meme_id IN (SELECT meme_id FROM TARGET_MEME_IDS)
                )
            )
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
            WHERE meme_id IN (SELECT meme_id FROM TARGET_MEME_IDS)
            GROUP BY meme_id
        ),

        BASIC_COUNTS AS (
            SELECT
                M.id AS meme_id
                , COUNT(*) FILTER (WHERE E.reaction_id = 1) AS nlikes
                , COUNT(*) FILTER (WHERE E.reaction_id = 2) AS ndislikes
                , COUNT(E.*) AS nmemes_sent
                , MAX(EXTRACT('DAYS' FROM NOW() - M.published_at)) AS age_days
                , COALESCE(EXTRACT(
                    EPOCH FROM
                    percentile_cont(0.5)
                        WITHIN GROUP (ORDER BY E.reacted_at - E.sent_at)
                        FILTER (
                            WHERE E.reacted_at - E.sent_at
                            BETWEEN '0.5 second'
                            AND '1 minute'
                        )
                ), 99999) AS sec_to_react
                , NOW() AS updated_at
            FROM meme M
            LEFT JOIN user_meme_reaction E ON E.meme_id = M.id
            WHERE M.id IN (SELECT meme_id FROM TARGET_MEME_IDS)
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
        ORDER BY BC.meme_id

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
    forced_meme_ids = meme_ids or [0]
    await execute_query(
        text(query),
        {
            "min_user_reactions": min_user_reactions,
            "min_meme_reactions": min_meme_reactions,
            "lookback_hours": lookback_hours,
            "has_forced_meme_ids": bool(meme_ids),
            "meme_ids": forced_meme_ids,
            "include_user_history": include_user_history,
        },
    )


async def get_low_sent_pool_skip_rate_alerts(
    skip_rate_threshold: float = LOW_SENT_POOL_SKIP_RATE_ALERT_THRESHOLD,
    min_sends: int = LOW_SENT_POOL_SKIP_RATE_ALERT_MIN_SENDS,
    lookback_days: int = LOW_SENT_POOL_SKIP_RATE_ALERT_LOOKBACK_DAYS,
    limit: int = LOW_SENT_POOL_SKIP_RATE_ALERT_LIMIT,
) -> list[dict]:
    """Return low_sent_pool memes whose explicit down/skip rate is above threshold.

    This is a shadow guardrail only. It reads historical delivery/reaction rows
    and intentionally does not update meme status or recommendation eligibility.
    """

    query = """
        WITH LOW_SENT_REACTIONS AS (
            SELECT
                R.meme_id,
                COUNT(*) AS sends,
                COUNT(*) FILTER (WHERE R.reaction_id = 1) AS likes,
                COUNT(*) FILTER (WHERE R.reaction_id = 2) AS skips,
                COUNT(*) FILTER (WHERE R.reaction_id IS NOT NULL) AS explicit_reactions,
                MIN(R.sent_at) AS first_sent_at,
                MAX(R.sent_at) AS last_sent_at
            FROM user_meme_reaction R
            WHERE R.recommended_by = 'low_sent_pool'
                AND R.sent_at >= NOW() - (:lookback_days * INTERVAL '1 day')
            GROUP BY R.meme_id
        )
        SELECT
            M.id AS meme_id,
            M.status AS meme_status,
            M.meme_source_id,
            M.published_at,
            MS.type AS source_type,
            MS.status AS source_status,
            CASE
                WHEN MS.type = 'telegram' AND MRT.post_id IS NOT NULL
                    THEN MS.url || '/' || MRT.post_id
                WHEN MS.type = 'vk' AND MRV.url IS NOT NULL
                    THEN MRV.url
                WHEN MS.type = 'instagram' AND MRI.url IS NOT NULL
                    THEN MRI.url
                ELSE MS.url
            END AS source_url,
            LSR.sends,
            LSR.likes,
            LSR.skips,
            LSR.explicit_reactions,
            LSR.first_sent_at,
            LSR.last_sent_at,
            EXTRACT(EPOCH FROM (NOW() - M.published_at)) / 86400.0 AS published_age_days,
            (LSR.likes::float / NULLIF(LSR.explicit_reactions, 0)) AS like_rate,
            (LSR.skips::float / NULLIF(LSR.explicit_reactions, 0)) AS skip_rate,
            (
                M.status IN ('rejected', 'snoozed')
                OR MS.status = 'snoozed'
            ) AS already_rejected_or_snoozed
        FROM LOW_SENT_REACTIONS LSR
        INNER JOIN meme M
            ON M.id = LSR.meme_id
        INNER JOIN meme_source MS
            ON MS.id = M.meme_source_id
        LEFT JOIN meme_raw_telegram MRT
            ON MS.type = 'telegram' AND MRT.id = M.raw_meme_id
        LEFT JOIN meme_raw_vk MRV
            ON MS.type = 'vk' AND MRV.id = M.raw_meme_id
        LEFT JOIN meme_raw_ig MRI
            ON MS.type = 'instagram' AND MRI.id = M.raw_meme_id
        WHERE LSR.sends >= :min_sends
            AND LSR.explicit_reactions > 0
            AND (LSR.skips::float / NULLIF(LSR.explicit_reactions, 0)) > :skip_rate_threshold
        ORDER BY
            already_rejected_or_snoozed ASC,
            skip_rate DESC,
            sends DESC,
            meme_id ASC
        LIMIT :limit
    """
    return await fetch_all(
        text(query),
        {
            "skip_rate_threshold": skip_rate_threshold,
            "min_sends": min_sends,
            "lookback_days": lookback_days,
            "limit": limit,
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
            WHERE M.status = 'ok'
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
    # Counts non-self bot starts from in-bot share links (m_{user_id}_{meme_id})
    insert_query = """
        WITH PARSED_SHARE_CLICKS AS (
            SELECT
                CAST(SPLIT_PART(deep_link, '_', 2) AS BIGINT) AS sharer_user_id,
                CAST(SPLIT_PART(deep_link, '_', 3) AS INTEGER) AS meme_id,
                user_id AS clicked_user_id
            FROM user_deep_link_log
            WHERE
                deep_link IS NOT NULL
                AND deep_link LIKE ANY (ARRAY['m\\_%\\_%', 's\\_%\\_%'])
                AND deep_link ~ '^[ms]_[0-9]+_[0-9]+$'
        ),
        AFFECTED_MEMES AS (
            SELECT M.id AS meme_id
            FROM meme M
            INNER JOIN (
                SELECT DISTINCT meme_id
                FROM PARSED_SHARE_CLICKS

                UNION

                SELECT meme_id
                FROM meme_stats
                WHERE invited_count > 0
            ) AFFECTED_MEME_IDS
                ON AFFECTED_MEME_IDS.meme_id = M.id
        ),
        NON_SELF_SHARE_CLICKS AS (
            SELECT
                meme_id,
                clicked_user_id
            FROM PARSED_SHARE_CLICKS
            WHERE clicked_user_id <> sharer_user_id
        )

        INSERT INTO meme_stats (
            meme_id,
            invited_count
        )
        SELECT
            AFFECTED_MEMES.meme_id,
            COUNT(DISTINCT NON_SELF_SHARE_CLICKS.clicked_user_id) AS invited_count
        FROM AFFECTED_MEMES
        LEFT JOIN NON_SELF_SHARE_CLICKS
            ON NON_SELF_SHARE_CLICKS.meme_id = AFFECTED_MEMES.meme_id
        GROUP BY AFFECTED_MEMES.meme_id
        ON CONFLICT (meme_id) DO
        UPDATE SET
            invited_count = EXCLUDED.invited_count
    """
    await execute(text(insert_query))


async def calculate_channel_invited_count():
    """Count bot starts from channel crosspost links (sc_{meme_id}_{channel}).

    Different deep link format from in-bot shares:
    - Bot shares: m_{user_id}_{meme_id} -> invited_count
    - Channel posts: sc_{meme_id}_{channel} -> channel_invited_count
    """
    # The actual bot_starts metric is computed on-demand via SQL queries in
    # analysis (T6). This function validates the deep link parsing works
    # correctly by logging per-channel counts.
    count_query = """
        SELECT
            SPLIT_PART(deep_link, '_', 3) AS channel,
            COUNT(DISTINCT user_id) AS bot_starts,
            COUNT(*) AS total_clicks
        FROM user_deep_link_log
        WHERE deep_link IS NOT NULL
          AND deep_link LIKE 'sc\\_%\\_%'
        GROUP BY channel
    """
    rows = await fetch_all(text(count_query))
    if rows:
        for row in rows:
            logger.info(
                "Channel %s: %d bot starts (%d total clicks)",
                row["channel"],
                row["bot_starts"],
                row["total_clicks"],
            )
    return rows
