"""Offline evaluation harness for the recommendation ranking.

Measures how well our scoring functions predict actual user preferences.
Uses held-out reactions as ground truth: did we rank liked memes higher
than disliked ones?

Usage:
    # Evaluate last 24 hours (default)
    python scripts/eval_ranking.py

    # Evaluate specific time window
    python scripts/eval_ranking.py --hours 48

    # Evaluate with minimum user reactions threshold
    python scripts/eval_ranking.py --min-reactions 10

Requires ANALYST_DATABASE_URL or DATABASE_URL in environment.
"""

import argparse
import asyncio
import os
import sys
import time

import asyncpg


async def get_connection() -> asyncpg.Connection:
    url = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: Set ANALYST_DATABASE_URL or DATABASE_URL", file=sys.stderr)
        sys.exit(1)
    return await asyncpg.connect(url, statement_cache_size=0)


async def eval_lr_smoothed(conn: asyncpg.Connection, hours: int, min_reactions: int):
    """Evaluate the lr_smoothed engine scoring.

    For each user in the test period, we compute the scoring function
    (user_source_lr * meme_lr_smoothed) for every meme they actually
    interacted with. Then we check: did liked memes get higher scores
    than disliked memes?

    Metric: pairwise accuracy — % of (liked, disliked) pairs where
    the liked meme has a higher score.
    """

    print(f"\n{'='*60}")
    print(f"  OFFLINE EVAL: lr_smoothed scoring")
    print(f"  Test window: last {hours} hours")
    print(f"  Min reactions per user: {min_reactions}")
    print(f"{'='*60}\n")

    t0 = time.time()

    # Core query: for each reaction in the test window, compute the
    # lr_smoothed scoring function that would have been used to rank it
    rows = await conn.fetch("""
        WITH test_reactions AS (
            SELECT
                umr.user_id,
                umr.meme_id,
                umr.reaction_id,
                m.meme_source_id
            FROM user_meme_reaction umr
            JOIN meme m ON m.id = umr.meme_id
            WHERE umr.sent_at > NOW() - ($1 || ' hours')::interval
              AND umr.reaction_id IS NOT NULL
        ),
        user_counts AS (
            SELECT user_id, COUNT(*) as cnt
            FROM test_reactions
            GROUP BY user_id
            HAVING COUNT(*) >= $2
        ),
        scored AS (
            SELECT
                tr.user_id,
                tr.meme_id,
                tr.reaction_id,
                -- lr_smoothed scoring: user_source_lr * meme_lr
                COALESCE(
                    (UMSS.nlikes + 1.0) / NULLIF(UMSS.nlikes + UMSS.ndislikes + 1.0, 0),
                    0.5
                ) *
                COALESCE(MS.lr_smoothed, 0.0) AS score
            FROM test_reactions tr
            JOIN user_counts uc ON uc.user_id = tr.user_id
            LEFT JOIN meme_stats MS ON MS.meme_id = tr.meme_id
            LEFT JOIN user_meme_source_stats UMSS
                ON UMSS.user_id = tr.user_id
                AND UMSS.meme_source_id = tr.meme_source_id
        )
        SELECT user_id, meme_id, reaction_id, score
        FROM scored
        ORDER BY user_id, score DESC
    """, str(hours), min_reactions)

    query_time = time.time() - t0
    print(f"Query time: {query_time:.1f}s")
    print(f"Total scored reactions: {len(rows)}")

    if not rows:
        print("No data in test window. Try increasing --hours.")
        return

    # Group by user
    users = {}
    for r in rows:
        uid = r["user_id"]
        if uid not in users:
            users[uid] = {"liked": [], "disliked": []}
        if r["reaction_id"] == 1:
            users[uid]["liked"].append(r["score"])
        elif r["reaction_id"] == 2:
            users[uid]["disliked"].append(r["score"])

    # Compute pairwise accuracy per user
    total_pairs = 0
    correct_pairs = 0
    tied_pairs = 0
    user_results = []

    for uid, data in users.items():
        liked_scores = data["liked"]
        disliked_scores = data["disliked"]

        if not liked_scores or not disliked_scores:
            continue

        user_correct = 0
        user_total = 0
        user_tied = 0

        for ls in liked_scores:
            for ds in disliked_scores:
                user_total += 1
                if ls > ds:
                    user_correct += 1
                elif ls == ds:
                    user_tied += 1

        total_pairs += user_total
        correct_pairs += user_correct
        tied_pairs += user_tied

        if user_total > 0:
            user_results.append({
                "user_id": uid,
                "accuracy": user_correct / user_total,
                "pairs": user_total,
                "likes": len(liked_scores),
                "dislikes": len(disliked_scores),
            })

    if total_pairs == 0:
        print("No users with both likes and dislikes in test window.")
        return

    # Results
    pairwise_acc = correct_pairs / total_pairs
    tie_rate = tied_pairs / total_pairs
    n_users = len(user_results)

    avg_user_acc = sum(u["accuracy"] for u in user_results) / n_users if n_users else 0

    print(f"\nUsers with both likes+dislikes: {n_users}")
    print(f"Total (liked, disliked) pairs: {total_pairs:,}")
    print()
    print(f"  Pairwise accuracy:  {pairwise_acc:.1%}")
    print(f"  Avg per-user acc:   {avg_user_acc:.1%}")
    print(f"  Tie rate:           {tie_rate:.1%}")
    print(f"  Random baseline:    50.0%")
    print()

    # Breakdown by user engagement level
    sorted_users = sorted(user_results, key=lambda u: u["pairs"], reverse=True)

    print("Top 10 users by pair count:")
    print(f"  {'User':>12}  {'Acc':>6}  {'Pairs':>7}  {'Likes':>6}  {'Dislikes':>8}")
    for u in sorted_users[:10]:
        print(
            f"  {u['user_id']:>12}  {u['accuracy']:>5.1%}  "
            f"{u['pairs']:>7,}  {u['likes']:>6}  {u['dislikes']:>8}"
        )

    # Score distribution
    print("\nScore distribution (liked vs disliked):")
    liked_all = [r["score"] for r in rows if r["reaction_id"] == 1]
    disliked_all = [r["score"] for r in rows if r["reaction_id"] == 2]

    if liked_all and disliked_all:
        avg_liked = sum(liked_all) / len(liked_all)
        avg_disliked = sum(disliked_all) / len(disliked_all)
        print(f"  Avg liked score:    {avg_liked:.4f}")
        print(f"  Avg disliked score: {avg_disliked:.4f}")
        print(f"  Separation:         {avg_liked - avg_disliked:.4f}")

    print(f"\nTotal eval time: {time.time() - t0:.1f}s")

    # Summary line for autoresearch parsing
    print(f"\n>>> METRIC pairwise_accuracy={pairwise_acc:.4f}")


