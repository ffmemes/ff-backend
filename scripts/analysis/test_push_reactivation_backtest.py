"""Regression checks for temporal leakage, frozen scoring and aggregate metrics."""

import io
import json
import math
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import push_reactivation_backtest as backtest


class BacktestTest(unittest.TestCase):
    def test_purge_excludes_unfinished_training_outcomes(self):
        cutoff = backtest.timestamp("2026-11-01")
        rows = [
            {"sent_at": cutoff - timedelta(hours=25)},
            {"sent_at": cutoff - timedelta(hours=24)},
            {"sent_at": cutoff - timedelta(hours=23)},
            {"sent_at": cutoff},
        ]
        train, test = backtest.temporal_split(rows, cutoff, cutoff + timedelta(days=1))
        self.assertEqual(train, rows[:2])
        self.assertEqual(test, rows[3:])

    def test_metrics_handle_ties_and_one_class(self):
        self.assertEqual(backtest.auc([0, 1], [0.5, 0.5]), 0.5)
        self.assertEqual(backtest.auc([0, 1, 0, 1], [0.1, 0.9, 0.1, 0.9]), 1)
        self.assertIsNone(backtest.auc([1, 1], [0.1, 0.9]))
        rows = [{"user": "a", "y": 0}, {"user": "a", "y": 1}]
        metrics = backtest.metrics(rows, [0.5, 0.5])
        self.assertAlmostEqual(metrics["log_loss"], math.log(2))
        self.assertEqual(metrics["brier"], 0.25)
        self.assertEqual(metrics["conditional_user_auc"], 0.5)

    def test_imputation_and_scaling_use_training_rows(self):
        features = {
            name: 0.5
            for name in backtest.REQUIRED - {"event_id", "user_key", "sent_at", "y_24h", "path"}
        }
        rows = [{"y": index % 2, "features": features} for index in range(20)]
        model = backtest.fit_models(rows)["user_content"]
        location = model["feature_names"].index("meme_like_rate")
        self.assertEqual(model["means"][location], 0.5)
        missing = dict(features, meme_like_rate=None)
        self.assertTrue(0 < backtest.score_features(model, missing) < 1)
        round_trip = json.loads(json.dumps(model))
        self.assertEqual(
            backtest.score_features(model, features), backtest.score_features(round_trip, features)
        )

    def test_read_filters_maturity_and_unknown_dormancy(self):
        columns = sorted(backtest.REQUIRED)
        import csv

        content = io.StringIO()
        writer = csv.DictWriter(content, fieldnames=columns)
        writer.writeheader()
        common = dict.fromkeys(columns, "0.5")
        common.update(
            user_key="private-key", y_24h="1", path="broadcast_reengagement", idle_days="8"
        )
        for event, sent, idle in [
            ("a", "2026-11-01", "8"),
            ("b", "2026-11-02T12:00:00Z", "8"),
            ("c", "2026-11-01", ""),
        ]:
            writer.writerow(dict(common, event_id=event, sent_at=sent, idle_days=idle))
        content.seek(0)
        rows, counts = backtest.read_rows(content, backtest.timestamp("2026-11-03"), 7)
        self.assertEqual(len(rows), 1)
        self.assertEqual(counts["immature"], 1)
        self.assertEqual(counts["unknown_idle"], 1)

    def test_frozen_model_does_not_refit_and_final_waits_for_full_window(self):
        from unittest.mock import patch

        cutoff = backtest.timestamp("2026-11-01")
        rows = []
        for index in range(120):
            features = {
                name: 0.5
                for name in backtest.REQUIRED - {"event_id", "user_key", "sent_at", "y_24h", "path"}
            }
            features["meme_like_rate"] = (index % 2) * 0.8 + 0.1
            rows.append(
                {
                    "user": str(index % 10),
                    "y": index % 2,
                    "features": features,
                    "sent_at": cutoff - timedelta(days=30) + timedelta(hours=index * 8),
                }
            )
        args = SimpleNamespace(
            input="-",
            as_of="2026-11-10",
            holdout_start=cutoff.isoformat(),
            frozen_model=None,
            min_idle_days=7,
            fold_days=14,
            dev_folds=1,
            min_train=10,
            min_test=2,
            min_users=2,
            min_class=2,
        )
        with patch.object(backtest, "read_rows", return_value=(rows, {})):
            report, bundle = backtest.run(args)
        self.assertEqual(report["final"]["status"], "pending_complete_outcome_window")
        self.assertIsNotNone(bundle)
        with tempfile.TemporaryDirectory() as directory:
            filename = Path(directory) / "model.json"
            filename.write_text(json.dumps(bundle))
            args.frozen_model = str(filename)
            args.as_of = "2026-11-16"
            with (
                patch.object(backtest, "read_rows", return_value=(rows, {})),
                patch.object(backtest, "fit_models", side_effect=AssertionError("refit")),
            ):
                frozen_report, reused = backtest.run(args)
            self.assertEqual(reused, bundle)
            self.assertEqual(frozen_report["final"]["status"], "evaluated")
            test_only = [row for row in rows if row["sent_at"] >= cutoff]
            with (
                patch.object(backtest, "read_rows", return_value=(test_only, {})),
                patch.object(backtest, "fit_models", side_effect=AssertionError("refit")),
            ):
                test_only_report, _ = backtest.run(args)
            self.assertIsNone(test_only_report["final"]["seen_user_send_fraction"])
            args.evaluation_start = "2026-10-31"
            with self.assertRaisesRegex(ValueError, "requires a frozen model"):
                backtest.run(args)
            args.evaluation_start = "2026-11-02"
            args.as_of = "2026-11-17"
            with (
                patch.object(backtest, "read_rows", return_value=(test_only, {})),
                patch.object(backtest, "fit_models", side_effect=AssertionError("refit")),
            ):
                later_report, unchanged = backtest.run(args)
            self.assertEqual(later_report["evaluation_start"], "2026-11-02T00:00:00+00:00")
            self.assertEqual(later_report["training_cutoff"], cutoff.isoformat())
            self.assertEqual(later_report["final"]["status"], "evaluated")
            self.assertEqual(unchanged, bundle)
            args.as_of = "2026-10-31"
            with self.assertRaisesRegex(ValueError, "training cutoff must not be later"):
                backtest.run(args)
            args.as_of = "2026-11-17"
            invalid = dict(bundle, training_last_send="2026-10-31T12:00:00Z")
            filename.write_text(json.dumps(invalid))
            with self.assertRaisesRegex(ValueError, "training outcomes extend beyond"):
                backtest.run(args)

    def test_tuning_excludes_unmatured_pre_cutoff_labels_and_breaks_ties(self):
        from unittest.mock import patch

        cutoff = backtest.timestamp("2026-11-01")
        rows = [
            {
                "user": str(index % 10),
                "sent_at": cutoff + timedelta(days=index - 90),
                "y": index % 2,
                "features": {},
            }
            for index in range(105)
        ]
        args = SimpleNamespace(
            dev_folds=3, fold_days=14, min_train=10, min_test=2, min_users=2, min_class=2
        )
        calls = []

        def fake_fit(train, regularization=None):
            calls.append(max(row["sent_at"] for row in train))
            return {
                name: {
                    "feature_names": [],
                    "imputation": [],
                    "means": [],
                    "scales": [],
                    "coefficients": [],
                    "intercept": -1.0,
                }
                for name in backtest.MODEL_FEATURES
            }

        with patch.object(backtest, "fit_models", side_effect=fake_fit):
            folds, first = backtest.tune_development(
                rows, cutoff, cutoff + timedelta(days=16), args
            )
            changed = [
                dict(row, y=1 - row["y"])
                if cutoff - timedelta(hours=24) <= row["sent_at"] < cutoff
                else row
                for row in rows
            ]
            _, second = backtest.tune_development(
                changed, cutoff, cutoff + timedelta(days=16), args
            )
        self.assertEqual(first, second)
        self.assertEqual(backtest.timestamp(folds[-1]["end"]), cutoff - timedelta(hours=24))
        self.assertEqual(first["selected_C"], {"user_only": 0.03, "user_content": 0.03})
        self.assertTrue(
            all(sent + timedelta(hours=24) <= cutoff - timedelta(days=14) for sent in calls)
        )


if __name__ == "__main__":
    unittest.main()
