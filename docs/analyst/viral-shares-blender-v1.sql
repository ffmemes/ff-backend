-- Viral shares blender v1 readout
-- Experiment: viral_shares_blender_v1
-- Primary: unique share clickers + new-user invites per 1k memes sent
-- Guardrails: session depth proxy, like rate

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
