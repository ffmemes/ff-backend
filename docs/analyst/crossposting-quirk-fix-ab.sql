-- Crosspost quirk-fix live A/B readout
-- (experiments/2026-11-01-crosspost-quirk-fix-ab.md).
-- One SELECT, one row per channel x arm. Each decision picks an arm at random
-- (src/crossposting/scoring.py AB_ARMS); crossposting.score_version records it:
--   control: RU v4 = 4, EN v2 = 2   fix: RU v4q = 9, EN v2q = 8
-- zf = ln(1+forwards) - channel x MSK-week mean over posted image memes >= 48h old.
-- diff_zf / ci95 are fix minus control within the channel (Welch, normal approx).
-- changed_pct: share of fix-arm decisions where the control score would have picked
-- a different meme from the same top-N (how often the fix actually mattered).
WITH posts AS (
    SELECT cp.channel, cp.score_version, cp.views, cp.forwards,
           LN(1 + cp.forwards) AS lfw,
           date_trunc('week', cp.created_at + INTERVAL '3 hours') AS wk
    FROM crossposting cp
    JOIN meme m ON m.id = cp.meme_id
    WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
      AND cp.score_version IN (2, 4, 8, 9)
      AND cp.telegram_message_id IS NOT NULL
      AND cp.views > 0
      AND cp.forwards IS NOT NULL
      AND m.type = 'image'
      AND cp.created_at >= '2026-11-01'
      AND cp.created_at < NOW() - INTERVAL '48 hours'
),
labeled AS (
    SELECT *, lfw - AVG(lfw) OVER (PARTITION BY channel, wk) AS zf,
           CASE WHEN score_version IN (8, 9) THEN 'fix' ELSE 'control' END AS arm
    FROM posts
),
arms AS (
    SELECT channel, arm, COUNT(*) AS n, AVG(zf) AS mzf, VAR_SAMP(zf) AS vzf,
           AVG(views) AS views, AVG(forwards::float / views) AS fwd_rate
    FROM labeled GROUP BY 1, 2
),
changed AS (
    SELECT channel,
           ROUND(100.0 * AVG((candidates->0->'picks'->>'v4q'
                   IS DISTINCT FROM candidates->0->'picks'->>'v4')::int), 1) AS ru,
           ROUND(100.0 * AVG((candidates->0->'picks'->>'v2q'
                   IS DISTINCT FROM candidates->0->'picks'->>'v2')::int), 1) AS en
    FROM crossposting_decision_log
    WHERE decided_at >= '2026-11-01' AND score_version IN (8, 9)
    GROUP BY 1
)
SELECT a.channel, a.arm, a.n, ROUND(a.mzf::numeric, 3) AS mean_zf,
       ROUND(a.views::numeric) AS avg_views, ROUND((100 * a.fwd_rate)::numeric, 3) AS fwd_rate_pct,
       CASE WHEN a.arm = 'fix' THEN ROUND((a.mzf - c.mzf)::numeric, 3) END AS diff_zf,
       CASE WHEN a.arm = 'fix'
            THEN ROUND((1.96 * SQRT(a.vzf / a.n + c.vzf / c.n))::numeric, 3) END AS ci95,
       CASE WHEN a.arm = 'fix'
            THEN CASE a.channel WHEN 'tgchannelru' THEN ch.ru ELSE ch.en END END AS changed_pct
FROM arms a
LEFT JOIN arms c ON c.channel = a.channel AND c.arm = 'control'
LEFT JOIN changed ch ON ch.channel = a.channel
ORDER BY a.channel, a.arm
