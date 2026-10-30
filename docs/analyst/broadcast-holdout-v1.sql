-- Readout: broadcast_cadence_holdout_v1_<step> (15m/24h/1w/2w/4w) and
-- monthly_reminder_v1, treated vs holdout. Read-only, one SELECT.
-- Experiment note: experiments/active/2026-10-30-broadcast-cadence-holdout.md
--
-- Assignment = first time the user was selected by that step (intent-to-treat;
-- holdout users were selected but not pushed). Steps are randomized
-- independently, so other steps act as shared background for both arms.
--
-- Cadence decision columns: reactions_per_user_week, weekly_reactor_pct,
--   active_d7_14_pct, blocked_pct.
-- Monthly decision columns: react_24h_pct, react_7d_pct, react_30d_pct,
--   blocked_30d_pct. Window columns only count users whose window has closed.

WITH A AS (
    SELECT
        EA.experiment_id,
        EA.variant,
        EA.user_id,
        EA.assigned_at,
        GREATEST(EXTRACT(EPOCH FROM NOW() - EA.assigned_at) / 604800.0, 1 / 7.0) AS weeks,
        U.blocked_bot_at
    FROM experiment_assignment EA
    JOIN "user" U ON U.id = EA.user_id
    WHERE EA.experiment_id LIKE 'broadcast_cadence_holdout_v1_%'
       OR EA.experiment_id = 'monthly_reminder_v1'
),

PER_USER AS (
    SELECT
        A.*,
        R.reactions,
        R.reacted_last_7d,
        R.active_d7_14,
        R.react_24h,
        R.react_7d,
        R.react_30d
    FROM A
    CROSS JOIN LATERAL (
        SELECT
            COUNT(*) AS reactions,
            BOOL_OR(UMR.reacted_at > NOW() - INTERVAL '7 days') AS reacted_last_7d,
            BOOL_OR(UMR.reacted_at > A.assigned_at + INTERVAL '7 days'
                AND UMR.reacted_at <= A.assigned_at + INTERVAL '14 days') AS active_d7_14,
            BOOL_OR(UMR.reacted_at <= A.assigned_at + INTERVAL '24 hours') AS react_24h,
            BOOL_OR(UMR.reacted_at <= A.assigned_at + INTERVAL '7 days') AS react_7d,
            BOOL_OR(UMR.reacted_at <= A.assigned_at + INTERVAL '30 days') AS react_30d
        FROM user_meme_reaction UMR
        WHERE UMR.user_id = A.user_id
          AND UMR.reacted_at > A.assigned_at
    ) R
)

SELECT
    experiment_id,
    variant,
    COUNT(*) AS users,
    MIN(assigned_at)::date AS first_assigned,
    ROUND(AVG(reactions / weeks)::numeric, 2) AS reactions_per_user_week,
    ROUND(100.0 * AVG(COALESCE(reacted_last_7d, FALSE)::int), 1) AS weekly_reactor_pct,
    ROUND(100.0 * AVG(COALESCE(active_d7_14, FALSE)::int)
        FILTER (WHERE assigned_at <= NOW() - INTERVAL '14 days'), 1) AS active_d7_14_pct,
    ROUND(100.0 * AVG(COALESCE(blocked_bot_at > assigned_at, FALSE)::int), 2) AS blocked_pct,
    ROUND(100.0 * AVG(COALESCE(react_24h, FALSE)::int)
        FILTER (WHERE assigned_at <= NOW() - INTERVAL '24 hours'), 1) AS react_24h_pct,
    ROUND(100.0 * AVG(COALESCE(react_7d, FALSE)::int)
        FILTER (WHERE assigned_at <= NOW() - INTERVAL '7 days'), 1) AS react_7d_pct,
    COUNT(*) FILTER (WHERE assigned_at <= NOW() - INTERVAL '30 days') AS users_30d_closed,
    ROUND(100.0 * AVG(COALESCE(react_30d, FALSE)::int)
        FILTER (WHERE assigned_at <= NOW() - INTERVAL '30 days'), 1) AS react_30d_pct,
    ROUND(100.0 * AVG(COALESCE(blocked_bot_at > assigned_at
        AND blocked_bot_at <= assigned_at + INTERVAL '30 days', FALSE)::int)
        FILTER (WHERE assigned_at <= NOW() - INTERVAL '30 days'), 2) AS blocked_30d_pct
FROM PER_USER
GROUP BY experiment_id, variant
ORDER BY experiment_id, variant
