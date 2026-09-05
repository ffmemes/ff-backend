-- Read-only readout: $1 = observed-as-of UTC timestamp; $2 = experiment ID.
-- Keep all assigned hosts in the denominator, including no exposure or sharing.
-- inviter_id is set in the NEW-user branch. This is an account-creation proxy,
-- not proof of first-ever Telegram contact. No friend-challenge tables required.
-- Reaction/delivery rows are mutable user×meme states, not immutable events.
WITH seeds AS MATERIALIZED (
    SELECT a.user_id, a.variant,
           (a.assignment_metadata->>'experiment_start_at')::timestamptz
               AT TIME ZONE 'UTC' AS start_at,
           (a.assignment_metadata->>'exposure_end_at')::timestamptz
               AT TIME ZONE 'UTC' AS end_at,
           (a.assignment_metadata->>'reactions_28d')::bigint AS baseline_reactions_28d,
           (a.assignment_metadata->>'active_days_28d')::integer AS baseline_days_28d
    FROM experiment_assignment a WHERE a.experiment_id = $2
), guests AS MATERIALIZED (
    SELECT g.id AS user_id, g.inviter_id, g.created_at, s.variant,
           $1::timestamp >= g.created_at + interval '14 days' AS followup_complete
    FROM "user" g JOIN seeds s ON s.user_id = g.inviter_id
    WHERE g.id <> g.inviter_id AND g.created_at >= s.start_at
      AND g.created_at < s.end_at AND g.created_at < $1::timestamp
), guest_outcomes AS MATERIALIZED (
    SELECT g.*, r.normal_memes_d7_13
    FROM guests g CROSS JOIN LATERAL (
        SELECT count(DISTINCT r.meme_id) AS normal_memes_d7_13
        FROM user_meme_reaction r
        WHERE r.user_id = g.user_id AND r.reaction_id IN (1, 2)
          AND r.reacted_at >= g.created_at + interval '7 days'
          AND r.reacted_at < g.created_at + interval '14 days'
          AND r.reacted_at < $1::timestamp
          AND r.recommended_by NOT IN ('uploaded_meme', 'low_sent_pool', 'friend_challenge')
          AND r.recommended_by NOT LIKE 'broadcast%'
          AND r.recommended_by NOT LIKE 'friend_challenge%'
    ) r
), link_events AS MATERIALIZED (
    SELECT s.user_id AS seed_id, s.variant, l.user_id AS recipient_id
    FROM user_deep_link_log l JOIN seeds s
      ON split_part(l.deep_link, '_', 2) = s.user_id::text
    WHERE l.deep_link ~ '^[ms]_[0-9]+_[0-9]+$'
      AND l.user_id <> s.user_id
      AND l.created_at >= s.start_at AND l.created_at < s.end_at
      AND l.created_at < $1::timestamp
), link_by_arm AS (
    SELECT variant, count(*) AS nonself_start_events,
           count(DISTINCT recipient_id) AS unique_nonself_recipients,
           count(DISTINCT seed_id) AS seeds_with_nonself_start
    FROM link_events GROUP BY variant
), per_seed AS (
    SELECT s.*, u.blocked_bot_at,
           g.new_invitees, g.mature_invitees, g.retained_invitees,
           d.feed_delivery_rows, d.hit_delivery_rows, d.hit_delivery_days,
           h.normal_reactions, h.normal_likes, h.normal_active_days,
           h.normal_reactions_d7_13
    FROM seeds s JOIN "user" u ON u.id = s.user_id
    CROSS JOIN LATERAL (
        SELECT count(*) AS new_invitees,
               count(*) FILTER (WHERE followup_complete) AS mature_invitees,
               count(*) FILTER (WHERE followup_complete AND normal_memes_d7_13 >= 3)
                   AS retained_invitees
        FROM guest_outcomes g WHERE g.inviter_id = s.user_id
    ) g
    CROSS JOIN LATERAL (
        SELECT count(*) AS feed_delivery_rows,
               count(*) FILTER (WHERE recommended_by = 'channel_hit_v1') AS hit_delivery_rows,
               count(DISTINCT r.sent_at::date) FILTER (
                   WHERE recommended_by = 'channel_hit_v1'
               ) AS hit_delivery_days
        FROM user_meme_reaction r
        WHERE r.user_id = s.user_id AND r.sent_at >= s.start_at
          AND r.sent_at < s.end_at AND r.sent_at < $1::timestamp
          AND r.recommended_by NOT IN ('uploaded_meme', 'low_sent_pool', 'friend_challenge')
          AND r.recommended_by NOT LIKE 'broadcast%'
          AND r.recommended_by NOT LIKE 'friend_challenge%'
    ) d
    CROSS JOIN LATERAL (
        SELECT count(*) AS normal_reactions,
               count(*) FILTER (WHERE reaction_id = 1) AS normal_likes,
               count(DISTINCT r.reacted_at::date) AS normal_active_days,
               count(*) FILTER (WHERE r.reacted_at >= s.start_at + interval '7 days')
                   AS normal_reactions_d7_13
        FROM user_meme_reaction r
        WHERE r.user_id = s.user_id AND r.reaction_id IN (1, 2)
          AND r.reacted_at >= s.start_at AND r.reacted_at < s.end_at
          AND r.reacted_at < $1::timestamp
          AND r.recommended_by NOT IN ('uploaded_meme', 'low_sent_pool', 'friend_challenge')
          AND r.recommended_by NOT LIKE 'broadcast%'
          AND r.recommended_by NOT LIKE 'friend_challenge%'
    ) h
), arms AS (
    SELECT variant, count(*) AS assigned_users,
           count(*) FILTER (WHERE hit_delivery_rows > 0) AS exposed_users,
           sum(hit_delivery_rows)::bigint AS hit_delivery_rows,
           sum(hit_delivery_days)::bigint AS hit_delivery_user_days,
           sum(feed_delivery_rows)::bigint AS normal_feed_delivery_rows,
           round(sum(hit_delivery_rows)::numeric / nullif(sum(feed_delivery_rows), 0), 4)
               AS observed_hit_delivery_fraction,
           sum(new_invitees)::bigint AS new_invitees,
           sum(mature_invitees)::bigint AS mature_invitees,
           sum(new_invitees - mature_invitees)::bigint AS pending_invitee_followups,
           sum(retained_invitees)::bigint AS retained_invitees,
           round(100.0 * sum(retained_invitees) / count(*), 4)
               AS retained_invitees_per_100_assigned,
           count(*) FILTER (WHERE retained_invitees > 0) AS successful_inviters,
           count(*) FILTER (WHERE normal_reactions_d7_13 > 0) AS hosts_active_d7_13,
           round(count(*) FILTER (WHERE normal_reactions_d7_13 > 0)::numeric / count(*), 4)
               AS host_active_d7_13_fraction,
           sum(normal_reactions)::bigint AS host_normal_reactions_14d,
           sum(normal_active_days)::bigint AS host_normal_active_days_14d,
           round(sum(normal_likes)::numeric / nullif(sum(normal_reactions), 0), 4)
               AS host_like_fraction_among_reactions,
           sum(baseline_reactions_28d)::bigint AS baseline_reactions_28d,
           sum(baseline_days_28d)::bigint AS baseline_days_28d,
           round(2.0 * sum(normal_reactions) / nullif(sum(baseline_reactions_28d), 0), 4)
               AS host_reaction_rate_vs_baseline,
           count(*) FILTER (WHERE blocked_bot_at >= start_at AND blocked_bot_at < end_at
                             AND blocked_bot_at < $1::timestamp)
               AS hosts_currently_marked_blocked_d0_13
    FROM per_seed GROUP BY variant
)
SELECT a.*, coalesce(l.nonself_start_events, 0) AS nonself_start_events,
       coalesce(l.unique_nonself_recipients, 0) AS unique_nonself_recipients,
       coalesce(l.seeds_with_nonself_start, 0) AS seeds_with_nonself_start
FROM arms a LEFT JOIN link_by_arm l USING (variant) ORDER BY variant;
