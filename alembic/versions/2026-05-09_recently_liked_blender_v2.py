"""recently liked blender v2 assignment metadata

Revision ID: 1a2b3c4d5e6f
Revises: 24cd1a8bd9b8
Create Date: 2026-05-09 10:45:00.000000

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "1a2b3c4d5e6f"
down_revision = "24cd1a8bd9b8"
branch_labels = None
depends_on = None


EXPERIMENT_ID = "recently_liked_blender_v2"


def upgrade() -> None:
    op.add_column(
        "experiment_assignment",
        sa.Column(
            "assignment_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    op.execute(
        sa.text(
            f"""
            CREATE VIEW v_recently_liked_blender_v2_assignment AS
            SELECT
                ea.user_id,
                ea.variant,
                ea.assigned_at,
                (ea.assignment_metadata->>'lr_quartile')::int AS lr_quartile,
                (ea.assignment_metadata->>'likes_7d')::int AS likes_7d,
                (ea.assignment_metadata->>'reactions_7d')::int AS reactions_7d,
                (ea.assignment_metadata->>'lr_7d')::float AS lr_7d,
                COALESCE(
                    (ea.assignment_metadata->>'high_volume_skipper')::boolean,
                    false
                ) AS high_volume_skipper,
                ea.assignment_metadata->>'excluded_reason' AS excluded_reason,
                ea.assignment_metadata->'assigned_weights' AS assigned_weights,
                (ea.assignment_metadata->>'sample_gate_per_variant')::int
                    AS sample_gate_per_variant,
                ea.assignment_metadata->'day3_guardrail' AS day3_guardrail
            FROM experiment_assignment ea
            WHERE ea.experiment_id = '{EXPERIMENT_ID}'
            """
        )
    )

    op.execute(
        sa.text(
            f"""
            CREATE VIEW v_recently_liked_blender_v2_sample_gate AS
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

    op.execute(
        sa.text(
            f"""
            CREATE VIEW v_recently_liked_blender_v2_engine_metrics AS
            WITH assignment AS (
                SELECT user_id, variant, assigned_at
                FROM experiment_assignment
                WHERE experiment_id = '{EXPERIMENT_ID}'
                    AND variant IN ('control', 'treatment')
            ),
            reactions AS (
                SELECT
                    a.variant,
                    r.user_id,
                    r.meme_id,
                    r.recommended_by,
                    r.reaction_id,
                    r.sent_at,
                    r.reacted_at,
                    LEAD(r.sent_at) OVER (
                        PARTITION BY r.user_id
                        ORDER BY r.sent_at
                    ) AS next_sent_at
                FROM assignment a
                INNER JOIN user_meme_reaction r
                    ON r.user_id = a.user_id
                    AND r.sent_at >= a.assigned_at
                WHERE r.recommended_by IS NOT NULL
            )
            SELECT
                variant,
                recommended_by,
                COUNT(*) AS total_sent,
                COUNT(reaction_id) AS total_reactions,
                COUNT(*) FILTER (WHERE reaction_id = 1) AS likes,
                ROUND(
                    100.0 * COUNT(*) FILTER (WHERE reaction_id = 1)
                    / NULLIF(COUNT(reaction_id), 0),
                    1
                ) AS like_rate_pct,
                ROUND(
                    100.0 * COUNT(*)
                    / NULLIF(SUM(COUNT(*)) OVER (PARTITION BY variant), 0),
                    1
                ) AS allocation_pct,
                COUNT(*) FILTER (
                    WHERE next_sent_at IS NOT NULL
                        AND next_sent_at - sent_at <= INTERVAL '30 minutes'
                ) AS continuation_events,
                ROUND(
                    100.0 * COUNT(*) FILTER (
                        WHERE next_sent_at IS NOT NULL
                            AND next_sent_at - sent_at <= INTERVAL '30 minutes'
                    ) / NULLIF(COUNT(*), 0),
                    1
                ) AS continuation_rate_pct
            FROM reactions
            GROUP BY variant, recommended_by
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS v_recently_liked_blender_v2_engine_metrics"))
    op.execute(sa.text("DROP VIEW IF EXISTS v_recently_liked_blender_v2_sample_gate"))
    op.execute(sa.text("DROP VIEW IF EXISTS v_recently_liked_blender_v2_assignment"))
    op.drop_column("experiment_assignment", "assignment_metadata")
