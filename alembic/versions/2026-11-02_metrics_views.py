"""Shared metrics layer: analytics_excluded_user + v_* views.

THE metric definitions for agents and experiment readouts
(docs/analyst/north_star.sql). Plain views; filter on their date columns.
Feed vs push: recommended_by LIKE 'broadcast%' is a push, everything else feed.
analytics_excluded_user is filled on prod by an operator
(docs/analyst/excluded-users-detector.sql), never by migrations.

Revision ID: a7c3e9f1b5d2
Revises: e5a7c9b1d3f4
Create Date: 2026-11-02
"""

from alembic import op

revision = "a7c3e9f1b5d2"
down_revision = "e5a7c9b1d3f4"
branch_labels = None
depends_on = None

EXCLUDED_TABLE = """
CREATE TABLE IF NOT EXISTS analytics_excluded_user (
    user_id BIGINT PRIMARY KEY,
    reason TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT now()
)
"""

# (name, select) in dependency order.
VIEWS = [
    (
        "v_metric_user",
        """
SELECT
    U.id AS user_id,
    CASE
        WHEN X.user_id IS NOT NULL THEN 'excluded'
        WHEN U.type IN ('moderator', 'admin', 'super_user') THEN U.type
        ELSE 'user'
    END AS segment,
    U.created_at AS signup_at,
    U.created_at::date AS signup_date,
    -- First /start deep link within a day of signup; 'unknown' = no log row
    -- (users older than the deep-link log).
    CASE
        WHEN DL.user_id IS NULL THEN 'unknown'
        WHEN DL.deep_link IS NULL THEN 'organic'
        WHEN DL.deep_link ~ '^[ms]_[0-9]+_[0-9]+$' THEN 'share'
        WHEN DL.deep_link LIKE 'sc\\_%' THEN 'channel'
        ELSE COALESCE(SUBSTRING(DL.deep_link FROM '^[A-Za-z]+'), 'other')
    END AS acquisition_channel,
    L.languages
FROM "user" U
LEFT JOIN analytics_excluded_user X
    ON X.user_id = U.id
LEFT JOIN (
    SELECT DISTINCT ON (user_id) user_id, deep_link, created_at
    FROM user_deep_link_log
    ORDER BY user_id, created_at, id
) DL
    ON DL.user_id = U.id
    AND DL.created_at < U.created_at + INTERVAL '1 day'
LEFT JOIN LATERAL (
    SELECT STRING_AGG(UL.language_code, ',' ORDER BY UL.language_code) AS languages
    FROM user_language UL
    WHERE UL.user_id = U.id
) L ON TRUE
""",
    ),
    (
        "v_feed_session",
        # A feed send starts a session when the same user had no feed send in
        # the previous 30 minutes. Filter on session_start (pushes to sent_at).
        """
SELECT
    S.user_id,
    S.sent_at AS session_start,
    X.memes_sent,
    X.reactions,
    X.likes,
    EXISTS (
        SELECT 1
        FROM user_meme_reaction P
        WHERE P.user_id = S.user_id
            AND P.recommended_by LIKE 'broadcast%'
            AND P.reacted_at >= S.sent_at - INTERVAL '30 minutes'
            AND P.reacted_at <= S.sent_at
            -- Opened soon after delivery. Idle users always have a push as the
            -- last chat message, so without this every return looks push-driven.
            AND P.reacted_at - P.sent_at <= INTERVAL '15 minutes'
    ) AS started_by_push
FROM user_meme_reaction S
-- LATERAL ... LIMIT 1, not NOT EXISTS: keeps the planner on per-row index
-- probes instead of hashing the whole table when the date filter misestimates.
LEFT JOIN LATERAL (
    SELECT 1 AS hit
    FROM user_meme_reaction P
    WHERE P.user_id = S.user_id
        AND P.recommended_by NOT LIKE 'broadcast%'
        AND P.sent_at >= S.sent_at - INTERVAL '30 minutes'
        AND P.sent_at <= S.sent_at
        AND (P.sent_at < S.sent_at OR P.meme_id < S.meme_id)
    LIMIT 1
) PREV ON TRUE
LEFT JOIN LATERAL (
    -- ponytail: sessions are capped at 24h; raise the cap if a real user
    -- ever scrolls longer without a 30-minute break.
    SELECT
        COUNT(*)::int AS memes_sent,
        COUNT(G.reaction_id)::int AS reactions,
        COUNT(*) FILTER (WHERE G.reaction_id = 1)::int AS likes
    FROM (
        SELECT
            B.reaction_id,
            SUM(B.gap) OVER (ORDER BY B.sent_at, B.meme_id) AS breaks
        FROM (
            SELECT
                R.sent_at,
                R.meme_id,
                R.reaction_id,
                CASE
                    WHEN R.sent_at - LAG(R.sent_at) OVER (ORDER BY R.sent_at, R.meme_id)
                        > INTERVAL '30 minutes'
                    THEN 1 ELSE 0
                END AS gap
            FROM user_meme_reaction R
            WHERE R.user_id = S.user_id
                AND R.recommended_by NOT LIKE 'broadcast%'
                AND R.sent_at >= S.sent_at
                AND R.sent_at < S.sent_at + INTERVAL '1 day'
        ) B
    ) G
    WHERE G.breaks = 0
) X ON TRUE
WHERE S.recommended_by NOT LIKE 'broadcast%'
    AND PREV.hit IS NULL
""",
    ),
    (
        "v_user_day",
        # Reactions are attributed to the day the meme was SENT (sent_at), not reacted_at.
        # memes_sent / reactions / likes: all sends (feed + push) by sent_at day.
        # sessions: feed sessions started that day.
        # shares: distinct non-self clicks (clicker x meme) on this user's
        # in-bot share links (m_/s_{sharer}_{meme}), by click day.
        """
SELECT
    E.user_id,
    E.day,
    SUM(E.memes_sent)::int AS memes_sent,
    SUM(E.reactions)::int AS reactions,
    SUM(E.likes)::int AS likes,
    SUM(E.sessions)::int AS sessions,
    SUM(E.shares)::int AS shares
FROM (
    SELECT
        R.user_id,
        R.sent_at::date AS day,
        1 AS memes_sent,
        CASE WHEN R.reaction_id IS NOT NULL THEN 1 ELSE 0 END AS reactions,
        CASE WHEN R.reaction_id = 1 THEN 1 ELSE 0 END AS likes,
        0 AS sessions,
        0 AS shares
    FROM user_meme_reaction R
    UNION ALL
    SELECT F.user_id, F.session_start::date, 0, 0, 0, 1, 0
    FROM v_feed_session F
    UNION ALL
    SELECT C.sharer_id, C.day, 0, 0, 0, 0, 1
    FROM (
        SELECT DISTINCT
            SPLIT_PART(D.deep_link, '_', 2)::bigint AS sharer_id,
            D.user_id AS clicker_id,
            SPLIT_PART(D.deep_link, '_', 3) AS meme_id,
            D.created_at::date AS day
        FROM user_deep_link_log D
        WHERE D.deep_link ~ '^[ms]_[0-9]+_[0-9]+$'
    ) C
    WHERE C.sharer_id <> C.clicker_id
) E
GROUP BY E.user_id, E.day
""",
    ),
    (
        "v_new_user",
        # One row per signup. first_tap / first_like = reaction on the first
        # meme sent. d1 / d7 = any reaction 24-48h / 7-8d after signup (NULL
        # until observable). blocked_within_24h uses blocked_bot_at, which only
        # keeps the latest block (cleared on unblock).
        """
SELECT
    MU.user_id,
    MU.segment,
    MU.signup_at,
    MU.acquisition_channel,
    F.sent_at IS NOT NULL AS got_first_meme,
    COALESCE(F.reaction_id IS NOT NULL, FALSE) AS first_tap,
    COALESCE(F.reaction_id = 1, FALSE) AS first_like,
    CASE WHEN now() >= MU.signup_at + INTERVAL '8 days' THEN A.reactions_7d >= 5 END
        AS reached_5_reactions,
    CASE WHEN now() >= MU.signup_at + INTERVAL '2 days' THEN A.d1 END AS d1_return,
    CASE WHEN now() >= MU.signup_at + INTERVAL '8 days' THEN A.d7 END AS d7_return,
    COALESCE(U.blocked_bot_at < U.created_at + INTERVAL '24 hours', FALSE)
        AS blocked_within_24h
FROM v_metric_user MU
JOIN "user" U
    ON U.id = MU.user_id
LEFT JOIN LATERAL (
    SELECT R.sent_at, R.reaction_id
    FROM user_meme_reaction R
    WHERE R.user_id = MU.user_id
    ORDER BY R.sent_at, R.meme_id
    LIMIT 1
) F ON TRUE
CROSS JOIN LATERAL (
    SELECT
        COUNT(*) FILTER (WHERE R.reacted_at < MU.signup_at + INTERVAL '7 days') AS reactions_7d,
        COALESCE(BOOL_OR(
            R.reacted_at >= MU.signup_at + INTERVAL '1 day'
            AND R.reacted_at < MU.signup_at + INTERVAL '2 days'
        ), FALSE) AS d1,
        COALESCE(BOOL_OR(R.reacted_at >= MU.signup_at + INTERVAL '7 days'), FALSE) AS d7
    FROM user_meme_reaction R
    WHERE R.user_id = MU.user_id
        AND R.reaction_id IS NOT NULL
        AND R.reacted_at < MU.signup_at + INTERVAL '8 days'
) A
""",
    ),
    (
        "v_experiment_user",
        # One row per experiment assignment; outcomes from assigned_at to now (open-ended:
        # bound by the experiment end date in the readout, e.g. AND day < decided).
        # reactions / likes count feed + push; sessions are feed sessions that
        # started after assignment. Average these per variant (user-level means).
        """
SELECT
    EA.experiment_id,
    EA.variant,
    EA.user_id,
    EA.assigned_at,
    MU.segment,
    W.weeks,
    S.memes_sent,
    S.reactions,
    S.likes,
    FS.sessions,
    FS.session_memes,
    S.reactions / W.weeks AS reactions_per_week,
    S.likes / W.weeks AS likes_per_week,
    FS.session_memes::numeric / NULLIF(FS.sessions, 0) AS memes_per_session
FROM experiment_assignment EA
JOIN v_metric_user MU
    ON MU.user_id = EA.user_id
CROSS JOIN LATERAL (
    SELECT GREATEST(EXTRACT(EPOCH FROM now() - EA.assigned_at) / 604800.0, 1.0 / 7) AS weeks
) W
CROSS JOIN LATERAL (
    SELECT
        COUNT(*)::int AS memes_sent,
        COUNT(R.reaction_id)::int AS reactions,
        COUNT(*) FILTER (WHERE R.reaction_id = 1)::int AS likes
    FROM user_meme_reaction R
    WHERE R.user_id = EA.user_id
        AND R.sent_at >= EA.assigned_at
) S
CROSS JOIN LATERAL (
    SELECT COUNT(*)::int AS sessions, COALESCE(SUM(F.memes_sent), 0)::int AS session_memes
    FROM v_feed_session F
    WHERE F.user_id = EA.user_id
        AND F.session_start >= EA.assigned_at
) FS
""",
    ),
]


def upgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    op.execute(EXCLUDED_TABLE)
    for name, select in VIEWS:
        op.execute(f"CREATE OR REPLACE VIEW {name} AS {select}")


def downgrade() -> None:
    op.execute("SET lock_timeout = '5s'")
    for name, _ in reversed(VIEWS):
        op.execute(f"DROP VIEW IF EXISTS {name}")
    op.execute("DROP TABLE IF EXISTS analytics_excluded_user")
