-- North star: THE metric definitions (read-only; built only on the v_* views
-- from alembic/versions/2026-11-02_metrics_views.py).
-- Window: the 28 days ending yesterday, in four 7-day buckets labeled by
-- their first day. Keep bounds as cheap date arithmetic (CURRENT_DATE - n):
-- view date filters run per row on user_meme_reaction, and DATE_TRUNC/EXTRACT
-- bounds make Q2/Q4 3-10x slower.
-- Every query drops segment = 'excluded' (automated accounts, see
-- excluded-users-detector.sql).
-- Moderators/admins are also dropped from Q2 and Q3: they work the
-- low_sent_pool review queue, which inflates reactions and session length.
-- They stay in Q1 (signups) and Q4 (their shares are real shares).
--
-- Run: psql "$ANALYST_DATABASE_URL" -f docs/analyst/north_star.sql

-- Q1. New users per week by acquisition channel (first /start deep link).
SELECT
    CURRENT_DATE - 28 + 7 * ((signup_at::date - (CURRENT_DATE - 28)) / 7) AS week,
    acquisition_channel,
    COUNT(*) AS new_users
FROM v_metric_user
WHERE signup_at >= CURRENT_DATE - 28
    AND signup_at < CURRENT_DATE
    AND segment <> 'excluded'
GROUP BY 1, 2
ORDER BY 1, 3 DESC;

-- Q2. Reactions per active user per week (active = >= 1 reaction that week).
SELECT
    CURRENT_DATE - 28 + 7 * ((D.day - (CURRENT_DATE - 28)) / 7) AS week,
    COUNT(DISTINCT D.user_id) AS active_users,
    SUM(D.reactions) AS reactions,
    ROUND(SUM(D.reactions)::numeric / COUNT(DISTINCT D.user_id), 1) AS reactions_per_active
FROM v_user_day D
JOIN v_metric_user U
    ON U.user_id = D.user_id
WHERE D.day >= CURRENT_DATE - 28
    AND D.day < CURRENT_DATE
    AND D.reactions > 0
    AND U.segment = 'user'
GROUP BY 1
ORDER BY 1;

-- Q3. Median memes per feed session (30-minute gap; push sends excluded).
SELECT
    CURRENT_DATE - 28 + 7 * ((S.session_start::date - (CURRENT_DATE - 28)) / 7) AS week,
    COUNT(*) AS sessions,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY S.memes_sent) AS median_memes_per_session,
    ROUND(AVG(S.memes_sent), 1) AS avg_memes_per_session,
    ROUND(AVG(S.started_by_push::int), 3) AS push_started_share
FROM v_feed_session S
JOIN v_metric_user U
    ON U.user_id = S.user_id
WHERE S.session_start >= CURRENT_DATE - 28
    AND S.session_start < CURRENT_DATE
    AND U.segment = 'user'
GROUP BY 1
ORDER BY 1;

-- Q4. Non-self share clicks and invites (new users whose first link was a
-- share link) per 1k active users per week.
WITH weekly AS (
    SELECT
        CURRENT_DATE - 28 + 7 * ((D.day - (CURRENT_DATE - 28)) / 7) AS week,
        COUNT(DISTINCT D.user_id) FILTER (WHERE D.reactions > 0) AS active_users,
        SUM(D.shares) AS shares
    FROM v_user_day D
    JOIN v_metric_user U
        ON U.user_id = D.user_id
    WHERE D.day >= CURRENT_DATE - 28
        AND D.day < CURRENT_DATE
        AND U.segment <> 'excluded'
    GROUP BY 1
),
invites AS (
    SELECT
        CURRENT_DATE - 28 + 7 * ((signup_at::date - (CURRENT_DATE - 28)) / 7) AS week,
        COUNT(*) AS invites
    FROM v_metric_user
    WHERE signup_at >= CURRENT_DATE - 28
        AND signup_at < CURRENT_DATE
        AND acquisition_channel = 'share'
        AND segment <> 'excluded'
    GROUP BY 1
)
SELECT
    W.week,
    W.active_users,
    W.shares,
    COALESCE(I.invites, 0) AS invites,
    ROUND(1000.0 * W.shares / NULLIF(W.active_users, 0), 1) AS shares_per_1k_active,
    ROUND(1000.0 * COALESCE(I.invites, 0) / NULLIF(W.active_users, 0), 1) AS invites_per_1k_active
FROM weekly W
LEFT JOIN invites I
    ON I.week = W.week
ORDER BY 1;
