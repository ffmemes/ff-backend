"""Meaningful frozen-cohort checks; stdlib unittest, no production connections."""

import copy
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone

from scripts.channel_hit_experiment import (
    build_cohort,
    build_parser,
    cohort_summary,
    validate_cohort,
)


class ChannelHitEnrollmentTests(unittest.TestCase):
    def setUp(self):
        self.snapshot = datetime(2026, 9, 5, tzinfo=timezone.utc)
        self.start = self.snapshot + timedelta(days=1)
        self.candidates = [
            {
                "user_id": 1000 + i,
                "active_days_28d": 8 + i % 14,
                "reactions_28d": 100 + i,
                "likes_28d": 20 + i,
                "inventory_count": 14,
            }
            for i in range(83)
        ]

    def cohort(self, candidates=None, seed="test"):
        return build_cohort(
            self.candidates if candidates is None else candidates, self.snapshot, self.start, seed
        )

    def test_all_eligible_users_included_and_odd_arms_balanced(self):
        for size in (2, 3, 60, 82, 83):
            with self.subTest(size=size):
                rows = self.cohort(self.candidates[:size])
                self.assertEqual(len(rows), size)
                self.assertEqual(
                    Counter(r["variant"] for r in rows),
                    {"control": (size + 1) // 2, "treatment": size // 2},
                )
                validate_cohort(rows)

    def test_order_independent_but_seed_changes_assignment(self):
        rows = self.cohort()
        self.assertEqual(rows, self.cohort(list(reversed(self.candidates))))
        self.assertNotEqual(validate_cohort(rows), validate_cohort(self.cohort(seed="different")))

    def test_duplicate_ineligible_or_single_users_rejected(self):
        with self.assertRaisesRegex(ValueError, "unique"):
            self.cohort(self.candidates + [self.candidates[0]])
        with self.assertRaisesRegex(ValueError, "at least two"):
            self.cohort(self.candidates[:1])
        for key, invalid in (("inventory_count", 13), ("active_days_28d", 7), ("likes_28d", 19)):
            with self.subTest(key=key):
                candidates = copy.deepcopy(self.candidates)
                candidates[0][key] = invalid
                with self.assertRaisesRegex(ValueError, "eligibility"):
                    self.cohort(candidates)

    def test_partial_enrollment_and_mutated_metadata_detected(self):
        rows = self.cohort()
        with self.assertRaisesRegex(ValueError, "Partial"):
            validate_cohort(rows[:-1])
        rows[0]["assignment_metadata"]["reactions_28d"] += 1
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_cohort(rows)

    def test_runtime_exposure_metadata_does_not_change_cohort(self):
        rows = self.cohort()
        digest = validate_cohort(rows)
        rows[0]["assignment_metadata"]["last_hit_at"] = "2026-09-07T00:00:00Z"
        self.assertEqual(validate_cohort(rows), digest)

    def test_windows_and_assignment_time_are_frozen(self):
        rows = self.cohort()
        first = rows[0]["assignment_metadata"]
        self.assertEqual(first["exposure_end_at"], "2026-09-20T00:00:00Z")
        self.assertEqual(first["readout_at"], "2026-10-04T00:00:00Z")
        rows[0]["assigned_at"] = self.start.replace(tzinfo=None) + timedelta(seconds=1)
        with self.assertRaisesRegex(ValueError, "Assignment time"):
            validate_cohort(rows)

    def test_summary_exports_aggregates_only_and_preview_is_default(self):
        summary = cohort_summary(self.cohort(), "dry_run")
        self.assertNotIn("user_id", str(summary))
        self.assertEqual(summary["inventory_count_is_capped_at"], 14)
        args = build_parser().parse_args(
            [
                "enroll",
                "--snapshot-at",
                "2026-09-05T00:00:00Z",
                "--start-at",
                "2026-09-06T00:00:00Z",
            ]
        )
        self.assertFalse(args.apply)


if __name__ == "__main__":
    unittest.main()
