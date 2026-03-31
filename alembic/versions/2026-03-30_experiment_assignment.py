"""Add experiment_assignment table and v_experiment_results view

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-03-30 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_assignment",
        sa.Column("id", sa.Integer(), sa.Identity(), primary_key=True),
        sa.Column("experiment_id", sa.String(100), nullable=False),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variant", sa.String(50), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("experiment_id", "user_id", name="uq_experiment_assignment"),
    )
    op.create_index(
        "idx_experiment_assignment_experiment_id",
        "experiment_assignment",
        ["experiment_id"],
    )

    # Backfill upload_promo_day1 from real exposure data.
    # On test DB with empty tables, INSERT SELECT returns 0 rows (safe no-op).

    # Treatment: users who were shown the popup.
    op.execute(
        sa.text(
            "INSERT INTO experiment_assignment"
            " (experiment_id, user_id, variant, assigned_at)"
            " SELECT 'upload_promo_day1', upl.user_id, 'treatment', upl.sent_at"
            " FROM user_popup_logs upl"
            " WHERE upl.popup_id = 'experiment.upload_promo_day1'"
            " ON CONFLICT (experiment_id, user_id) DO NOTHING"
        )
    )

    # Control: users with nmemes_sent >= 10, odd user_id, not in treatment.
    op.execute(
        sa.text(
            "INSERT INTO experiment_assignment"
            " (experiment_id, user_id, variant, assigned_at)"
            " SELECT 'upload_promo_day1', us.user_id, 'control',"
            " COALESCE("
            "   (SELECT r.sent_at FROM user_meme_reaction r"
            "    WHERE r.user_id = us.user_id"
            "    ORDER BY r.sent_at OFFSET 9 LIMIT 1),"
            "   us.updated_at"
            " )"
            " FROM user_stats us"
            " WHERE us.nmemes_sent >= 10"
            "   AND MOD(us.user_id, 2) = 1"
            "   AND NOT EXISTS ("
            "     SELECT 1 FROM experiment_assignment ea"
            "     WHERE ea.experiment_id = 'upload_promo_day1'"
            "       AND ea.user_id = us.user_id"
            "   )"
            " ON CONFLICT (experiment_id, user_id) DO NOTHING"
        )
    )

    # v_experiment_results view: session length + upload conversion per variant.
    op.execute(
        sa.text(
            "CREATE VIEW v_experiment_results AS"
            " WITH experiment_reactions AS ("
            "   SELECT"
            "     ea.experiment_id, ea.variant, ea.user_id,"
            "     r.reaction_id, r.reacted_at,"
            "     CASE"
            "       WHEN r.reacted_at - LAG(r.reacted_at)"
            "         OVER (PARTITION BY ea.experiment_id, ea.user_id"
            "               ORDER BY r.reacted_at)"
            "         > INTERVAL '30 minutes'"
            "       THEN 1 ELSE 0"
            "     END AS new_session"
            "   FROM experiment_assignment ea"
            "   LEFT JOIN user_meme_reaction r"
            "     ON r.user_id = ea.user_id"
            "     AND r.reacted_at >= ea.assigned_at"
            " ),"
            " sessions AS ("
            "   SELECT"
            "     experiment_id, variant, user_id, reaction_id,"
            "     SUM(new_session) OVER ("
            "       PARTITION BY experiment_id, user_id"
            "       ORDER BY reacted_at"
            "     ) AS session_id"
            "   FROM experiment_reactions"
            "   WHERE reacted_at IS NOT NULL"
            " ),"
            " session_lengths AS ("
            "   SELECT"
            "     experiment_id, variant, user_id, session_id,"
            "     COUNT(*) AS memes_in_session"
            "   FROM sessions"
            "   GROUP BY experiment_id, variant, user_id, session_id"
            "   HAVING COUNT(*) >= 2"
            " )"
            " SELECT"
            "   ea.experiment_id,"
            "   ea.variant,"
            "   COUNT(DISTINCT ea.user_id) AS users,"
            "   COUNT(r.meme_id) AS total_reactions,"
            "   ROUND("
            "     100.0 * COUNT(*) FILTER (WHERE r.reaction_id = 1)"
            "     / NULLIF(COUNT(r.reaction_id), 0), 1"
            "   ) AS like_rate_pct,"
            "   (SELECT PERCENTILE_CONT(0.5)"
            "      WITHIN GROUP (ORDER BY sl.memes_in_session)"
            "    FROM session_lengths sl"
            "    WHERE sl.experiment_id = ea.experiment_id"
            "      AND sl.variant = ea.variant"
            "   ) AS median_session_length,"
            "   COUNT(DISTINCT ea.user_id) FILTER ("
            "     WHERE EXISTS ("
            "       SELECT 1 FROM meme_raw_upload mu"
            "       WHERE mu.user_id = ea.user_id"
            "         AND mu.date >= ea.assigned_at"
            "     )"
            "   ) AS users_who_uploaded"
            " FROM experiment_assignment ea"
            " LEFT JOIN user_meme_reaction r"
            "   ON r.user_id = ea.user_id AND r.reacted_at >= ea.assigned_at"
            " GROUP BY ea.experiment_id, ea.variant"
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP VIEW IF EXISTS v_experiment_results"))
    op.drop_index("idx_experiment_assignment_experiment_id")
    op.drop_table("experiment_assignment")
