"""Run extraction regressions in an explicitly supplied disposable PostgreSQL.

Set PUSH_SQL_TEST_PSQL to the psql command targeting a task-owned test database,
then run this file with Python. Each invocation uses temporary fixture relations
inside BEGIN/ROLLBACK. With no explicit command the integration tests skip.
"""

import csv
import hashlib
import io
import os
import shlex
import subprocess
import unittest
from datetime import datetime, timedelta
from pathlib import Path

SQL_PATH = Path(__file__).resolve().parents[2] / "docs/analyst/push-reactivation-training.sql"
TEST_PSQL = os.environ.get("PUSH_SQL_TEST_PSQL")
SALT = "synthetic-sql-regression-salt"
DECISION = datetime(2026, 11, 10, 12)
DAY = timedelta(days=1)
MICROSECOND = timedelta(microseconds=1)


def literal(value):
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def fixture():
    users = {1, 2, 3, 6, 10, 11, 12, 20, 30, 31, 32, 33, 34, 35}
    memes = {}
    rows = []

    def add(user, meme, sent, reacted=None, path="lr_smoothed", source=None, kind="image"):
        memes[meme] = (meme, source or meme, kind, datetime(2020, 1, 1))
        rows.append((user, meme, path, sent, 1 if reacted else None, reacted))

    # Inclusive 35-day boundary, outside boundary, same-time callback, synthetic
    # callbacks and excluded actors must all produce distinguishable outcomes.
    add(2, 100, DECISION - 35 * DAY, DECISION - 35 * DAY, source=100)
    add(3, 100, DECISION - 35 * DAY - MICROSECOND, DECISION - 35 * DAY - MICROSECOND, source=100)
    add(1, 101, DECISION - timedelta(hours=1), DECISION, source=100)
    add(
        1,
        102,
        DECISION - timedelta(minutes=1),
        DECISION - timedelta(minutes=1),
        path="uploaded_meme",
        source=100,
    )
    add(
        1,
        103,
        DECISION - timedelta(minutes=1),
        DECISION - timedelta(minutes=1),
        path="friend_challenge",
        source=100,
    )
    add(6, 104, DECISION - timedelta(minutes=1), DECISION - timedelta(minutes=1), source=100)
    add(1, 100, DECISION, path="broadcast_reengagement_hq", source=100)

    # Pre-warmup callback seed is retained at exactly 365d, then censored beyond.
    for user, age in ((10, 365 * DAY), (11, 365 * DAY + MICROSECOND), (12, 90 * DAY)):
        add(user, user * 100, DECISION - age, DECISION - age)
        add(user, user * 100 + 1, DECISION, path="broadcast_reengagement_hq")

    # The maturity event at the exact decision time must remain unavailable.
    add(
        20,
        2000,
        DECISION - DAY,
        DECISION - DAY + timedelta(hours=1),
        path="broadcast_reengagement_hq",
    )
    add(
        20,
        2001,
        DECISION - DAY - timedelta(seconds=1),
        DECISION - DAY + timedelta(hours=1),
        path="broadcast_reengagement_hq",
    )
    add(20, 2002, DECISION, DECISION + DAY, path="broadcast_reengagement_hq")

    for user, response in ((30, DAY - MICROSECOND), (31, DAY), (32, DAY + MICROSECOND)):
        add(
            user,
            user * 100,
            DECISION,
            DECISION + response,
            path="broadcast_reengagement",
            kind="video" if user == 30 else "animation",
        )
    add(33, 3300, datetime(2026, 11, 11), path="broadcast_reengagement_hq")
    add(
        34,
        3400,
        datetime(2026, 11, 10, 23, 59, 59),
        datetime(2026, 11, 11, 23, 59, 58),
        path="broadcast_reengagement_hq",
    )
    add(35, 3500, datetime(2026, 11, 9), path="broadcast_reengagement_hq")

    def values(records):
        return ",\n".join("(" + ",".join(map(literal, row)) + ")" for row in records)

    return "\n".join(
        [
            "BEGIN;",
            "CREATE TEMP TABLE v_metric_user (user_id bigint, segment text);",
            "CREATE TEMP TABLE meme (id int, meme_source_id int, type text, created_at timestamp);",
            "CREATE TEMP TABLE user_meme_reaction (user_id bigint, meme_id int, "
            "recommended_by text, sent_at timestamp, reaction_id int, reacted_at timestamp);",
            "INSERT INTO v_metric_user VALUES "
            + values((user, "excluded" if user == 6 else "user") for user in sorted(users))
            + ";",
            "INSERT INTO meme VALUES " + values(memes.values()) + ";",
            "INSERT INTO user_meme_reaction VALUES " + values(rows) + ";",
        ]
    )


