"""Export a minimal, pseudonymous dormant-push snapshot to private local storage."""

import argparse
import csv
import ctypes
import gzip
import hashlib
import io
import json
import os
import re
import signal
import stat
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from datetime import time as day_time
from decimal import Decimal
from pathlib import Path

from run_push_backtest import collect

ROOT = Path.home() / ".local" / "share" / "ffmemes-analyst"
COLUMNS = (
    "event_id",
    "user_key",
    "sent_at",
    "y_24h",
    "path",
    "idle_days",
    "dormancy_cohort",
    "user_push_send_count",
    "user_push_count",
    "user_push_reaction_rate",
    "user_feed_callback_count",
    "hours_since_push",
    "user_source_reaction_count",
    "user_source_like_rate",
    "meme_like_rate",
    "meme_send_count",
    "source_like_rate",
    "source_send_count",
    "legacy_proxy_score",
    "meme_age_days",
    "meme_is_video",
    "meme_is_animation",
    "taste_feed_count",
    "taste_feed_like_rate",
    "taste_source_count",
    "taste_source_like_rate",
)
PATHS = {"broadcast_reengagement", "broadcast_reengagement_hq"}
HASH = re.compile(r"[a-f0-9]{32}")
NUMBER = re.compile(r"[0-9]{1,20}(?:\.[0-9]{1,40})?")
UTC_STAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z")
NULLABLE = {"hours_since_push", "meme_age_days"}


def private_dir(path):
    if path.is_symlink() or path != path.resolve():
        raise ValueError("private path cannot follow symlinks")
    path.mkdir(mode=0o700, exist_ok=True)
    if (
        not path.is_dir()
        or path.stat().st_uid != os.getuid()
        or stat.S_IMODE(path.stat().st_mode) != 0o700
    ):
        raise ValueError("private directory must be owned by this account, mode 0700")


def publish(staged, output):
    # Unlike POSIX rename(), these also refuse to replace an empty destination directory.
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        result = libc.renamex_np(os.fsencode(staged), os.fsencode(output), 4)  # RENAME_EXCL
    elif sys.platform.startswith("linux"):
        result = libc.renameat2(-100, os.fsencode(staged), -100, os.fsencode(output), 1)
    else:
        raise RuntimeError("atomic exclusive directory rename is unavailable on this platform")
    if result:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), output)


