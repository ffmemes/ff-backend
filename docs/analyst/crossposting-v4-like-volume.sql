-- RU crosspost score_version=4 (meme like volume) readout
-- HIT := f1k >= 30.9 OR forwards >= 12  (refresh p75 from 120d quantiles periodically)
-- Compare score_version 2 (control historical) vs 4 (like-volume) after deploy 2026-08-10+

\set ON_ERROR_STOP on

-- 1) Volume by score_version (30d)
SELECT
  score_version,
  count(*) AS posts,
  min(created_at)::date AS first_d,
  max(created_at)::date AS last_d
FROM crossposting
WHERE channel = 'tgchannelru'
  AND created_at > now() - interval '30 days'
GROUP BY 1
ORDER BY 1;

-- 2) Mature ~24h outcomes by score_version (image)
WITH posts AS (
  SELECT cp.meme_id, cp.created_at, cp.score_version, cp.telegram_message_id
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '30 days'
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
    AND cp.telegram_message_id IS NOT NULL
),
snap AS (
  SELECT DISTINCT ON (p.meme_id)
    p.score_version,
    s.views,
    s.forwards,
    1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
  FROM posts p
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = p.telegram_message_id
   AND s.snapshot_at BETWEEN p.created_at + interval '18 hours'
                         AND p.created_at + interval '36 hours'
   AND s.views > 0
  ORDER BY p.meme_id,
    abs(extract(epoch from (s.snapshot_at - (p.created_at + interval '24 hours'))))
)
SELECT
  score_version,
  count(*) AS n,
  round(avg(views)::numeric, 1) AS avg_views,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS p50_f1k,
  round(
    100.0 * count(*) FILTER (WHERE f1k >= 30.9 OR forwards >= 12) / nullif(count(*), 0),
    1
  ) AS hit_rate_pct
FROM snap
GROUP BY 1
ORDER BY 1;

-- 3) Decision log: like_volume_factor present on v4
SELECT
  score_version,
  count(*) AS decisions,
  count(*) FILTER (
    WHERE (candidates->0->>'like_volume_enabled')::boolean IS TRUE
  ) AS top1_like_vol_on,
  round(avg((candidates->0->>'like_volume_factor')::float)::numeric, 3) AS avg_top1_like_vol
FROM crossposting_decision_log
WHERE channel = 'tgchannelru'
  AND decided_at > now() - interval '14 days'
GROUP BY 1
ORDER BY 1;
