#!/usr/bin/env python3
"""Run SQL EDA queries via asyncpg (no TEMP tables required) → reports/eda-sql.md"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import asyncpg

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "reports" / "eda-sql.md"


def fmt_rows(rows) -> str:
    if not rows:
        return "_(empty)_\n"
    keys = list(rows[0].keys())
    lines = ["| " + " | ".join(keys) + " |", "| " + " | ".join("---" for _ in keys) + " |"]
    for r in rows:
        lines.append("| " + " | ".join(str(r[k]) for k in keys) + " |")
    return "\n".join(lines) + "\n"


async def main() -> None:
    url = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("Set ANALYST_DATABASE_URL")
    conn = await asyncpg.connect(url, statement_cache_size=0)
    sections = []
    try:
        await conn.execute("SET statement_timeout = '180s'")

        sections.append("## 1) Label quantiles (180d mature)\n")
        q1 = await conn.fetch(
            """
            WITH posts AS (
              SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
              FROM crossposting cp JOIN meme m ON m.id = cp.meme_id
              WHERE cp.channel = 'tgchannelru'
                AND cp.created_at > now() - interval '180 days'
                AND cp.created_at < now() - interval '36 hours'
                AND m.type = 'image' AND cp.telegram_message_id IS NOT NULL
            ),
            labels AS (
              SELECT DISTINCT ON (p.meme_id)
                p.posted_at, s.views, s.forwards, s.reactions, s.comments,
                1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
              FROM posts p
              JOIN crossposting_snapshots s ON s.channel = 'tgchannelru'
               AND s.telegram_message_id = p.telegram_message_id
               AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                                     AND p.posted_at + interval '36 hours'
               AND s.views > 0
              ORDER BY p.meme_id,
                abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
            )
            SELECT count(*)::int AS n,
              min(posted_at)::date AS first_d, max(posted_at)::date AS last_d,
              round(percentile_cont(0.50) WITHIN GROUP (ORDER BY views)::numeric,1) AS views_p50,
              round(percentile_cont(0.50) WITHIN GROUP (ORDER BY forwards)::numeric,2) AS fwd_p50,
              round(percentile_cont(0.75) WITHIN GROUP (ORDER BY forwards)::numeric,2) AS fwd_p75,
              round(percentile_cont(0.25) WITHIN GROUP (ORDER BY f1k)::numeric,2) AS f1k_p25,
              round(percentile_cont(0.50) WITHIN GROUP (ORDER BY f1k)::numeric,2) AS f1k_p50,
              round(percentile_cont(0.75) WITHIN GROUP (ORDER BY f1k)::numeric,2) AS f1k_p75,
              round(percentile_cont(0.90) WITHIN GROUP (ORDER BY f1k)::numeric,2) AS f1k_p90,
              round(avg(reactions)::numeric,2) AS avg_react,
              round(avg(comments)::numeric,2) AS avg_comments,
              round(100.0 * count(*) FILTER (WHERE f1k >= 30.9 OR forwards >= 12) / count(*), 1) AS hit_rate_fixed
            FROM labels
            """
        )
        sections.append(fmt_rows(q1))

        sections.append("## 2) Coverage + premium\n")
        q2 = await conn.fetch(
            """
            WITH posts AS (
              SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
              FROM crossposting cp JOIN meme m ON m.id = cp.meme_id
              WHERE cp.channel = 'tgchannelru'
                AND cp.created_at > now() - interval '180 days'
                AND cp.created_at < now() - interval '36 hours'
                AND m.type = 'image' AND cp.telegram_message_id IS NOT NULL
            ),
            labeled AS (
              SELECT DISTINCT ON (p.meme_id) p.meme_id, p.posted_at
              FROM posts p
              JOIN crossposting_snapshots s ON s.channel = 'tgchannelru'
               AND s.telegram_message_id = p.telegram_message_id
               AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                                     AND p.posted_at + interval '36 hours'
               AND s.views > 0
              ORDER BY p.meme_id,
                abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
            ),
            pre AS (
              SELECT l.meme_id,
                count(*) FILTER (WHERE umr.reaction_id = 1) AS pre_likes,
                count(*) FILTER (WHERE umr.reaction_id = 1 AND coalesce(ut.is_premium,false)) AS pre_premium_likes,
                count(*) AS pre_reacts
              FROM labeled l
              JOIN user_meme_reaction umr ON umr.meme_id = l.meme_id AND umr.reacted_at < l.posted_at
              LEFT JOIN user_tg ut ON ut.id = umr.user_id
              GROUP BY l.meme_id
            )
            SELECT count(*)::int AS n_labeled,
              round(100.0 * count(*) FILTER (WHERE coalesce(pre_likes,0) >= 5) / count(*),1) AS pct_likes_ge5,
              round(100.0 * count(*) FILTER (WHERE coalesce(pre_likes,0) >= 20) / count(*),1) AS pct_likes_ge20,
              round(100.0 * count(*) FILTER (WHERE coalesce(pre_premium_likes,0) >= 1) / count(*),1) AS pct_any_premium,
              round(avg(CASE WHEN pre_likes > 0 THEN pre_premium_likes::float/pre_likes END)::numeric,3) AS avg_premium_frac,
              round(avg(coalesce(pre_likes,0))::numeric,1) AS avg_pre_likes
            FROM labeled l LEFT JOIN pre ON pre.meme_id = l.meme_id
            """
        )
        sections.append(fmt_rows(q2))

        sections.append("## 3) Quintiles pre_likes / pre_lr / premium_frac\n")
        for driver_sql, name in [
            ("pre_likes", "pre_likes"),
            ("pre_lr", "pre_lr"),
            ("premium_frac", "premium_frac"),
        ]:
            rows = await conn.fetch(
                f"""
                WITH posts AS (
                  SELECT cp.meme_id, cp.created_at AS posted_at, cp.telegram_message_id
                  FROM crossposting cp JOIN meme m ON m.id = cp.meme_id
                  WHERE cp.channel = 'tgchannelru'
                    AND cp.created_at > now() - interval '180 days'
                    AND cp.created_at < now() - interval '36 hours'
                    AND m.type = 'image' AND cp.telegram_message_id IS NOT NULL
                ),
                labels AS (
                  SELECT DISTINCT ON (p.meme_id)
                    p.meme_id, p.posted_at, s.views, s.forwards, s.reactions,
                    1000.0 * s.forwards / NULLIF(s.views, 0) AS f1k
                  FROM posts p
                  JOIN crossposting_snapshots s ON s.channel = 'tgchannelru'
                   AND s.telegram_message_id = p.telegram_message_id
                   AND s.snapshot_at BETWEEN p.posted_at + interval '18 hours'
                                         AND p.posted_at + interval '36 hours'
                   AND s.views > 0
                  ORDER BY p.meme_id,
                    abs(extract(epoch from (s.snapshot_at - (p.posted_at + interval '24 hours'))))
                ),
                pre AS (
                  SELECT l.meme_id,
                    count(*) FILTER (WHERE umr.reaction_id = 1) AS pre_likes,
                    count(*) FILTER (WHERE umr.reaction_id = 2) AS pre_dislikes,
                    count(*) FILTER (WHERE umr.reaction_id = 1 AND coalesce(ut.is_premium,false)) AS pre_premium_likes
                  FROM labels l
                  JOIN user_meme_reaction umr ON umr.meme_id = l.meme_id AND umr.reacted_at < l.posted_at
                  LEFT JOIN user_tg ut ON ut.id = umr.user_id
                  GROUP BY l.meme_id
                ),
                feat AS (
                  SELECT l.f1k, l.forwards, l.views, l.reactions,
                    coalesce(p.pre_likes,0) AS pre_likes,
                    CASE WHEN coalesce(p.pre_likes,0)+coalesce(p.pre_dislikes,0)>0
                      THEN p.pre_likes::float/(p.pre_likes+p.pre_dislikes) END AS pre_lr,
                    CASE WHEN coalesce(p.pre_likes,0)>0
                      THEN p.pre_premium_likes::float/p.pre_likes END AS premium_frac
                  FROM labels l LEFT JOIN pre p ON p.meme_id = l.meme_id
                ),
                q AS (
                  SELECT *, ntile(5) OVER (ORDER BY {driver_sql}) AS q5
                  FROM feat WHERE {driver_sql} IS NOT NULL
                )
                SELECT {name!r} AS driver, q5, count(*)::int AS n,
                  round(avg({driver_sql})::numeric,3) AS avg_driver,
                  round(avg(f1k)::numeric,2) AS avg_f1k,
                  round(avg(forwards)::numeric,2) AS avg_fwd,
                  round(avg(views)::numeric,1) AS avg_views,
                  round(avg(reactions)::numeric,2) AS avg_react
                FROM q GROUP BY q5 ORDER BY q5
                """
            )
            sections.append(f"### driver = {name}\n")
            sections.append(fmt_rows(rows))

        sections.append("## 4) Source prior (90d lookback)\n")
        q4 = await conn.fetch(
            """
            WITH hist AS (
              SELECT cp.meme_id, cp.created_at AS posted_at, m.meme_source_id,
                1000.0 * s.forwards / NULLIF(s.views,0) AS f1k, s.forwards
              FROM crossposting cp
              JOIN meme m ON m.id = cp.meme_id
              JOIN LATERAL (
                SELECT s.views, s.forwards FROM crossposting_snapshots s
                WHERE s.channel='tgchannelru' AND s.telegram_message_id=cp.telegram_message_id
                  AND s.snapshot_at BETWEEN cp.created_at + interval '18 hours'
                                        AND cp.created_at + interval '36 hours'
                  AND s.views > 0
                ORDER BY abs(extract(epoch from (s.snapshot_at - (cp.created_at + interval '24 hours'))))
                LIMIT 1
              ) s ON true
              WHERE cp.channel='tgchannelru' AND cp.created_at > now() - interval '360 days'
                AND m.type='image' AND cp.telegram_message_id IS NOT NULL
            ),
            labels AS (
              SELECT * FROM hist
              WHERE posted_at > now() - interval '180 days'
                AND posted_at < now() - interval '36 hours'
            ),
            with_prior AS (
              SELECT l.f1k, l.forwards,
                (SELECT avg(h.f1k) FROM hist h
                 WHERE h.meme_source_id=l.meme_source_id AND h.posted_at < l.posted_at
                   AND h.posted_at > l.posted_at - interval '90 days'
                   AND h.meme_id <> l.meme_id) AS src_prior_f1k,
                (SELECT count(*) FROM hist h
                 WHERE h.meme_source_id=l.meme_source_id AND h.posted_at < l.posted_at
                   AND h.posted_at > l.posted_at - interval '90 days'
                   AND h.meme_id <> l.meme_id) AS src_prior_n
              FROM labels l
            )
            SELECT count(*)::int AS n,
              count(*) FILTER (WHERE src_prior_n >= 3)::int AS n_prior_ge3,
              round(corr(src_prior_f1k, f1k)::numeric,3) AS r_prior_f1k,
              round(corr(src_prior_f1k, forwards::float)::numeric,3) AS r_prior_fwd
            FROM with_prior WHERE src_prior_f1k IS NOT NULL
            """
        )
        sections.append(fmt_rows(q4))

    finally:
        await conn.close()

    body = (
        f"# SQL EDA — bot→channel\n\n"
        f"**When:** {datetime.now(timezone.utc).isoformat()}\n"
        f"**Channel:** tgchannelru, image, mature 18–36h\n\n"
        + "\n".join(sections)
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(body)
    print(body)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
