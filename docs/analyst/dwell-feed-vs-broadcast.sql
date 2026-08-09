-- Dwell / sec_to_react readout: like vs skip × feed vs broadcast
--
-- Product context
--   reaction_id = 1  like (strong positive)
--   reaction_id = 2  skip / "next" (NOT hard hate)
--   recommended_by = broadcast_reengagement  → retention push (post-#340)
--   other recommended_by                    → in-session feed engines
--
-- sec_to_react = EXTRACT(EPOCH FROM reacted_at - sent_at)
-- Long lags (>1h) are usually delayed open / night push, not "watched for an hour".
-- Use the dwell_bucket column to exclude stale reactions from ranking decisions.
--
-- Run via analyst_readonly (ANALYST_DATABASE_URL). Statement timeout 30s —
-- all queries filter reacted_at / sent_at to hit indexes.
--
-- After deploy of soft-demote + broadcast label, re-run section 1–4 weekly.

\set ON_ERROR_STOP on

-- =============================================================================
-- 0) Params
-- =============================================================================
-- Default: last 7 full-ish days of reactions with both timestamps.

-- =============================================================================
-- 1) Percentiles of sec_to_react by reaction × delivery path
-- =============================================================================
WITH base AS (
  SELECT
    CASE
      WHEN recommended_by LIKE 'broadcast%' THEN 'broadcast'
      ELSE 'feed'
    END AS delivery_path,
    CASE reaction_id
      WHEN 1 THEN 'like'
      WHEN 2 THEN 'skip'
      ELSE 'other'
    END AS reaction,
    EXTRACT(EPOCH FROM reacted_at - sent_at)::float AS sec_to_react
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '7 days'
    AND reacted_at IS NOT NULL
    AND sent_at IS NOT NULL
    AND reaction_id IN (1, 2)
    AND reacted_at >= sent_at
    AND EXTRACT(EPOCH FROM reacted_at - sent_at) BETWEEN 0 AND 86400  -- drop clock noise
)
SELECT
  delivery_path,
  reaction,
  count(*) AS n,
  round(percentile_cont(0.10) WITHIN GROUP (ORDER BY sec_to_react)::numeric, 2) AS p10_s,
  round(percentile_cont(0.25) WITHIN GROUP (ORDER BY sec_to_react)::numeric, 2) AS p25_s,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY sec_to_react)::numeric, 2) AS p50_s,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY sec_to_react)::numeric, 2) AS p75_s,
  round(percentile_cont(0.90) WITHIN GROUP (ORDER BY sec_to_react)::numeric, 2) AS p90_s,
  round(avg(sec_to_react)::numeric, 2) AS mean_s
FROM base
GROUP BY 1, 2
ORDER BY 1, 2;


-- =============================================================================
-- 2) Dwell buckets (for "what to feed ranking")
-- =============================================================================
-- Suggested policy buckets:
--   instant   < 2s     → often skip-without-reading (esp. text-heavy)
--   quick     2–15s    → typical feed swipe
--   engaged   15–60s   → read / rewatch / decide
--   long      60–3600s → come-back-to-meme or share flow
--   stale     > 3600s  → do not use for content affinity

WITH base AS (
  SELECT
    CASE
      WHEN recommended_by LIKE 'broadcast%' THEN 'broadcast'
      ELSE 'feed'
    END AS delivery_path,
    CASE reaction_id
      WHEN 1 THEN 'like'
      WHEN 2 THEN 'skip'
    END AS reaction,
    EXTRACT(EPOCH FROM reacted_at - sent_at)::float AS sec
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '7 days'
    AND reaction_id IN (1, 2)
    AND reacted_at >= sent_at
    AND EXTRACT(EPOCH FROM reacted_at - sent_at) BETWEEN 0 AND 86400
)
SELECT
  delivery_path,
  reaction,
  CASE
    WHEN sec < 2 THEN '1_instant_<2s'
    WHEN sec < 15 THEN '2_quick_2_15s'
    WHEN sec < 60 THEN '3_engaged_15_60s'
    WHEN sec < 3600 THEN '4_long_1m_1h'
    ELSE '5_stale_>1h'
  END AS dwell_bucket,
  count(*) AS n,
  round(100.0 * count(*) / sum(count(*)) OVER (PARTITION BY delivery_path, reaction), 1)
    AS pct_of_path_reaction
FROM base
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;


-- =============================================================================
-- 3) Broadcast-specific: how fast do people react to retention pushes?
-- =============================================================================
-- Only meaningful after #340 labels new sends as broadcast_reengagement.
-- Historical rows may still show engine names for push-delivered memes.

