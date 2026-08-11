-- H7 taste-cohort shadow readout (does not change ranking)
-- Requires decision_log candidates with n_taste_likes (post deploy of shadow).
-- Join to 24h labels when mature.

\set ON_ERROR_STOP on

-- 1) Shadow coverage on recent decisions
SELECT
  count(*) AS decisions,
  count(*) FILTER (
    WHERE (candidates->0->>'n_taste_likes') IS NOT NULL
  ) AS with_field,
  count(*) FILTER (
    WHERE COALESCE((candidates->0->>'n_taste_likes')::int, 0) >= 1
  ) AS top1_taste_ge1,
  round(avg(COALESCE((candidates->0->>'n_taste_likes')::float, 0))::numeric, 2)
    AS avg_top1_n_taste,
  max(candidates->0->>'taste_cohort_version') AS cohort_version
FROM crossposting_decision_log
WHERE channel = 'tgchannelru'
  AND decided_at > now() - interval '14 days'
  AND score_version = 4;

-- 2) Picked meme: n_taste vs eventual early/live forwards (young ok for smoke)
SELECT
  d.decided_at,
  d.picked_meme_id,
  (d.candidates->0->>'n_taste_likes')::int AS n_taste,
  (d.candidates->0->>'taste_boost_shadow')::float AS boost_shadow,
  (d.candidates->0->>'nlikes')::int AS nlikes,
  c.views,
  c.forwards,
  round(1000.0 * c.forwards / nullif(c.views, 0), 1) AS f1k_live,
  round(extract(epoch from (now() - c.created_at)) / 3600.0, 1) AS age_h
FROM crossposting_decision_log d
JOIN crossposting c
  ON c.channel = d.channel AND c.meme_id = d.picked_meme_id
WHERE d.channel = 'tgchannelru'
  AND d.decided_at > now() - interval '14 days'
  AND d.score_version = 4
ORDER BY d.decided_at DESC
LIMIT 30;

-- 3) When mature: n_taste vs 24h f1k (run after >=20 v4 mature with field)
WITH decided AS (
  SELECT
    d.picked_meme_id AS meme_id,
    d.decided_at,
    COALESCE((d.candidates->0->>'n_taste_likes')::int, 0) AS n_taste
  FROM crossposting_decision_log d
  WHERE d.channel = 'tgchannelru'
    AND d.score_version = 4
    AND d.decided_at > now() - interval '30 days'
),
labeled AS (
  SELECT DISTINCT ON (c.meme_id)
    c.meme_id,
    d.n_taste,
    s.views,
    s.forwards,
    1000.0 * s.forwards / nullif(s.views, 0) AS f1k
  FROM decided d
  JOIN crossposting c
    ON c.channel = 'tgchannelru' AND c.meme_id = d.meme_id
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = c.telegram_message_id
   AND s.snapshot_at BETWEEN c.created_at + interval '18 hours'
                         AND c.created_at + interval '36 hours'
   AND s.views > 0
  WHERE c.created_at < now() - interval '36 hours'
  ORDER BY c.meme_id, abs(extract(epoch from (
    s.snapshot_at - (c.created_at + interval '24 hours')
  )))
)
SELECT
  CASE WHEN n_taste >= 1 THEN 'taste_ge1' ELSE 'taste_0' END AS bucket,
  count(*) AS n,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(forwards)::numeric, 2) AS avg_fwd
FROM labeled
GROUP BY 1
ORDER BY 1;

-- 4) H7 falsifiable: among n_taste>=1, top half of n_taste vs bottom half
-- Pass (2026-08-24): top_half avg_f1k > bottom_half AND n_taste_ge1 >= 20
WITH decided AS (
  SELECT
    d.picked_meme_id AS meme_id,
    COALESCE((d.candidates->0->>'n_taste_likes')::int, 0) AS n_taste
  FROM crossposting_decision_log d
  WHERE d.channel = 'tgchannelru'
    AND d.score_version = 4
    AND d.decided_at > now() - interval '30 days'
),
labeled AS (
  SELECT DISTINCT ON (c.meme_id)
    c.meme_id,
    d.n_taste,
    1000.0 * s.forwards / nullif(s.views, 0) AS f1k
  FROM decided d
  JOIN crossposting c
    ON c.channel = 'tgchannelru' AND c.meme_id = d.meme_id
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = c.telegram_message_id
   AND s.snapshot_at BETWEEN c.created_at + interval '18 hours'
                         AND c.created_at + interval '36 hours'
   AND s.views > 0
  WHERE c.created_at < now() - interval '36 hours'
    AND d.n_taste >= 1
  ORDER BY c.meme_id, abs(extract(epoch from (
    s.snapshot_at - (c.created_at + interval '24 hours')
  )))
),
ranked AS (
  SELECT
    *,
    ntile(2) OVER (ORDER BY n_taste, meme_id) AS half
  FROM labeled
)
SELECT
  CASE half WHEN 2 THEN 'top_half_n_taste' ELSE 'bottom_half_n_taste' END AS bucket,
  count(*) AS n,
  round(avg(n_taste)::numeric, 2) AS avg_n_taste,
  round(avg(f1k)::numeric, 2) AS avg_f1k
FROM ranked
GROUP BY half
ORDER BY half;
