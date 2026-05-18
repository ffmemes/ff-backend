-- =============================================================================
-- CROSSPOSTING CHANNEL GROWTH ANALYTICS
-- =============================================================================
-- Usage: run against prod DB via ANALYST_DATABASE_URL.
-- Safety: read-only queries. Keep statement_timeout enabled.
--
-- Domain vocabulary:
-- - In-bot share clicks: user_deep_link_log.deep_link LIKE 's_%_%'
-- - Channel deep links: user_deep_link_log.deep_link LIKE 'sc_%_%'
-- - Channel forwards/views: crossposting + crossposting_snapshots
--
-- Reference:
-- - specs/crossposting-share-optimization-2026-05-18.md
-- - specs/channel-growth-optimization.md
-- - CONTEXT.md "Share Attribution"
-- =============================================================================


-- =============================================
-- SECTION: STATS FRESHNESS
-- =============================================

SELECT
  channel,
  count(*) AS snapshots_7d,
  max(snapshot_at) AS latest_snapshot
FROM crossposting_snapshots
WHERE snapshot_at > now() - interval '7 days'
GROUP BY channel
ORDER BY channel;


-- =============================================
-- SECTION: 24H CHANNEL POST LABELS
-- =============================================
-- One row per crossposted meme with the snapshot nearest posted_at + 24h.
-- Use this as the canonical target for offline evaluation.

WITH labels AS (
  SELECT
    cp.channel,
    cp.meme_id,
    cp.score_version,
    cp.created_at AS posted_at,
    m.type AS meme_type,
    s24.snapshot_at,
    s24.views AS views_24h,
    s24.forwards AS forwards_24h,
    s24.reactions AS reactions_24h,
    1000.0 * s24.forwards / NULLIF(s24.views, 0) AS fwd_per_1k_24h,
    abs(extract(epoch FROM s24.snapshot_at - (cp.created_at + interval '24 hours')))
      AS snapshot_lag_sec
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  JOIN LATERAL (
    SELECT cps.snapshot_at, cps.views, cps.forwards, cps.reactions
    FROM crossposting_snapshots cps
    WHERE cps.channel = cp.channel
      AND cps.meme_id = cp.meme_id
      AND cps.snapshot_at BETWEEN cp.created_at + interval '20 hours'
                              AND cp.created_at + interval '36 hours'
      AND cps.views > 0
      AND cps.forwards IS NOT NULL
    ORDER BY abs(extract(epoch FROM cps.snapshot_at - (cp.created_at + interval '24 hours')))
    LIMIT 1
  ) s24 ON true
  WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
    AND cp.created_at < now() - interval '36 hours'
)
SELECT *
FROM labels
ORDER BY posted_at DESC
LIMIT 100;


-- =============================================
-- SECTION: SCORE VERSION IMAGE READOUT
-- =============================================
-- Fair v2 readout: image-only, 24h target. All-content comparisons are
-- confounded by the Apr 13 video boost.

