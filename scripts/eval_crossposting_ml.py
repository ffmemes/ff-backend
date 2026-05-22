"""Offline evaluator for simple crossposting virality models.

The goal is deliberately narrow: predict whether a posted image meme lands
above the channel median 24h forward rate. This is not a production ranker.
It is a read-only gate for deciding whether simple linear ML features are worth
promoting into shadow scoring.

Usage:
    ANALYST_DATABASE_URL=... python scripts/eval_crossposting_ml.py
    ANALYST_DATABASE_URL=... python scripts/eval_crossposting_ml.py --days 120
"""

from __future__ import annotations

import argparse
import asyncio
import math
import os
import sys
from dataclasses import dataclass
from typing import Iterable

import asyncpg

FEATURE_NAMES = [
    "log_source_signal",
    "log_source_posts",
    "log_pre_likes",
    "pre_like_rate",
    "log_pre_reactions",
    "log_pre_share_users",
    "caption_present",
    "hour_sin",
    "hour_cos",
]


@dataclass
class Example:
    channel: str
    posted_at: object
    fwd_per_1k_24h: float
    features: list[float]


async def get_connection() -> asyncpg.Connection:
    url = os.environ.get("ANALYST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: set ANALYST_DATABASE_URL or DATABASE_URL", file=sys.stderr)
        sys.exit(1)
    return await asyncpg.connect(url, statement_cache_size=0)


async def fetch_examples(conn: asyncpg.Connection, days: int) -> list[Example]:
    rows = await conn.fetch(
        """
        WITH labels AS (
          SELECT
            cp.channel,
            cp.meme_id,
            cp.created_at AS posted_at,
            m.meme_source_id,
            (m.caption IS NOT NULL)::int AS caption_present,
            s24.views AS views_24h,
            s24.forwards AS forwards_24h,
            1000.0 * s24.forwards / NULLIF(s24.views, 0) AS fwd_per_1k_24h
          FROM crossposting cp
          JOIN meme m ON m.id = cp.meme_id
          JOIN LATERAL (
            SELECT cps.snapshot_at, cps.views, cps.forwards
            FROM crossposting_snapshots cps
            WHERE cps.channel = cp.channel
              AND cps.meme_id = cp.meme_id
              AND cps.snapshot_at BETWEEN cp.created_at + interval '20 hours'
                                      AND cp.created_at + interval '36 hours'
              AND cps.views > 0
              AND cps.forwards IS NOT NULL
            ORDER BY abs(
              extract(epoch FROM cps.snapshot_at - (cp.created_at + interval '24 hours'))
            )
            LIMIT 1
          ) s24 ON true
          WHERE cp.channel IN ('tgchannelru', 'tgchannelen')
            AND cp.created_at < now() - interval '36 hours'
            AND cp.created_at >= now() - ($1 || ' days')::interval
            AND m.type = 'image'
        ),
        reaction_features AS (
          SELECT
            l.channel,
            l.meme_id,
            count(*) FILTER (WHERE r.reaction_id = 1) AS pre_likes,
            count(*) FILTER (WHERE r.reaction_id = 2) AS pre_skips,
            count(*) FILTER (WHERE r.reaction_id IN (1, 2)) AS pre_reactions
          FROM labels l
          LEFT JOIN user_meme_reaction r
            ON r.meme_id = l.meme_id
           AND r.reacted_at IS NOT NULL
           AND r.reacted_at < l.posted_at
           AND r.reaction_id IN (1, 2)
          GROUP BY l.channel, l.meme_id
        ),
        share_clicks AS (
          SELECT
            share_match.parts[2]::bigint AS meme_id,
            udll.user_id,
            udll.created_at
          FROM user_deep_link_log udll
          CROSS JOIN LATERAL regexp_matches(
            udll.deep_link,
            '^s_([1-9][0-9]{0,18})_([1-9][0-9]{0,18})$'
          ) AS share_match(parts)
          WHERE udll.created_at >= now() - ($1 || ' days')::interval
            AND CASE
              WHEN length(share_match.parts[1]) = 19
                AND share_match.parts[1] > '9223372036854775807' THEN false
              WHEN length(share_match.parts[2]) = 19
                AND share_match.parts[2] > '9223372036854775807' THEN false
              ELSE udll.user_id <> share_match.parts[1]::bigint
            END
        ),
        share_features AS (
          SELECT
            l.channel,
            l.meme_id,
            count(*) AS pre_share_clicks,
            count(DISTINCT sc.user_id) AS pre_share_users
          FROM labels l
          LEFT JOIN share_clicks sc
            ON sc.meme_id = l.meme_id
           AND sc.created_at < l.posted_at
          GROUP BY l.channel, l.meme_id
        )
        SELECT
          l.channel,
          l.posted_at,
          l.fwd_per_1k_24h,
          l.caption_present,
          COALESCE(rf.pre_likes, 0) AS pre_likes,
          COALESCE(rf.pre_skips, 0) AS pre_skips,
          COALESCE(rf.pre_reactions, 0) AS pre_reactions,
          COALESCE(sf.pre_share_users, 0) AS pre_share_users,
          extract(hour FROM l.posted_at + interval '3 hours')::int AS hour_msk,
          COALESCE(sq.source_signal, 0) AS source_signal,
          COALESCE(sq.source_posts, 0) AS source_posts
        FROM labels l
        JOIN reaction_features rf ON rf.channel = l.channel AND rf.meme_id = l.meme_id
        JOIN share_features sf ON sf.channel = l.channel AND sf.meme_id = l.meme_id
        LEFT JOIN LATERAL (
          SELECT
            AVG(cp2.forwards * SQRT(GREATEST(cp2.views, 1) / 100.0)) AS source_signal,
            COUNT(*) AS source_posts
          FROM crossposting cp2
          JOIN meme m2 ON m2.id = cp2.meme_id
          WHERE cp2.channel = l.channel
            AND cp2.created_at > l.posted_at - interval '30 days'
            AND cp2.created_at < l.posted_at - interval '48 hours'
            AND cp2.views IS NOT NULL
            AND cp2.views > 0
            AND cp2.forwards IS NOT NULL
            AND m2.type = 'image'
            AND m2.meme_source_id = l.meme_source_id
        ) sq ON true
        ORDER BY l.channel, l.posted_at
        """,
        str(days),
    )

    examples: list[Example] = []
    for row in rows:
        pre_reactions = row["pre_reactions"] or 0
        pre_likes = row["pre_likes"] or 0
        pre_like_rate = pre_likes / pre_reactions if pre_reactions else 0.5
        hour_angle = 2 * math.pi * (row["hour_msk"] or 0) / 24
        features = [
            math.log1p(float(row["source_signal"] or 0)),
            math.log1p(float(row["source_posts"] or 0)),
            math.log1p(float(pre_likes)),
            pre_like_rate,
            math.log1p(float(pre_reactions)),
            math.log1p(float(row["pre_share_users"] or 0)),
            float(row["caption_present"] or 0),
            math.sin(hour_angle),
            math.cos(hour_angle),
        ]
        examples.append(
            Example(
                channel=row["channel"],
                posted_at=row["posted_at"],
                fwd_per_1k_24h=float(row["fwd_per_1k_24h"]),
                features=features,
            )
        )
    return examples