async def eval_engagement_score(conn: asyncpg.Connection, hours: int, min_reactions: int):
    """Evaluate engagement_score as a ranking signal."""

    print(f"\n{'='*60}")
    print(f"  OFFLINE EVAL: engagement_score")
    print(f"{'='*60}\n")

    t0 = time.time()

    rows = await conn.fetch("""
        WITH test_reactions AS (
            SELECT umr.user_id, umr.meme_id, umr.reaction_id
            FROM user_meme_reaction umr
            WHERE umr.sent_at > NOW() - ($1 || ' hours')::interval
              AND umr.reaction_id IS NOT NULL
        ),
        user_counts AS (
            SELECT user_id, COUNT(*) FROM test_reactions
            GROUP BY user_id HAVING COUNT(*) >= $2
        )
        SELECT tr.user_id, tr.meme_id, tr.reaction_id,
               COALESCE(MS.engagement_score, 0) AS score
        FROM test_reactions tr
        JOIN user_counts uc ON uc.user_id = tr.user_id
        LEFT JOIN meme_stats MS ON MS.meme_id = tr.meme_id
        ORDER BY tr.user_id, score DESC
    """, str(hours), min_reactions)

    query_time = time.time() - t0
    print(f"Query time: {query_time:.1f}s, rows: {len(rows)}")

    if not rows:
        print("No data.")
        return

    # Same pairwise calculation
    users = {}
    for r in rows:
        uid = r["user_id"]
        if uid not in users:
            users[uid] = {"liked": [], "disliked": []}
        if r["reaction_id"] == 1:
            users[uid]["liked"].append(r["score"])
        elif r["reaction_id"] == 2:
            users[uid]["disliked"].append(r["score"])

    total_pairs = 0
    correct_pairs = 0
    n_users = 0

    for uid, data in users.items():
        if not data["liked"] or not data["disliked"]:
            continue
        n_users += 1
        for ls in data["liked"]:
            for ds in data["disliked"]:
                total_pairs += 1
                if ls > ds:
                    correct_pairs += 1

    if total_pairs == 0:
        print("No valid pairs.")
        return

    acc = correct_pairs / total_pairs
    print(f"Users: {n_users}, Pairs: {total_pairs:,}")
    print(f"  Pairwise accuracy: {acc:.1%}")
    print(f"\n>>> METRIC engagement_pairwise_accuracy={acc:.4f}")


