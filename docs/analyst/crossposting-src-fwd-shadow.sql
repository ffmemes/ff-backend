-- Crosspost source-forward-rate shadow readout
-- (experiments/active/2026-11-01-crosspost-src-forward-rate.md).
-- One SELECT, one row per channel. Production pick is unchanged; v5f is log-only.
--
-- score_v5f = score_v5 * (0.5 + src_fwd_pct), 1.0 multiplier when src_fwd_pct is NULL
-- src_fwd_pct = within-source percentile of forwards/views of the meme's source post
--   (meme_raw_telegram, Telethon read at ~20-48h)
-- zf = ln(1+forwards) - channel x MSK-week mean over posted image memes >= 48h old
-- (same label as docs/analyst/crossposting-content-tags-shadow.sql).
--
-- coverage_pct     share of decisions whose posted pick has src_fwd_pct
-- v5f_vs_v5_pct    share of decisions where the v5f top-1 differs from the v5 top-1
-- rho_v5f/rho_v5   Spearman(score, zf) over posted picks (score logged at decision time)
-- rho_*_cov        same, only picks that have src_fwd_pct (where v5f can differ)
WITH dec AS (
    SELECT d.channel, d.decided_at, d.picked_meme_id,
           (d.candidates->0->>'shadow_v5_pick_meme_id')::int AS v5_pick,
           (d.candidates->0->>'shadow_v5f_pick_meme_id')::int AS v5f_pick,
           (d.candidates->0->>'score_v5')::float AS score_v5,
           (d.candidates->0->>'score_v5f')::float AS score_v5f,
           d.candidates->0->>'src_fwd_pct' IS NOT NULL AS covered
    FROM crossposting_decision_log d
    WHERE d.channel IN ('tgchannelru', 'tgchannelen')
      AND d.candidates->0 ? 'score_v5f'
),
posts AS (
    SELECT cp.channel, cp.meme_id, LN(1 + cp.forwards) AS lfw,
           date_trunc('week', cp.created_at + INTERVAL '3 hours') AS wk
    FROM crossposting cp
    JOIN meme m ON m.id = cp.meme_id
    WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
      AND cp.telegram_message_id IS NOT NULL
      AND cp.views > 0
      AND cp.forwards IS NOT NULL
      AND m.type = 'image'
      AND cp.created_at < NOW() - INTERVAL '48 hours'
      AND cp.created_at > (SELECT MIN(decided_at) FROM dec) - INTERVAL '7 days'
),
labeled AS (
    SELECT channel, meme_id,
           lfw - AVG(lfw) OVER (PARTITION BY channel, wk) AS zf
    FROM posts
),
joined AS (
    SELECT dec.*, p.zf
    FROM dec
    LEFT JOIN labeled p ON p.channel = dec.channel AND p.meme_id = dec.picked_meme_id
),
ranked AS (
    SELECT channel, covered,
           RANK() OVER (PARTITION BY channel ORDER BY score_v5) AS r5,
           RANK() OVER (PARTITION BY channel ORDER BY score_v5f) AS r5f,
           RANK() OVER (PARTITION BY channel ORDER BY zf) AS rz,
           RANK() OVER (PARTITION BY channel, covered ORDER BY score_v5) AS c5,
           RANK() OVER (PARTITION BY channel, covered ORDER BY score_v5f) AS c5f,
           RANK() OVER (PARTITION BY channel, covered ORDER BY zf) AS cz
    FROM joined
    WHERE zf IS NOT NULL AND score_v5 IS NOT NULL
)
SELECT j.channel,
       COUNT(*) AS decisions,
       ROUND(100.0 * AVG(j.covered::int), 1) AS coverage_pct,
       ROUND(100.0 * AVG((j.v5f_pick <> j.v5_pick)::int), 1) AS v5f_vs_v5_pct,
       COUNT(j.zf) AS n_posted,
       COUNT(j.zf) FILTER (WHERE j.covered) AS n_posted_covered,
       (SELECT ROUND(CORR(r5f, rz)::numeric, 3) FROM ranked r WHERE r.channel = j.channel)
           AS rho_v5f,
       (SELECT ROUND(CORR(r5, rz)::numeric, 3) FROM ranked r WHERE r.channel = j.channel)
           AS rho_v5,
       (SELECT ROUND(CORR(c5f, cz)::numeric, 3) FROM ranked r
        WHERE r.channel = j.channel AND r.covered) AS rho_v5f_cov,
       (SELECT ROUND(CORR(c5, cz)::numeric, 3) FROM ranked r
        WHERE r.channel = j.channel AND r.covered) AS rho_v5_cov,
       MIN(j.decided_at) AS since
FROM joined j
GROUP BY j.channel
ORDER BY j.channel
