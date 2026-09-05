"""Preview/freeze channel-hit enrollment or read its outcomes; no IDs in output.

Enrollment is a dry run by default. --apply writes one complete frozen cohort,
requires the reviewed preview digest, and never appends or reallocates members.
Eligibility uses the existing cached pool and channel membership backfill only;
this script makes no Telegram HTTP requests and sends no messages.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

EXPERIMENT_ID = "channel_hits_v1"
ALGORITHM_VERSION = "all_eligible_hashrank_alternating_v1"
DEFAULT_SEED = f"{EXPERIMENT_ID}:1"
MIN_INVENTORY = 14
READOUT_SQL = Path(__file__).resolve().parents[1] / "docs/analyst/channel-hits-v1.sql"
FROZEN_FIELDS = (
    "snapshot_at",
    "experiment_start_at",
    "exposure_end_at",
    "readout_at",
    "seed",
    "algorithm_version",
    "cohort_size",
    "active_days_28d",
    "reactions_28d",
    "likes_28d",
    "inventory_count",
    "inventory_count_limit",
)

ELIGIBILITY_SQL = """
SELECT u.id AS user_id, count(*) AS reactions_28d,
       count(*) FILTER (WHERE reaction_id = 1) AS likes_28d,
       count(DISTINCT reacted_at::date) AS active_days_28d
FROM user_meme_reaction r JOIN "user" u ON u.id = r.user_id
WHERE reacted_at >= $1::timestamp - interval '28 days' AND reacted_at < $1::timestamp
  AND reaction_id IN (1, 2) AND u.type = 'user' AND u.blocked_bot_at IS NULL
  AND recommended_by NOT IN ('uploaded_meme', 'low_sent_pool', 'friend_challenge')
  AND recommended_by NOT LIKE 'broadcast%' AND recommended_by NOT LIKE 'friend_challenge%'
GROUP BY u.id
HAVING count(DISTINCT reacted_at::date) >= 8
   AND count(*) FILTER (WHERE reaction_id = 1) >= 20
"""
EXISTING_SQL = """
SELECT user_id, variant, assignment_metadata, assigned_at
FROM experiment_assignment WHERE experiment_id = $1 ORDER BY user_id
"""
INSERT_SQL = """
INSERT INTO experiment_assignment
    (experiment_id, user_id, variant, assignment_metadata, assigned_at)
