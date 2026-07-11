"""Run the true-new cold-start first-10 quality readout.

Usage:
    source .env
    python scripts/cold_start_first10_quality_readout.py --lookback-days 14

The query is shadow-only analytics: it reads user_meme_reaction/meme stats and
does not change recommendation ranking, thresholds, weights, or assignments.
"""

import argparse
import asyncio
import os
from collections.abc import Sequence
from decimal import Decimal
from typing import Any


def _to_asyncpg_url(url: str) -> str:
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _configure_database_url() -> None:
    analyst_url = os.environ.get("ANALYST_DATABASE_URL")
    if analyst_url and not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = _to_asyncpg_url(analyst_url)
    elif os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = _to_asyncpg_url(os.environ["DATABASE_URL"])


def _format_value(value: Any) -> str:
    if isinstance(value, Decimal):
        return str(value.normalize())
    if value is None:
        return ""
    return str(value)


def _print_rows(title: str, rows: Sequence[dict[str, Any]]) -> None:
    print(f"\n## {title}")
    if not rows:
        print("(no rows)")
        return

    columns = list(rows[0].keys())
    print("\t".join(columns))
    for row in rows:
        print("\t".join(_format_value(row[column]) for column in columns))


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lookback-days", type=int, default=14)
    parser.add_argument("--min-candidate-sends", type=int, default=3)
    parser.add_argument("--candidate-limit", type=int, default=20)
    args = parser.parse_args()

    _configure_database_url()

    from src.stats.cold_start_quality import fetch_cold_start_first10_quality_readout

    readout = await fetch_cold_start_first10_quality_readout(
        lookback_days=args.lookback_days,
        min_candidate_sends=args.min_candidate_sends,
        candidate_limit=args.candidate_limit,
    )
    for section, rows in readout.items():
        _print_rows(section, rows)


if __name__ == "__main__":
    asyncio.run(_main())
