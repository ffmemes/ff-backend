"""Synthetic checks for matched arms, prequential selection and frozen evaluation."""

import csv
import gzip
import hashlib
import json
import math
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import compare_push_models as compare
import push_reactivation_backtest as base

LIMITS = {"min_train": 4, "min_test": 4, "min_users": 2, "min_class": 1}


def synthetic_rows(cutoff, days=120):
    return [
        {
            "user": str(index % 5),
            "y": index % 2,
            "sent_at": cutoff + timedelta(hours=12 * index - days * 24),
            "features": {name: (40 if name == "idle_days" else 0.5) for name in base.FEATURE_NAMES},
            "path": "broadcast_reengagement_hq" if index % 3 else "broadcast_reengagement",
        }
        for index in range(days * 2)
    ]


def constant_models():
    return {
        name: {
            "feature_names": list(features),
            "imputation": [0] * len(features),
            "means": [0] * len(features),
            "scales": [1] * len(features),
            "coefficients": [0] * (2 * len(features)),
            "intercept": -0.7,
        }
        for name, features in compare.FEATURE_SETS.items()
    }


class MatchedComparisonTest(unittest.TestCase):
    def test_manifest_requires_full_observation_window_and_correct_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "rows.csv"
            columns = sorted(base.REQUIRED | base.OPTIONAL_FEATURES | {"dormancy_cohort"})
            header = ",".join(columns) + "\n"
            data_path.write_text(header)
            manifest = {
                "schema_version": 1,
                "segment": "user",
                "label_horizon_hours": 24,
                "idle_days_inclusive": [7, 365],
                "delivery_start_inclusive": "2026-12-01",
                "delivery_end_exclusive": "2026-12-15",
                "label_cutoff_utc": "2026-12-16",
                "batches": [
                    {"start_inclusive": "2026-12-01", "end_exclusive": "2026-12-15", "rows": 0}
                ],
                "input_rows": 0,
                "eligible_rows": 0,
                "bytes": data_path.stat().st_size,
                "columns": columns,
                "data_sha256": compare.file_digest(data_path),
                "sql_sha256": "0" * 64,
                "schema_sha256": hashlib.sha256(header.encode()).hexdigest(),
            }
            manifest_path = Path(directory) / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            kwargs = {
                "start": base.timestamp("2026-12-01"),
                "end": base.timestamp("2026-12-15"),
                "label_cutoff": base.timestamp("2026-12-16"),
                "as_of": base.timestamp("2026-12-16"),
                "min_idle": 7,
            }
            receipt = compare.verify_manifest(data_path, manifest_path, **kwargs)
            self.assertEqual(receipt["data_sha256"], manifest["data_sha256"])
            for change, message in (
                ({"delivery_end_exclusive": "2026-12-05"}, "complete delivery window"),
                ({"label_cutoff_utc": "2026-12-15"}, "observation cutoff"),
                ({"data_sha256": "f" * 64}, "data SHA-256"),
                ({"segment": "moderator"}, "ordinary-user"),
            ):
                manifest_path.write_text(json.dumps(dict(manifest, **change)))
                with self.assertRaisesRegex(ValueError, message):
                    compare.verify_manifest(data_path, manifest_path, **kwargs)
            manifest_path.write_text(json.dumps(manifest))
            for idle in (float("nan"), float("inf"), 0):
                with self.assertRaisesRegex(ValueError, "must be finite"):
                    compare.verify_manifest(data_path, manifest_path, **dict(kwargs, min_idle=idle))

    def test_as_of_cannot_claim_future_outcomes(self):
        with self.assertRaisesRegex(ValueError, "in the future"):
            compare.reject_future_as_of(
                base.timestamp("2026-12-16"), now=base.timestamp("2026-11-21")
            )
        compare.reject_future_as_of(base.timestamp("2026-11-21"), now=base.timestamp("2026-11-21"))

    def test_arms_change_only_intended_history_features(self):
        features = {name: set(values) for name, values in compare.FEATURE_SETS.items()}
        self.assertEqual(
            features["long_user"] - features["recent_user"],
            {"taste_feed_count", "taste_feed_like_rate"},
        )
        self.assertEqual(
            features["full_long"] - features["long_user_recent_full"],
            {"taste_source_count", "taste_source_like_rate"},
        )
        self.assertEqual(
            features["recent_full"] - features["recent_user"],
            features["long_user_recent_full"] - features["long_user"],
        )

    def test_outer_selection_cannot_see_outer_or_unmatured_labels(self):
        cutoff = base.timestamp("2026-11-21")
        outer_start = compare.calendar_blocks(cutoff)[0][0]
        rows = synthetic_rows(cutoff)
        train_ends = []

        def fake_fit(train, *args, **kwargs):
            train_ends.append(max(row["sent_at"] for row in train))
            return constant_models()

        changed = [
            dict(row, y=1 - row["y"]) if row["sent_at"] >= outer_start - compare.HORIZON else row
            for row in rows
        ]
        with patch.object(base, "fit_models", side_effect=fake_fit):
            selected, trace = compare.select_regularization(rows, outer_start, LIMITS)
            selected_changed, trace_changed = compare.select_regularization(
                changed, outer_start, LIMITS
            )
        self.assertEqual(selected, selected_changed)
        self.assertEqual(trace, trace_changed)
        self.assertEqual(set(selected.values()), {0.03})
        self.assertTrue(
            all(
                base.timestamp(fold["outcomes_available_by"]) <= outer_start
                for fold in trace["folds"]
            )
        )
        latest_inner_start = compare.calendar_blocks(outer_start)[-1][0]
        self.assertTrue(all(value + compare.HORIZON <= latest_inner_start for value in train_ends))

    def test_sparse_inner_history_uses_fixed_fallback(self):
        selected, trace = compare.select_regularization([], base.timestamp("2026-11-21"), LIMITS)
        self.assertEqual(set(selected.values()), {0.3})
        self.assertEqual(trace["supported_folds"], 0)

    def test_paired_estimand_gives_each_user_equal_weight(self):
        rows = [{"user": "heavy", "y": 0} for _ in range(9)] + [{"user": "light", "y": 0}]
        probabilities = {name: [0.5] * 10 for name in compare.FEATURE_SETS}
        probabilities["full_long"] = [0.2] * 9 + [0.8]
        result = compare.paired_contrasts(rows, probabilities)["source_history_primary"]
        expected = (-math.log(0.5) + math.log(0.8) - math.log(0.5) + math.log(0.2)) / 2
        self.assertAlmostEqual(result["estimate"], expected)
        self.assertEqual(result["loss_coefficients"], {"long_user_recent_full": 1, "full_long": -1})

    def test_custom_feature_fitter_preserves_default_models(self):
        rows = synthetic_rows(base.timestamp("2026-11-21"), days=10)
        ordinary = base.fit_models(rows)
        custom = base.fit_models(rows, feature_sets={"matched": base.USER_FEATURES})
        self.assertEqual(ordinary["user_only"], custom["matched"])

    def test_gzip_and_plain_inputs_have_identical_matched_rows(self):
        columns = sorted(base.REQUIRED | base.OPTIONAL_FEATURES)
        with tempfile.TemporaryDirectory() as directory:
            plain = Path(directory) / "rows.csv"
            with plain.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=columns)
                writer.writeheader()
                for index in range(2):
                    row = dict.fromkeys(columns, "0.5")
                    row.update(
                        event_id=str(index),
                        user_key=str(index),
                        y_24h=str(index),
                        sent_at="2026-11-19",
                        idle_days="40",
                        path="broadcast_reengagement",
                    )
                    writer.writerow(row)
            compressed = Path(directory) / "rows.csv.gz"
            with gzip.open(compressed, "wb") as handle:
                handle.write(plain.read_bytes())
            first = compare.load_snapshot(plain, base.timestamp("2026-11-21"), 7)
            second = compare.load_snapshot(compressed, base.timestamp("2026-11-21"), 7)
            self.assertEqual(first[:2], second[:2])
            self.assertNotEqual(first[2], second[2])
            self.assertEqual(first[0][0]["path"], "broadcast_reengagement")

    def test_december_evaluation_rejects_immature_and_never_refits(self):
        cutoff = base.timestamp("2026-11-21")
        bundle = {
            "version": compare.VERSION,
            "models": constant_models(),
            "limits": LIMITS,
            "training_cutoff": cutoff.isoformat(),
            "training_first_send": "2026-10-01",
            "training_last_send": "2026-11-19",
            "evaluation_plan": {
                "start": "2026-12-01T00:00:00+00:00",
                "end": "2026-12-15T00:00:00+00:00",
            },
        }
        with self.assertRaisesRegex(ValueError, "prospective outcomes unavailable"):
            compare.evaluate_frozen([], bundle, base.timestamp("2026-11-21"))
        rows = synthetic_rows(base.timestamp("2026-12-15"), days=14)
        unchanged = json.dumps(bundle, sort_keys=True)
        with patch.object(base, "fit_models", side_effect=AssertionError("refit")):
            report = compare.evaluate_frozen(rows, bundle, base.timestamp("2026-12-16"))
        self.assertEqual(report["evaluation"]["status"], "evaluated")
        self.assertEqual(unchanged, json.dumps(bundle, sort_keys=True))
        self.assertEqual(report["evaluation"]["sends"], len(rows))

    def test_december_cutoff_uses_january_window_and_keeps_maturity_guards(self):
        cutoff = base.timestamp("2026-12-21")
        start, end = compare.prospective_window(cutoff)
        self.assertEqual(start, base.timestamp("2027-01-01"))
        self.assertEqual(end, base.timestamp("2027-01-15"))
        pending, untrained = compare.train_comparison([], cutoff, LIMITS)
        self.assertIsNone(untrained)
        self.assertEqual(pending["evaluation_plan"]["start"], start.isoformat())
        self.assertEqual(
            pending["evaluation_plan"]["required_as_of"], base.timestamp("2027-01-16").isoformat()
        )
        bundle = {
            "version": compare.VERSION,
            "models": constant_models(),
            "limits": LIMITS,
            "training_cutoff": cutoff.isoformat(),
            "training_first_send": "2026-11-01",
            "training_last_send": "2026-12-19",
            "evaluation_plan": {"start": start.isoformat(), "end": end.isoformat()},
        }
        with self.assertRaisesRegex(ValueError, "2027-01-16"):
            compare.evaluate_frozen([], bundle, base.timestamp("2027-01-15"))
        rows = synthetic_rows(end, days=14)
        with patch.object(base, "fit_models", side_effect=AssertionError("refit")):
            report = compare.evaluate_frozen(rows, bundle, base.timestamp("2027-01-16"))
        self.assertEqual(report["evaluation"]["status"], "evaluated")
        self.assertEqual(report["evaluation_start"], start.isoformat())
        wrong_plan = dict(bundle, evaluation_plan={"start": "2026-12-01", "end": "2026-12-15"})
        with self.assertRaisesRegex(ValueError, "month after training cutoff"):
            compare.evaluate_frozen(rows, wrong_plan, base.timestamp("2027-01-16"))
        wrong_observation = dict(
            bundle, evaluation_plan=dict(bundle["evaluation_plan"], required_as_of="2027-01-15")
        )
        with self.assertRaisesRegex(ValueError, "observation cutoff"):
            compare.evaluate_frozen(rows, wrong_observation, base.timestamp("2027-01-16"))
        self.assertEqual(
            compare.prospective_window(base.timestamp("2026-11-21")),
            (base.timestamp("2026-12-01"), base.timestamp("2026-12-15")),
        )


if __name__ == "__main__":
    unittest.main()
