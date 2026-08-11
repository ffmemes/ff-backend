-- Shadow hybrid readout: v4_x_src_v1 (ln(nlikes+1) * src_quality_mult)
-- Logged on decision_log candidates[]; does NOT change production pick.
-- Join to mature 24h channel labels when available.

\set ON_ERROR_STOP on

-- 1) Shadow field coverage (recent RU decisions)
SELECT
  count(*) AS decisions,
  count(*) FILTER (WHERE candidates->0 ? 'shadow_score') AS with_shadow,
  count(*) FILTER (WHERE (candidates->0->>'shadow_vs_prod_disagree')::boolean IS TRUE)
    AS disagree_top1,
  round(
    100.0 * count(*) FILTER (
      WHERE (candidates->0->>'shadow_vs_prod_disagree')::boolean IS TRUE
    ) / nullif(count(*), 0),
    1
  ) AS disagree_pct,
  max(candidates->0->>'shadow_version') AS shadow_version
FROM crossposting_decision_log
WHERE channel = 'tgchannelru'
  AND decided_at > now() - interval '14 days'
  AND score_version = 4;

-- 2) Would-shadow top1 vs prod pick: early live f1k (smoke)
SELECT
  d.decided_at,
  d.picked_meme_id AS prod_pick,
  (d.candidates->0->>'shadow_pick_meme_id')::bigint AS shadow_pick,
  (d.candidates->0->>'shadow_vs_prod_disagree')::boolean AS disagree,
  (d.candidates->0->>'shadow_score')::float AS shadow_score_prod_row,
  c.views,
  c.forwards,
  round(1000.0 * c.forwards / nullif(c.views, 0), 1) AS f1k_live
FROM crossposting_decision_log d
JOIN crossposting c
  ON c.channel = d.channel AND c.meme_id = d.picked_meme_id
WHERE d.channel = 'tgchannelru'
  AND d.decided_at > now() - interval '14 days'
  AND d.score_version = 4
ORDER BY d.decided_at DESC
LIMIT 30;

-- 3) Mature: when shadow disagrees, compare eventual 24h f1k of prod pick
--    (shadow counterfactual needs candidate meme_id stats — often only pick is posted)
WITH decided AS (
  SELECT
    d.picked_meme_id,
    d.decided_at,
    (d.candidates->0->>'shadow_score')::float AS shadow_of_prod,
    (d.candidates->0->>'final_score')::float AS prod_score,
    (d.candidates->0->>'shadow_vs_prod_disagree')::boolean AS disagree,
    (d.candidates->0->>'shadow_rank')::int AS shadow_rank_of_prod
  FROM crossposting_decision_log d
  WHERE d.channel = 'tgchannelru'
    AND d.score_version = 4
    AND d.decided_at > now() - interval '30 days'
    AND d.candidates->0 ? 'shadow_score'
),
labeled AS (
  SELECT DISTINCT ON (c.meme_id)
    d.*,
    1000.0 * s.forwards / nullif(s.views, 0) AS f1k,
    s.forwards,
    s.views
  FROM decided d
  JOIN crossposting c
    ON c.channel = 'tgchannelru' AND c.meme_id = d.picked_meme_id
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = c.telegram_message_id
   AND s.snapshot_at BETWEEN c.created_at + interval '18 hours'
                         AND c.created_at + interval '36 hours'
   AND s.views > 0
  WHERE c.created_at < now() - interval '36 hours'
  ORDER BY c.meme_id, abs(extract(epoch from (
    s.snapshot_at - (c.created_at + interval '24 hours')
  )))
)
SELECT
  CASE WHEN disagree THEN 'shadow_disagreed' ELSE 'shadow_agreed' END AS bucket,
  count(*) AS n,
  round(avg(f1k)::numeric, 2) AS avg_f1k,
  round(avg(forwards)::numeric, 2) AS avg_fwd,
  round(avg(shadow_of_prod)::numeric, 3) AS avg_shadow_of_prod
FROM labeled
GROUP BY 1
ORDER BY 1;

-- 4) Among posted picks: does higher shadow_score (of the pick) predict higher f1k?
--    (correlation of logged shadow on production choice — weak but free)
WITH decided AS (
  SELECT
    d.picked_meme_id,
    (d.candidates->0->>'shadow_score')::float AS shadow_score,
    (d.candidates->0->>'shadow_score_maturity')::float AS shadow_maturity
  FROM crossposting_decision_log d
  WHERE d.channel = 'tgchannelru'
    AND d.score_version = 4
    AND d.decided_at > now() - interval '30 days'
    AND d.candidates->0 ? 'shadow_score'
),
labeled AS (
  SELECT DISTINCT ON (c.meme_id)
    d.shadow_score,
    d.shadow_maturity,
    1000.0 * s.forwards / nullif(s.views, 0) AS f1k
  FROM decided d
  JOIN crossposting c
    ON c.channel = 'tgchannelru' AND c.meme_id = d.picked_meme_id
  JOIN crossposting_snapshots s
    ON s.channel = 'tgchannelru'
   AND s.telegram_message_id = c.telegram_message_id
   AND s.snapshot_at BETWEEN c.created_at + interval '18 hours'
                         AND c.created_at + interval '36 hours'
   AND s.views > 0
  WHERE c.created_at < now() - interval '36 hours'
  ORDER BY c.meme_id, abs(extract(epoch from (
    s.snapshot_at - (c.created_at + interval '24 hours')
  )))
)
SELECT
  count(*) AS n,
  round(corr(shadow_score, f1k)::numeric, 3) AS r_shadow_f1k,
  round(corr(shadow_maturity, f1k)::numeric, 3) AS r_maturity_f1k
FROM labeled
WHERE shadow_score IS NOT NULL AND f1k IS NOT NULL;
