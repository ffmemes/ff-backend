-- =============================================================================
-- ANALYST AGENT: SQL METRICS REFERENCE
-- =============================================================================
-- Usage: Analyst agent runs these queries against prod DB via ANALYST_DATABASE_URL
-- Connection: read-only user (analyst_readonly), statement_timeout = 30s
-- Reference: CLAUDE.md "Production Health Checklist" for base health query
-- =============================================================================


-- =============================================
-- SECTION: HEALTH CHECK (run every heartbeat)
-- =============================================
-- Same query as CLAUDE.md Production Health Checklist
-- Expected healthy: new_memes > 100, ok_pct ~90-96%, active_users > 100,
--                   reactions > 5000, stats updated within last 15 min

SELECT
  (SELECT count(*) FROM meme WHERE created_at > now() - interval '24 hours') AS new_memes_24h,
  (SELECT round(100.0 * count(*) FILTER (WHERE status = 'ok') / NULLIF(count(*), 0))
   FROM meme WHERE created_at > now() - interval '24 hours') AS ok_pct,
  (SELECT count(DISTINCT user_id) FROM user_meme_reaction
   WHERE reacted_at > now() - interval '24 hours') AS active_users_24h,
  (SELECT count(*) FROM user_meme_reaction
   WHERE reacted_at > now() - interval '24 hours') AS reactions_24h,
  (SELECT max(updated_at) FROM user_stats) AS user_stats_updated,
  (SELECT max(updated_at) FROM meme_stats) AS meme_stats_updated;


-- =============================================
-- SECTION: NORTH STAR — SESSION LENGTH
-- =============================================
-- Session = gap > 30 min between reactions
-- North star metric: median memes per session (higher = better)

WITH sessions AS (
  SELECT
    user_id,
    reacted_at,
    CASE
      WHEN reacted_at - lag(reacted_at) OVER (PARTITION BY user_id ORDER BY reacted_at)
           > interval '30 minutes'
      THEN 1 ELSE 0
    END AS new_session
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '7 days'
),
session_ids AS (
  SELECT
    user_id,
    reacted_at,
    sum(new_session) OVER (PARTITION BY user_id ORDER BY reacted_at) AS session_id
  FROM sessions
),
session_lengths AS (
  SELECT
    user_id,
    session_id,
    count(*) AS memes_in_session
  FROM session_ids
  GROUP BY user_id, session_id
  HAVING count(*) >= 2  -- ignore single-meme "sessions"
)
SELECT
  percentile_cont(0.5) WITHIN GROUP (ORDER BY memes_in_session) AS median_session_length,
  round(avg(memes_in_session), 1) AS avg_session_length,
  count(*) AS total_sessions,
  count(DISTINCT user_id) AS unique_users
FROM session_lengths;


-- =============================================
-- SECTION: GROWTH — SHARES & REFERRALS
-- =============================================
-- Share tracking: user clicks link under meme → logged in user_deep_link_log
-- This is the only proxy for "shares" (TG Bot API doesn't expose forward counts)

SELECT
  count(*) AS deep_link_clicks_7d,
  count(DISTINCT user_id) AS unique_clickers_7d,
  count(*) FILTER (WHERE deep_link LIKE 'meme_%') AS meme_share_clicks_7d
FROM user_deep_link_log
WHERE created_at > now() - interval '7 days';

-- Top shared memes (by invited_count in meme_stats)
SELECT m.id, m.type, ms.invited_count, ms.nlikes, ms.ndislikes, ms.lr_smoothed,
       ms.nmemes_sent, src.url AS source_url
FROM meme_stats ms
JOIN meme m ON m.id = ms.meme_id
JOIN meme_source src ON src.id = m.meme_source_id
WHERE ms.invited_count > 0
ORDER BY ms.invited_count DESC
LIMIT 20;


-- =============================================
-- SECTION: ENGINE PERFORMANCE
-- =============================================
-- Per-engine like rate and volume (last 7 days)
-- Key: recommended_by = engine name from candidates.py

SELECT
  recommended_by AS engine,
  count(*) AS total_sent,
  count(*) FILTER (WHERE reaction_id = 1) AS likes,
  count(*) FILTER (WHERE reaction_id = 2) AS dislikes,
  count(*) FILTER (WHERE reaction_id IS NULL) AS unreacted,
  round(100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0), 1) AS like_rate_pct
FROM user_meme_reaction
WHERE sent_at > now() - interval '7 days'
GROUP BY recommended_by
ORDER BY total_sent DESC;

-- Per-engine SESSION CONTINUATION RATE (North Star proxy!)
-- Did the user keep scrolling after seeing a meme from this engine?
-- THIS IS MORE IMPORTANT THAN LIKE RATE for session length optimization.

