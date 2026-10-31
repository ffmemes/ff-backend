-- Candidate automated accounts for analytics_excluded_user (read-only SELECT).
-- Rule (2026-10-31 investigation): >= 50 push reactions and >= 50% of them in
-- ONE 10-second bin of (reacted_at - sent_at). A human opens pushes at random
-- delays; a script answers at a fixed one.
-- Push = user_meme_reaction.recommended_by LIKE 'broadcast%'
-- (broadcast_reengagement[_hq], broadcast_channel_viral, ...).
--
-- Operator, on prod after reviewing the output (user IDs stay in the DB,
-- never in the repo):
--   INSERT INTO analytics_excluded_user (user_id, reason)
--   <this query>
--   ON CONFLICT (user_id) DO NOTHING;
WITH per_bin AS (
    SELECT
        user_id,
        FLOOR(EXTRACT(EPOCH FROM reacted_at - sent_at) / 10)::int AS bin,
        COUNT(*) AS n,
        SUM(COUNT(*)) OVER (PARTITION BY user_id) AS total
    FROM user_meme_reaction
    WHERE recommended_by LIKE 'broadcast%'
        AND reaction_id IS NOT NULL
        AND reacted_at IS NOT NULL
    GROUP BY 1, 2
),
top_bin AS (
    SELECT DISTINCT ON (user_id) user_id, bin, n, total
    FROM per_bin
    ORDER BY user_id, n DESC
)
SELECT
    user_id,
    FORMAT(
        'push-timing bot: %s of %s push reactions at %s-%ss after send',
        n, total, bin * 10, bin * 10 + 10
    ) AS reason
FROM top_bin
WHERE total >= 50
    AND n >= 0.5 * total
ORDER BY user_id
