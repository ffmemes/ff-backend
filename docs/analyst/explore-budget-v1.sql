-- explore_budget_v1 readout (one SELECT; read-only)
-- Experiment doc: experiments/active/2026-10-30-explore-budget.md
-- Rows: variant x segment (mod = moderator/admin, user = everyone else).
-- Per-user means, feed sends only (recommended_by NOT LIKE 'broadcast%'),
-- counted from each user's assigned_at.
--
-- Primary:   likes_per_user_week, memes_per_session
-- Guardrails: pos2_abandon (first feed meme after a reacted push, no reaction
--             within 30 min), fresh_ru_labeled_share (global, same on every row:
--             RU ok memes created 14..7d ago with >= 10 reactions within 7d;
--             must stay >= 0.90; global, not per arm, and only reflects the
--             experiment once memes created after its start are 7d old). Empty-queue errors live in Sentry/logs
--             ("recommendation batch diagnostics", selected_count = 0).
-- Diagnostics: like_rate, low_sent_share, fresh_viral_share.
--
-- Bounded: user_meme_reaction is read via (user_id, sent_at) and
-- (sent_at, meme_id, user_id) indexes only; no meme_id-keyed scans.
WITH assigned AS (
    SELECT
        EA.user_id,
        EA.variant,
        EA.assigned_at,
        CASE WHEN U.type IN ('moderator', 'admin') THEN 'mod' ELSE 'user' END AS seg
    FROM experiment_assignment EA
    JOIN "user" U ON U.id = EA.user_id
    WHERE EA.experiment_id = 'explore_budget_v1'
),
sends AS (
    SELECT
        A.variant,
        A.seg,
        A.user_id,
        A.assigned_at,
        R.sent_at,
        R.reacted_at,
        R.reaction_id,
        R.recommended_by,
        R.recommended_by LIKE 'broadcast%' AS is_push
    FROM assigned A
    JOIN user_meme_reaction R
        ON R.user_id = A.user_id
        AND R.sent_at >= A.assigned_at
),
feed AS (
    SELECT
        *,
        CASE
            WHEN LAG(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at) IS NULL
                OR sent_at - LAG(sent_at) OVER (PARTITION BY user_id ORDER BY sent_at)
                    > INTERVAL '30 minutes'
            THEN 1 ELSE 0
        END AS new_session
    FROM sends
    WHERE NOT is_push
),
per_user AS (
    SELECT
        variant,
        seg,
        user_id,
        COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
        COUNT(*) FILTER (WHERE reaction_id IS NOT NULL) AS reactions,
        COUNT(*) AS feed_sends,
        COUNT(*) FILTER (WHERE recommended_by = 'low_sent_pool') AS low_sent_sends,
        COUNT(*) FILTER (WHERE recommended_by = 'fresh_viral') AS fresh_viral_sends,
        SUM(new_session) AS sessions,
        GREATEST(EXTRACT(EPOCH FROM NOW() - MIN(assigned_at)) / 604800.0, 1.0 / 7) AS weeks
    FROM feed
    GROUP BY 1, 2, 3
),
pushes AS (
    SELECT variant, seg, user_id, reacted_at
    FROM sends
    WHERE is_push AND reacted_at IS NOT NULL
),
pos2 AS (
    SELECT
        P.variant,
        P.seg,
        (NXT.reacted_at IS NULL OR NXT.reacted_at > NXT.sent_at + INTERVAL '30 minutes')
            AS abandoned
    FROM pushes P
    JOIN LATERAL (
        SELECT R.sent_at, R.reacted_at
        FROM user_meme_reaction R
        WHERE R.user_id = P.user_id
            AND R.sent_at >= P.reacted_at
            AND R.sent_at < P.reacted_at + INTERVAL '30 minutes'
            AND R.recommended_by NOT LIKE 'broadcast%'
        ORDER BY R.sent_at
        LIMIT 1
    ) NXT ON TRUE
),
fresh_ru AS (
    SELECT
        AVG(CASE WHEN COALESCE(L.n, 0) >= 10 THEN 1.0 ELSE 0.0 END) AS labeled_share,
        COUNT(*) AS memes
    FROM meme M
    LEFT JOIN (
        SELECT R.meme_id, COUNT(*) AS n
        FROM user_meme_reaction R
        JOIN meme M2 ON M2.id = R.meme_id
        WHERE R.sent_at >= NOW() - INTERVAL '14 days'
            AND R.reaction_id IS NOT NULL
            AND R.reacted_at < M2.created_at + INTERVAL '7 days'
        GROUP BY 1
    ) L ON L.meme_id = M.id
    WHERE M.status = 'ok'
        AND M.language_code = 'ru'
        AND M.created_at >= NOW() - INTERVAL '14 days'
        AND M.created_at < NOW() - INTERVAL '7 days'
)
SELECT
    U.variant,
    U.seg,
    COUNT(*) AS users,
    SUM(U.feed_sends) AS feed_sends,
    ROUND(AVG(U.likes / U.weeks)::numeric, 2) AS likes_per_user_week,
    ROUND(AVG(U.feed_sends::numeric / NULLIF(U.sessions, 0)), 2) AS memes_per_session,
    ROUND(AVG(U.likes::numeric / NULLIF(U.reactions, 0)), 3) AS like_rate,
    ROUND(SUM(U.low_sent_sends)::numeric / NULLIF(SUM(U.feed_sends), 0), 3) AS low_sent_share,
    ROUND(SUM(U.fresh_viral_sends)::numeric / NULLIF(SUM(U.feed_sends), 0), 3)
        AS fresh_viral_share,
    (SELECT COUNT(*) FROM pos2 WHERE pos2.variant = U.variant AND pos2.seg = U.seg)
        AS pos2_n,
    (
        SELECT ROUND(AVG(CASE WHEN abandoned THEN 1.0 ELSE 0.0 END), 3)
        FROM pos2
        WHERE pos2.variant = U.variant AND pos2.seg = U.seg
    ) AS pos2_abandon,
    (SELECT ROUND(labeled_share, 3) FROM fresh_ru) AS fresh_ru_labeled_share,
    (SELECT memes FROM fresh_ru) AS fresh_ru_memes
FROM per_user U
GROUP BY 1, 2
ORDER BY 2, 1
