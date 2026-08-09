-- Offline spot-check: RU channel 24h label distribution + hit rate
-- Full residual analysis: docs/analyst/readouts/2026-08-09-crosspost-meme-level-offline.md
--
-- HIT := f1k >= p75_120d (~30.9 as of 2026-08-09) OR forwards >= 12

\set ON_ERROR_STOP on

-- 1) 120d label quantiles
WITH posts AS (
  SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '120 days'
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
    AND cp.telegram_message_id IS NOT NULL
),
labels AS (
  SELECT DISTINCT ON (p.meme_id)
    s.views, s.forwards,
    1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
  FROM posts p
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = p.telegram_message_id
   AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                         AND p.posted_at + interval '36 hours'
   AND s.views > 0
  ORDER BY p.meme_id,
    abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
)
SELECT
  count(*) AS n,
  round(percentile_cont(0.25) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p25,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p50,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p75,
  round(percentile_cont(0.90) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p90,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY forwards)::numeric, 2) AS fwd_p50,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY forwards)::numeric, 2) AS fwd_p75
FROM labels;

-- 2) Hit rate (update p75 threshold when quantiles drift)
WITH posts AS (
  SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '30 days'
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
),
labels AS (
  SELECT DISTINCT ON (p.meme_id)
    s.forwards,
    1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
  FROM posts p
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = p.telegram_message_id
   AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                         AND p.posted_at + interval '36 hours'
   AND s.views > 0
  ORDER BY p.meme_id,
    abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
)
SELECT
  count(*) AS n_30d,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(
    100.0 * count(*) FILTER (WHERE f1k >= 30.9 OR forwards >= 12)
    / nullif(count(*), 0),
    1
  ) AS hit_rate_pct
FROM labels;
