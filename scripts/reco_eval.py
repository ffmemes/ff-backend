#!/usr/bin/env python3
"""Offline reco playground (v1): counterfactual policies on historical sends.

Usage (read-only DB recommended):

  set -a; source .env; set +a
  python scripts/reco_eval.py counterfactual-block-disliked --days 7

Requires ANALYST_DATABASE_URL or DATABASE_URL. Never prints connection strings.
"""

from __future__ import annotations

import argparse
import os
import sys


def _dsn() -> str:
    dsn = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        print("Set ANALYST_DATABASE_URL or DATABASE_URL", file=sys.stderr)
        sys.exit(2)
    return dsn


def cmd_counterfactual_block_disliked(days: int, min_reactions: int) -> None:
    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("psycopg2 required for scripts/reco_eval.py", file=sys.stderr)
        sys.exit(2)

    dsn = _dsn()
    sql = """
    WITH sends AS (
      SELECT
        r.user_id,
        r.meme_id,
        r.reaction_id,
        r.recommended_by,
        m.meme_source_id,
        umss.nlikes AS src_likes,
        umss.ndislikes AS src_dislikes
      FROM user_meme_reaction r
      JOIN meme m ON m.id = r.meme_id
      JOIN "user" u ON u.id = r.user_id AND u.type = 'user'
      LEFT JOIN user_meme_source_stats umss
        ON umss.user_id = r.user_id
       AND umss.meme_source_id = m.meme_source_id
      WHERE r.sent_at > now() - (%s || ' days')::interval
    ),
    labeled AS (
      SELECT
        *,
        (
          src_dislikes IS NOT NULL
          AND src_dislikes > src_likes
          AND (src_likes + src_dislikes) >= %s
        ) AS would_block
      FROM sends
    )
    SELECT
      count(*) AS total_sends,
      count(*) FILTER (WHERE would_block) AS would_block_sends,
      round(100.0 * count(*) FILTER (WHERE would_block) / nullif(count(*),0), 2)
        AS would_block_pct,
      round(
        100.0 * count(*) FILTER (WHERE would_block AND reaction_id = 1)
        / nullif(count(*) FILTER (WHERE would_block AND reaction_id IS NOT NULL), 0),
        2
      ) AS lr_blocked_pct,
      round(
        100.0 * count(*) FILTER (WHERE NOT would_block AND reaction_id = 1)
        / nullif(count(*) FILTER (WHERE NOT would_block AND reaction_id IS NOT NULL), 0),
        2
      ) AS lr_kept_pct,
      round(
        100.0 * count(*) FILTER (WHERE would_block AND reaction_id = 2)
        / nullif(count(*) FILTER (WHERE would_block AND reaction_id IS NOT NULL), 0),
        2
      ) AS dislike_rate_blocked_pct
    FROM labeled;
    """
    with psycopg2.connect(dsn) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SET statement_timeout = '120s'")
            cur.execute(sql, (str(days), min_reactions))
            row = cur.fetchone()
    print("counterfactual-block-disliked")
    print(f"  days={days} min_reactions={min_reactions}")
    for k, v in row.items():
        print(f"  {k}: {v}")
    print()
    print("Interpretation:")
    print("  would_block_pct ~ share of feed that policy removes.")
    print("  If lr_blocked_pct << lr_kept_pct, filter removes junk (good).")
    print("  If dislike_rate_blocked_pct is high, filter targets real negatives.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Reco offline playground")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser(
        "counterfactual-block-disliked",
        help="Estimate impact of blocking disliked sources on past sends",
    )
    p1.add_argument("--days", type=int, default=7)
    p1.add_argument("--min-reactions", type=int, default=5)

    args = parser.parse_args(argv)
    if args.cmd == "counterfactual-block-disliked":
        cmd_counterfactual_block_disliked(args.days, args.min_reactions)
    else:
        parser.error(f"unknown command {args.cmd}")


if __name__ == "__main__":
    main()
