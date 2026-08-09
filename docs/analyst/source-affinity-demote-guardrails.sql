-- Soft-demote post-deploy guardrails (PR #340)
--
-- Policy:
--   demote ON  — score ×0.15 when ndislikes > nlikes and n>=5
--   hard block OFF — only opt-in 3× ratio + n>=15
--
-- Goals:
--   1) Feed still producing volume (no empty-queue spike)
--   2) Like rate stable vs pre-deploy baseline window
--   3) Strong-hate sources rare; majority-dislike common (must stay soft)

\set ON_ERROR_STOP on

-- 1) Hourly send volume + like rate (last 72h)
SELECT
  date_trunc('hour', sent_at) AS hour_utc,
  count(*) AS sends,
  count(DISTINCT user_id) AS active_senders,
  count(*) FILTER (WHERE reaction_id IS NOT NULL) AS reactions,
  round(
    100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS like_rate_pct
FROM user_meme_reaction
WHERE sent_at > now() - interval '72 hours'
GROUP BY 1
ORDER BY 1 DESC;

-- 2) Users with very few recent sends but recent activity
--    (weak empty-queue proxy: reacted recently but almost no new sends)
WITH recent_reactors AS (
  SELECT user_id, max(reacted_at) AS last_react
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '24 hours'
  GROUP BY 1
),
recent_sends AS (
  SELECT user_id, count(*) AS sends_24h
  FROM user_meme_reaction
  WHERE sent_at > now() - interval '24 hours'
  GROUP BY 1
)
SELECT
  count(*) AS reactors_24h,
  count(*) FILTER (WHERE coalesce(s.sends_24h, 0) < 3) AS low_send_reactors,
  round(
    100.0 * count(*) FILTER (WHERE coalesce(s.sends_24h, 0) < 3) / NULLIF(count(*), 0),
    2
  ) AS pct_low_send
FROM recent_reactors r
LEFT JOIN recent_sends s ON s.user_id = r.user_id;

-- 3) Broadcast label live after deploy
SELECT
  recommended_by,
  count(*) AS n_sent_24h,
  min(sent_at) AS first_seen,
  max(sent_at) AS last_seen
FROM user_meme_reaction
WHERE sent_at > now() - interval '24 hours'
  AND recommended_by LIKE 'broadcast%'
GROUP BY 1
ORDER BY 2 DESC;

-- 4) Engine mix still diversified (demote should not collapse to one engine)
SELECT
  recommended_by,
  count(*) AS n_sent_24h,
  round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS pct
FROM user_meme_reaction
WHERE sent_at > now() - interval '24 hours'
GROUP BY 1
ORDER BY 2 DESC
LIMIT 25;
