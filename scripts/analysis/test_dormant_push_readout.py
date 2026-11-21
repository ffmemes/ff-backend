"""Readout regressions against temporary tables in an explicitly supplied test DB.

PUSH_READOUT_TEST_PSQL must name a psql command for a disposable PostgreSQL DB.
"""

import json
import os
import shlex
import subprocess
import unittest
from pathlib import Path

READOUT = Path(__file__).resolve().parents[2] / "docs/analyst/dormant-push-exploration.sql"
PSQL = os.environ.get("PUSH_READOUT_TEST_PSQL")

FIXTURE = """
BEGIN;
CREATE TEMP TABLE v_metric_user (user_id bigint, segment text);
CREATE TEMP TABLE "user" (id bigint, blocked_bot_at timestamp);
CREATE TEMP TABLE push_content_opportunity (
    id bigint, campaign text DEFAULT 'dormant_push_exploration_v1', user_id bigint,
    enrolled boolean DEFAULT true, variant text, state text,
    assigned_at timestamp DEFAULT '2027-01-01', meme_id bigint,
    recommended_by text DEFAULT 'broadcast_reengagement_hq', selection jsonb DEFAULT
    '{"candidate_ids":[10,11,12],"chosen_index":0,"selection_probability":1}',
    attempted_at timestamp DEFAULT '2027-01-01 00:00:01', accepted_at timestamp, error_code text
);
CREATE TEMP TABLE user_meme_reaction (
    user_id bigint, meme_id bigint, sent_at timestamp, reacted_at timestamp,
    reaction_id int, recommended_by text DEFAULT 'broadcast_reengagement_hq'
);
CREATE TEMP TABLE v_feed_session (user_id bigint, session_start timestamp, reactions int);
INSERT INTO v_metric_user VALUES (1,'moderator'),(2,'user'),(3,'user'),(4,'user'),
    (5,'excluded'),(6,'user'),(7,'user'),(8,'user');
INSERT INTO "user" SELECT user_id, CASE WHEN user_id=2 THEN '2027-01-03'::timestamp END
    FROM v_metric_user;
INSERT INTO push_content_opportunity (id,user_id,variant,state,meme_id,accepted_at) VALUES
    (1,1,'hq','accepted',10,'2027-01-01 00:00:02'),
    (2,2,'explore','failed',20,NULL),
    (3,3,'explore','accepted',30,'2027-01-01 00:00:02'),
    (4,4,'hq','failed',40,NULL),
    (5,5,'hq','accepted',50,'2027-01-01 00:00:02'),
    (7,7,'explore','accepted',70,'2027-01-01 00:00:02'),
    (8,8,'explore','accepted',80,'2027-01-01 00:00:02');
UPDATE push_content_opportunity SET enrolled=false WHERE id=8;
INSERT INTO push_content_opportunity
    (id,user_id,variant,state,meme_id,assigned_at,attempted_at,accepted_at) VALUES
    (9,4,'hq','accepted',41,'2027-01-02','2027-01-02','2027-01-02'),
    (6,6,'hq','reserved',60,'2027-01-31 12:00:00',NULL,NULL);
INSERT INTO user_meme_reaction(user_id,meme_id,sent_at,reacted_at,reaction_id) VALUES
    (1,10,'2027-01-01 00:00:03','2027-01-01 00:00:04',1),
    (2,20,'2027-01-01 00:00:03','2027-01-01 00:00:04',1),
    (3,30,'2027-01-01 00:00:03','2027-01-02',1),
    (4,41,'2027-01-02','2027-01-02 00:00:02',1),
    (5,50,'2027-01-01 00:00:03','2027-01-01 00:00:04',1),
    (7,70,'2027-01-01 00:00:03','2027-01-01 00:00:04',1),
    (8,80,'2027-01-01 00:00:03','2027-01-01 00:00:04',1);
UPDATE user_meme_reaction SET recommended_by='feed' WHERE user_id=7;
INSERT INTO v_feed_session VALUES (1,'2027-01-08',1),(2,'2027-01-15',1),
    (3,'2027-01-09',0),(4,'2027-01-07 23:59:59',1);
"""


@unittest.skipUnless(PSQL, "set PUSH_READOUT_TEST_PSQL to a disposable PostgreSQL DB")
class ReadoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sql = "\\set as_of 2027-02-01T00:00:00Z\n" + FIXTURE
        sql += READOUT.read_text() + "\nROLLBACK;\n"
        result = subprocess.run(
            shlex.split(PSQL) + ["-XqAt", "-F", "\t", "-v", "ON_ERROR_STOP=1"],
            input=sql,
            text=True,
            capture_output=True,
            check=True,
        )
        cls.rows = [
            (section, json.loads(data))
            for section, data in (
                line.split("\t", 1) for line in result.stdout.splitlines() if "\t" in line
            )
        ]
        cls.arms = {row["variant"]: row for section, row in cls.rows if section == "arm"}

    def test_first_assignment_itt_and_maturity(self):
        self.assertEqual(self.arms["hq"]["enrolled_people"], 3)
        self.assertEqual(self.arms["hq"]["primary_n"], 2)
        self.assertEqual(self.arms["hq"]["primary_events"], 1)
        self.assertEqual(self.arms["explore"]["primary_n"], 3)
        self.assertEqual(self.arms["explore"]["primary_events"], 0)

    def test_followup_has_exact_boundaries_and_requires_reactions(self):
        self.assertEqual(self.arms["hq"]["feed_d7_14_people"], 1)
        self.assertEqual(self.arms["explore"]["feed_d7_14_people"], 0)
        self.assertEqual(self.arms["explore"]["recorded_blocks_14d"], 1)

    def test_immature_readout_never_scans_feed_sessions(self):
        query = READOUT.read_text()
        query = query[query.index("WITH ranked AS (") :]
        sql = "\\set as_of 2027-01-01T01:00:00Z\n" + FIXTURE
        sql += "EXPLAIN (ANALYZE, FORMAT JSON) " + query + "\nROLLBACK;\n"
        result = subprocess.run(
            shlex.split(PSQL) + ["-XqAt", "-v", "ON_ERROR_STOP=1"],
            input=sql,
            text=True,
            capture_output=True,
            check=True,
        )
        plan = json.loads(result.stdout)[0]["Plan"]

        def feed_scans(node):
            found = [node] if node.get("Relation Name") == "v_feed_session" else []
            for child in node.get("Plans", []):
                found.extend(feed_scans(child))
            return found

        scans = feed_scans(plan)
        self.assertTrue(scans)
        self.assertTrue(all(node["Actual Loops"] == 0 for node in scans))

    def test_receipt_and_path_failures_stay_visible(self):
        self.assertEqual(self.arms["explore"]["accepted_people"], 2)
        self.assertEqual(self.arms["explore"]["accepted_missing_delivery_row"], 1)
        self.assertEqual(self.arms["explore"]["failed_people"], 1)
        self.assertEqual(self.arms["hq"]["stale_inflight_people"], 1)
        effect = next(row for section, row in self.rows if section == "primary_difference")
        self.assertEqual(effect["explore_minus_hq"], -0.5)
        self.assertFalse(effect["minimum_sample_reached"])


if __name__ == "__main__":
    unittest.main()
