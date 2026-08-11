-- Bot→channel lab: label distributions (RU image, mature 18–36h snap)
\set ON_ERROR_STOP on

WITH posts AS (
  SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id, cp.score_version
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '180 days'
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
    AND cp.telegram_message_id IS NOT NULL
),
labels AS (
  SELECT DISTINCT ON (p.meme_id)
    p.meme_id, p.posted_at, p.score_version,
    s.views, s.forwards, s.reactions, s.comments,
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
  min(posted_at)::date AS first_d,
  max(posted_at)::date AS last_d,
  round(percentile_cont(0.25) WITHIN GROUP (ORDER BY views)::numeric, 1) AS views_p25,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY views)::numeric, 1) AS views_p50,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY views)::numeric, 1) AS views_p75,
  round(percentile_cont(0.25) WITHIN GROUP (ORDER BY forwards)::numeric, 2) AS fwd_p25,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY forwards)::numeric, 2) AS fwd_p50,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY forwards)::numeric, 2) AS fwd_p75,
  round(percentile_cont(0.25) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p25,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p50,
  round(percentile_cont(0.75) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p75,
  round(percentile_cont(0.90) WITHIN GROUP (ORDER BY f1k)::numeric, 2) AS f1k_p90,
  round(avg(reactions)::numeric, 2) AS avg_react,
  round(avg(comments)::numeric, 2) AS avg_comments,
  round(
    100.0 * count(*) FILTER (
      WHERE f1k >= percentile_cont(0.75) WITHIN GROUP (ORDER BY f1k)
         OR forwards >= 12
    ) / nullif(count(*), 0),
    1
  ) AS hit_rate_train_p75_or_fwd12
FROM labels;

-- By score_version (last 180d mature)
WITH posts AS (
  SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id, cp.score_version
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  WHERE cp.channel = 'tgchannelru'
    AND cp.created_at > now() - interval '180 days'
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
    AND cp.telegram_message_id IS NOT NULL
),
labels AS (
  SELECT DISTINCT ON (p.meme_id)
    p.score_version, s.views, s.forwards, s.reactions,
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
  score_version,
  count(*) AS n,
  round(avg(views)::numeric, 1) AS avg_views,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(reactions)::numeric, 2) AS avg_react
FROM labels
GROUP BY 1
ORDER BY 1;
