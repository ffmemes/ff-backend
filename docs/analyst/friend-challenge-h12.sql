-- Friend challenge H12 readout ("Пять мемов для друга"). Read-only.
-- Design: docs/growth/2026-09-05-friend-meme-challenge.md
--
-- Senders = experiment_assignment rows for friend_challenge_h12 (eligible users,
-- sha256 90% treatment / 10% holdout, assigned on their first like after enable).
-- Every assigned sender stays in the denominator, including non-sharers.
-- Invitee = user whose user.inviter_id is the sender (meme-share links AND
-- challenge links write the same column, once, at registration) and who was
-- created after the sender's assignment. Each new user counts once.
-- Primary: invitees with >=3 distinct normal-feed memes reacted on days 7-13
-- after their first start, per 100 assigned senders. Only matured invitees
-- (>=14 days old) can count, pending_invitees shows the rest.
-- Timestamps are naive UTC.
WITH senders AS MATERIALIZED (
    SELECT ea.user_id, ea.variant, ea.assigned_at,
           ea.assignment_metadata ? 'offered_at' AS offered
    FROM experiment_assignment ea
    WHERE ea.experiment_id = 'friend_challenge_h12'
), invitees AS MATERIALIZED (
    SELECT s.variant, s.user_id AS sender_id, u.id AS invitee_id, u.created_at,
           u.blocked_bot_at,
           (NOW() AT TIME ZONE 'UTC') >= u.created_at + interval '14 days' AS matured,
           EXISTS (
               SELECT 1 FROM friend_challenge_participation p
               JOIN friend_challenge_pack k ON k.id = p.pack_id
               WHERE p.user_id = u.id AND k.owner_id = s.user_id
           ) AS via_challenge,
           (
               SELECT count(DISTINCT r.meme_id)
               FROM user_meme_reaction r
               WHERE r.user_id = u.id AND r.reaction_id IS NOT NULL
                 AND r.reacted_at >= u.created_at + interval '7 days'
                 AND r.reacted_at < u.created_at + interval '14 days'
                 AND coalesce(r.recommended_by, '') NOT IN
                     ('friend_challenge', 'uploaded_meme', 'low_sent_pool')
                 AND coalesce(r.recommended_by, '') NOT LIKE 'broadcast%'
           ) AS feed_memes_d7_13
    FROM senders s
    JOIN "user" u ON u.inviter_id = s.user_id AND u.created_at >= s.assigned_at
), packs AS (
    SELECT s.variant,
           count(DISTINCT k.id) AS challenges_created,
           count(p.user_id) AS friend_starts,
           count(p.user_id) FILTER (WHERE p.completed_at IS NOT NULL) AS friend_completions,
           count(p.user_id) FILTER (WHERE ru.blocked_bot_at IS NOT NULL) AS recipients_blocked
    FROM senders s
    JOIN friend_challenge_pack k ON k.owner_id = s.user_id AND k.confirmed_at IS NOT NULL
    LEFT JOIN friend_challenge_participation p ON p.pack_id = k.id
    LEFT JOIN "user" ru ON ru.id = p.user_id
    GROUP BY s.variant
), per_variant AS (
    SELECT variant, count(*) AS assigned_senders,
           count(*) FILTER (WHERE offered) AS offered_senders
    FROM senders
    GROUP BY variant
), invitee_stats AS (
    SELECT variant,
           count(*) AS new_invitees,
           count(*) FILTER (WHERE via_challenge) AS new_invitees_via_challenge,
           count(*) FILTER (WHERE NOT matured) AS pending_invitees,
           count(*) FILTER (WHERE matured AND feed_memes_d7_13 >= 3) AS retained_invitees,
           count(DISTINCT sender_id) FILTER (
               WHERE matured AND feed_memes_d7_13 >= 3
           ) AS senders_with_retained_invitee
    FROM invitees
    GROUP BY variant
)
SELECT v.variant,
       v.assigned_senders,
       v.offered_senders,
       coalesce(i.new_invitees, 0) AS new_invitees,
       coalesce(i.new_invitees_via_challenge, 0) AS new_invitees_via_challenge,
       coalesce(i.pending_invitees, 0) AS pending_invitees,
       coalesce(i.retained_invitees, 0) AS retained_invitees,
       coalesce(i.senders_with_retained_invitee, 0) AS senders_with_retained_invitee,
       round(100.0 * coalesce(i.retained_invitees, 0) / v.assigned_senders, 2)
           AS retained_invitees_per_100_senders,
       coalesce(p.challenges_created, 0) AS challenges_created,
       round(100.0 * coalesce(p.challenges_created, 0) / v.assigned_senders, 2)
           AS challenges_per_100_eligible,
       coalesce(p.friend_starts, 0) AS friend_starts,
       round(coalesce(p.friend_starts, 0)::numeric / nullif(p.challenges_created, 0), 2)
           AS friend_starts_per_challenge,
       coalesce(p.friend_completions, 0) AS friend_completions,
       round(100.0 * coalesce(p.recipients_blocked, 0) / nullif(p.friend_starts, 0), 1)
           AS recipient_block_rate_pct
FROM per_variant v
LEFT JOIN invitee_stats i ON i.variant = v.variant
LEFT JOIN packs p ON p.variant = v.variant
ORDER BY v.variant;

-- Ambitious target (bot-wide, run separately): new users activated per week,
-- activated = >=5 reactions in the first 7 days after registration.
-- SELECT date_trunc('week', u.created_at)::date AS week,
--        count(*) AS new_users,
--        count(*) FILTER (WHERE a.n >= 5) AS activated_users
-- FROM "user" u
-- CROSS JOIN LATERAL (
--     SELECT count(*) AS n FROM user_meme_reaction r
--     WHERE r.user_id = u.id AND r.reaction_id IS NOT NULL
--       AND r.reacted_at < u.created_at + interval '7 days'
-- ) a
-- WHERE u.created_at >= (NOW() AT TIME ZONE 'UTC') - interval '12 weeks'
-- GROUP BY 1 ORDER BY 1;