def write_rows(stream, destination, start, end, as_of):
    reader = csv.DictReader(stream, strict=True)
    if tuple(reader.fieldnames or ()) != COLUMNS:
        raise ValueError("unexpected SQL result schema")
    writer = csv.DictWriter(destination, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    filtered, paths, cohorts, outcomes = (Counter() for _ in range(4))
    cutoff = datetime.combine(as_of, day_time.min, UTC)
    users, events = set(), set()
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("unexpected SQL row width")
        if row["path"] not in PATHS or row["y_24h"] not in {"0", "1"}:
            raise ValueError("invalid surface or outcome")
        if not all(HASH.fullmatch(row[key]) for key in ("event_id", "user_key")):
            raise ValueError("invalid pseudonymous identifier")
        if not UTC_STAMP.fullmatch(row["sent_at"]):
            raise ValueError("invalid UTC timestamp")
        sent_at = datetime.fromisoformat(row["sent_at"])
        if not start <= sent_at.date() < end:
            raise ValueError("row outside requested delivery interval")
        if sent_at + timedelta(hours=24) > cutoff:
            filtered["immature"] += 1
            continue
        if not row["idle_days"]:
            filtered["unknown_idle"] += 1
            continue
        if not NUMBER.fullmatch(row["idle_days"]):
            raise ValueError("invalid idle value")
        idle = Decimal(row["idle_days"])
        if not 7 <= idle <= 365:
            filtered["idle_below_7" if idle < 7 else "idle_above_365"] += 1
            continue
        cohort = "7_to_29d" if idle < 29 else "29_to_90d" if idle < 90 else "90d_plus"
        if row["dormancy_cohort"] != cohort:
            raise ValueError("invalid dormancy cohort")
        for key in COLUMNS[7:]:
            value = row[key]
            if not value and key in NULLABLE:
                continue
            if not NUMBER.fullmatch(value):
                raise ValueError(f"invalid numeric feature {key}")
            if key.endswith("_count") and not value.isdecimal():
                raise ValueError(f"invalid count {key}")
            if (key.endswith("_rate") or key == "legacy_proxy_score") and Decimal(value) > 1:
                raise ValueError(f"invalid rate {key}")
            if key.startswith("meme_is_") and value not in {"0", "1"}:
                raise ValueError(f"invalid media flag {key}")
        if row["event_id"] in events:
            raise ValueError("duplicate eligible delivery")
        events.add(row["event_id"])
        users.add(row["user_key"])
        paths[row["path"]] += 1
        cohorts[cohort] += 1
        outcomes[row["y_24h"]] += 1
        writer.writerow(row)
    return {
        "eligible_rows": len(events),
        "unique_users": len(users),
        "outcomes": dict(outcomes),
        "paths": dict(paths),
        "cohorts": dict(cohorts),
        "excluded": dict(filtered),
        "input_rows": len(events) + sum(filtered.values()),
    }


def export(root, name, start, end, as_of, batch_days=7, *, psql=None):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", name):
        raise ValueError("invalid dataset directory name")
    if not start < end <= as_of - timedelta(days=1) or as_of > datetime.now(UTC).date():
        raise ValueError("require a past delivery interval and fully elapsed 24h horizon")
    if not 1 <= batch_days <= 31:
        raise ValueError("batch size must be 1..31 days")
    directory = root / "datasets"
    if any((ancestor / ".git").exists() for ancestor in [directory, *directory.parents]):
        raise ValueError("dataset storage must be outside Git")
    private_dir(root)
    private_dir(directory)
    output = directory / name
    if os.path.lexists(output):
        raise FileExistsError("snapshot destination already exists")
    started = time.monotonic()
    batches = []
    with tempfile.TemporaryFile() as raw, tempfile.TemporaryDirectory(dir=directory) as tmp:
        stage = Path(tmp) / "snapshot"
        private_dir(stage)
        sql_hash = collect(psql or ["psql", "-Xq"], start, end, batch_days, raw, batches=batches)
        data = stage / "rows.csv.gz"
        with open_private(data) as blob:
            with gzip.GzipFile(filename="", mode="wb", fileobj=blob, mtime=0) as gz:
                with io.TextIOWrapper(gz, encoding="ascii", newline="") as out:
                    with io.TextIOWrapper(raw, encoding="ascii", newline="") as source:
                        counts = write_rows(source, out, start, end, as_of)
        if sum(batch["rows"] for batch in batches) != counts["input_rows"]:
            raise ValueError("chunk totals differ from parsed row count")
        with data.open("rb") as stored:
            digest = hashlib.file_digest(stored, "sha256").hexdigest()
        header = ",".join(COLUMNS) + "\n"
        manifest = {
            "schema_version": 1,
            "columns": COLUMNS,
            "schema_sha256": hashlib.sha256(header.encode()).hexdigest(),
            "sql_sha256": sql_hash,
            "data_sha256": digest,
            "bytes": data.stat().st_size,
            "delivery_start_inclusive": start.isoformat(),
            "delivery_end_exclusive": end.isoformat(),
            "label_cutoff_utc": as_of.isoformat(),
            "label_horizon_hours": 24,
            "source_consistency": "separate read-only database snapshots per sequential batch",
            "segment": "user",
            "idle_days_inclusive": [7, 365],
            "batch_days": batch_days,
            "batches": batches,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            **counts,
        }
        with open_private(stage / "manifest.json") as file:
            file.write((json.dumps(manifest, indent=2) + "\n").encode())
        publish(stage, output)
    return output


def open_private(path):
    return os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb")


if __name__ == "__main__":
    # Use normal context-manager cleanup when an operator stops the CLI mid-export.
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="private non-Git data root")
    parser.add_argument("--name", required=True)
    parser.add_argument("--start", required=True, type=date.fromisoformat)
    parser.add_argument("--end", required=True, type=date.fromisoformat)
    parser.add_argument("--as-of", required=True, type=date.fromisoformat)
    parser.add_argument("--batch-days", type=int, default=7)
    parser.add_argument("psql", nargs=argparse.REMAINDER, help="-- psql -Xq or read-only wrapper")
    args = parser.parse_args()
    command = args.psql[1:] if args.psql[:1] == ["--"] else args.psql
    print(
        export(
            args.root.expanduser().absolute(),
            args.name,
            args.start,
            args.end,
            args.as_of,
            args.batch_days,
            psql=command,
        )
    )
