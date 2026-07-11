from typing import Any, Literal

from sqlalchemy import text
from sqlalchemy.sql.elements import TextClause

ReadoutSection = Literal[
    "summary",
    "per_position",
    "per_engine",
    "segments",
    "candidate_memes",
]

READOUT_SECTIONS: tuple[ReadoutSection, ...] = (
    "summary",
    "per_position",
    "per_engine",
    "segments",
    "candidate_memes",
)

DEFAULT_LOOKBACK_DAYS = 14
DEFAULT_MIN_CANDIDATE_SENDS = 3
DEFAULT_CANDIDATE_LIMIT = 20

_BASE_CTE = """
WITH first_sends AS (
    SELECT DISTINCT ON (user_id)
        user_id,
        meme_id,
        recommended_by,
        sent_at
    FROM user_meme_reaction
    ORDER BY user_id, sent_at, meme_id
),

true_new_users AS (
    SELECT
        user_id,
        sent_at AS first_send_at
    FROM first_sends
    WHERE sent_at >= NOW() - (:lookback_days * INTERVAL '1 day')
      AND recommended_by IN ('cold_start_explore', 'cold_start_adapt')
),

candidate_sends AS (
    SELECT
        R.user_id,
        R.meme_id,
        R.recommended_by,
        R.sent_at,
        R.reaction_id,
        R.reacted_at
    FROM user_meme_reaction R
    JOIN true_new_users TNU ON TNU.user_id = R.user_id
    WHERE R.sent_at >= TNU.first_send_at
),

ordered_sends AS (
    SELECT
        CS.*,
        ROW_NUMBER() OVER (
            PARTITION BY CS.user_id
            ORDER BY CS.sent_at, CS.meme_id
        ) AS send_position,
        LAG(CS.sent_at) OVER (
            PARTITION BY CS.user_id
            ORDER BY CS.sent_at, CS.meme_id
        ) AS previous_sent_at,
        LEAD(CS.sent_at) OVER (
            PARTITION BY CS.user_id
            ORDER BY CS.sent_at, CS.meme_id
        ) AS next_sent_at,
        MAX(CASE WHEN CS.reaction_id IS NOT NULL THEN CS.sent_at END) OVER (
            PARTITION BY CS.user_id
        ) AS user_last_reaction_sent_at
    FROM candidate_sends CS
),

sessionized_sends AS (
    SELECT
        OS.*,
        CASE
            WHEN OS.previous_sent_at IS NULL THEN 1
            WHEN OS.sent_at - OS.previous_sent_at > INTERVAL '30 minutes' THEN 1
            ELSE 0
        END AS new_session_flag
    FROM ordered_sends OS
),

ranked_sends AS (
    SELECT
        SS.*,
        SUM(SS.new_session_flag) OVER (
            PARTITION BY SS.user_id
            ORDER BY SS.sent_at, SS.meme_id
        ) AS session_number
    FROM sessionized_sends SS
),

first10_sends AS (
    SELECT
        RS.user_id,
        RS.meme_id,
        RS.recommended_by,
        RS.sent_at,
        RS.reaction_id,
        RS.reacted_at,
        RS.send_position AS first10_position,
        RS.session_number,
        RS.next_sent_at,
        RS.next_sent_at IS NOT NULL
            AND RS.next_sent_at - RS.sent_at < INTERVAL '30 minutes'
            AS continued_within_30m,
        CASE
            WHEN RS.reaction_id = 1 THEN 1.0
            WHEN RS.reaction_id = 2
                AND EXTRACT(EPOCH FROM RS.reacted_at - RS.sent_at) BETWEEN 0.5 AND 60
                AND EXTRACT(EPOCH FROM RS.reacted_at - RS.sent_at) > 3
                THEN -1.0
            WHEN RS.reaction_id = 2
                AND EXTRACT(EPOCH FROM RS.reacted_at - RS.sent_at) BETWEEN 0.5 AND 60
                AND EXTRACT(EPOCH FROM RS.reacted_at - RS.sent_at) <= 3
                THEN -0.5
            WHEN RS.reaction_id = 2 THEN -1.0
            WHEN RS.reaction_id IS NULL
                AND RS.sent_at < RS.user_last_reaction_sent_at THEN -0.3
            ELSE NULL
        END AS first10_engagement_value,
        M.type AS meme_type,
        M.language_code AS meme_language_code,
        M.meme_source_id,
        SRC.url AS source_url,
        SRC.type AS source_type,
        SRC.language_code AS source_language_code,
        MS.lr_smoothed,
        MS.engagement_score AS meme_engagement_score,
        MS.nlikes AS historical_likes,
        MS.ndislikes AS historical_dislikes,
        MS.nmemes_sent AS historical_sends
    FROM ranked_sends RS
    JOIN meme M ON M.id = RS.meme_id
    LEFT JOIN meme_source SRC ON SRC.id = M.meme_source_id
    LEFT JOIN meme_stats MS ON MS.meme_id = RS.meme_id
    WHERE RS.send_position <= 10
),

cohort_depth AS (
    SELECT
        user_id,
        COUNT(*) AS first10_sends
    FROM first10_sends
    GROUP BY user_id
),

cohort_sessions AS (
    SELECT
        user_id,
        BOOL_OR(session_number >= 2) AS has_second_session
    FROM ranked_sends
    GROUP BY user_id
),

cohort_users AS (
    SELECT
        TNU.user_id,
        TNU.first_send_at,
        COALESCE(CD.first10_sends, 0) AS first10_sends,
        COALESCE(CS.has_second_session, FALSE) AS has_second_session
    FROM true_new_users TNU
    LEFT JOIN cohort_depth CD ON CD.user_id = TNU.user_id
    LEFT JOIN cohort_sessions CS ON CS.user_id = TNU.user_id
)
"""

