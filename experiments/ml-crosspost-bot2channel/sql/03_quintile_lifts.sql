-- Descriptive quintile lifts (full 180d; not a train/test claim)
-- Run as a whole; four result sets.
\set ON_ERROR_STOP on

CREATE TEMP TABLE _lab_feat ON COMMIT DROP AS
WITH posts AS (
  SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
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
    p.meme_id, p.posted_at,
    s.views, s.forwards, s.reactions,
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
),
pre AS (
  SELECT
    l.meme_id,
    count(*) FILTER (WHERE umr.reaction_id = 1) AS pre_likes,
    count(*) FILTER (WHERE umr.reaction_id = 2) AS pre_dislikes,
    count(*) FILTER (WHERE umr.reaction_id = 1 AND coalesce(ut.is_premium, false)) AS pre_premium_likes
  FROM labels l
  JOIN user_meme_reaction umr
    ON umr.meme_id = l.meme_id AND umr.reacted_at < l.posted_at
  LEFT JOIN user_tg ut ON ut.id = umr.user_id
  GROUP BY l.meme_id
)
SELECT
  l.meme_id, l.views, l.forwards, l.reactions, l.f1k,
  coalesce(p.pre_likes, 0) AS pre_likes,
  coalesce(p.pre_dislikes, 0) AS pre_dislikes,
  CASE WHEN coalesce(p.pre_likes, 0) + coalesce(p.pre_dislikes, 0) > 0
    THEN p.pre_likes::float / (p.pre_likes + p.pre_dislikes) END AS pre_lr,
  CASE WHEN coalesce(p.pre_likes, 0) > 0
    THEN p.pre_premium_likes::float / p.pre_likes END AS premium_frac,
  ln(coalesce(p.pre_likes, 0) + 1) AS pre_ln_likes
FROM labels l
LEFT JOIN pre p ON p.meme_id = l.meme_id;

SELECT 'pre_likes' AS driver, q5, count(*) AS n,
  round(avg(pre_likes)::numeric, 1) AS avg_driver,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(avg(views)::numeric, 1) AS avg_views,
  round(avg(reactions)::numeric, 2) AS avg_react
FROM (SELECT *, ntile(5) OVER (ORDER BY pre_likes) AS q5 FROM _lab_feat) t
GROUP BY q5 ORDER BY q5;

SELECT 'pre_lr' AS driver, q5, count(*) AS n,
  round(avg(pre_lr)::numeric, 3) AS avg_driver,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(avg(views)::numeric, 1) AS avg_views,
  round(avg(reactions)::numeric, 2) AS avg_react
FROM (SELECT *, ntile(5) OVER (ORDER BY pre_lr) AS q5 FROM _lab_feat WHERE pre_lr IS NOT NULL) t
GROUP BY q5 ORDER BY q5;

SELECT 'premium_frac' AS driver, q5, count(*) AS n,
  round(avg(premium_frac)::numeric, 3) AS avg_driver,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(avg(views)::numeric, 1) AS avg_views,
  round(avg(reactions)::numeric, 2) AS avg_react
FROM (SELECT *, ntile(5) OVER (ORDER BY premium_frac) AS q5 FROM _lab_feat WHERE premium_frac IS NOT NULL) t
GROUP BY q5 ORDER BY q5;

SELECT 'pre_ln_likes' AS driver, q5, count(*) AS n,
  round(avg(pre_ln_likes)::numeric, 2) AS avg_driver,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(avg(views)::numeric, 1) AS avg_views,
  round(avg(reactions)::numeric, 2) AS avg_react
FROM (SELECT *, ntile(5) OVER (ORDER BY pre_ln_likes) AS q5 FROM _lab_feat) t
GROUP BY q5 ORDER BY q5;