def median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        raise ValueError("median of empty list")
    midpoint = n // 2
    if n % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


def standardize(
    train_x: list[list[float]],
    test_x: list[list[float]],
) -> tuple[list[list[float]], list[list[float]]]:
    n_features = len(train_x[0])
    means = [sum(x[j] for x in train_x) / len(train_x) for j in range(n_features)]
    stds = []
    for j in range(n_features):
        variance = sum((x[j] - means[j]) ** 2 for x in train_x) / len(train_x)
        stds.append(math.sqrt(variance) or 1.0)

    def transform(rows: list[list[float]]) -> list[list[float]]:
        return [[(x[j] - means[j]) / stds[j] for j in range(n_features)] for x in rows]

    return transform(train_x), transform(test_x)


def sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1 / (1 + z)
    z = math.exp(value)
    return z / (1 + z)


def train_logistic_regression(
    train_x: list[list[float]],
    train_y: list[int],
    *,
    iterations: int,
    lr: float,
    l2: float,
) -> list[float]:
    n_features = len(train_x[0])
    weights = [0.0] * (n_features + 1)

    for _ in range(iterations):
        gradients = [0.0] * (n_features + 1)
        for x, y in zip(train_x, train_y):
            z = weights[0] + sum(w * v for w, v in zip(weights[1:], x))
            error = sigmoid(z) - y
            gradients[0] += error
            for j, value in enumerate(x, start=1):
                gradients[j] += error * value

        n = len(train_x)
        weights[0] -= lr * gradients[0] / n
        for j in range(1, len(weights)):
            gradients[j] = gradients[j] / n + l2 * weights[j]
            weights[j] -= lr * gradients[j]

    return weights


def predict(weights: list[float], rows: list[list[float]]) -> list[float]:
    return [sigmoid(weights[0] + sum(w * v for w, v in zip(weights[1:], x))) for x in rows]


