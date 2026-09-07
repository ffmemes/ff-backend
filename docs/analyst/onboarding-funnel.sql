-- Onboarding funnel + first-meme quality
--
-- Companion: docs/analyst/readouts/2026-09-07-onboarding-and-dormant-blast.md
-- Hypotheses: docs/growth/HYPOTHESES.md H9 / H10 / H11
--
-- Growth bar for any onboarding change:
--   1) less leaky: first-tap %, first-like %, reached-5
--   2) k-factor: unique non-self share clicks / new-user invites from the cohort
--
-- Pitfall: user_stats.nmemes_sent stays 0 until a reaction. Count sends from
-- user_meme_reaction, not stats.
--
-- Run: psql "$ANALYST_DATABASE_URL" -f docs/analyst/onboarding-funnel.sql
-- Keep statement_timeout; 90d cohort is small.

\set ON_ERROR_STOP on

-- 1) 90d new-user funnel
WITH cohort AS (
  SELECT u.id, u.created_at, u.blocked_bot_at
  FROM "user" u
  WHERE u.type = 'user'
    AND u.created_at >= now() - interval '90 days'
),
first_dl AS (
  SELECT DISTINCT ON (l.user_id)
    l.user_id,
    l.deep_link
  FROM user_deep_link_log l
  JOIN cohort c ON c.id = l.user_id
  ORDER BY l.user_id, l.created_at
),
agg AS (
  SELECT
    r.user_id,
    COUNT(*) AS n_sends,
    MIN(r.sent_at) AS first_sent,
    MIN(r.reacted_at) FILTER (WHERE r.reaction_id IS NOT NULL) AS first_reacted,
    (ARRAY_AGG(r.recommended_by ORDER BY r.sent_at))[1] AS first_engine,
    (ARRAY_AGG(r.reaction_id ORDER BY r.reacted_at)
      FILTER (WHERE r.reaction_id IS NOT NULL))[1] AS first_rid
  FROM user_meme_reaction r
  JOIN cohort c ON c.id = r.user_id
  GROUP BY r.user_id
),
has_lang AS (
  SELECT DISTINCT user_id FROM user_language
)
SELECT
  COUNT(*) AS n_registered,
  COUNT(a.first_sent) AS got_meme,
  COUNT(a.first_reacted) AS ever_reacted,
  COUNT(*) FILTER (
    WHERE a.first_reacted IS NOT NULL
      AND a.first_reacted < a.first_sent + interval '1 hour'
  ) AS reacted_1h,
  COUNT(*) FILTER (
    WHERE a.first_sent IS NOT NULL AND a.first_reacted IS NULL
  ) AS got_meme_never_reacted,
  COUNT(*) FILTER (WHERE a.first_sent IS NULL) AS never_got_meme,
  COUNT(*) FILTER (WHERE hl.user_id IS NULL) AS no_lang,
  COUNT(*) FILTER (
    WHERE hl.user_id IS NULL AND c.blocked_bot_at IS NULL
  ) AS no_lang_alive,
  ROUND(
    100.0 * COUNT(a.first_reacted) / NULLIF(COUNT(a.first_sent), 0),
    1
  ) AS first_tap_pct_of_got_meme
FROM cohort c
LEFT JOIN agg a ON a.user_id = c.id
LEFT JOIN has_lang hl ON hl.user_id = c.id;

-- 2) Entry path (empty start vs share vs channel)
WITH cohort AS (
  SELECT u.id, u.created_at, u.blocked_bot_at
  FROM "user" u
  WHERE u.type = 'user'
    AND u.created_at >= now() - interval '90 days'
),
first_dl AS (
  SELECT DISTINCT ON (l.user_id)
    l.user_id,
    l.deep_link
  FROM user_deep_link_log l
  JOIN cohort c ON c.id = l.user_id
  ORDER BY l.user_id, l.created_at
),
agg AS (
  SELECT
    r.user_id,
    MIN(r.sent_at) AS first_sent,
    MIN(r.reacted_at) FILTER (WHERE r.reaction_id IS NOT NULL) AS first_reacted,
    (ARRAY_AGG(r.reaction_id ORDER BY r.reacted_at)
      FILTER (WHERE r.reaction_id IS NOT NULL))[1] AS first_rid
  FROM user_meme_reaction r
  JOIN cohort c ON c.id = r.user_id
  GROUP BY r.user_id
)
SELECT
  CASE
    WHEN d.deep_link IS NULL OR d.deep_link = '' THEN 'empty_start'
    WHEN d.deep_link ~ '^(s|m)_' THEN 'share_meme'
    WHEN d.deep_link LIKE 'sc_%' THEN 'channel_sc'
    ELSE 'other'
  END AS entry,
  COUNT(*) AS n,
  COUNT(a.first_sent) AS got_meme,
  COUNT(a.first_reacted) AS ever_reacted,
  ROUND(100.0 * COUNT(a.first_reacted) / NULLIF(COUNT(*), 0), 1)
    AS pct_reacted_of_reg,
  COUNT(*) FILTER (WHERE a.first_rid = 1) AS first_like,
  COUNT(*) FILTER (WHERE a.first_rid = 2) AS first_skip,
  ROUND(
    PERCENTILE_CONT(0.5) WITHIN GROUP (
      ORDER BY EXTRACT(EPOCH FROM (a.first_sent - c.created_at))
    )::numeric,
    1
  ) AS p50_sec_to_first_meme
