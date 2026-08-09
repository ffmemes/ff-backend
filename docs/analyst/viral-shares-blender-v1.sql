-- Viral shares blender v1 readout
-- Experiment: viral_shares_blender_v1
-- Primary: unique share clickers + new-user invites per 1k memes sent
-- Guardrails: session depth proxy, like rate
--
-- Decision calendar: experiments/HYPOTHESES.md (H1)
--   smoke 2026-08-12 | primary 2026-08-16 | final 2026-08-23
-- Realistic sample at current WAU: >=80 users/arm and >=2k sends/arm
-- (code SAMPLE_GATE 1000 is aspirational, not a hard wait).

\set ON_ERROR_STOP on

-- 0) Age
SELECT
  now() AS as_of,
  min(assigned_at) AS first_assignment,
  round(extract(epoch from (now() - min(assigned_at))) / 86400.0, 2) AS days_since_start
FROM experiment_assignment
WHERE experiment_id = 'viral_shares_blender_v1';

-- 1) Cohort sizes by variant
SELECT
  variant,
  count(*) AS n_users,
  min(assigned_at) AS first_assigned,
  max(assigned_at) AS last_assigned
FROM experiment_assignment
WHERE experiment_id = 'viral_shares_blender_v1'
GROUP BY 1
ORDER BY 1;

-- 2) Exposure + reactions after assignment
WITH assigned AS (
  SELECT user_id, variant, assigned_at
  FROM experiment_assignment
  WHERE experiment_id = 'viral_shares_blender_v1'
),
sent AS (
  SELECT
    a.variant,
    r.user_id,
    r.meme_id,
    r.recommended_by,
    r.sent_at,
    r.reacted_at,
    r.reaction_id
  FROM assigned a
  JOIN user_meme_reaction r
    ON r.user_id = a.user_id
   AND r.sent_at >= a.assigned_at
)
SELECT
  variant,
  count(*) AS memes_sent,
  count(*) FILTER (WHERE reaction_id IS NOT NULL) AS reactions,
  round(
    100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / nullif(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    2
  ) AS like_rate_pct,
  count(*) FILTER (WHERE recommended_by = 'viral_shares') AS viral_engine_sends
FROM sent
GROUP BY 1
ORDER BY 1;

-- 3) Share clicks (m_ and s_) on memes sent post-assignment, non-self
WITH assigned AS (
  SELECT user_id, variant, assigned_at
  FROM experiment_assignment
  WHERE experiment_id = 'viral_shares_blender_v1'
),
sent AS (
  SELECT a.variant, a.user_id AS sharer_user_id, r.meme_id, r.sent_at
  FROM assigned a
  JOIN user_meme_reaction r
    ON r.user_id = a.user_id
   AND r.sent_at >= a.assigned_at
),
clicks AS (
  SELECT
    s.variant,
    udll.user_id AS clicker_id,
    s.meme_id,
    s.sharer_user_id
  FROM user_deep_link_log udll
  JOIN sent s
    ON udll.deep_link IN (
      'm_' || s.sharer_user_id || '_' || s.meme_id,
      's_' || s.sharer_user_id || '_' || s.meme_id
    )
   AND udll.created_at >= s.sent_at
  WHERE udll.user_id <> s.sharer_user_id
)
SELECT
  s.variant,
  count(DISTINCT s.sharer_user_id || ':' || s.meme_id) AS meme_sends_proxy,
  count(*) AS share_clicks,
  count(DISTINCT c.clicker_id) AS unique_clickers,
  round(
    1000.0 * count(DISTINCT c.clicker_id)
    / nullif(count(*), 0),
    3
  ) AS unique_clickers_per_1k_sent_rows
FROM sent s
LEFT JOIN clicks c
  ON c.variant = s.variant
 AND c.meme_id = s.meme_id
 AND c.sharer_user_id = s.sharer_user_id
GROUP BY 1
ORDER BY 1;

