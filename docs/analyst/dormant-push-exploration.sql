-- One row per section, JSON aggregate only. Run with -v as_of='2027-02-01T00:00:00Z'.
-- The primary clock is first assignment, including every dispatch state in ITT.
-- accepted_at is a Telegram receipt, independent of reaction bookkeeping.
\if :{?as_of}
\else
\set as_of 'now'
\endif
WITH ranked AS (
    SELECT p.*, row_number() OVER (
        PARTITION BY p.user_id ORDER BY p.assigned_at, p.id
    ) AS occurrence_number
    FROM push_content_opportunity p
    JOIN v_metric_user mu ON mu.user_id = p.user_id AND mu.segment <> 'excluded'
    WHERE p.campaign = 'dormant_push_exploration_v1' AND p.enrolled
      AND p.assigned_at < :'as_of'::timestamptz AT TIME ZONE 'UTC'
), first AS MATERIALIZED (
    SELECT r.*, u.blocked_bot_at,
           r.assigned_at + INTERVAL '24 hours' <=
               (:'as_of'::timestamptz AT TIME ZONE 'UTC') AS mature_24h,
           r.assigned_at + INTERVAL '14 days' <=
               (:'as_of'::timestamptz AT TIME ZONE 'UTC') AS mature_14d
    FROM ranked r JOIN "user" u ON u.id = r.user_id
    WHERE r.occurrence_number = 1
), outcomes AS MATERIALIZED (
    SELECT f.*,
           EXISTS (
               SELECT 1 FROM user_meme_reaction r
               WHERE f.accepted_at IS NOT NULL AND r.user_id = f.user_id
                 AND r.meme_id = f.meme_id AND r.recommended_by = f.recommended_by
                 AND r.sent_at >= f.attempted_at
                 AND r.sent_at <= f.accepted_at + INTERVAL '1 minute'
           ) AS delivery_row_present,
           CASE WHEN f.mature_24h THEN EXISTS (
               SELECT 1 FROM user_meme_reaction r
               WHERE f.accepted_at IS NOT NULL AND r.user_id = f.user_id
                 AND r.meme_id = f.meme_id AND r.recommended_by = f.recommended_by
                 AND r.sent_at >= f.attempted_at
                 AND r.sent_at <= f.accepted_at + INTERVAL '1 minute'
                 AND r.reaction_id IN (1, 2) AND r.reacted_at >= r.sent_at
                 AND r.reacted_at < f.assigned_at + INTERVAL '24 hours'
           ) ELSE false END AS pressed_24h,
           CASE WHEN f.mature_14d THEN EXISTS (
               SELECT 1 FROM v_feed_session s
               WHERE s.user_id = f.user_id AND s.reactions > 0
                 AND s.session_start >= f.assigned_at + INTERVAL '7 days'
                 AND s.session_start < f.assigned_at + INTERVAL '14 days'
           ) ELSE false END AS feed_d7_14,
           f.blocked_bot_at >= f.assigned_at AND
               f.blocked_bot_at < f.assigned_at + INTERVAL '14 days' AS recorded_block_14d
    FROM first f
), arms AS (
    SELECT variant, count(*) AS enrolled_people,
           count(*) FILTER (WHERE mature_24h) AS primary_n,
           count(*) FILTER (WHERE mature_24h AND pressed_24h) AS primary_events,
           count(*) FILTER (WHERE mature_14d) AS followup_n,
           count(*) FILTER (WHERE mature_14d AND feed_d7_14) AS feed_d7_14_people,
           count(*) FILTER (WHERE mature_14d AND recorded_block_14d) AS recorded_blocks_14d,
           count(*) FILTER (WHERE accepted_at IS NOT NULL) AS accepted_people,
           count(*) FILTER (WHERE accepted_at IS NOT NULL AND NOT delivery_row_present)
               AS accepted_missing_delivery_row,
           count(*) FILTER (WHERE state = 'unknown') AS unknown_people,
           count(*) FILTER (WHERE state = 'failed') AS failed_people,
           count(*) FILTER (WHERE state = 'skipped') AS skipped_people,
           count(*) FILTER (WHERE state IN ('reserved', 'selected', 'sending')
               AND assigned_at < (:'as_of'::timestamptz AT TIME ZONE 'UTC') -
                   INTERVAL '10 minutes') AS stale_inflight_people,
           count(*) FILTER (WHERE jsonb_array_length(
               COALESCE(selection->'candidate_ids', '[]'::jsonb)) >= 2) AS multiple_candidates,
           count(*) FILTER (WHERE selection->>'fallback_reason' IS NOT NULL) AS fallback_people,
           count(*) FILTER (WHERE selection->>'chosen_index' IS NOT NULL
               AND (selection->>'chosen_index')::int > 0) AS non_top_picks,
           count(*) FILTER (WHERE selection->>'selection_probability' IS NOT NULL
               AND (selection->>'selection_probability')::double precision > 0
               AND (selection->>'selection_probability')::double precision <= 1) AS valid_propensity_people
    FROM outcomes GROUP BY variant
), rates AS (
    SELECT *, primary_events::double precision / NULLIF(primary_n, 0) AS rate
    FROM arms
), difference AS (
    SELECT e.primary_n AS explore_n, h.primary_n AS hq_n,
           e.rate - h.rate AS difference,
           sqrt(e.rate * (1 - e.rate) / NULLIF(e.primary_n, 0) +
               h.rate * (1 - h.rate) / NULLIF(h.primary_n, 0)) AS standard_error
    FROM rates e CROSS JOIN rates h WHERE e.variant = 'explore' AND h.variant = 'hq'
)
SELECT 'arm' AS section, to_jsonb(r) AS result FROM rates r
UNION ALL
SELECT 'primary_difference', jsonb_build_object(
    'explore_n', explore_n, 'hq_n', hq_n, 'explore_minus_hq', difference,
    'approximate_95ci_low', difference - 1.96 * standard_error,
    'approximate_95ci_high', difference + 1.96 * standard_error,
    'minimum_sample_reached', explore_n >= 200 AND hq_n >= 200
) FROM difference
UNION ALL
SELECT 'dispatch_states', jsonb_build_object('variant', variant, 'state', state,
    'opportunities', count(*), 'enrolled_opportunities', count(*) FILTER (WHERE enrolled),
    'accepted', count(*) FILTER (WHERE accepted_at IS NOT NULL),
    'attempted', count(*) FILTER (WHERE attempted_at IS NOT NULL),
    'forbidden', count(*) FILTER (WHERE error_code = 'forbidden'))
FROM push_content_opportunity p
JOIN v_metric_user mu ON mu.user_id = p.user_id AND mu.segment <> 'excluded'
WHERE campaign = 'dormant_push_exploration_v1'
  AND assigned_at < :'as_of'::timestamptz AT TIME ZONE 'UTC'
GROUP BY variant, state
ORDER BY section, result;
