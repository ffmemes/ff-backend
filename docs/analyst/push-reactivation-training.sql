-- Historical push-response examples, SELECT-only. No production writes.
-- Run with psql -X --csv -v ON_ERROR_STOP=1 -v as_of=YYYY-MM-DD -v days=7
--   -v salt=<fresh random value of at least 16 characters> -f this-file.sql
-- as_of is exclusive UTC observation midnight. Deliveries are selected in
-- [as_of - 1 day - days, as_of - 1 day), with complete 24h outcome windows.
-- Adjacent as_of values separated by days produce contiguous delivery chunks.
-- Use consecutive chunks with the SAME ephemeral salt for one local model run.
-- Destroy the salt after the run. Never commit exported examples or the salt.
--
-- Count/rate features use exactly [decision - 35 days, decision), independent
-- of chunk size. They are bounded-history features, not lifetime rates.
-- Offset RANGE windows exclude events at the decision timestamp strictly.
-- Source/content quality uses ordinary
-- feed events only. friend_challenge and uploaded_meme rows are excluded
-- because uploaded_meme also records author auto-likes. Historical direct
-- deliveries with this ambiguous label are consequently omitted.
-- User activity and push outcomes use their actual callback
-- timestamps, not send-date attribution from v_user_day.
--
-- Historical limitation: reaction corrections overwrite reacted_at/reaction_id.
-- Original first callbacks and historical reaction values cannot be recovered.
-- This extraction uses the last surviving valid callback and cannot erase that
-- retrospective measurement error. Mutable meme/source mapping is also current.
-- A delivered row records accepted Telegram delivery, not a known human view.
--
-- Idle time also uses one indexed prior-callback seek per target user, covering
-- the 365 days preceding the chunk. This seed affects idle only, never counts.
-- The final idle timestamp must also be within 365 days before its own decision.
-- No observed callback in either history means censored_unknown. Primary >=7d
-- analysis requires observed idle_days, with unknown opportunities reported.
-- legacy_proxy_score is affinity x posterior feed-like-rate. Historical
-- lr_smoothed snapshots are absent, so it does not replay the deployed picker.
-- User features are observational and do not estimate incremental send uplift.
-- Prospective v2 taste features are available only for observed idle >=7d.
-- Per opportunity, cap at the last 200 genuine feed callbacks in the preceding
-- 365 days before aggregation. Ties use reacted_at, sent_at, meme_id descending.
-- This uses the user_id/reacted_at index with a bounded top-N seek. Source
-- identity has the same current-mapping limitation as other source features.
-- Counts are explicit, rates use Beta(1,1); non-dormant/unknown rows get NULL.
-- Content age assumes stored meme.created_at is the immutable creation time,
-- and media type is stable. Age is NULL when creation follows the historical
-- send. OCR, mutable language and current aggregate quality are not features.
--
-- Runtime: one bounded history extraction and four partition orderings.
-- There are no per-opportunity full-history scans. Start with days=7 under the
-- analyst statement timeout. Params require days 1..31 and salt length >=16;
-- invalid ranges return zero rows. SQL timestamp columns are UTC without zone.
\set ON_ERROR_STOP on
WITH params AS MATERIALIZED (
    SELECT :'as_of'::date::timestamp AS as_of,
           :'as_of'::date::timestamp - INTERVAL '1 day' AS end_at,
           :'as_of'::date::timestamp - (:'days'::int + 1) * INTERVAL '1 day' AS start_at,
           :'as_of'::date::timestamp - (:'days'::int + 36) * INTERVAL '1 day' AS history_at,
           :'salt'::text AS salt
    WHERE :'days'::int BETWEEN 1 AND 31 AND length(:'salt') >= 16
),
ordinary_users AS MATERIALIZED (
    SELECT user_id FROM v_metric_user WHERE segment = 'user'
),
opportunities AS MATERIALIZED (
    SELECT r.user_id, r.meme_id, m.meme_source_id AS source_id,
           r.sent_at, r.recommended_by AS path,
           (r.reaction_id IN (1, 2)
            AND r.reacted_at >= r.sent_at
            AND r.reacted_at < r.sent_at + INTERVAL '24 hours')::int AS outcome
    FROM params p
    JOIN user_meme_reaction r
      ON r.sent_at >= p.start_at AND r.sent_at < p.end_at
     AND r.sent_at + INTERVAL '24 hours' <= p.as_of
    JOIN ordinary_users u ON u.user_id = r.user_id
    JOIN meme m ON m.id = r.meme_id
    WHERE r.recommended_by IN ('broadcast_reengagement', 'broadcast_reengagement_hq')
),
user_activity_seed AS MATERIALIZED (
    SELECT target.user_id, prior.reacted_at AS seed_callback_at
    FROM (SELECT DISTINCT user_id FROM opportunities) target
    CROSS JOIN params p
    LEFT JOIN LATERAL (
        SELECT r.reacted_at
        FROM user_meme_reaction r
        WHERE r.user_id = target.user_id
          AND r.reacted_at IS NOT NULL
          AND r.reacted_at < p.history_at
          AND r.reacted_at >= p.start_at - INTERVAL '365 days'
          AND r.reacted_at >= r.sent_at
          AND r.reaction_id IN (1, 2)
          AND r.recommended_by NOT IN ('friend_challenge', 'uploaded_meme')
        ORDER BY r.reacted_at DESC
        LIMIT 1
    ) prior ON true
),
history AS MATERIALIZED (
    SELECT r.user_id, r.meme_id, m.meme_source_id AS source_id,
           r.sent_at, r.reacted_at, r.reaction_id,
           r.recommended_by LIKE 'broadcast%' AS is_push,
           r.recommended_by IN ('broadcast_reengagement', 'broadcast_reengagement_hq')
               AS is_target_push
    FROM params p
    JOIN user_meme_reaction r
      ON r.sent_at < p.as_of
     AND (r.sent_at >= p.history_at - INTERVAL '24 hours'
          OR r.reacted_at >= p.history_at)
    JOIN ordinary_users u ON u.user_id = r.user_id
    JOIN meme m ON m.id = r.meme_id
    WHERE r.recommended_by NOT IN ('friend_challenge', 'uploaded_meme')
),
events AS (
    -- Accepted deliveries. The extra day in history is only for maturity events.
    SELECT h.user_id, h.meme_id, h.source_id, h.sent_at AS event_at,
           false AS opportunity, NULL::text AS path,
           NULL::int AS outcome,
           (NOT h.is_push)::int AS feed_send,
           h.is_push::int AS push_send,
           0 AS callback, 0 AS feed_callback, 0 AS feed_like,
           0 AS mature_push, 0 AS successful_push
    FROM history h CROSS JOIN params p
    WHERE h.sent_at >= p.history_at
    UNION ALL
    -- Only callbacks already observable at the decision can affect features.
    SELECT h.user_id, h.meme_id, h.source_id, h.reacted_at,
           false, NULL::text, NULL::int,
           0, 0, 1, (NOT h.is_push)::int,
           (NOT h.is_push AND h.reaction_id = 1)::int, 0, 0
    FROM history h CROSS JOIN params p
    WHERE h.reaction_id IN (1, 2)
      AND h.reacted_at >= h.sent_at
      AND h.reacted_at >= p.history_at AND h.reacted_at < p.as_of
    UNION ALL
    -- A past push enters its rate denominator only after its full 24h window.
    SELECT h.user_id, h.meme_id, h.source_id, h.sent_at + INTERVAL '24 hours',
           false, NULL::text, NULL::int,
           0, 0, 0, 0, 0, 1,
           COALESCE((h.reaction_id IN (1, 2)
             AND h.reacted_at >= h.sent_at
             AND h.reacted_at < h.sent_at + INTERVAL '24 hours')::int, 0)
    FROM history h CROSS JOIN params p
    WHERE h.is_target_push
      AND h.sent_at + INTERVAL '24 hours' >= p.history_at
      AND h.sent_at + INTERVAL '24 hours' < p.as_of
    UNION ALL
    SELECT o.user_id, o.meme_id, o.source_id, o.sent_at,
           true, o.path, COALESCE(o.outcome, 0),
           0, 0, 0, 0, 0, 0, 0
    FROM opportunities o
),
features AS (
    SELECT e.*,
           COALESCE(sum(push_send) OVER wu, 0) AS user_push_send_count,
           COALESCE(sum(mature_push) OVER wu, 0) AS user_push_count,
           COALESCE(sum(successful_push) OVER wu, 0) AS user_push_success_count,
           COALESCE(sum(feed_callback) OVER wu, 0) AS user_feed_callback_count,
           max(event_at) FILTER (WHERE callback = 1) OVER wu_idle AS observed_last_callback_at,
           max(event_at) FILTER (WHERE push_send = 1) OVER wu_idle AS observed_last_push_at,
           COALESCE(sum(feed_callback) OVER wus, 0) AS user_source_reaction_count,
           COALESCE(sum(feed_like) OVER wus, 0) AS user_source_like_count,
           COALESCE(sum(feed_send) OVER wm, 0) AS meme_send_count,
           COALESCE(sum(feed_callback) OVER wm, 0) AS meme_reaction_count,
           COALESCE(sum(feed_like) OVER wm, 0) AS meme_like_count,
           COALESCE(sum(feed_send) OVER ws, 0) AS source_send_count,
           COALESCE(sum(feed_callback) OVER ws, 0) AS source_reaction_count,
           COALESCE(sum(feed_like) OVER ws, 0) AS source_like_count
    FROM events e
    WINDOW
      wu AS (PARTITION BY user_id ORDER BY event_at
             RANGE BETWEEN INTERVAL '35 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING),
      wus AS (PARTITION BY user_id, source_id ORDER BY event_at
              RANGE BETWEEN INTERVAL '35 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING),
      wm AS (PARTITION BY meme_id ORDER BY event_at
             RANGE BETWEEN INTERVAL '35 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING),
      ws AS (PARTITION BY source_id ORDER BY event_at
             RANGE BETWEEN INTERVAL '35 days' PRECEDING AND INTERVAL '1 microsecond' PRECEDING),
      wu_idle AS (PARTITION BY user_id ORDER BY event_at
                  RANGE BETWEEN UNBOUNDED PRECEDING AND INTERVAL '1 microsecond' PRECEDING)
),
with_idle AS (
    SELECT f.*,
           CASE WHEN greatest(f.observed_last_callback_at, seed.seed_callback_at)
                          >= f.event_at - INTERVAL '365 days'
                THEN greatest(f.observed_last_callback_at, seed.seed_callback_at)
           END AS last_callback_at,
           CASE WHEN f.observed_last_push_at >= f.event_at - INTERVAL '35 days'
                THEN f.observed_last_push_at END AS last_push_at
    FROM features f
    LEFT JOIN user_activity_seed seed ON seed.user_id = f.user_id
    WHERE opportunity
),
examples AS (
    SELECT f.*,
           EXTRACT(EPOCH FROM (event_at - last_callback_at)) / 86400.0 AS idle_days,
           (user_source_like_count + 1.0) / (user_source_reaction_count + 2.0)
               AS user_source_like_rate,
           (meme_like_count + 1.0) / (meme_reaction_count + 2.0) AS meme_like_rate,
           (source_like_count + 1.0) / (source_reaction_count + 2.0) AS source_like_rate
    FROM with_idle f
)
SELECT md5(e.user_id::text || ':' || e.meme_id::text || ':' || p.salt) AS event_id,
       md5(e.user_id::text || ':' || p.salt) AS user_key,
       to_char(e.event_at, 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') AS sent_at,
       e.outcome AS y_24h,
       e.path,
       e.idle_days,
       CASE WHEN e.last_callback_at IS NULL THEN 'censored_unknown'
            WHEN e.idle_days < 1 THEN 'under_1d'
            WHEN e.idle_days < 7 THEN '1_to_7d'
            WHEN e.idle_days < 29 THEN '7_to_29d'
            WHEN e.idle_days < 90 THEN '29_to_90d'
            ELSE '90d_plus' END AS dormancy_cohort,
       e.user_push_send_count,
       e.user_push_count,
       (e.user_push_success_count + 1.0) / (e.user_push_count + 2.0)
           AS user_push_reaction_rate,
       e.user_feed_callback_count,
       EXTRACT(EPOCH FROM (e.event_at - e.last_push_at)) / 3600.0 AS hours_since_push,
       e.user_source_reaction_count,
       e.user_source_like_rate,
       e.meme_like_rate,
       e.meme_send_count,
       e.source_like_rate,
       e.source_send_count,
       e.user_source_like_rate * e.meme_like_rate AS legacy_proxy_score,
       CASE WHEN content.created_at <= e.event_at
            THEN EXTRACT(EPOCH FROM (e.event_at - content.created_at)) / 86400.0
       END AS meme_age_days,
       (content.type = 'video')::int AS meme_is_video,
       (content.type = 'animation')::int AS meme_is_animation,
       taste.taste_feed_count,
       taste.taste_feed_like_rate,
       taste.taste_source_count,
       taste.taste_source_like_rate
FROM examples e
JOIN meme content ON content.id = e.meme_id
LEFT JOIN LATERAL (
    SELECT COUNT(*) AS taste_feed_count,
           (COUNT(*) FILTER (WHERE recent.reaction_id = 1) + 1.0)
               / (COUNT(*) + 2.0) AS taste_feed_like_rate,
           COUNT(*) FILTER (WHERE prior_meme.meme_source_id = e.source_id)
               AS taste_source_count,
           (COUNT(*) FILTER (WHERE prior_meme.meme_source_id = e.source_id
                                  AND recent.reaction_id = 1) + 1.0)
               / (COUNT(*) FILTER (WHERE prior_meme.meme_source_id = e.source_id) + 2.0)
               AS taste_source_like_rate
    FROM (
        SELECT r.meme_id, r.reaction_id
        FROM user_meme_reaction r
        WHERE e.idle_days >= 7
          AND r.user_id = e.user_id
          AND r.reacted_at IS NOT NULL
          AND r.reacted_at < e.event_at
          AND r.reacted_at >= e.event_at - INTERVAL '365 days'
          AND r.reacted_at >= r.sent_at
          AND r.reaction_id IN (1, 2)
          AND r.recommended_by NOT LIKE 'broadcast%'
          AND r.recommended_by NOT IN ('friend_challenge', 'uploaded_meme')
        ORDER BY r.reacted_at DESC, r.sent_at DESC, r.meme_id DESC
        LIMIT 200
    ) recent
    JOIN meme prior_meme ON prior_meme.id = recent.meme_id
) taste ON e.idle_days >= 7
CROSS JOIN params p
ORDER BY e.event_at, event_id;
