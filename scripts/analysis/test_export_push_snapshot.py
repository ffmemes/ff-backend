"""Private snapshot schema, validation and publication checks using synthetic records."""

import csv
import gzip
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import export_push_snapshot as snapshot

START = date(2026, 8, 9)
END = date(2026, 8, 11)
AS_OF = date(2026, 8, 12)


def delivery(event_number=1, **changes):
    row = dict.fromkeys(snapshot.COLUMNS, "0")
    row.update(
        event_id=f"{event_number:032x}",
        user_key="a" * 32,
        sent_at="2026-08-09T10:10:10.000000Z",
        path="broadcast_reengagement_hq",
        idle_days="7.00",
        dormancy_cohort="7_to_29d",
    )
    row.update(changes)
    return row


def source(rows, columns=snapshot.COLUMNS):
    result = io.StringIO()
    writer = csv.DictWriter(result, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)
    result.seek(0)
    return result


class SnapshotTest(unittest.TestCase):
    def test_projection_excludes_unknown_active_and_expired_idle(self):
        rows = [
            delivery(1, idle_days=""),
            delivery(2, idle_days="6.999999"),
            delivery(3),
            delivery(4, idle_days="365", dormancy_cohort="90d_plus"),
            delivery(5, idle_days="365.10"),
            delivery(6, idle_days="29", dormancy_cohort="29_to_90d"),
        ]
        out = io.StringIO()
        counts = snapshot.write_rows(source(rows), out, START, END, AS_OF)
        self.assertEqual(counts["eligible_rows"], 3)
        self.assertEqual(counts["unique_users"], 1)
        self.assertEqual(
            counts["excluded"], {"unknown_idle": 1, "idle_below_7": 1, "idle_above_365": 1}
        )
        self.assertEqual(len(snapshot.COLUMNS), 26)
        self.assertEqual(
            [row["event_id"] for row in csv.DictReader(io.StringIO(out.getvalue()))],
            [rows[i]["event_id"] for i in (2, 3, 5)],
        )

    def test_24h_maturity_and_interval(self):
        mature = delivery(sent_at="2026-08-10T00:00:00.000000Z")
        immature = delivery(2, sent_at="2026-08-10T00:00:00.000001Z")
        counts = snapshot.write_rows(source([mature, immature]), io.StringIO(), START, END, END)
        self.assertEqual(counts["eligible_rows"], 1)
        self.assertEqual(counts["excluded"], {"immature": 1})
        with self.assertRaisesRegex(ValueError, "interval"):
            snapshot.write_rows(
                source([delivery(sent_at="2026-08-11T00:00:00.000000Z")]),
                io.StringIO(),
                START,
                END,
                AS_OF,
            )

    def test_rejects_personal_data_and_invalid_fields(self):
        for change in (
            {"event_id": "1234567"},
            {"user_key": "a" * 31},
            {"path": "uploaded_meme"},
            {"y_24h": "3"},
            {"meme_age_days": "private text"},
            {"taste_source_count": "2.5"},
            {"idle_days": "Infinity"},
            {"sent_at": "2026-08-09"},
            {"meme_is_video": "3"},
            {"meme_like_rate": "2"},
            {"dormancy_cohort": "private"},
        ):
            with self.subTest(field=next(iter(change))), self.assertRaises(ValueError):
                snapshot.write_rows(source([delivery(**change)]), io.StringIO(), START, END, AS_OF)
        with self.assertRaisesRegex(ValueError, "duplicate"):
            snapshot.write_rows(source([delivery(), delivery()]), io.StringIO(), START, END, AS_OF)

    def test_rejects_header_drift_and_excess_row_values(self):
        for columns in (
            snapshot.COLUMNS[::-1],
            snapshot.COLUMNS + ("secret",),
            snapshot.COLUMNS[1:],
        ):
            with self.assertRaisesRegex(ValueError, "schema"):
                snapshot.write_rows(source([], columns), io.StringIO(), START, END, AS_OF)
        csv_text = source([delivery()]).read().rstrip() + ",extra\n"
        with self.assertRaisesRegex(ValueError, "width"):
            snapshot.write_rows(io.StringIO(csv_text), io.StringIO(), START, END, AS_OF)

    def test_private_publication_manifest_cleanup_and_no_overwrite(self):
        def fake_collect(psql, start, end, batch_days, file, *, batches):
            self.assertEqual(psql, ["psql", "-Xq"])
            file.write(source([delivery(), delivery(2, idle_days="3")]).read().encode())
            file.seek(0)
            batches.append({"rows": 2, "seconds": 0.0})
            return "b" * 64

        with tempfile.TemporaryDirectory() as tmp, patch.object(snapshot, "collect", fake_collect):
            root = Path(tmp).resolve()
            dest = snapshot.export(root, "test", START, END, AS_OF)
            self.assertEqual(stat.S_IMODE(dest.stat().st_mode), 0o700)
            data = dest / "rows.csv.gz"
            manifest_path = dest / "manifest.json"
            for file in [data, manifest_path]:
                self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)
            manifest = json.loads(manifest_path.read_bytes())
            self.assertEqual(manifest["data_sha256"], hashlib.sha256(data.read_bytes()).hexdigest())
            self.assertEqual(manifest["bytes"], data.stat().st_size)
            with gzip.open(data, "rt") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [delivery()])
            self.assertNotIn(delivery()["user_key"], manifest_path.read_text())
            with self.assertRaises(FileExistsError):
                snapshot.export(root, "test", START, END, AS_OF)

            def reject(*args, **kwargs):
                raise RuntimeError("incomplete batch")

            with patch.object(snapshot, "collect", reject), self.assertRaises(RuntimeError):
                snapshot.export(root, "incomplete", START, END, AS_OF)
            self.assertEqual(list(dest.parent.iterdir()), [dest])
            empty = dest.parent / "existing-empty"
            empty.mkdir()
            with self.assertRaises(FileExistsError):
                snapshot.publish(dest, empty)
            self.assertTrue(data.is_file())

    def test_cli_accepts_external_psql_adapter_and_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fixture = source([delivery()]).read()
            # Verifies that the CLI forwards the adapter argv and sends SQL over stdin.
            adapter = (
                "import sys; sql=sys.stdin.read(); "
                "assert 'BEGIN READ ONLY;' in sql and 'ROLLBACK;' in sql; "
                "assert \"statement_timeout = '30s'\" in sql; "
                f"sys.stdout.write({fixture!r})"
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(snapshot.__file__)),
                    "--root",
                    str(root),
                    "--name",
                    "cli",
                    "--start",
                    START.isoformat(),
                    "--end",
                    END.isoformat(),
                    "--as-of",
                    AS_OF.isoformat(),
                    "--",
                    sys.executable,
                    "-c",
                    adapter,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertTrue((root / "datasets" / "cli" / "rows.csv.gz").is_file())
            self.assertNotIn(delivery()["user_key"], result.stdout + result.stderr)

    def test_private_directory_git_and_symlink_guards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            os.chmod(root, 0o755)
            with self.assertRaisesRegex(ValueError, "0700"):
                snapshot.export(root, "test", START, END, AS_OF)
            os.chmod(root, 0o700)
            datasets = root / "datasets"
            datasets.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "symlink"):
                snapshot.export(root, "test", START, END, AS_OF)
            datasets.unlink()
            datasets.mkdir(mode=0o700)
            (datasets / ".git").mkdir()
            with self.assertRaisesRegex(ValueError, "Git"):
                snapshot.export(root, "test", START, END, AS_OF)
            (datasets / ".git").rmdir()
            (root / ".git").mkdir()
            with self.assertRaisesRegex(ValueError, "Git"):
                snapshot.export(root, "test", START, END, AS_OF)
