-- Frozen decision readout for explore_budget_v1. Read-only, aggregate output.
-- Run from the repository root: psql "$ANALYST_DATABASE_URL" -X -v ON_ERROR_STOP=1 -f docs/analyst/explore-budget-decision.sql
-- Defaults to the November 20 decision cutoff and the tracked file of restored IDs.
-- Override as_of (UTC) and restored_ids when the psql client runs on another host.
-- This example sends both parameters and SQL through stdin, so it also works
-- with an established read-only psql wrapper that accepts stdin only:
--
-- python3 - <<'PY' | psql "$ANALYST_DATABASE_URL" -X -v ON_ERROR_STOP=1
-- from pathlib import Path
-- ids = [int(line) for line in Path(
--     'docs/analyst/data/2026-10-31-dedup-restored-meme-ids.txt'
-- ).read_text().splitlines() if line.strip()]
-- print("\\set as_of '2026-11-20 23:59:59'")
-- print("\\set restored_ids '{" + ','.join(map(str, ids)) + "}'")
-- print(Path('docs/analyst/explore-budget-decision.sql').read_text())
-- PY
--
-- Primary excludes sends of the restored memes. all_sends retains them for the
-- prespecified sensitivity analysis. Both exclude broadcasts and automated users.
-- Each scenario includes users with at least one qualifying feed send. Session
-- boundaries are computed after that scenario's exclusions, using a >30m gap.
-- Likes and reactions must have occurred before as_of. Observation time starts
-- at first assignment, with the original one-day minimum exposure denominator.
-- User roles, meme/reaction records and exclusion membership can change later,
-- so a historical cutoff is a reconstruction from the current stored records.
-- Protocol: experiments/2026-10-30-explore-budget.md.
\if :{?as_of}
\else
\set as_of '2026-11-20 23:59:59'
\endif
\if :{?restored_ids}
\else
\set restored_ids `python3 -c "from pathlib import Path; ids=Path('docs/analyst/data/2026-10-31-dedup-restored-meme-ids.txt').read_text().split(); assert len(set(ids)) == len(ids) == 7762; print('{'+','.join(str(int(x)) for x in ids)+'}')"`
\endif
WITH params AS (
    SELECT
        :'as_of'::timestamp AS cutoff,
        :'restored_ids'::int[] AS restored_ids
),
assigned AS MATERIALIZED (
    SELECT
        ea.user_id,
        ea.assigned_at,
        ea.variant,
        CASE WHEN mu.segment IN ('moderator', 'admin') THEN 'mod' ELSE 'user' END AS seg
    FROM experiment_assignment ea
    JOIN v_metric_user mu USING (user_id)
    CROSS JOIN params
    WHERE ea.experiment_id = 'explore_budget_v1'
        AND mu.segment <> 'excluded'
        AND ea.assigned_at < params.cutoff
),
sends AS MATERIALIZED (
    SELECT
        a.*,
        r.sent_at,
        r.reacted_at,
        r.meme_id,
        r.reaction_id,
        r.recommended_by,
        r.recommended_by LIKE 'broadcast%' AS is_push,
        r.meme_id = ANY(params.restored_ids) AS restored
    FROM assigned a
    JOIN user_meme_reaction r
        ON r.user_id = a.user_id
        AND r.sent_at >= a.assigned_at
    CROSS JOIN params
    WHERE r.sent_at < params.cutoff
),
feed AS (
    SELECT
        scenario,
        variant,
        seg,
        user_id,
        assigned_at,
        sent_at,
        reaction_id,
        reacted_at,
        recommended_by,
        restored,
        COALESCE(
            sent_at - LAG(sent_at) OVER (
                PARTITION BY scenario, user_id ORDER BY sent_at, meme_id
            ) > INTERVAL '30 minutes',
            TRUE
        ) AS session_start
    FROM sends
    CROSS JOIN (VALUES ('primary'), ('all_sends')) scenarios(scenario)
    WHERE NOT is_push
        AND (scenario = 'all_sends' OR NOT restored)
),
per_user AS (
    SELECT
        scenario,
        variant,
        seg,
        user_id,
        COUNT(*) AS feed_sends,
        COUNT(*) FILTER (WHERE session_start) AS sessions,
        COUNT(*) FILTER (
            WHERE reaction_id = 1 AND reacted_at < (SELECT cutoff FROM params)
        ) AS likes,
        COUNT(*) FILTER (
            WHERE reaction_id IS NOT NULL AND reacted_at < (SELECT cutoff FROM params)
        ) AS reactions,
        COUNT(*) FILTER (WHERE recommended_by = 'low_sent_pool') AS low_sent,
        COUNT(*) FILTER (WHERE recommended_by = 'fresh_viral') AS fresh_viral,
        COUNT(*) FILTER (WHERE recommended_by = 'last_resort') AS last_resort,
        COUNT(*) FILTER (WHERE recommended_by = 'low_sent_pool' AND restored) AS restored_low,
        GREATEST(
            EXTRACT(EPOCH FROM (SELECT cutoff FROM params) - MIN(assigned_at)) / 604800.0,
            1.0 / 7
        ) AS weeks
    FROM feed
    GROUP BY scenario, variant, seg, user_id
)
SELECT
    scenario,
    seg,
    variant,
    COUNT(*) AS n,
    SUM(feed_sends) AS sends,
    SUM(sessions) AS sessions,
    AVG(likes / weeks) AS likes_user_wk,
    AVG(feed_sends::numeric / sessions) AS memes_session,
    AVG(likes::numeric / NULLIF(reactions, 0)) AS like_rate,
    SUM(low_sent)::float / SUM(feed_sends) AS low_sent_share,
    SUM(fresh_viral)::float / SUM(feed_sends) AS fresh_share,
    SUM(last_resort) AS last_resort_sends,
    SUM(restored_low) AS restored_low_sent,
    SUM(low_sent) AS low_sent_sends
FROM per_user
GROUP BY scenario, seg, variant
ORDER BY scenario, seg, variant;
