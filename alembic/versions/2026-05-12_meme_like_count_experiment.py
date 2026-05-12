"""meme like count experiment measurement views

Revision ID: 3d9b4f6a2c10
Revises: 1a2b3c4d5e6f
Create Date: 2026-05-12 18:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "3d9b4f6a2c10"
down_revision = "1a2b3c4d5e6f"
branch_labels = None
depends_on = None


EXPERIMENT_ID = "meme_like_count"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            CREATE VIEW v_meme_like_count_experiment_results AS
            WITH assignment AS (
                SELECT
                    user_id,
                    variant,
                    assigned_at,
                    COALESCE(
                        (assignment_metadata->>'min_visible_likes')::int,
                        5
                    ) AS min_visible_likes
                FROM experiment_assignment
                WHERE experiment_id = '{EXPERIMENT_ID}'
                    AND variant IN ('control', 'treatment')
            ),
            feed_events AS (
                SELECT
                    a.variant,
                    a.user_id,
                    r.meme_id,
                    r.recommended_by,
                    r.sent_at,
                    r.reaction_id,
                    r.reacted_at,
                    COALESCE(ms.nlikes, 0) AS current_nlikes,
                    a.min_visible_likes,
                    LEAD(r.sent_at) OVER (
                        PARTITION BY a.user_id
                        ORDER BY r.sent_at
                    ) AS next_sent_at
                FROM assignment a
                INNER JOIN user_meme_reaction r
                    ON r.user_id = a.user_id
                    AND r.sent_at >= a.assigned_at
                LEFT JOIN meme_stats ms
                    ON ms.meme_id = r.meme_id
            ),
            per_user AS (
                SELECT
                    variant,
                    user_id,
                    COUNT(*) AS memes_sent,
                    COUNT(reaction_id) AS explicit_reactions,
                    COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
                    COUNT(*) FILTER (WHERE reaction_id = 2) AS dislikes
                FROM feed_events
                GROUP BY variant, user_id
            ),
            event_rollup AS (
                SELECT
                    a.variant,
                    COUNT(DISTINCT a.user_id) AS assigned_users,
                    COUNT(DISTINCT fe.user_id) AS active_users,
                    COUNT(fe.meme_id) AS memes_sent,
                    COUNT(fe.reaction_id) AS explicit_reactions,
                    COUNT(fe.meme_id) FILTER (
                        WHERE fe.current_nlikes >= fe.min_visible_likes
                    ) AS current_threshold_eligible_events,
                    COUNT(fe.reaction_id) FILTER (
                        WHERE fe.current_nlikes >= fe.min_visible_likes
                    ) AS current_threshold_eligible_reactions,
                    COUNT(*) FILTER (WHERE fe.reaction_id = 1) AS likes,
                    COUNT(*) FILTER (WHERE fe.reaction_id = 2) AS dislikes,
                    ROUND(
                        100.0 * COUNT(*) FILTER (WHERE fe.reaction_id = 1)
                        / NULLIF(COUNT(fe.reaction_id), 0),
                        1
                    ) AS like_rate_pct,
                    ROUND(
                        100.0 * COUNT(fe.reaction_id)
                        / NULLIF(COUNT(fe.meme_id), 0),
                        1
                    ) AS explicit_reaction_rate_pct,
                    COUNT(fe.meme_id) FILTER (
                        WHERE fe.next_sent_at IS NOT NULL
                            AND fe.next_sent_at - fe.sent_at <= INTERVAL '30 minutes'
                    ) AS continuation_events,
                    ROUND(
                        100.0 * COUNT(fe.meme_id) FILTER (
                            WHERE fe.next_sent_at IS NOT NULL
                                AND fe.next_sent_at - fe.sent_at <= INTERVAL '30 minutes'
                        ) / NULLIF(COUNT(fe.meme_id), 0),
                        1
                    ) AS continuation_rate_pct
                FROM assignment a
                LEFT JOIN feed_events fe
                    ON fe.user_id = a.user_id
                    AND fe.variant = a.variant
                GROUP BY a.variant
            ),
            user_rollup AS (
                SELECT
                    variant,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY memes_sent
                    ) AS median_memes_sent_per_user,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (
                        ORDER BY explicit_reactions
                    ) AS median_reactions_per_user
                FROM per_user
                GROUP BY variant
            )
            SELECT
                er.*,
                ur.median_memes_sent_per_user,
                ur.median_reactions_per_user
            FROM event_rollup er
            LEFT JOIN user_rollup ur
                ON ur.variant = er.variant
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            CREATE VIEW v_meme_like_count_experiment_sample_gate AS
            SELECT
                variant,
                COUNT(*) AS assigned_users,
                COUNT(*) >= 1000 AS sample_gate_met
            FROM experiment_assignment
            WHERE experiment_id = '{EXPERIMENT_ID}'
                AND variant IN ('control', 'treatment')
            GROUP BY variant
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS v_meme_like_count_experiment_sample_gate"))
    op.execute(sa.text("DROP VIEW IF EXISTS v_meme_like_count_experiment_results"))
