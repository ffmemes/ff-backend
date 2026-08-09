-- Retention broadcast effectiveness readout
--
-- Labels (after HQ pick ship):
--   broadcast_reengagement_hq  — affinity + proven-LR picker
--   broadcast_reengagement     — feed-queue fallback (or pre-HQ era)
--
-- Compare to in-session feed engines (recommended_by NOT LIKE 'broadcast%').
-- Primary: reactivation (react within 1h), LR, sec_to_react p50.
--
-- See experiments/HYPOTHESES.md H3 / H5.

\set ON_ERROR_STOP on

-- 1) Volume by broadcast label (14d)
SELECT
  recommended_by,
  count(*) AS sends,
  count(DISTINCT user_id) AS users,
  count(*) FILTER (WHERE reaction_id IS NOT NULL) AS reactions,
  round(
    100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / nullif(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS like_rate_pct,
  round(
    100.0 * count(*) FILTER (
      WHERE reacted_at IS NOT NULL
        AND reacted_at - sent_at < interval '1 hour'
    ) / nullif(count(*), 0),
    1
  ) AS react_within_1h_pct,
  round(
    percentile_cont(0.50) WITHIN GROUP (
      ORDER BY EXTRACT(EPOCH FROM reacted_at - sent_at)
    ) FILTER (
      WHERE reaction_id IS NOT NULL
        AND reacted_at >= sent_at
        AND EXTRACT(EPOCH FROM reacted_at - sent_at) BETWEEN 0 AND 86400
    )::numeric,
    1
  ) AS p50_sec_to_react
FROM user_meme_reaction
WHERE sent_at > now() - interval '14 days'
  AND recommended_by LIKE 'broadcast%'
GROUP BY 1
ORDER BY sends DESC;

-- 2) HQ vs queue-fallback vs feed (7d reacted)
WITH base AS (
  SELECT
    CASE
      WHEN recommended_by = 'broadcast_reengagement_hq' THEN 'broadcast_hq'
      WHEN recommended_by LIKE 'broadcast%' THEN 'broadcast_queue_or_legacy'
      ELSE 'feed'
    END AS path,
    reaction_id,
    EXTRACT(EPOCH FROM reacted_at - sent_at) AS sec
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '7 days'
    AND reaction_id IN (1, 2)
    AND reacted_at >= sent_at
    AND EXTRACT(EPOCH FROM reacted_at - sent_at) BETWEEN 0 AND 86400
)
SELECT
  path,
  count(*) AS n,
  round(100.0 * count(*) FILTER (WHERE reaction_id = 1) / nullif(count(*), 0), 1)
    AS like_rate_pct,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY sec)::numeric, 1) AS p50_s,
  round(
    100.0 * count(*) FILTER (WHERE sec < 120) / nullif(count(*), 0),
    1
  ) AS pct_react_under_2m
FROM base
GROUP BY 1
ORDER BY 1;

-- 3) Daily HQ adoption (post-deploy)
SELECT
  date_trunc('day', sent_at)::date AS day_utc,
  count(*) FILTER (WHERE recommended_by = 'broadcast_reengagement_hq') AS hq,
  count(*) FILTER (WHERE recommended_by = 'broadcast_reengagement') AS queue_fallback,
  count(*) FILTER (WHERE recommended_by LIKE 'broadcast%') AS all_broadcast
FROM user_meme_reaction
WHERE sent_at > now() - interval '14 days'
GROUP BY 1
ORDER BY 1 DESC;
