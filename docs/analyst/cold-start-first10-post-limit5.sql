-- Cold-start first-10 readout (pre vs post queue limit=5 fix)
-- Fix deployed: 2026-08-11 ~19:42 UTC (PR #351)
-- Cohort: users whose *first-ever* user_meme_reaction.sent_at is in the last 7 days.
-- Run via analyst_readonly. statement_timeout 60s recommended.
--
-- Companion readout: docs/analyst/readouts/2026-08-13-cold-start-first10-post-limit5.md

\set fix_at '2026-08-11 19:42:00'

-- 1) Cohort sizes
WITH first_send AS (
  SELECT user_id, MIN(sent_at) AS first_sent_at
  FROM user_meme_reaction
  GROUP BY user_id
),
cohort AS (
  SELECT
    user_id,
    first_sent_at,
    CASE
      WHEN first_sent_at >= TIMESTAMP :'fix_at' THEN 'post_fix'
      ELSE 'pre_fix'
    END AS period
  FROM first_send
  WHERE first_sent_at >= now() - interval '7 days'
)
SELECT period, COUNT(*) AS n_users, MIN(first_sent_at), MAX(first_sent_at)
FROM cohort
GROUP BY 1
ORDER BY 1;

-- 2) First-10 overall skip/like
WITH first_send AS (
  SELECT user_id, MIN(sent_at) AS first_sent_at
  FROM user_meme_reaction
  GROUP BY user_id
),
cohort AS (
  SELECT
    user_id,
    first_sent_at,
    CASE
      WHEN first_sent_at >= TIMESTAMP :'fix_at' THEN 'post_fix'
      ELSE 'pre_fix'
    END AS period
  FROM first_send
  WHERE first_sent_at >= now() - interval '7 days'
),
ranked AS (
  SELECT
    R.user_id,
    R.reaction_id,
    R.recommended_by,
    c.period,
    row_number() OVER (PARTITION BY R.user_id ORDER BY R.sent_at, R.meme_id) AS rn
  FROM user_meme_reaction R
  JOIN cohort c ON c.user_id = R.user_id
),
f10 AS (SELECT * FROM ranked WHERE rn <= 10)
SELECT
  period,
  COUNT(DISTINCT user_id) AS users,
  COUNT(*) AS sends,
  COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
  COUNT(*) FILTER (WHERE reaction_id = 2) AS skips,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE reaction_id = 2)
    / NULLIF(COUNT(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS skip_pct
FROM f10
GROUP BY period
ORDER BY period;

-- 3) Engine mix in first-10
WITH first_send AS (
  SELECT user_id, MIN(sent_at) AS first_sent_at
  FROM user_meme_reaction
  GROUP BY user_id
),
cohort AS (
  SELECT
    user_id,
    CASE
      WHEN first_sent_at >= TIMESTAMP :'fix_at' THEN 'post_fix'
      ELSE 'pre_fix'
    END AS period
  FROM first_send
  WHERE first_sent_at >= now() - interval '7 days'
),
ranked AS (
  SELECT
    R.user_id,
    R.reaction_id,
    R.recommended_by,
    c.period,
    row_number() OVER (PARTITION BY R.user_id ORDER BY R.sent_at, R.meme_id) AS rn
  FROM user_meme_reaction R
  JOIN cohort c ON c.user_id = R.user_id
),
f10 AS (SELECT * FROM ranked WHERE rn <= 10)
SELECT
  period,
  recommended_by,
  COUNT(*) AS n,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE reaction_id = 2)
    / NULLIF(COUNT(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS skip_pct
FROM f10
GROUP BY 1, 2
ORDER BY 1, n DESC;

-- 4) pos 1-5 vs 6-10 engines (expect adapt in 6-10 after a working fix)
WITH first_send AS (
  SELECT user_id, MIN(sent_at) AS first_sent_at
  FROM user_meme_reaction
  GROUP BY user_id
),
cohort AS (
  SELECT
    user_id,
    CASE
      WHEN first_sent_at >= TIMESTAMP :'fix_at' THEN 'post_fix'
      ELSE 'pre_fix'
    END AS period
  FROM first_send
  WHERE first_sent_at >= now() - interval '7 days'
),
ranked AS (
  SELECT
    R.user_id,
    R.reaction_id,
    R.recommended_by,
    c.period,
    row_number() OVER (PARTITION BY R.user_id ORDER BY R.sent_at, R.meme_id) AS rn
  FROM user_meme_reaction R
  JOIN cohort c ON c.user_id = R.user_id
),
f10 AS (SELECT * FROM ranked WHERE rn <= 10)
SELECT
  period,
  CASE WHEN rn <= 5 THEN 'pos_1_5' ELSE 'pos_6_10' END AS band,
  recommended_by,
  COUNT(*) AS n,
  ROUND(
    100.0 * COUNT(*) FILTER (WHERE reaction_id = 2)
    / NULLIF(COUNT(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS skip_pct
FROM f10
GROUP BY 1, 2, 3
ORDER BY 1, 2, n DESC;
