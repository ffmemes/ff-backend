-- Exact-meme inline share canary readout.
--
-- Replace the timestamps below with the trial window. Always exclude the
-- current partial UTC day from final day-7 reads.
--
-- Primary:
--   non-self m_/s_ deep-link opens per 1k meme sends
-- Send proxy:
--   inline_search_chosen_result_logs rows with exact #meme_id queries
-- Guardrails:
--   like rate and continued feed consumption by assigned variant
--
-- Do not call this native Telegram forward tracking. Telegram does not expose
-- whether a user forwarded or sent the URL; we only observe later recipient
-- starts and inline chosen-result callbacks.

WITH params AS (
    SELECT
        TIMESTAMP '2026-06-16 00:00:00' AS started_at,
        TIMESTAMP '2026-06-23 00:00:00' AS ended_at
),
assignments AS (
    SELECT
        ea.user_id,
        ea.variant,
        ea.assigned_at,
        (ea.assignment_metadata->>'bucket')::int AS bucket,
        (ea.assignment_metadata->>'inline_canary_percent')::int AS inline_canary_percent
    FROM experiment_assignment ea, params p
    WHERE ea.experiment_id = 'meme_share_button'
      AND ea.assigned_at >= p.started_at
      AND ea.assigned_at < p.ended_at
),
assigned_sends AS (
    SELECT
        a.user_id,
        a.variant,
        count(*) AS meme_sends,
        count(*) FILTER (WHERE umr.reaction_id IS NOT NULL) AS reactions,
        count(*) FILTER (WHERE umr.reaction_id = 1) AS likes
    FROM assignments a
    JOIN user_meme_reaction umr
      ON umr.user_id = a.user_id
     AND umr.sent_at >= a.assigned_at
    JOIN params p ON true
    WHERE umr.sent_at >= p.started_at
      AND umr.sent_at < p.ended_at
    GROUP BY a.user_id, a.variant
),
inline_chosen AS (
    SELECT
        a.variant,
        count(*) AS exact_inline_sends,
        count(DISTINCT ic.user_id) AS exact_inline_senders
    FROM assignments a
    JOIN inline_search_chosen_result_logs ic
      ON ic.user_id = a.user_id
     AND ic.chosen_at >= a.assigned_at
    JOIN params p ON true
    WHERE ic.chosen_at >= p.started_at
      AND ic.chosen_at < p.ended_at
      AND ic.query ~ '^#[0-9]+$'
    GROUP BY a.variant
),
parsed_share_clicks AS (
    SELECT
        udll.created_at,
        udll.user_id AS clicked_user_id,
        split_part(udll.deep_link, '_', 2)::bigint AS sharer_user_id,
        split_part(udll.deep_link, '_', 3)::int AS meme_id
    FROM user_deep_link_log udll, params p
    WHERE udll.created_at >= p.started_at
      AND udll.created_at < p.ended_at
      AND udll.deep_link ~ '^[ms]_[0-9]+_[0-9]+$'
),
nonself_share_starts AS (
    SELECT
        a.variant,
        count(*) AS nonself_share_starts,
        count(DISTINCT psc.clicked_user_id) AS nonself_share_users,
        count(DISTINCT psc.sharer_user_id) AS sharers_with_nonself_starts
    FROM assignments a
    JOIN parsed_share_clicks psc
      ON psc.sharer_user_id = a.user_id
     AND psc.clicked_user_id <> psc.sharer_user_id
     AND psc.created_at >= a.assigned_at
    GROUP BY a.variant
)
SELECT
    a.variant,
    count(DISTINCT a.user_id) AS assigned_users,
    max(a.inline_canary_percent) AS inline_canary_percent,
    count(DISTINCT a.user_id) FILTER (WHERE s.meme_sends >= 1) AS users_sent_after_assignment,
    coalesce(sum(s.meme_sends), 0) AS meme_sends,
    round(100.0 * sum(s.likes) / nullif(sum(s.reactions), 0), 2) AS like_rate_pct,
    round(
        100.0 * count(DISTINCT a.user_id) FILTER (WHERE s.meme_sends >= 2)
        / nullif(count(DISTINCT a.user_id) FILTER (WHERE s.meme_sends >= 1), 0),
        2
    ) AS continued_after_first_sent_pct,
    coalesce(max(ic.exact_inline_sends), 0) AS exact_inline_sends,
    coalesce(max(ic.exact_inline_senders), 0) AS exact_inline_senders,
    coalesce(max(ns.nonself_share_starts), 0) AS nonself_share_starts,
    coalesce(max(ns.nonself_share_users), 0) AS nonself_share_users,
    coalesce(max(ns.sharers_with_nonself_starts), 0) AS sharers_with_nonself_starts,
    round(
        1000.0 * coalesce(max(ns.nonself_share_starts), 0)
        / nullif(coalesce(sum(s.meme_sends), 0), 0),
        3
    ) AS nonself_share_starts_per_1k_sends
FROM assignments a
LEFT JOIN assigned_sends s
  ON s.user_id = a.user_id
 AND s.variant = a.variant
LEFT JOIN inline_chosen ic
  ON ic.variant = a.variant
LEFT JOIN nonself_share_starts ns
  ON ns.variant = a.variant
GROUP BY a.variant
ORDER BY a.variant;