SELECT
  recommended_by,
  count(*) AS n_reactions,
  count(*) FILTER (WHERE reaction_id = 1) AS likes,
  count(*) FILTER (WHERE reaction_id = 2) AS skips,
  round(
    100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS like_rate_pct,
  round(
    percentile_cont(0.50) WITHIN GROUP (
      ORDER BY EXTRACT(EPOCH FROM reacted_at - sent_at)
    ) FILTER (WHERE reaction_id = 1)::numeric,
    2
  ) AS like_p50_s,
  round(
    percentile_cont(0.50) WITHIN GROUP (
      ORDER BY EXTRACT(EPOCH FROM reacted_at - sent_at)
    ) FILTER (WHERE reaction_id = 2)::numeric,
    2
  ) AS skip_p50_s,
  round(
    100.0 * count(*) FILTER (
      WHERE EXTRACT(EPOCH FROM reacted_at - sent_at) > 3600
    ) / NULLIF(count(*), 0),
    1
  ) AS pct_stale_gt_1h
FROM user_meme_reaction
WHERE sent_at > now() - interval '7 days'
  AND reacted_at IS NOT NULL
  AND (
    recommended_by LIKE 'broadcast%'
    OR recommended_by IN ('broadcast_reengagement', 'broadcast', 'reengagement')
  )
GROUP BY 1
ORDER BY n_reactions DESC;


-- =============================================================================
-- 4) Feed engines only: like vs skip dwell (exclude broadcasts + unknown)
-- =============================================================================
WITH base AS (
  SELECT
    recommended_by AS engine,
    reaction_id,
    EXTRACT(EPOCH FROM reacted_at - sent_at)::float AS sec
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '7 days'
    AND reaction_id IN (1, 2)
    AND reacted_at >= sent_at
    AND recommended_by NOT LIKE 'broadcast%'
    AND EXTRACT(EPOCH FROM reacted_at - sent_at) BETWEEN 0.5 AND 3600  -- in-session
)
SELECT
  engine,
  count(*) AS n,
  round(100.0 * count(*) FILTER (WHERE reaction_id = 1) / NULLIF(count(*), 0), 1)
    AS like_rate_pct,
  round(
    percentile_cont(0.50) WITHIN GROUP (ORDER BY sec)
      FILTER (WHERE reaction_id = 1)::numeric,
    2
  ) AS like_p50_s,
  round(
    percentile_cont(0.50) WITHIN GROUP (ORDER BY sec)
      FILTER (WHERE reaction_id = 2)::numeric,
    2
  ) AS skip_p50_s,
  round(
    percentile_cont(0.50) WITHIN GROUP (ORDER BY sec)
      FILTER (WHERE reaction_id = 1)::numeric
    - percentile_cont(0.50) WITHIN GROUP (ORDER BY sec)
      FILTER (WHERE reaction_id = 2)::numeric,
    2
  ) AS like_minus_skip_p50_s
FROM base
GROUP BY 1
HAVING count(*) >= 500
ORDER BY n DESC
LIMIT 30;


-- =============================================================================
-- 5) Soft-demote inventory risk: how many majority-dislike sources per active user?
-- =============================================================================
-- If hard-block were ON (majority dislike, n>=5), this is the share of affinity
-- rows that would be banned — proxy for empty-queue risk.

WITH active AS (
  SELECT DISTINCT user_id
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '7 days'
),
umss AS (
  SELECT
    u.user_id,
    count(*) AS sources_touched,
    count(*) FILTER (
      WHERE s.ndislikes > s.nlikes
        AND (s.nlikes + s.ndislikes) >= 5
    ) AS majority_dislike_sources,
    count(*) FILTER (
      WHERE s.ndislikes >= 3 * GREATEST(s.nlikes, 1)
        AND (s.nlikes + s.ndislikes) >= 15
    ) AS strong_hate_sources
  FROM active u
  JOIN user_meme_source_stats s ON s.user_id = u.user_id
  GROUP BY u.user_id
)
SELECT
  count(*) AS active_users_7d,
  round(avg(sources_touched)::numeric, 1) AS avg_sources_touched,
  round(avg(majority_dislike_sources)::numeric, 1) AS avg_majority_dislike_sources,
  round(avg(strong_hate_sources)::numeric, 1) AS avg_strong_hate_sources,
  round(
    100.0 * avg(majority_dislike_sources::float / NULLIF(sources_touched, 0))::numeric,
    1
  ) AS avg_pct_sources_majority_dislike,
  percentile_cont(0.50) WITHIN GROUP (
    ORDER BY majority_dislike_sources::float / NULLIF(sources_touched, 0)
  ) AS p50_frac_majority_dislike,
  percentile_cont(0.90) WITHIN GROUP (
    ORDER BY majority_dislike_sources::float / NULLIF(sources_touched, 0)
  ) AS p90_frac_majority_dislike
FROM umss;


-- =============================================================================
-- 6) Post-deploy guardrail: sends still flowing + broadcast label adoption
-- =============================================================================
SELECT
  date_trunc('hour', sent_at) AS hour_utc,
  count(*) AS sends,
  count(*) FILTER (WHERE recommended_by = 'broadcast_reengagement') AS broadcast_labeled,
  count(*) FILTER (WHERE reaction_id IS NOT NULL) AS reacted,
  round(
    100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS like_rate_pct
FROM user_meme_reaction
WHERE sent_at > now() - interval '48 hours'
GROUP BY 1
ORDER BY 1 DESC
LIMIT 48;