async def eval_per_engine(conn: asyncpg.Connection, hours: int):
    """Per-engine like rate and volume — quick health check."""

    print(f"\n{'='*60}")
    print(f"  ENGINE HEALTH (last {hours}h)")
    print(f"{'='*60}\n")

    rows = await conn.fetch("""
        SELECT
            recommended_by,
            COUNT(*) as reactions,
            ROUND(100.0 * COUNT(*) FILTER (WHERE reaction_id = 1)
                  / NULLIF(COUNT(*), 0), 1) as like_rate,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as traffic_pct
        FROM user_meme_reaction
        WHERE sent_at > NOW() - ($1 || ' hours')::interval
          AND recommended_by IS NOT NULL
        GROUP BY recommended_by
        ORDER BY reactions DESC
    """, str(hours))

    print(f"  {'Engine':<30} {'Reactions':>10} {'LR%':>6} {'Traffic%':>9}")
    print(f"  {'-'*30} {'-'*10} {'-'*6} {'-'*9}")
    for r in rows:
        print(
            f"  {r['recommended_by']:<30} {r['reactions']:>10,} "
            f"{r['like_rate'] or 0:>5.1f}% {r['traffic_pct'] or 0:>8.1f}%"
        )


async def eval_cold_start(conn: asyncpg.Connection, days: int = 7):
    """Cold start funnel for new users."""

    print(f"\n{'='*60}")
    print(f"  COLD START FUNNEL (new users, last {days} days)")
    print(f"{'='*60}\n")

    rows = await conn.fetch("""
        WITH new_users AS (
            SELECT user_id, MIN(sent_at) as first_seen
            FROM user_meme_reaction
            GROUP BY user_id
            HAVING MIN(sent_at) > NOW() - ($1 || ' days')::interval
        ),
        user_counts AS (
            SELECT umr.user_id, COUNT(*) as total_memes,
                   COUNT(*) FILTER (WHERE reaction_id = 1) as likes
            FROM user_meme_reaction umr
            JOIN new_users nu ON nu.user_id = umr.user_id
            GROUP BY umr.user_id
        )
        SELECT
            CASE
                WHEN total_memes = 1 THEN '1 (bounced)'
                WHEN total_memes <= 5 THEN '2-5 (tried)'
                WHEN total_memes <= 10 THEN '6-10'
                WHEN total_memes <= 30 THEN '11-30'
                WHEN total_memes <= 100 THEN '31-100'
                ELSE '100+ (retained)'
            END as cohort,
            COUNT(*) as users,
            ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 1) as pct,
            ROUND(AVG(total_memes), 1) as avg_memes,
            ROUND(AVG(CASE WHEN total_memes > 0
                       THEN 100.0 * likes / total_memes END), 1) as avg_lr
        FROM user_counts
        GROUP BY 1
        ORDER BY MIN(total_memes)
    """, str(days))

    total_users = sum(r["users"] for r in rows)
    print(f"  Total new users: {total_users}\n")
    print(f"  {'Cohort':<20} {'Users':>6} {'%':>6} {'Avg memes':>10} {'Avg LR%':>8}")
    print(f"  {'-'*20} {'-'*6} {'-'*6} {'-'*10} {'-'*8}")
    for r in rows:
        print(
            f"  {r['cohort']:<20} {r['users']:>6} {r['pct'] or 0:>5.1f}% "
            f"{r['avg_memes'] or 0:>10.1f} {r['avg_lr'] or 0:>7.1f}%"
        )

    retained = sum(r["users"] for r in rows if "100+" in r.get("cohort", ""))
    ret_pct = 100.0 * retained / total_users if total_users else 0
    print(f"\n  Retention (100+ memes): {ret_pct:.1f}%")
    print(f"\n>>> METRIC cold_start_retention={ret_pct/100:.4f}")


async def main():
    parser = argparse.ArgumentParser(description="Offline ranking evaluation")
    parser.add_argument("--hours", type=int, default=24, help="Test window in hours")
    parser.add_argument("--min-reactions", type=int, default=5,
                        help="Min reactions per user in test window")
    parser.add_argument("--cold-start-days", type=int, default=7)
    parser.add_argument("--section", type=str, default="all",
                        choices=["all", "lr", "engagement", "engines", "coldstart"],
                        help="Which eval to run")
    args = parser.parse_args()

    conn = await get_connection()

    try:
        if args.section in ("all", "engines"):
            await eval_per_engine(conn, args.hours)
        if args.section in ("all", "lr"):
            await eval_lr_smoothed(conn, args.hours, args.min_reactions)
        if args.section in ("all", "engagement"):
            await eval_engagement_score(conn, args.hours, args.min_reactions)
        if args.section in ("all", "coldstart"):
            await eval_cold_start(conn, args.cold_start_days)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
