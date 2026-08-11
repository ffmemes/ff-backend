-- Coverage of pre-post bot / premium (descriptive)
\set ON_ERROR_STOP on

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
labeled AS (
  SELECT DISTINCT ON (p.meme_id)
    p.meme_id, p.posted_at,
    s.forwards, 1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
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
    count(*) AS pre_reacts,
    count(*) FILTER (WHERE umr.reaction_id = 1 AND coalesce(ut.is_premium, false)) AS pre_premium_likes
  FROM labeled l
  JOIN user_meme_reaction umr
    ON umr.meme_id = l.meme_id AND umr.reacted_at < l.posted_at
  LEFT JOIN user_tg ut ON ut.id = umr.user_id
  GROUP BY l.meme_id
)
SELECT
  count(*) AS n_labeled,
  round(100.0 * count(*) FILTER (WHERE coalesce(pre_likes, 0) >= 1) / count(*), 1) AS pct_pre_likes_ge1,
  round(100.0 * count(*) FILTER (WHERE coalesce(pre_likes, 0) >= 5) / count(*), 1) AS pct_pre_likes_ge5,
  round(100.0 * count(*) FILTER (WHERE coalesce(pre_likes, 0) >= 20) / count(*), 1) AS pct_pre_likes_ge20,
  round(100.0 * count(*) FILTER (WHERE coalesce(pre_premium_likes, 0) >= 1) / count(*), 1) AS pct_any_premium_like,
  round(avg(CASE WHEN pre_likes > 0 THEN pre_premium_likes::float / pre_likes END)::numeric, 3)
    AS avg_premium_like_frac,
  round(avg(coalesce(pre_likes, 0))::numeric, 1) AS avg_pre_likes,
  round(avg(coalesce(pre_reacts, 0))::numeric, 1) AS avg_pre_reacts
FROM labeled l
LEFT JOIN pre ON pre.meme_id = l.meme_id;

-- Post-channel bot likes
WITH posts AS (
  SELECT meme_id, created_at AS posted_at
  FROM crossposting
  WHERE channel = 'tgchannelru'
    AND created_at > now() - interval '180 days'
)
SELECT
  count(DISTINCT p.meme_id) AS n_posts,
  count(*) FILTER (WHERE umr.reacted_at < p.posted_at AND umr.reaction_id = 1) AS pre_likes_sum,
  count(*) FILTER (WHERE umr.reacted_at >= p.posted_at AND umr.reaction_id = 1) AS post_likes_sum
FROM posts p
JOIN user_meme_reaction umr ON umr.meme_id = p.meme_id;
