-- Crosspost v5 shadow readout (experiments/2026-10-30-crosspost-v5-shadow.md).
-- One SELECT, one row per channel. Production pick is unchanged; v5 is log-only.
--
-- zf = ln(1+forwards) - channel x MSK-week mean over posted image memes >= 48h old
-- (crossposting.forwards = latest Telethon snapshot, same as the 2026-10-30 study).
--
-- disagree_pct          share of decisions where shadow v5 top-1 != prod pick
-- zf_prod_agree/disagree mean zf of the prod pick, split by agreement
-- zf_v5_pick_disagree   mean zf of the v5 pick when it disagreed AND was posted later
--                       (counterfactual exists only for memes that got posted)
-- corr_v5 / corr_v4     corr(score, zf) over posted picks (score logged at decision time)
-- Decision rule: canary v5 on a channel if corr_v5 - corr_v4 >= 0.05 with n_posted >= 60.
WITH dec AS (
    SELECT d.channel, d.decided_at, d.picked_meme_id,
           (d.candidates->0->>'shadow_v5_pick_meme_id')::int AS v5_pick,
           (d.candidates->0->>'score_v5')::float AS score_v5,
           (d.candidates->0->>'final_score')::float AS score_v4
    FROM crossposting_decision_log d
    WHERE d.channel IN ('tgchannelru', 'tgchannelen')
      AND d.candidates->0->>'shadow_v5_pick_meme_id' IS NOT NULL
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
       ROUND(100.0 * AVG((dec.v5_pick <> dec.picked_meme_id)::int), 1) AS disagree_pct,
       COUNT(p.zf) AS n_posted,
       ROUND(AVG(p.zf) FILTER (WHERE dec.v5_pick = dec.picked_meme_id)::numeric, 3)
           AS zf_prod_agree,
       ROUND(AVG(p.zf) FILTER (WHERE dec.v5_pick <> dec.picked_meme_id)::numeric, 3)
           AS zf_prod_disagree,
       ROUND(AVG(v.zf) FILTER (WHERE dec.v5_pick <> dec.picked_meme_id)::numeric, 3)
           AS zf_v5_pick_disagree,
       COUNT(v.zf) FILTER (WHERE dec.v5_pick <> dec.picked_meme_id) AS n_v5_pick_posted,
       ROUND(CORR(dec.score_v5, p.zf)::numeric, 3) AS corr_v5,
       ROUND(CORR(dec.score_v4, p.zf)::numeric, 3) AS corr_v4,
       MIN(dec.decided_at) AS since
FROM dec
LEFT JOIN labeled p ON p.channel = dec.channel AND p.meme_id = dec.picked_meme_id
LEFT JOIN labeled v ON v.channel = dec.channel AND v.meme_id = dec.v5_pick
GROUP BY dec.channel
ORDER BY dec.channel