WITH reactions AS (
  SELECT
    user_id, meme_id, recommended_by, sent_at, reaction_id,
    LEAD(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at) AS next_sent_at
  FROM user_meme_reaction
  WHERE sent_at > now() - interval '7 days'
)
SELECT
  recommended_by AS engine,
  count(*) AS total,
  count(*) FILTER (WHERE next_sent_at IS NOT NULL
    AND next_sent_at - sent_at < interval '30 minutes') AS continued,
  round(100.0 * count(*) FILTER (WHERE next_sent_at IS NOT NULL
    AND next_sent_at - sent_at < interval '30 minutes')
    / NULLIF(count(*), 0), 1) AS continuation_rate,
  round(100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0), 1) AS like_rate
FROM reactions
GROUP BY recommended_by
ORDER BY continuation_rate DESC;


-- =============================================
-- SECTION: USER ENGAGEMENT
-- =============================================
-- DAU / WAU / MAU
-- IMPORTANT: Must filter by reacted_at to use index. Without WHERE clause,
-- this query scans all 22M+ rows and times out at 30s.

SELECT
  count(DISTINCT user_id) FILTER (
    WHERE reacted_at > now() - interval '1 day'
  ) AS dau,
  count(DISTINCT user_id) FILTER (
    WHERE reacted_at > now() - interval '7 days'
  ) AS wau,
  count(DISTINCT user_id) AS mau
FROM user_meme_reaction
WHERE reacted_at > now() - interval '30 days';

-- New users (last 7 days)
SELECT
  date_trunc('day', created_at) AS day,
  count(*) AS new_users
FROM "user"
WHERE created_at > now() - interval '7 days'
GROUP BY 1
ORDER BY 1;


-- =============================================
-- SECTION: RETENTION
-- =============================================
-- D1 and D7 retention for users who joined in last 30 days

WITH cohort AS (
  SELECT
    u.id AS user_id,
    u.created_at::date AS signup_date
  FROM "user" u
  WHERE u.created_at > now() - interval '30 days'
),
activity AS (
  SELECT DISTINCT
    user_id,
    reacted_at::date AS active_date
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '37 days'
)
SELECT
  c.signup_date,
  count(DISTINCT c.user_id) AS cohort_size,
  count(DISTINCT CASE WHEN a1.active_date = c.signup_date + 1 THEN c.user_id END) AS d1_retained,
  count(DISTINCT CASE WHEN a7.active_date = c.signup_date + 7 THEN c.user_id END) AS d7_retained,
  round(100.0 * count(DISTINCT CASE WHEN a1.active_date = c.signup_date + 1 THEN c.user_id END)
    / NULLIF(count(DISTINCT c.user_id), 0), 1) AS d1_pct,
  round(100.0 * count(DISTINCT CASE WHEN a7.active_date = c.signup_date + 7 THEN c.user_id END)
    / NULLIF(count(DISTINCT c.user_id), 0), 1) AS d7_pct
FROM cohort c
LEFT JOIN activity a1 ON a1.user_id = c.user_id AND a1.active_date = c.signup_date + 1
LEFT JOIN activity a7 ON a7.user_id = c.user_id AND a7.active_date = c.signup_date + 7
GROUP BY c.signup_date
ORDER BY c.signup_date;


-- =============================================
-- SECTION: SOURCE QUALITY
-- =============================================
-- Top and bottom sources by like rate (minimum 50 memes sent)

SELECT
  src.url,
  src.language_code,
  mss.nlikes,
  mss.ndislikes,
  mss.nmemes_sent,
  round(100.0 * mss.nlikes / NULLIF(mss.nlikes + mss.ndislikes, 0), 1) AS like_rate_pct,
  mss.nmemes_parsed,
  mss.latest_meme_age
FROM meme_source_stats mss
JOIN meme_source src ON src.id = mss.meme_source_id
WHERE mss.nmemes_sent >= 50
ORDER BY like_rate_pct DESC;


-- =============================================
-- SECTION: COLD START
-- =============================================
-- First-meme and first-10-memes experience for recent new users

WITH first_reactions AS (
  SELECT
    user_id,
    meme_id,
    reaction_id,
    recommended_by,
    row_number() OVER (PARTITION BY user_id ORDER BY sent_at) AS meme_number
  FROM user_meme_reaction
  WHERE user_id IN (
    SELECT id FROM "user" WHERE created_at > now() - interval '7 days'
  )
)
SELECT
  'first_meme' AS segment,
  count(*) AS total,
  count(*) FILTER (WHERE reaction_id = 1) AS likes,
  round(100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0), 1) AS like_rate_pct