def extract(as_of="2026-11-12", days=2):
    command = shlex.split(TEST_PSQL) + [
        "-X",
        "-q",
        "--csv",
        "-v",
        "ON_ERROR_STOP=1",
        "-v",
        f"as_of={as_of}",
        "-v",
        f"days={days}",
        "-v",
        f"salt={SALT}",
        "-f",
        "-",
    ]
    script = fixture() + "\n" + SQL_PATH.read_text() + "\nROLLBACK;\n"
    result = subprocess.run(command, input=script, text=True, capture_output=True, check=True)
    return list(csv.DictReader(io.StringIO(result.stdout)))


def event(rows, user, meme):
    key = hashlib.md5(f"{user}:{meme}:{SALT}".encode()).hexdigest()
    return next(row for row in rows if row["event_id"] == key)


@unittest.skipUnless(TEST_PSQL, "set PUSH_SQL_TEST_PSQL to a disposable test database")
class ExtractionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = extract()

    def test_strict_past_and_rolling_boundary(self):
        row = event(self.rows, 1, 100)
        self.assertEqual(row["user_feed_callback_count"], "0")
        self.assertEqual(row["dormancy_cohort"], "censored_unknown")
        self.assertEqual(row["meme_send_count"], "1")
        self.assertEqual(row["user_source_reaction_count"], "0")
        self.assertEqual(row["source_send_count"], "2")
        self.assertAlmostEqual(float(row["source_like_rate"]), 2 / 3)

    def test_push_maturity_and_label_boundaries(self):
        row = event(self.rows, 20, 2002)
        self.assertEqual(row["user_push_count"], "1")
        self.assertEqual(row["user_push_send_count"], "2")
        self.assertAlmostEqual(float(row["user_push_reaction_rate"]), 2 / 3)
        for user, expected in ((30, "1"), (31, "0"), (32, "0"), (34, "1")):
            self.assertEqual(event(self.rows, user, user * 100)["y_24h"], expected)

    def test_idle_seed_and_censoring(self):
        self.assertEqual(float(event(self.rows, 10, 1001)["idle_days"]), 365)
        self.assertEqual(event(self.rows, 10, 1001)["dormancy_cohort"], "90d_plus")
        self.assertEqual(event(self.rows, 11, 1101)["idle_days"], "")
        self.assertEqual(event(self.rows, 11, 1101)["dormancy_cohort"], "censored_unknown")
        self.assertEqual(float(event(self.rows, 12, 1201)["idle_days"]), 90)

    def test_contiguous_chunks_match_batch_exactly(self):
        split = extract("2026-11-11", 1) + extract("2026-11-12", 1)
        self.assertEqual(
            sorted(split, key=lambda r: r["event_id"]),
            sorted(self.rows, key=lambda r: r["event_id"]),
        )
        self.assertEqual(len({r["event_id"] for r in split}), len(split))
        self.assertEqual(len(self.rows), 12)
        self.assertEqual(event(self.rows, 35, 3500)["sent_at"], "2026-11-09T00:00:00.000000Z")
        later = extract("2026-11-13", 1)
        self.assertEqual(event(later, 33, 3300)["sent_at"], "2026-11-11T00:00:00.000000Z")

    def test_media_metadata_and_private_columns(self):
        video = event(self.rows, 30, 3000)
        animation = event(self.rows, 31, 3100)
        self.assertEqual((video["meme_is_video"], video["meme_is_animation"]), ("1", "0"))
        self.assertEqual((animation["meme_is_video"], animation["meme_is_animation"]), ("0", "1"))
        self.assertGreater(float(video["meme_age_days"]), 0)
        self.assertTrue({"user_id", "meme_id", "source_id", "caption", "salt"}.isdisjoint(video))


if __name__ == "__main__":
    unittest.main()
