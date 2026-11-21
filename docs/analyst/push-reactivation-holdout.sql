-- Randomized November-era send/no-send assignments (ITT), one row per arm and step.
-- as_of: UTC midnight. Include ordinary users with a fully observed 14-day window.
-- Both arms can generate any valid callback, including an organic return.
-- The day 7-14 measure requires a callback to a personal feed meme after day 7.
-- A send may reveal a pre-existing block; holdouts lack the same delivery probe.
-- The timestamp is cleared on unblock, so this only measures recorded blocks.
-- The day 7-14 callback may be on a feed meme delivered before assignment.
WITH assigned AS (
    SELECT ea.experiment_id, ea.variant, ea.user_id, ea.assigned_at, u.blocked_bot_at
    FROM experiment_assignment ea
    JOIN v_metric_user mu ON mu.user_id = ea.user_id AND mu.segment = 'user'
    JOIN "user" u ON u.id = ea.user_id
    WHERE ea.experiment_id IN (
        'monthly_reminder_v1', 'broadcast_cadence_holdout_v1_1w',
        'broadcast_cadence_holdout_v1_2w', 'broadcast_cadence_holdout_v1_4w'
    )
      AND ea.assigned_at + INTERVAL '14 days' <= :'as_of'::date
)
SELECT a.experiment_id, a.variant, count(*) AS assigned_users,
       count(*) FILTER (WHERE outcome.active_24h) AS active_24h,
       count(*) FILTER (WHERE outcome.feed_d7_14) AS feed_d7_14,
       count(*) FILTER (WHERE a.blocked_bot_at >= a.assigned_at
           AND a.blocked_bot_at < a.assigned_at + INTERVAL '14 days') AS recorded_blocks_14d
FROM assigned a
CROSS JOIN LATERAL (
    SELECT bool_or(r.reacted_at < a.assigned_at + INTERVAL '24 hours') AS active_24h,
           bool_or(r.reacted_at >= a.assigned_at + INTERVAL '7 days'
               AND r.recommended_by NOT LIKE 'broadcast%') AS feed_d7_14
    FROM user_meme_reaction r
    WHERE r.user_id = a.user_id AND r.reacted_at > a.assigned_at
      AND r.reacted_at < a.assigned_at + INTERVAL '14 days'
      AND r.reacted_at >= r.sent_at AND r.reaction_id IN (1, 2)
      AND r.recommended_by NOT IN ('uploaded_meme', 'friend_challenge')
) outcome
GROUP BY a.experiment_id, a.variant
ORDER BY a.experiment_id, a.variant;