FROM first_reactions
WHERE meme_number = 1
UNION ALL
SELECT
  'first_10_memes',
  count(*),
  count(*) FILTER (WHERE reaction_id = 1),
  round(100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0), 1)
FROM first_reactions
WHERE meme_number <= 10;


-- =============================================
-- SECTION: ANOMALY DETECTION (for Analyst)
-- =============================================
-- Compare today vs yesterday vs 7-day average
-- Analyst should flag if today differs >30% from 7-day avg

WITH daily AS (
  SELECT
    reacted_at::date AS day,
    count(*) AS reactions,
    count(DISTINCT user_id) AS active_users,
    count(*) FILTER (WHERE reaction_id = 1) AS likes,
    round(100.0 * count(*) FILTER (WHERE reaction_id = 1)
      / NULLIF(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0), 1) AS like_rate
  FROM user_meme_reaction
  WHERE reacted_at > now() - interval '8 days'
  GROUP BY 1
)
SELECT
  day,
  reactions,
  active_users,
  likes,
  like_rate,
  round(avg(reactions) OVER (ORDER BY day ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING)) AS reactions_7d_avg,
  round(avg(active_users) OVER (ORDER BY day ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING)) AS users_7d_avg
FROM daily
ORDER BY day;


-- =============================================
-- SECTION: CHAT AGENT (Meme Sommelier)
-- =============================================
-- Tracks the AI chat agent in group chats.
-- Tables: chat_agent_usage, chat_meme_reaction, message_tg

-- Agent activity summary (last 24h and 7d)
SELECT
  count(*) FILTER (WHERE created_at > now() - interval '24 hours') AS agent_calls_24h,
  count(*) FILTER (WHERE created_at > now() - interval '7 days') AS agent_calls_7d,
  count(DISTINCT chat_id) FILTER (WHERE created_at > now() - interval '24 hours') AS active_chats_24h,
  count(DISTINCT chat_id) FILTER (WHERE created_at > now() - interval '7 days') AS active_chats_7d,
  count(DISTINCT user_id) FILTER (WHERE created_at > now() - interval '24 hours') AS chat_users_24h,
  round(avg(response_time_ms) FILTER (WHERE created_at > now() - interval '24 hours')) AS avg_response_ms_24h,
  sum(prompt_tokens + completion_tokens) FILTER (WHERE created_at > now() - interval '24 hours') AS total_tokens_24h,
  sum(tool_calls) FILTER (WHERE created_at > now() - interval '24 hours') AS total_tool_calls_24h
FROM chat_agent_usage;

-- Agent cost estimate (DeepSeek pricing: $0.14/M input, $0.28/M output)
SELECT
  sum(prompt_tokens) AS total_prompt_tokens,
  sum(completion_tokens) AS total_completion_tokens,
  round((sum(prompt_tokens) * 0.14 / 1000000 + sum(completion_tokens) * 0.28 / 1000000)::numeric, 4) AS cost_usd,
  count(*) AS total_calls
FROM chat_agent_usage
WHERE created_at > now() - interval '24 hours';

-- Group meme reactions (like/dislike buttons in chats)
SELECT
  count(*) FILTER (WHERE reacted_at > now() - interval '24 hours') AS reactions_24h,
  count(*) FILTER (WHERE reaction = 1 AND reacted_at > now() - interval '24 hours') AS likes_24h,
  count(*) FILTER (WHERE reaction = 2 AND reacted_at > now() - interval '24 hours') AS dislikes_24h,
  count(DISTINCT chat_id) FILTER (WHERE reacted_at > now() - interval '24 hours') AS chats_with_reactions_24h,
  count(*) AS total_reactions_alltime
FROM chat_meme_reaction;

-- Group message logging (how many groups are we tracking?)
SELECT
  count(DISTINCT chat_id) FILTER (WHERE date > now() - interval '24 hours') AS groups_logging_24h,
  count(*) FILTER (WHERE date > now() - interval '24 hours') AS messages_logged_24h,
  count(DISTINCT chat_id) AS total_groups_alltime
FROM message_tg
WHERE date > now() - interval '30 days';

-- Per-group agent engagement (top groups by agent usage)
SELECT
  chat_id,
  count(*) AS agent_calls,
  count(DISTINCT user_id) AS unique_users,
  sum(tool_calls) AS tool_calls,
  round(avg(response_time_ms)) AS avg_response_ms
FROM chat_agent_usage
WHERE created_at > now() - interval '7 days'
GROUP BY chat_id
ORDER BY agent_calls DESC
LIMIT 10;