WITH bounds AS (
  SELECT channel, min(created_at) FILTER (WHERE score_version = 2) AS v2_ship
  FROM crossposting
  WHERE channel IN ('tgchannelru', 'tgchannelen')
  GROUP BY channel
),
labels AS (
  SELECT
    cp.channel,
    CASE
      WHEN cp.created_at >= timestamp '2026-04-13 00:00:00'
       AND cp.created_at < b.v2_ship THEN 'phase1_image'
      WHEN cp.score_version = 2
       AND cp.created_at >= b.v2_ship THEN 'phase2_v2_image'
    END AS period,
    s24.views AS views_24h,
    s24.forwards AS forwards_24h,
    1000.0 * s24.forwards / NULLIF(s24.views, 0) AS fwd_per_1k_24h
  FROM crossposting cp
  JOIN bounds b ON b.channel = cp.channel
  JOIN meme m ON m.id = cp.meme_id
  JOIN LATERAL (
    SELECT cps.views, cps.forwards, cps.snapshot_at
    FROM crossposting_snapshots cps
    WHERE cps.channel = cp.channel
      AND cps.meme_id = cp.meme_id
      AND cps.snapshot_at BETWEEN cp.created_at + interval '20 hours'
                              AND cp.created_at + interval '36 hours'
      AND cps.views > 0
      AND cps.forwards IS NOT NULL
    ORDER BY abs(extract(epoch FROM cps.snapshot_at - (cp.created_at + interval '24 hours')))
    LIMIT 1
  ) s24 ON true
  WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
)
SELECT
  channel,
  period,
  count(*) AS n_image_posts,
  round(avg(views_24h), 1) AS avg_views_24h,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY views_24h) AS med_views_24h,
  round(avg(forwards_24h), 2) AS avg_forwards_24h,
  percentile_cont(0.5) WITHIN GROUP (ORDER BY forwards_24h) AS med_forwards_24h,
  round(sum(forwards_24h)::numeric / NULLIF(sum(views_24h), 0) * 1000, 2)
    AS agg_fwd_per_1k_24h,
  round(avg(fwd_per_1k_24h), 2) AS avg_post_fwd_per_1k_24h
FROM labels
WHERE period IS NOT NULL
GROUP BY channel, period
ORDER BY channel, period;


-- =============================================
-- SECTION: PRE-POSTING SIGNAL FEATURES
-- =============================================
-- Reconstruct signals available before each channel post. Do not use current
-- all-time meme_stats.invited_count for offline evaluation.

WITH labels AS (
  SELECT
    cp.channel,
    cp.meme_id,
    cp.created_at AS posted_at,
    s24.views AS views_24h,
    s24.forwards AS forwards_24h,
    1000.0 * s24.forwards / NULLIF(s24.views, 0) AS fwd_per_1k_24h
  FROM crossposting cp
  JOIN meme m ON m.id = cp.meme_id
  JOIN LATERAL (
    SELECT cps.views, cps.forwards, cps.snapshot_at
    FROM crossposting_snapshots cps
    WHERE cps.channel = cp.channel
      AND cps.meme_id = cp.meme_id
      AND cps.snapshot_at BETWEEN cp.created_at + interval '20 hours'
                              AND cp.created_at + interval '36 hours'
      AND cps.views > 0
      AND cps.forwards IS NOT NULL
    ORDER BY abs(extract(epoch FROM cps.snapshot_at - (cp.created_at + interval '24 hours')))
    LIMIT 1
  ) s24 ON true
  WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
    AND cp.created_at < now() - interval '36 hours'
    AND m.type = 'image'
),
reaction_features AS (
  SELECT
    l.channel,
    l.meme_id,
    count(*) FILTER (WHERE r.reaction_id = 1) AS pre_likes,
    count(*) FILTER (WHERE r.reaction_id = 2) AS pre_skips,
    count(*) AS pre_reactions
  FROM labels l
  LEFT JOIN user_meme_reaction r
    ON r.meme_id = l.meme_id
   AND r.reacted_at IS NOT NULL
   AND r.reacted_at < l.posted_at
   AND r.reaction_id IN (1, 2)
  GROUP BY l.channel, l.meme_id
),
parsed_share_clicks AS (
  SELECT
    CAST(split_part(deep_link, '_', 3) AS integer) AS meme_id,
    user_id,
    created_at
  FROM user_deep_link_log
  WHERE deep_link ~ '^s_[0-9]+_[0-9]+$'
),
share_features AS (
  SELECT
    l.channel,
    l.meme_id,
    count(DISTINCT psc.user_id) AS pre_inbot_share_click_users
  FROM labels l
  LEFT JOIN parsed_share_clicks psc
    ON psc.meme_id = l.meme_id
   AND psc.created_at < l.posted_at
  GROUP BY l.channel, l.meme_id
)
SELECT
  l.*,
  rf.pre_likes,
  rf.pre_skips,
  rf.pre_reactions,
  100.0 * rf.pre_likes / NULLIF(rf.pre_reactions, 0) AS pre_like_rate_pct,
  sf.pre_inbot_share_click_users