_SECTION_SQL: dict[ReadoutSection, str] = {
    "summary": """
, summary_counts AS (
    SELECT
        (SELECT COUNT(*) FROM cohort_users) AS cohort_users,
        (SELECT COUNT(*) FROM cohort_users WHERE first10_sends >= 5) AS reached5_users,
        (SELECT COUNT(*) FROM cohort_users WHERE first10_sends >= 10) AS reached10_users,
        (SELECT COUNT(*) FROM cohort_users WHERE has_second_session) AS second_session_users,
        COUNT(*) FILTER (WHERE first10_position = 1) AS first_meme_sends,
        COUNT(*) FILTER (
            WHERE first10_position = 1 AND reaction_id = 1
        ) AS first_meme_likes,
        COUNT(*) FILTER (
            WHERE first10_position = 1 AND reaction_id IS NOT NULL
        ) AS first_meme_reacted,
        COUNT(*) FILTER (
            WHERE first10_position = 1 AND continued_within_30m
        ) AS first_meme_continued,
        COUNT(*) AS first10_sends,
        COUNT(*) FILTER (WHERE reaction_id = 1) AS first10_likes,
        COUNT(*) FILTER (WHERE reaction_id IS NOT NULL) AS first10_reacted,
        COUNT(*) FILTER (WHERE continued_within_30m) AS first10_continued,
        AVG(first10_engagement_value) AS first10_quality_score,
        AVG(meme_engagement_score) AS avg_meme_engagement_score
    FROM first10_sends
)
SELECT
    cohort_users,
    first_meme_sends,
    first_meme_likes,
    first_meme_reacted,
    ROUND((100.0 * first_meme_likes / NULLIF(first_meme_reacted, 0))::numeric, 1)
        AS first_meme_lr_pct,
    ROUND((100.0 * first_meme_continued / NULLIF(first_meme_sends, 0))::numeric, 1)
        AS first_meme_continuation_pct,
    first10_sends,
    first10_likes,
    first10_reacted,
    ROUND((100.0 * first10_likes / NULLIF(first10_reacted, 0))::numeric, 1)
        AS first10_lr_pct,
    ROUND((100.0 * first10_continued / NULLIF(first10_sends, 0))::numeric, 1)
        AS first10_continuation_pct,
    reached5_users,
    ROUND((100.0 * reached5_users / NULLIF(cohort_users, 0))::numeric, 1)
        AS reached5_pct,
    reached10_users,
    ROUND((100.0 * reached10_users / NULLIF(cohort_users, 0))::numeric, 1)
        AS reached10_pct,
    second_session_users,
    ROUND((100.0 * second_session_users / NULLIF(cohort_users, 0))::numeric, 1)
        AS second_session_pct,
    ROUND(first10_quality_score::numeric, 3) AS first10_quality_score,
    ROUND(avg_meme_engagement_score::numeric, 3) AS avg_meme_engagement_score
FROM summary_counts
""",
    "per_position": """
SELECT
    first10_position,
    COUNT(DISTINCT user_id) AS users,
    COUNT(*) AS sends,
    COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
    COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes,
    COUNT(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
    ROUND(
        (100.0 * COUNT(*) FILTER (WHERE reaction_id = 1)
            / NULLIF(COUNT(*) FILTER (WHERE reaction_id IS NOT NULL), 0))::numeric,
        1
    ) AS like_rate_pct,
    ROUND(
        (100.0 * COUNT(*) FILTER (WHERE continued_within_30m) / NULLIF(COUNT(*), 0))::numeric,
        1
    ) AS continuation_pct,
    ROUND(AVG(first10_engagement_value)::numeric, 3) AS first10_quality_score,
    ROUND(AVG(meme_engagement_score)::numeric, 3) AS avg_meme_engagement_score
FROM first10_sends
GROUP BY first10_position
ORDER BY first10_position
""",
    "per_engine": """
SELECT
    recommended_by AS engine,
    COUNT(DISTINCT user_id) AS users,
    COUNT(*) AS sends,
    COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
    COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes,
    COUNT(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
    ROUND(
        (100.0 * COUNT(*) FILTER (WHERE reaction_id = 1)
            / NULLIF(COUNT(*) FILTER (WHERE reaction_id IS NOT NULL), 0))::numeric,
        1
    ) AS like_rate_pct,
    ROUND(
        (100.0 * COUNT(*) FILTER (WHERE continued_within_30m) / NULLIF(COUNT(*), 0))::numeric,
        1
    ) AS continuation_pct,
    ROUND(AVG(first10_engagement_value)::numeric, 3) AS first10_quality_score,
    ROUND(AVG(meme_engagement_score)::numeric, 3) AS avg_meme_engagement_score
FROM first10_sends
GROUP BY recommended_by
ORDER BY sends DESC, engine
""",
    "segments": """
, segment_rollups AS (
    SELECT
        'source' AS segment_type,
        COALESCE(source_url, 'unknown') AS segment_value,
        COUNT(DISTINCT user_id) AS users,
        COUNT(*) AS sends,
        COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
        COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes,
        COUNT(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
        COUNT(*) FILTER (WHERE continued_within_30m) AS continued,
        AVG(first10_engagement_value) AS first10_quality_score,
        AVG(meme_engagement_score) AS avg_meme_engagement_score
    FROM first10_sends
    GROUP BY source_url

    UNION ALL

    SELECT
        'meme_type' AS segment_type,
        COALESCE(meme_type, 'unknown') AS segment_value,
        COUNT(DISTINCT user_id) AS users,
        COUNT(*) AS sends,
        COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
        COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes,
        COUNT(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
        COUNT(*) FILTER (WHERE continued_within_30m) AS continued,
        AVG(first10_engagement_value) AS first10_quality_score,
        AVG(meme_engagement_score) AS avg_meme_engagement_score
    FROM first10_sends
    GROUP BY meme_type

    UNION ALL

    SELECT
        'meme_language' AS segment_type,
        COALESCE(meme_language_code, 'unknown') AS segment_value,
        COUNT(DISTINCT user_id) AS users,
        COUNT(*) AS sends,
        COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
        COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes,
        COUNT(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
        COUNT(*) FILTER (WHERE continued_within_30m) AS continued,
        AVG(first10_engagement_value) AS first10_quality_score,
        AVG(meme_engagement_score) AS avg_meme_engagement_score
    FROM first10_sends
    GROUP BY meme_language_code

    UNION ALL

    SELECT
        'source_language' AS segment_type,
        COALESCE(source_language_code, 'unknown') AS segment_value,
        COUNT(DISTINCT user_id) AS users,
        COUNT(*) AS sends,
        COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
        COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes,
        COUNT(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
        COUNT(*) FILTER (WHERE continued_within_30m) AS continued,
        AVG(first10_engagement_value) AS first10_quality_score,
        AVG(meme_engagement_score) AS avg_meme_engagement_score
    FROM first10_sends
    GROUP BY source_language_code
)
SELECT
    segment_type,
    segment_value,
    users,
    sends,
    likes,
    dislikes,
    unreacted,
    ROUND((100.0 * likes / NULLIF(likes + dislikes, 0))::numeric, 1) AS like_rate_pct,
    ROUND((100.0 * continued / NULLIF(sends, 0))::numeric, 1) AS continuation_pct,
    ROUND(first10_quality_score::numeric, 3) AS first10_quality_score,
    ROUND(avg_meme_engagement_score::numeric, 3) AS avg_meme_engagement_score
FROM segment_rollups
ORDER BY segment_type, sends DESC, segment_value
""",
    "candidate_memes": """
, meme_rollups AS (
    SELECT
        meme_id,
        MAX(source_url) AS source_url,
        MAX(meme_type) AS meme_type,
        MAX(meme_language_code) AS meme_language_code,
        MIN(first10_position) AS min_first10_position,
        MAX(first10_position) AS max_first10_position,
        ROUND(AVG(first10_position)::numeric, 2) AS avg_first10_position,
        COUNT(DISTINCT user_id) AS users,
        COUNT(*) AS sends,
        COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
        COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes,
        COUNT(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
        COUNT(*) FILTER (WHERE continued_within_30m) AS continued,
        AVG(first10_engagement_value) AS first10_quality_score,
        AVG(meme_engagement_score) AS avg_meme_engagement_score,
        MAX(lr_smoothed) AS lr_smoothed,
        MAX(historical_likes) AS historical_likes,
        MAX(historical_dislikes) AS historical_dislikes,
        MAX(historical_sends) AS historical_sends
    FROM first10_sends
    GROUP BY meme_id
    HAVING COUNT(*) >= :min_candidate_sends
),

ranked_meme_rollups AS (
    SELECT
        MR.*,
        ROW_NUMBER() OVER (
            ORDER BY first10_quality_score DESC NULLS LAST, sends DESC, meme_id
        ) AS top_rank,
        ROW_NUMBER() OVER (
            ORDER BY first10_quality_score ASC NULLS LAST, sends DESC, meme_id
        ) AS bottom_rank
    FROM meme_rollups MR
)
SELECT
    'top' AS quality_bucket,
    top_rank AS bucket_rank,
    meme_id,
    source_url,
    meme_type,
    meme_language_code,
    min_first10_position,
    max_first10_position,
    avg_first10_position,
    users,
    sends,
    likes,
    dislikes,
    unreacted,
    ROUND((100.0 * likes / NULLIF(likes + dislikes, 0))::numeric, 1) AS like_rate_pct,
    ROUND((100.0 * continued / NULLIF(sends, 0))::numeric, 1) AS continuation_pct,
    ROUND(first10_quality_score::numeric, 3) AS first10_quality_score,
    ROUND(avg_meme_engagement_score::numeric, 3) AS avg_meme_engagement_score,
    lr_smoothed,
    historical_likes,
    historical_dislikes,
    historical_sends
FROM ranked_meme_rollups
WHERE top_rank <= :candidate_limit

UNION ALL

SELECT
    'bottom' AS quality_bucket,
    bottom_rank AS bucket_rank,
    meme_id,
    source_url,
    meme_type,
    meme_language_code,
    min_first10_position,
    max_first10_position,
    avg_first10_position,
    users,
    sends,
    likes,
    dislikes,
    unreacted,
    ROUND((100.0 * likes / NULLIF(likes + dislikes, 0))::numeric, 1) AS like_rate_pct,
    ROUND((100.0 * continued / NULLIF(sends, 0))::numeric, 1) AS continuation_pct,
    ROUND(first10_quality_score::numeric, 3) AS first10_quality_score,
    ROUND(avg_meme_engagement_score::numeric, 3) AS avg_meme_engagement_score,
    lr_smoothed,
    historical_likes,
    historical_dislikes,
    historical_sends
FROM ranked_meme_rollups
WHERE bottom_rank <= :candidate_limit
ORDER BY quality_bucket DESC, bucket_rank
""",
}


def cold_start_first10_quality_params(
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_candidate_sends: int = DEFAULT_MIN_CANDIDATE_SENDS,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> dict[str, int]:
    return {
        "lookback_days": lookback_days,
        "min_candidate_sends": min_candidate_sends,
        "candidate_limit": candidate_limit,
    }


def build_cold_start_first10_quality_query(section: ReadoutSection) -> TextClause:
    return text(f"{_BASE_CTE}\n{_SECTION_SQL[section]}")


async def fetch_cold_start_first10_quality_readout(
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    min_candidate_sends: int = DEFAULT_MIN_CANDIDATE_SENDS,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> dict[ReadoutSection, list[dict[str, Any]]]:
    from src.database import fetch_all

    params = cold_start_first10_quality_params(
        lookback_days=lookback_days,
        min_candidate_sends=min_candidate_sends,
        candidate_limit=candidate_limit,
    )
    readout: dict[ReadoutSection, list[dict[str, Any]]] = {}
    for section in READOUT_SECTIONS:
        readout[section] = await fetch_all(
            build_cold_start_first10_quality_query(section),
            params,
        )
    return readout
