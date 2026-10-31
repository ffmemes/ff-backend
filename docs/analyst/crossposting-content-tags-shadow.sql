-- Crosspost content-tags shadow readout (experiments/active/2026-10-31-crosspost-content-tags.md).
-- One SELECT, one row per channel. Production pick is unchanged; v5c is log-only.
--
-- score_v5c = score_v5 * content_mult_v1, content_mult_v1 = 0.85 ^ (relatable + tweet_screenshot)
-- zf = ln(1+forwards) - channel x MSK-week mean over posted image memes >= 48h old
-- (same label as docs/analyst/crossposting-v5-shadow.sql).
--
-- tagged_pct      share of decisions whose posted pick has Describe Memes tags
-- v5c_vs_v5_pct   share of decisions where the v5c top-1 differs from the v5 top-1
-- corr_v5c/corr_v5 corr(score, zf) over posted picks (score logged at decision time)
-- zf_flagged/zf_clean mean zf of posted picks with >=1 / 0 content flags (tagged only)
WITH dec AS (
    SELECT d.channel, d.decided_at, d.picked_meme_id,
           (d.candidates->0->>'shadow_v5_pick_meme_id')::int AS v5_pick,
           (d.candidates->0->>'shadow_v5c_pick_meme_id')::int AS v5c_pick,
           (d.candidates->0->>'score_v5')::float AS score_v5,
           (d.candidates->0->>'score_v5c')::float AS score_v5c,
           (d.candidates->0->>'content_mult_v1')::float AS mult,
           d.candidates->0->>'content_format' IS NOT NULL AS tagged
    FROM crossposting_decision_log d
    WHERE d.channel IN ('tgchannelru', 'tgchannelen')
      AND d.candidates->0 ? 'score_v5c'
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
)
SELECT dec.channel,
       COUNT(*) AS decisions,
       ROUND(100.0 * AVG(dec.tagged::int), 1) AS tagged_pct,
       ROUND(100.0 * AVG((dec.v5c_pick <> dec.v5_pick)::int), 1) AS v5c_vs_v5_pct,
       COUNT(p.zf) AS n_posted,
       COUNT(p.zf) FILTER (WHERE dec.tagged) AS n_posted_tagged,
       ROUND(CORR(dec.score_v5c, p.zf)::numeric, 3) AS corr_v5c,
       ROUND(CORR(dec.score_v5, p.zf)::numeric, 3) AS corr_v5,
       ROUND(AVG(p.zf) FILTER (WHERE dec.tagged AND dec.mult < 1)::numeric, 3) AS zf_flagged,
       ROUND(AVG(p.zf) FILTER (WHERE dec.tagged AND dec.mult = 1)::numeric, 3) AS zf_clean,
       MIN(dec.decided_at) AS since
FROM dec
LEFT JOIN labeled p ON p.channel = dec.channel AND p.meme_id = dec.picked_meme_id
GROUP BY dec.channel
ORDER BY dec.channel