FROM cohort c
LEFT JOIN first_dl d ON d.user_id = c.id
LEFT JOIN agg a ON a.user_id = c.id
GROUP BY 1
ORDER BY n DESC;

-- 3) First-meme age (cold_start_explore only) vs first like
WITH cohort AS (
  SELECT u.id
  FROM "user" u
  WHERE u.type = 'user'
    AND u.created_at >= now() - interval '90 days'
),
first_meme AS (
  SELECT DISTINCT ON (r.user_id)
    r.user_id,
    r.meme_id,
    r.sent_at,
    r.recommended_by,
    r.reaction_id
  FROM user_meme_reaction r
  JOIN cohort c ON c.id = r.user_id
  ORDER BY r.user_id, r.sent_at
)
SELECT
  CASE
    WHEN m.created_at > fm.sent_at - interval '7 days' THEN '0-7d'
    WHEN m.created_at > fm.sent_at - interval '30 days' THEN '7-30d'
    WHEN m.created_at > fm.sent_at - interval '90 days' THEN '30-90d'
    ELSE '90d+'
  END AS meme_age,
  COUNT(*) AS n,
  COUNT(*) FILTER (WHERE fm.reaction_id IS NOT NULL) AS reacted,
  COUNT(*) FILTER (WHERE fm.reaction_id = 1) AS liked,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE fm.reaction_id = 1) / NULLIF(COUNT(*), 0),
    1
  ) AS first_like_pct
FROM first_meme fm
JOIN meme m ON m.id = fm.meme_id
WHERE fm.recommended_by = 'cold_start_explore'
GROUP BY 1
ORDER BY MIN(EXTRACT(EPOCH FROM (fm.sent_at - m.created_at)));

-- 4) All-time never-reacted buckets (type user + blocked_bot)
WITH reacted AS (
  SELECT DISTINCT user_id
  FROM user_meme_reaction
  WHERE reaction_id IS NOT NULL
),
got_meme AS (
  SELECT
    user_id,
    COUNT(*) AS n_sends,
    MIN(sent_at) AS first_sent
  FROM user_meme_reaction
  GROUP BY user_id
)
SELECT
  CASE
    WHEN g.user_id IS NULL
      AND COALESCE(u.blocked_bot_at IS NOT NULL, u.type = 'blocked_bot')
      THEN 'blocked_no_meme'
    WHEN g.user_id IS NULL THEN 'alive_no_meme'
    WHEN COALESCE(u.blocked_bot_at IS NOT NULL, u.type = 'blocked_bot')
      THEN 'blocked_got_meme_silent'
    ELSE 'alive_got_meme_silent'
  END AS bucket,
  COUNT(*) AS n,
  COUNT(*) FILTER (WHERE g.n_sends = 1) AS n_1,
  COUNT(*) FILTER (WHERE g.n_sends BETWEEN 2 AND 5) AS n_2_5,
  COUNT(*) FILTER (WHERE g.n_sends >= 6) AS n_6plus,
  COUNT(*) FILTER (
    WHERE u.blocked_bot_at IS NOT NULL
      AND u.blocked_bot_at < u.created_at + interval '5 minutes'
  ) AS block_5m_from_start,
  COUNT(*) FILTER (
    WHERE g.first_sent IS NOT NULL
      AND u.blocked_bot_at IS NOT NULL
      AND u.blocked_bot_at < g.first_sent + interval '5 minutes'
  ) AS block_5m_after_first
FROM "user" u
LEFT JOIN reacted r ON r.user_id = u.id
LEFT JOIN got_meme g ON g.user_id = u.id
WHERE u.type IN ('user', 'blocked_bot')
  AND r.user_id IS NULL
GROUP BY 1
ORDER BY n DESC;

-- 5) H10 assignment + first-tap by variant (true-new, last 14d)
WITH assigned AS (
  SELECT
    a.user_id,
    a.variant,
    a.assigned_at
  FROM experiment_assignment a
  WHERE a.experiment_id = 'cold_start_fresh_viral_v1'
    AND a.assigned_at >= now() - interval '14 days'
),
first_meme AS (
  SELECT DISTINCT ON (r.user_id)
    r.user_id,
    r.recommended_by,
    r.reaction_id,
    r.sent_at
  FROM user_meme_reaction r
  JOIN assigned a ON a.user_id = r.user_id
  ORDER BY r.user_id, r.sent_at
)
SELECT
  a.variant,
  COUNT(*) AS n_assigned,
  COUNT(f.user_id) AS got_meme,
  COUNT(*) FILTER (WHERE f.reaction_id IS NOT NULL) AS tapped,
  COUNT(*) FILTER (WHERE f.reaction_id = 1) AS first_like,
  COUNT(*) FILTER (
    WHERE f.recommended_by LIKE 'cold_start_explore_fresh%'
  ) AS fresh_first_meme,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE f.reaction_id IS NOT NULL)
    / NULLIF(COUNT(f.user_id), 0),
    1
  ) AS first_tap_pct
FROM assigned a
LEFT JOIN first_meme f ON f.user_id = a.user_id
GROUP BY 1
ORDER BY 1;