def auc(scores: list[float], labels: list[int]) -> float:
    positives = [(s, y) for s, y in zip(scores, labels) if y == 1]
    negatives = [(s, y) for s, y in zip(scores, labels) if y == 0]
    if not positives or not negatives:
        return 0.5

    wins = 0.0
    total = 0
    for pos_score, _ in positives:
        for neg_score, _ in negatives:
            total += 1
            if pos_score > neg_score:
                wins += 1
            elif pos_score == neg_score:
                wins += 0.5
    return wins / total


def top_quintile_lift(scores: list[float], labels: list[int]) -> float:
    if not labels or sum(labels) == 0:
        return 0.0
    paired = sorted(zip(scores, labels), key=lambda pair: pair[0], reverse=True)
    top_n = max(1, math.ceil(len(paired) * 0.2))
    selected_count = 0.0
    selected_positives = 0.0
    index = 0
    while selected_count < top_n and index < len(paired):
        score = paired[index][0]
        group_labels: list[int] = []
        while index < len(paired) and paired[index][0] == score:
            group_labels.append(paired[index][1])
            index += 1

        remaining = top_n - selected_count
        if len(group_labels) <= remaining:
            selected_count += len(group_labels)
            selected_positives += sum(group_labels)
        else:
            selected_count += remaining
            selected_positives += sum(group_labels) * (remaining / len(group_labels))

    top_rate = selected_positives / top_n
    base_rate = sum(labels) / len(labels)
    return top_rate / base_rate if base_rate else 0.0


def evaluate_channel(channel: str, examples: list[Example], train_fraction: float) -> None:
    channel_examples = [e for e in examples if e.channel == channel]
    channel_examples.sort(key=lambda e: e.posted_at)
    if len(channel_examples) < 30:
        print(f"\n{channel}: not enough labeled posts ({len(channel_examples)})")
        return

    split = max(1, min(len(channel_examples) - 1, int(len(channel_examples) * train_fraction)))
    train = channel_examples[:split]
    test = channel_examples[split:]
    threshold = median(e.fwd_per_1k_24h for e in train)

    train_x = [e.features for e in train]
    test_x = [e.features for e in test]
    train_y = [int(e.fwd_per_1k_24h >= threshold) for e in train]
    test_y = [int(e.fwd_per_1k_24h >= threshold) for e in test]

    if len(set(train_y)) < 2 or len(set(test_y)) < 2:
        print(f"\n{channel}: split has one target class, cannot evaluate")
        return

    train_x_std, test_x_std = standardize(train_x, test_x)
    weights = train_logistic_regression(
        train_x_std,
        train_y,
        iterations=2500,
        lr=0.05,
        l2=0.05,
    )
    scores = predict(weights, test_x_std)

    baselines = {
        "source_signal": [x[0] for x in test_x],
        "pre_likes": [x[2] for x in test_x],
        "pre_share_users": [x[5] for x in test_x],
    }

    print(f"\n{channel}")
    print(f"  labeled posts: {len(channel_examples)}")
    print(f"  train/test: {len(train)}/{len(test)}")
    print(f"  train median target: {threshold:.2f} fwd/1k")
    print(f"  logistic_auc: {auc(scores, test_y):.3f}")
    print(f"  logistic_top20_lift: {top_quintile_lift(scores, test_y):.2f}x")
    print(f"  pre_share_users_coverage: {sum(1 for x in test_x if x[5] > 0)}/{len(test_x)}")
    for name, baseline_scores in baselines.items():
        print(f"  {name}_auc: {auc(baseline_scores, test_y):.3f}")
        print(f"  {name}_top20_lift: {top_quintile_lift(baseline_scores, test_y):.2f}x")

    coef_pairs = sorted(
        zip(FEATURE_NAMES, weights[1:]),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    print("  strongest coefficients:")
    for name, value in coef_pairs[:5]:
        print(f"    {name}: {value:+.3f}")


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=120)
    parser.add_argument("--train-fraction", type=float, default=0.7)
    args = parser.parse_args()

    conn = await get_connection()
    try:
        await conn.execute("SET statement_timeout = '30s'")
        examples = await fetch_examples(conn, args.days)
    finally:
        await conn.close()

    print("Crossposting ML offline eval")
    print(f"Examples: {len(examples)} image posts over {args.days} days")
    for channel in ("tgchannelru", "tgchannelen"):
        evaluate_channel(channel, examples, args.train_fraction)


if __name__ == "__main__":
    asyncio.run(main())
