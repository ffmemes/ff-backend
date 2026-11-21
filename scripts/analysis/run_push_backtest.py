"""Extract UTC batches and evaluate the dormant push model in an analyst workspace."""

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
SQL = HERE.parents[1] / "docs" / "analyst" / "push-reactivation-training.sql"


def collect(psql, start, end, batch_days, file):
    """Write only complete, matching CSV batches to an anonymous temporary file."""
    sql = SQL.read_text()
    salt = secrets.token_hex(32)
    expected_header = None
    while start < end:
        stop = min(start + timedelta(days=batch_days), end)
        # The SQL takes the label horizon (one day after the exclusive delivery end).
        request = (
            "\\set ON_ERROR_STOP on\n\\set QUIET on\n\\pset format csv\n"
            f"\\set as_of {(stop + timedelta(days=1)).isoformat()}\n"
            f"\\set days {(stop - start).days}\n\\set salt {salt}\n"
            "BEGIN READ ONLY;\nSET LOCAL timezone = 'UTC';\n"
            "SET LOCAL statement_timeout = '30s';\n" + sql + "\nROLLBACK;\n"
        )
        result = subprocess.run(psql, input=request.encode(), stdout=subprocess.PIPE, timeout=65)
        result.check_returncode()
        header, newline, rows = result.stdout.partition(b"\n")
        if not newline or header.split(b",")[:3] != [b"event_id", b"user_key", b"sent_at"]:
            raise ValueError("Unexpected extraction header; use psql -Xq with CSV output")
        if expected_header is None:
            expected_header = header
            file.write(header + b"\n")
        elif header != expected_header:
            raise ValueError("SQL schema changed between batches")
        file.write(rows)
        count = rows.count(b"\n")
        print(f"{start} to {stop}: {count} deliveries", file=sys.stderr, flush=True)
        start = stop
    file.seek(0)
    return hashlib.sha256(sql.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, required=True, help="UTC label cutoff")
    parser.add_argument(
        "--start", type=date.fromisoformat, required=True, help="first delivery date"
    )
    parser.add_argument("--output", type=Path, required=True, help="new private run directory")
    parser.add_argument("--holdout-start", type=date.fromisoformat, required=True)
    parser.add_argument("--previous-model", type=Path, help="also score these frozen weights")
    parser.add_argument("--fold-days", type=int, default=14)
    parser.add_argument("--batch-days", type=int, choices=range(1, 32), default=7)
    parser.add_argument("psql", nargs=argparse.REMAINDER, help="-- psql -Xq [connection options]")
    args = parser.parse_args()
    if args.as_of > datetime.now(UTC).date():
        parser.error("as-of cannot include future outcomes")
    end = args.as_of - timedelta(days=1)
    if not args.start < min(end, args.holdout_start) or args.holdout_start > args.as_of:
        parser.error("need historical deliveries and a training cutoff on or before as-of")
    if args.output.exists():
        parser.error("choose a new output directory to preserve the previous model")
    psql = args.psql[1:] if args.psql[:1] == ["--"] else args.psql
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryFile() as rows,
        tempfile.TemporaryDirectory(dir=args.output.parent, prefix=".push-run-") as tmp,
    ):
        sql_hash = collect(psql or ["psql", "-Xq"], args.start, end, args.batch_days, rows)
        staging = Path(tmp)
        run = [
            sys.executable,
            str(HERE / "push_reactivation_backtest.py"),
            "--input",
            "-",
            "--as-of",
            args.as_of.isoformat(),
        ]
        fit = [
            "--holdout-start",
            args.holdout_start.isoformat(),
            "--fold-days",
            str(args.fold_days),
            "--model-out",
            str(staging / "model.json"),
        ]
        with (staging / "report.json").open("xb") as report:
            subprocess.run(run + fit, stdin=rows, stdout=report, check=True)
        if args.previous_model:
            previous = json.loads(args.previous_model.read_text())
            current = json.loads((staging / "report.json").read_text())
            if (
                previous["final_days"] != args.fold_days
                or previous["min_idle_days"] != current["min_idle_days"]
            ):
                raise ValueError("Both models must use the same window and dormancy threshold")
            rows.seek(0)
            evaluate = [
                "--frozen-model",
                str(args.previous_model),
                "--evaluation-start",
                args.holdout_start.isoformat(),
            ]
            with (staging / "previous.json").open("xb") as report:
                subprocess.run(run + evaluate, stdin=rows, stdout=report, check=True)
        manifest = {
            "delivery_start_inclusive": args.start.isoformat(),
            "delivery_end_exclusive": end.isoformat(),
            "label_cutoff_utc": args.as_of.isoformat(),
            "batch_days": args.batch_days,
            "sql_sha256": sql_hash,
            "source_consistency": "separate read-only database snapshots per batch",
        }
        (staging / "extraction.json").write_text(json.dumps(manifest, indent=2) + "\n")
        # Publish the complete pair (or report alone when support is insufficient).
        os.rename(staging, args.output)
    print(args.output / "report.json")


if __name__ == "__main__":
    main()