-- 4) New-user invites attributed after assignment (user.inviter_id)
WITH assigned AS (
  SELECT user_id, variant, assigned_at
  FROM experiment_assignment
  WHERE experiment_id = 'viral_shares_blender_v1'
),
invites AS (
  SELECT a.variant, u.id AS invitee_id, u.created_at
  FROM assigned a
  JOIN "user" u
    ON u.inviter_id = a.user_id
   AND u.created_at >= a.assigned_at
)
SELECT
  a.variant,
  count(DISTINCT a.user_id) AS cohort_users,
  count(i.invitee_id) AS new_invites,
  round(
    1000.0 * count(i.invitee_id)
    / nullif(
      (
        SELECT count(*)
        FROM user_meme_reaction r
        JOIN assigned ax ON ax.user_id = r.user_id AND r.sent_at >= ax.assigned_at
        WHERE ax.variant = a.variant
      ),
      0
    ),
    3
  ) AS invites_per_1k_sends
FROM assigned a
LEFT JOIN invites i ON i.variant = a.variant
GROUP BY a.variant
ORDER BY 1;

-- 5) Session depth guardrail (p50 memes per session, 30m gap)
WITH assigned AS (
  SELECT user_id, variant, assigned_at
  FROM experiment_assignment
  WHERE experiment_id = 'viral_shares_blender_v1'
),
reacts AS (
  SELECT
    a.variant,
    r.user_id,
    r.reacted_at,
    CASE
      WHEN lag(r.reacted_at) OVER (PARTITION BY r.user_id ORDER BY r.reacted_at) IS NULL
        OR r.reacted_at - lag(r.reacted_at) OVER (PARTITION BY r.user_id ORDER BY r.reacted_at)
           > interval '30 minutes'
      THEN 1 ELSE 0
    END AS new_session
  FROM assigned a
  JOIN user_meme_reaction r
    ON r.user_id = a.user_id
   AND r.reacted_at >= a.assigned_at
   AND r.reacted_at IS NOT NULL
),
sess AS (
  SELECT
    variant,
    user_id,
    sum(new_session) OVER (PARTITION BY user_id ORDER BY reacted_at) AS session_id
  FROM reacts
),
lengths AS (
  SELECT variant, user_id, session_id, count(*) AS session_len
  FROM sess
  GROUP BY 1, 2, 3
)
SELECT
  variant,
  count(*) AS sessions,
  round(percentile_cont(0.50) WITHIN GROUP (ORDER BY session_len)::numeric, 2)
    AS p50_session_len,
  round(avg(session_len)::numeric, 2) AS mean_session_len
FROM lengths
GROUP BY 1
ORDER BY 1;

-- 6) Engine slice: viral_shares vs peers (global 7d)
WITH base AS (
  SELECT
    user_id, recommended_by, sent_at, reaction_id,
    LEAD(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at) AS next_sent_at
  FROM user_meme_reaction
  WHERE sent_at > now() - interval '7 days'
    AND recommended_by IN (
      'viral_shares', 'lr_smoothed', 'recently_liked', 'es_ranked', 'goat'
    )
)
SELECT
  recommended_by,
  count(*) AS n,
  round(
    100.0 * count(*) FILTER (WHERE reaction_id = 1)
    / nullif(count(*) FILTER (WHERE reaction_id IS NOT NULL), 0),
    1
  ) AS like_rate_pct,
  round(
    100.0 * count(*) FILTER (
      WHERE next_sent_at IS NOT NULL
        AND next_sent_at - sent_at < interval '30 minutes'
    ) / nullif(count(*), 0),
    1
  ) AS continuation_30m_pct
FROM base
GROUP BY 1
ORDER BY n DESC;

-- 7) Pass/fail snapshot for decision day (fill by eye against HYPOTHESES.md)
WITH assigned AS (
  SELECT user_id, variant, assigned_at
  FROM experiment_assignment
  WHERE experiment_id = 'viral_shares_blender_v1'
),
stats AS (
  SELECT
    a.variant,
    count(DISTINCT a.user_id) AS n_users,
    count(r.*) AS memes_sent
  FROM assigned a
  LEFT JOIN user_meme_reaction r
    ON r.user_id = a.user_id AND r.sent_at >= a.assigned_at
  GROUP BY 1
)
SELECT
  variant,
  n_users,
  memes_sent,
  n_users >= 80 AS users_gate_ok,
  memes_sent >= 2000 AS sends_gate_ok
FROM stats
ORDER BY 1;