VALUES ($1, $2, $3, $4::jsonb, $5)
"""


def utc_datetime(value: str | datetime) -> datetime:
    result = (
        datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    )
    if result.tzinfo is None:
        raise ValueError("Timestamps must include UTC or an explicit timezone offset")
    return result.astimezone(timezone.utc)


def iso_utc(value: datetime) -> str:
    return utc_datetime(value).isoformat().replace("+00:00", "Z")


def database_time(value: datetime) -> datetime:
    return utc_datetime(value).replace(tzinfo=None)


def _digest(rows: list[dict[str, Any]]) -> str:
    payload = [
        {
            "user_id": r["user_id"],
            "variant": r["variant"],
            "metadata": {k: r["assignment_metadata"][k] for k in FROZEN_FIELDS},
        }
        for r in sorted(rows, key=lambda r: r["user_id"])
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def build_cohort(
    candidates: list[dict[str, Any]],
    snapshot_at: datetime,
    start_at: datetime,
    seed: str = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    """Include every eligible host, with deterministic arms differing by at most one."""
    snapshot_at, start_at = utc_datetime(snapshot_at), utc_datetime(start_at)
    if start_at < snapshot_at:
        raise ValueError("Start must be at or after the baseline snapshot")
    if not seed or len(candidates) < 2:
        raise ValueError("Need a nonempty seed and at least two eligible users")
    if len({r["user_id"] for r in candidates}) != len(candidates):
        raise ValueError("Candidate users must be unique")
    ordered = sorted(
        candidates,
        key=lambda r: hashlib.sha256(
            json.dumps([seed, int(r["user_id"])], separators=(",", ":")).encode()
        ).hexdigest(),
    )
    shared = {
        "snapshot_at": iso_utc(snapshot_at),
        "experiment_start_at": iso_utc(start_at),
        "exposure_end_at": iso_utc(start_at + timedelta(days=14)),
        "readout_at": iso_utc(start_at + timedelta(days=28)),
        "seed": seed,
        "algorithm_version": ALGORITHM_VERSION,
        "cohort_size": len(ordered),
    }
    rows = []
    for position, candidate in enumerate(ordered):
        metadata = {
            **shared,
            **{
                key: int(candidate[key])
                for key in ("active_days_28d", "reactions_28d", "likes_28d", "inventory_count")
            },
            "inventory_count_limit": MIN_INVENTORY,
        }
        if (
            metadata["active_days_28d"] < 8
            or metadata["likes_28d"] < 20
            or metadata["inventory_count"] < MIN_INVENTORY
        ):
            raise ValueError("Candidate does not meet the declared eligibility")
        rows.append(
            {
                "user_id": int(candidate["user_id"]),
                "variant": "control" if position % 2 == 0 else "treatment",
                "assignment_metadata": metadata,
            }
        )
    digest = _digest(rows)
    for row in rows:
        row["assignment_metadata"]["cohort_digest"] = digest
    return sorted(rows, key=lambda r: r["user_id"])


def validate_cohort(rows: list[dict[str, Any]]) -> str:
    if len(rows) < 2 or len({r["user_id"] for r in rows}) != len(rows):
        raise ValueError("Stored cohort must contain at least two unique users")
    first = rows[0]["assignment_metadata"]
    shared = FROZEN_FIELDS[:7]
    for row in rows:
        meta = row["assignment_metadata"]
        if any(meta.get(k) != first.get(k) for k in shared) or meta.get("cohort_size") != len(rows):
            raise ValueError("Partial or inconsistent frozen cohort; refusing to append")
        if meta.get("algorithm_version") != ALGORITHM_VERSION:
            raise ValueError("Unsupported enrollment algorithm")
        if (
            meta.get("active_days_28d", 0) < 8
            or meta.get("likes_28d", 0) < 20
            or meta.get("inventory_count", 0) < MIN_INVENTORY
        ):
            raise ValueError("Frozen baseline does not meet eligibility")
        if meta.get("inventory_count_limit") != MIN_INVENTORY:
            raise ValueError("Frozen inventory count convention differs")
        if "assigned_at" in row:
            assigned_at = row["assigned_at"]
            if assigned_at.tzinfo is None:
                assigned_at = assigned_at.replace(tzinfo=timezone.utc)
            if iso_utc(assigned_at) != first["experiment_start_at"]:
                raise ValueError("Assignment time differs from the common start")
    counts = Counter(r["variant"] for r in rows)
    if counts != Counter(control=(len(rows) + 1) // 2, treatment=len(rows) // 2):
        raise ValueError("Stored arms are not balanced")
    start = utc_datetime(first["experiment_start_at"])
    if utc_datetime(first["snapshot_at"]) > start:
        raise ValueError("Snapshot is after experiment start")
    if utc_datetime(first["exposure_end_at"]) != start + timedelta(days=14) or utc_datetime(
        first["readout_at"]
    ) != start + timedelta(days=28):
        raise ValueError("Stored windows differ from the 14/28-day protocol")
    digest = _digest(rows)
    if any(r["assignment_metadata"].get("cohort_digest") != digest for r in rows):
        raise ValueError("Frozen cohort digest mismatch")
    return digest


def cohort_summary(rows: list[dict[str, Any]], status: str) -> dict[str, Any]:
    digest = validate_cohort(rows)
    first = rows[0]["assignment_metadata"]
    return {
        "experiment_id": EXPERIMENT_ID,
        "status": status,
        "cohort_digest": digest,
        **{
            k: first[k]
            for k in ("snapshot_at", "experiment_start_at", "exposure_end_at", "readout_at")
        },
        "inventory_count_is_capped_at": MIN_INVENTORY,
        "arms": {
            arm: {
                "assigned_users": sum(r["variant"] == arm for r in rows),
                "baseline_reactions_28d": sum(
                    r["assignment_metadata"]["reactions_28d"] for r in rows if r["variant"] == arm
                ),
            }
            for arm in ("control", "treatment")
        },
    }


async def _existing(conn: Any) -> list[dict[str, Any]]:
    rows = [dict(r) for r in await conn.fetch(EXISTING_SQL, EXPERIMENT_ID)]
    for row in rows:
        if isinstance(row["assignment_metadata"], str):
            row["assignment_metadata"] = json.loads(row["assignment_metadata"])
    return rows


async def enroll(conn: Any, args: argparse.Namespace) -> dict[str, Any]:
    snapshot_at, start_at = utc_datetime(args.snapshot_at), utc_datetime(args.start_at)
    async with conn.transaction(readonly=not args.apply):
        if args.apply:
            if not args.expected_cohort_digest:
                raise ValueError("--apply requires --expected-cohort-digest from a preview")
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", EXPERIMENT_ID
            )
        existing = await _existing(conn)
        if existing:
            digest = validate_cohort(existing)
            meta = existing[0]["assignment_metadata"]
            if (meta["snapshot_at"], meta["experiment_start_at"], meta["seed"]) != (
                iso_utc(snapshot_at),
                iso_utc(start_at),
                args.seed,
            ):
                raise ValueError("A differently configured cohort is already frozen")
            if args.expected_cohort_digest and args.expected_cohort_digest != digest:
                raise ValueError("Expected digest differs from the frozen cohort")
            return cohort_summary(existing, "already_frozen")
        now = await conn.fetchval("SELECT now()")
        if snapshot_at > now:
            raise ValueError("Baseline snapshot cannot be in the future")
        if args.apply and start_at <= now:
            raise ValueError("Initial enrollment requires a future common start")
        candidates = [
            dict(r) for r in await conn.fetch(ELIGIBILITY_SQL, database_time(snapshot_at))
        ]
        root = str(Path(__file__).resolve().parents[1])
        if root not in sys.path:
            sys.path.insert(0, root)
        from src.recommendations.channel_hits import eligible_channel_hits

        eligible = []
        for candidate in candidates:
            hits = await eligible_channel_hits(candidate["user_id"], limit=MIN_INVENTORY)
            count = len({hit["id"] for hit in hits})
            if count >= MIN_INVENTORY:
                eligible.append({**candidate, "inventory_count": MIN_INVENTORY})
        rows = build_cohort(eligible, snapshot_at, start_at, args.seed)
        digest = validate_cohort(rows)
        if args.expected_cohort_digest and args.expected_cohort_digest != digest:
            raise ValueError("Cohort changed since preview; review a new preview digest")
        if args.apply:
            await conn.executemany(
                INSERT_SQL,
                [
                    (
                        EXPERIMENT_ID,
                        r["user_id"],
                        r["variant"],
                        json.dumps(r["assignment_metadata"]),
                        database_time(start_at),
                    )
                    for r in rows
                ],
            )
            validate_cohort(await _existing(conn))
        result = cohort_summary(rows, "applied" if args.apply else "dry_run")
        result["ordinary_core_checked"] = len(candidates)
        result["eligible_users"] = len(eligible)
        return result


async def readout(conn: Any, args: argparse.Namespace) -> dict[str, Any]:
    async with conn.transaction(readonly=True, isolation="repeatable_read"):
        rows = await _existing(conn)
        if not rows:
            return {"experiment_id": EXPERIMENT_ID, "status": "not_enrolled"}
        validate_cohort(rows)
        now = await conn.fetchval("SELECT now()")
        as_of = utc_datetime(args.as_of) if args.as_of else now
        if as_of > now:
            raise ValueError("Readout time cannot be in the future")
        arms = [
            dict(r)
            for r in await conn.fetch(READOUT_SQL.read_text(), database_time(as_of), EXPERIMENT_ID)
        ]
        mature = as_of >= utc_datetime(rows[0]["assignment_metadata"]["readout_at"])
        return {
            **cohort_summary(rows, "mature" if mature else "pending"),
            "as_of": iso_utc(as_of),
            "outcomes": arms,
            "interpretation": (
                "Descriptive intent-to-treat results; pending followups are not failures. "
                "No automatic statistical or growth-win declaration."
            ),
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    enrollment = commands.add_parser("enroll", help="Preview all eligible core users")
    enrollment.add_argument("--snapshot-at", required=True, type=utc_datetime)
    enrollment.add_argument("--start-at", required=True, type=utc_datetime)
    enrollment.add_argument("--seed", default=DEFAULT_SEED)
    enrollment.add_argument("--apply", action="store_true")
    enrollment.add_argument("--expected-cohort-digest")
    analysis = commands.add_parser(
        "readout", help="Read exposure, referral, retention and guardrails"
    )
    analysis.add_argument("--as-of", type=utc_datetime)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    import asyncpg
    from sqlalchemy.engine import make_url

    apply = args.command == "enroll" and args.apply
    variable = "DATABASE_URL" if apply else "ANALYST_DATABASE_URL"
    url = os.environ.get(variable)
    if not url:
        raise ValueError(f"Set {variable}; credentials must stay in environment/secret storage")
    # The root eligibility API uses src.database; bind its read queries to the
    # same selected database, with the analyst role on every dry run.
    parsed_url = make_url(url)
    os.environ["DATABASE_URL"] = parsed_url.set(drivername="postgresql+asyncpg").render_as_string(
        hide_password=False
    )
    conn = await asyncpg.connect(
        parsed_url.set(drivername="postgresql").render_as_string(hide_password=False),
        timeout=10,
        statement_cache_size=0,
        server_settings={
            "timezone": "UTC",
            "statement_timeout": "30000",
            "lock_timeout": "5000",
            "default_transaction_read_only": "off" if apply else "on",
        },
    )
    try:
        return await enroll(conn, args) if args.command == "enroll" else await readout(conn, args)
    finally:
        await conn.close()
        if "src.database" in sys.modules:
            await sys.modules["src.database"].engine.dispose()
        if "src.redis" in sys.modules:
            await sys.modules["src.redis"].redis_client.aclose()
            await sys.modules["src.redis"].pool.disconnect()


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = asyncio.run(_run(args))
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2
    except Exception as exc:
        print(json.dumps({"ok": False, "error": type(exc).__name__}), file=sys.stderr)
        return 1
    print(json.dumps(result, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