FROM labels l
JOIN reaction_features rf ON rf.channel = l.channel AND rf.meme_id = l.meme_id
JOIN share_features sf ON sf.channel = l.channel AND sf.meme_id = l.meme_id
ORDER BY l.posted_at DESC
LIMIT 100;


-- =============================================
-- SECTION: SHADOW DECISION LOG SHARE FEATURES
-- =============================================
-- Production shadow experiment crossposting-pre-share-shadow-v1:
-- the live ranker still uses score_version=2, but top-N decision-log candidates
-- include pre_inbot_share_clicks and pre_inbot_share_click_users.

SELECT
  dl.decided_at,
  dl.channel,
  dl.picked_meme_id,
  dl.score_version,
  candidate->>'rank' AS rank,
  (candidate->>'meme_id')::int AS candidate_meme_id,
  (candidate->>'pre_inbot_share_clicks')::int AS pre_inbot_share_clicks,
  (candidate->>'pre_inbot_share_click_users')::int AS pre_inbot_share_click_users,
  (candidate->>'final_score')::numeric AS live_v2_score
FROM crossposting_decision_log dl
CROSS JOIN LATERAL jsonb_array_elements(dl.candidates) AS candidate
WHERE dl.channel IN ('tgchannelru', 'tgchannelen')
  AND dl.decided_at > now() - interval '14 days'
  AND candidate ? 'pre_inbot_share_click_users'
ORDER BY dl.decided_at DESC, (candidate->>'rank')::int
LIMIT 100;


-- =============================================
-- SECTION: SOURCE QUALITY 30D
-- =============================================
-- Mirrors the hot ranker formula. Use only mature posts available before the
-- simulated decision time when backtesting.

SELECT
  cp.channel,
  m.meme_source_id,
  src.url,
  count(*) AS posts,
  round(avg(cp.views), 1) AS avg_views,
  round(avg(cp.forwards), 2) AS avg_forwards,
  round(1000.0 * sum(cp.forwards) / NULLIF(sum(cp.views), 0), 2) AS fwd_per_1k,
  round(avg(cp.forwards * sqrt(greatest(cp.views, 1) / 100.0)), 2) AS source_signal
FROM crossposting cp
JOIN meme m ON m.id = cp.meme_id
JOIN meme_source src ON src.id = m.meme_source_id
WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
  AND cp.created_at > now() - interval '30 days'
  AND cp.created_at < now() - interval '48 hours'
  AND cp.views IS NOT NULL
  AND cp.views > 0
  AND cp.forwards IS NOT NULL
  AND m.type = 'image'
GROUP BY cp.channel, m.meme_source_id, src.url
HAVING count(*) >= 5
ORDER BY cp.channel, source_signal DESC;


-- =============================================
-- SECTION: SOURCE CONCENTRATION GUARDRAIL
-- =============================================

SELECT
  cp.channel,
  m.meme_source_id,
  src.url,
  count(*) AS posts_7d
FROM crossposting cp
JOIN meme m ON m.id = cp.meme_id
JOIN meme_source src ON src.id = m.meme_source_id
WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
  AND cp.created_at > now() - interval '7 days'
GROUP BY cp.channel, m.meme_source_id, src.url
ORDER BY cp.channel, posts_7d DESC
LIMIT 30;


-- =============================================
-- SECTION: CHANNEL DEEP LINK STARTS
-- =============================================
-- sc_{meme_id}_{channel}: channel post -> bot starts/clicks.

SELECT
  split_part(deep_link, '_', 3) AS channel,
  split_part(deep_link, '_', 2)::int AS meme_id,
  count(*) AS clicks,
  count(DISTINCT user_id) AS unique_clickers,
  min(created_at) AS first_click_at,
  max(created_at) AS last_click_at
FROM user_deep_link_log
WHERE deep_link ~ '^sc_[0-9]+_[a-z]+'
GROUP BY 1, 2
ORDER BY unique_clickers DESC, clicks DESC
LIMIT 100;
