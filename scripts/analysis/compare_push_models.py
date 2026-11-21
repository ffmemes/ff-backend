"""Matched-date prequential L2 ablation on one local push feature snapshot.

Train writes aggregate JSON and a private frozen bundle for five feature arms.
Every outer fold chooses regularization using only earlier, matured inner folds.
Evaluate uses unchanged weights on the predeclared December 1-14 window and
rejects incomplete observation windows. Neither command queries production.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import importlib.metadata
import json
import math
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import push_reactivation_backtest as base

VERSION = "push-matched-prequential-l2-v1"
C_GRID = (0.03, 0.3, 1.0)
FALLBACK_C = 0.3
HORIZON = timedelta(hours=24)
FOLD_DAYS = 14
OUTER_FOLDS = 3
INNER_FOLDS = 3
MIN_INNER_FOLDS = 2
RECENT_USER = tuple(name for name in base.USER_FEATURES if name not in base.TASTE_FEATURES)
RECENT_CONTENT = tuple(name for name in base.CONTENT_FEATURES if name not in base.TASTE_FEATURES)
FEATURE_SETS = {
    "recent_user": RECENT_USER,
    "long_user": base.USER_FEATURES,
    "recent_full": RECENT_USER + RECENT_CONTENT,
    "long_user_recent_full": base.USER_FEATURES + RECENT_CONTENT,
    "full_long": base.USER_FEATURES + base.CONTENT_FEATURES,
}
CONTRASTS = {
    "source_history_primary": {"long_user_recent_full": 1, "full_long": -1},
    "difference_in_differences_secondary": {
        "recent_full": 1,
        "full_long": -1,
        "recent_user": -1,
        "long_user": 1,
    },
    "content_beyond_long_user_secondary": {"long_user": 1, "full_long": -1},
}
EVALUATION_START = base.timestamp("2026-12-01")
EVALUATION_END = EVALUATION_START + timedelta(days=14)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_snapshot(path: Path, as_of, min_idle: float) -> tuple[list, dict, str]:
    opener = gzip.open if path.suffix == ".gz" else open
    required = tuple(dict.fromkeys(name for names in FEATURE_SETS.values() for name in names))
    with opener(path, "rt", newline="") as handle:
        rows, counts = base.read_rows(handle, as_of, min_idle, required_features=required)
    return rows, counts, file_digest(path)


def reject_future_as_of(as_of, now=None) -> None:
    if as_of > (now or datetime.now(timezone.utc)):
        raise ValueError("--as-of is in the future; observed outcomes cannot be declared early")


def verify_manifest(
    data_path: Path, manifest_path: Path, *, start, end, label_cutoff, as_of, min_idle: float
) -> dict:
    manifest = json.loads(manifest_path.read_text())
    if not math.isfinite(min_idle) or not 7 <= min_idle <= 365:
        raise ValueError("pilot minimum idle days must be finite and between 7 and 365")
    if manifest.get("schema_version") != 1 or manifest.get("segment") != "user":
        raise ValueError("require a published schema-v1 ordinary-user export manifest")
    if manifest.get("status", "complete") not in {"complete", "published"}:
        raise ValueError("snapshot export is incomplete")
    if manifest.get("label_horizon_hours") != 24:
        raise ValueError("snapshot label horizon must be 24 hours")
    lower, upper = manifest["idle_days_inclusive"]
    if lower > min_idle or upper < 365:
        raise ValueError("snapshot does not cover the required dormant-user range")
    declared_start = base.timestamp(manifest["delivery_start_inclusive"])
    declared_end = base.timestamp(manifest["delivery_end_exclusive"])
    declared_cutoff = base.timestamp(manifest["label_cutoff_utc"])
    if declared_start > start or declared_end < end or declared_start >= declared_end:
        raise ValueError("snapshot does not cover the complete delivery window")
    if declared_cutoff < label_cutoff or declared_cutoff > as_of:
        raise ValueError("snapshot label observation cutoff does not cover the requested window")
    if declared_end + HORIZON > declared_cutoff:
        raise ValueError("snapshot contains delivery days with incomplete labels")
    cursor = declared_start
    total_rows = 0
    for batch in manifest["batches"]:
        batch_start = base.timestamp(batch["start_inclusive"])
        batch_end = base.timestamp(batch["end_exclusive"])
        if batch_start != cursor or batch_end <= batch_start or batch_end > declared_end:
            raise ValueError("snapshot batch windows contain a gap or overlap")
        cursor = batch_end
        total_rows += batch["rows"]
    if cursor != declared_end or total_rows != manifest["input_rows"]:
        raise ValueError("snapshot batch coverage or row totals are incomplete")
    if manifest["eligible_rows"] > total_rows:
        raise ValueError("snapshot eligible row count exceeds exported input")
    for name in ("data_sha256", "sql_sha256", "schema_sha256"):
        digest = manifest[name]
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("invalid snapshot digest")
    if file_digest(data_path) != manifest["data_sha256"]:
        raise ValueError("snapshot data SHA-256 does not match manifest")
    if data_path.stat().st_size != manifest["bytes"]:
        raise ValueError("snapshot byte size does not match manifest")
    expected_schema = hashlib.sha256((",".join(manifest["columns"]) + "\n").encode()).hexdigest()
    required_columns = base.REQUIRED | base.OPTIONAL_FEATURES | {"dormancy_cohort"}
    if not required_columns.issubset(manifest["columns"]):
        raise ValueError("snapshot manifest omits required feature columns")
    if expected_schema != manifest["schema_sha256"]:
        raise ValueError("snapshot schema SHA-256 does not match manifest columns")
    opener = gzip.open if data_path.suffix == ".gz" else open
    with opener(data_path, "rt", newline="") as handle:
        if next(csv.reader(handle), None) != manifest["columns"]:
            raise ValueError("snapshot CSV header differs from manifest")
    return {
        "manifest_sha256": file_digest(manifest_path),
        "data_sha256": manifest["data_sha256"],
        "sql_sha256": manifest["sql_sha256"],
        "schema_sha256": manifest["schema_sha256"],
        "eligible_rows": manifest["eligible_rows"],
        "delivery_start_inclusive": declared_start.isoformat(),
        "delivery_end_exclusive": declared_end.isoformat(),
        "label_cutoff_utc": declared_cutoff.isoformat(),
        "source_consistency": manifest.get("source_consistency"),
    }


def supported(rows: list, limits: dict, *, training: bool = False) -> bool:
    minimum = limits["min_train"] if training else limits["min_test"]
    return base.enough(rows, minimum, limits["min_users"], limits["min_class"])


def calendar_blocks(cutoff, count: int = INNER_FOLDS) -> list[tuple]:
    end = cutoff - HORIZON
    return [
        (end - timedelta(days=FOLD_DAYS * index), end - timedelta(days=FOLD_DAYS * (index - 1)))
        for index in range(count, 0, -1)
    ]


def select_regularization(rows: list, cutoff, limits: dict) -> tuple[dict, dict]:
    """An outer test label cannot participate in its own C selection."""
    eligible = [row for row in rows if row["sent_at"] + HORIZON <= cutoff]
    scores = {name: {strength: [] for strength in C_GRID} for name in FEATURE_SETS}
    folds = []
    for start, end in calendar_blocks(cutoff):
        train, test = base.temporal_split(eligible, start, end)
        fold = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "outcomes_available_by": (end + HORIZON).isoformat(),
            "train": base.support(train),
            "test": base.support(test),
            "status": "insufficient_support",
        }
        folds.append(fold)
        if not supported(train, limits, training=True) or not supported(test, limits):
            continue
        fold["status"] = "evaluated"
        fold["scores"] = []
        for strength in C_GRID:
            models = base.fit_models(
                train, dict.fromkeys(FEATURE_SETS, strength), feature_sets=FEATURE_SETS
            )
            losses = {}
            for name, model in models.items():
                probabilities = [base.score_features(model, row["features"]) for row in test]
                losses[name] = base.user_mean_loss(test, probabilities)
                scores[name][strength].append(losses[name])
            fold["scores"].append({"C": strength, "user_log_loss": losses})
    number_supported = sum(fold["status"] == "evaluated" for fold in folds)
    selected = {
        name: min(
            C_GRID, key=lambda strength: (round(statistics.mean(values[strength]), 12), strength)
        )
        if number_supported >= MIN_INNER_FOLDS
        else FALLBACK_C
        for name, values in scores.items()
    }
    return selected, {
        "selection_cutoff": cutoff.isoformat(),
        "grid": list(C_GRID),
        "fallback_C": FALLBACK_C,
        "minimum_supported_folds": MIN_INNER_FOLDS,
        "supported_folds": number_supported,
        "rule": "independent per arm; equal-weight fold means of user-averaged log loss; "
        "ties at 12 decimals choose smaller C",
        "selected_C": selected,
        "folds": folds,
    }


def predictions(rows: list, models: dict) -> dict:
    return {
        name: [base.score_features(model, row["features"]) for row in rows]
        for name, model in models.items()
    }


def paired_contrasts(rows: list, probabilities: dict) -> dict:
    per_user = {name: defaultdict(list) for name in FEATURE_SETS}
    for name, values in probabilities.items():
        for row, loss in zip(rows, base.losses(rows, values), strict=True):
            per_user[name][row["user"]].append(loss)
    users = sorted({row["user"] for row in rows})
    means = {
        name: {user: statistics.mean(values[user]) for user in users}
        for name, values in per_user.items()
    }
    contrasts = {}
    for name, coefficients in CONTRASTS.items():
        values = [
            sum(weight * means[arm][user] for arm, weight in coefficients.items()) for user in users
        ]
        generator = random.Random(20261121)
        bootstrap = sorted(
            statistics.mean(generator.choices(values, k=len(values))) for _ in range(1000)
        )
        contrasts[name] = {
            "estimate": statistics.mean(values),
            "user_cluster_95pct": [bootstrap[24], bootstrap[974]],
            "loss_coefficients": coefficients,
            "positive_means_improvement": True,
        }
    return contrasts


def calibration(rows: list, probabilities: list) -> list:
    bins = []
    for index in range(10):
        observations = [
            (row["y"], value)
            for row, value in zip(rows, probabilities, strict=True)
            if min(int(value * 10), 9) == index
        ]
        bins.append(
            {
                "lower": index / 10,
                "upper": (index + 1) / 10,
                "n": len(observations),
                "observed": statistics.mean(y for y, _ in observations) if observations else None,
                "predicted": statistics.mean(value for _, value in observations)
                if observations
                else None,
            }
        )
    return bins


def evaluate_predictions(rows: list, probabilities: dict, limits: dict) -> dict:
    result = {**base.support(rows), "status": "insufficient_support"}
    if not rows:
        return result
    result["observed_rate"] = sum(row["y"] for row in rows) / len(rows)
    result["mean_predicted"] = {
        name: statistics.mean(values) for name, values in probabilities.items()
    }
    if not supported(rows, limits):
        return result
    result["status"] = "evaluated"
    result["arms"] = {
        name: {
            "user_log_loss": base.user_mean_loss(rows, values),
            "send_metrics": base.metrics(rows, values),
            "calibration": calibration(rows, values),
        }
        for name, values in probabilities.items()
    }
    result["paired_contrasts"] = paired_contrasts(rows, probabilities)
    return result


def descriptive_groups(rows: list, probabilities: dict, limits: dict) -> dict:
    masks = {
        "HQ": [i for i, row in enumerate(rows) if row["path"] == "broadcast_reengagement_hq"],
        "fallback": [i for i, row in enumerate(rows) if row["path"] == "broadcast_reengagement"],
        "dormancy_29_plus": [i for i, row in enumerate(rows) if row["features"]["idle_days"] >= 29],
    }
    return {
        label: evaluate_predictions(
            [rows[i] for i in indices],
            {name: [values[i] for i in indices] for name, values in probabilities.items()},
            limits,
        )
        for label, indices in masks.items()
    }


def train_comparison(rows: list, cutoff, limits: dict) -> tuple[dict, dict | None]:
    eligible = [row for row in rows if row["sent_at"] + HORIZON <= cutoff]
    folds = []
    pooled = []
    pooled_probabilities = {name: [] for name in FEATURE_SETS}
    for start, end in calendar_blocks(cutoff, OUTER_FOLDS):
        train, test = base.temporal_split(eligible, start, end)
        selected, tuning = select_regularization(eligible, start, limits)
        fold = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "train": base.support(train),
            "test": base.support(test),
            "regularization": tuning,
            "status": "insufficient_support",
        }
        folds.append(fold)
        if not supported(train, limits, training=True) or not supported(test, limits):
            continue
        models = base.fit_models(train, selected, feature_sets=FEATURE_SETS)
        probabilities = predictions(test, models)
        fold["status"] = "evaluated"
        fold["evaluation"] = evaluate_predictions(test, probabilities, limits)
        pooled.extend(test)
        for name, values in probabilities.items():
            pooled_probabilities[name].extend(values)
    selected, tuning = select_regularization(eligible, cutoff, limits)
    report = {
        "version": VERSION,
        "training_cutoff": cutoff.isoformat(),
        "training_support": base.support(eligible),
        "training_feature_coverage": base.training_feature_coverage(eligible),
        "outer_folds": folds,
        "pooled_prequential": evaluate_predictions(pooled, pooled_probabilities, limits),
        "descriptive": descriptive_groups(pooled, pooled_probabilities, limits),
        "final_regularization": tuning,
        "evaluation_plan": {
            "start": EVALUATION_START.isoformat(),
            "end": EVALUATION_END.isoformat(),
            "required_as_of": (EVALUATION_END + HORIZON).isoformat(),
            "status": "unavailable_until_complete",
        },
        "interpretation": "Matched prediction ablation on the same observed deliveries; "
        "subgroups are descriptive; no causal or deployment decision.",
    }
    if not supported(eligible, limits, training=True):
        return report, None
    models = base.fit_models(eligible, selected, feature_sets=FEATURE_SETS)
    bundle = {
        "version": VERSION,
        "feature_schema": base.VERSION,
        "training_cutoff": cutoff.isoformat(),
        "training_first_send": eligible[0]["sent_at"].isoformat(),
        "training_last_send": eligible[-1]["sent_at"].isoformat(),
        "training_support": base.support(eligible),
        "training_feature_coverage": report["training_feature_coverage"],
        "regularization": tuning,
        "models": models,
        "limits": limits,
        "evaluation_plan": report["evaluation_plan"],
        "feature_sets": {name: list(values) for name, values in FEATURE_SETS.items()},
        "reproducibility": {
            "python": sys.version.split()[0],
            "numpy": importlib.metadata.version("numpy"),
            "scikit_learn": importlib.metadata.version("scikit-learn"),
            "driver_sha256": file_digest(Path(__file__)),
            "fitter_sha256": file_digest(Path(base.__file__)),
        },
    }
    return report, bundle


def evaluate_frozen(rows: list, bundle: dict, as_of) -> dict:
    if bundle.get("version") != VERSION or set(bundle["models"]) != set(FEATURE_SETS):
        raise ValueError("unsupported matched bundle")
    cutoff = base.timestamp(bundle["training_cutoff"])
    first_send = base.timestamp(bundle["training_first_send"])
    last_send = base.timestamp(bundle["training_last_send"])
    if first_send > last_send or last_send + HORIZON > cutoff:
        raise ValueError("training outcome crosses frozen cutoff")
    if any(
        tuple(bundle["models"][name]["feature_names"]) != features
        for name, features in FEATURE_SETS.items()
    ):
        raise ValueError("frozen arm feature schema differs from its declared ablation")
    start = base.timestamp(bundle["evaluation_plan"]["start"])
    end = base.timestamp(bundle["evaluation_plan"]["end"])
    if start != EVALUATION_START or end != EVALUATION_END or start < cutoff:
        raise ValueError("frozen evaluation must be the aligned December 1-14 window")
    if as_of < end + HORIZON:
        raise ValueError("December outcomes unavailable; require as-of December 16 or later")
    test = [row for row in rows if start <= row["sent_at"] < end]
    probabilities = predictions(test, bundle["models"])
    return {
        "version": VERSION,
        "training_cutoff": cutoff.isoformat(),
        "evaluation_start": start.isoformat(),
        "evaluation_end": end.isoformat(),
        "frozen_weights": True,
        "evaluation": evaluate_predictions(test, probabilities, bundle["limits"]),
        "descriptive": descriptive_groups(test, probabilities, bundle["limits"]),
    }


def write_private(path: Path, value: dict) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    train = commands.add_parser("train")
    train.add_argument("--input", type=Path, required=True)
    train.add_argument("--manifest", type=Path, help="default: manifest.json beside input")
    train.add_argument("--as-of", required=True)
    train.add_argument("--cutoff", default="2026-11-21")
    train.add_argument("--model-out", type=Path, required=True)
    train.add_argument("--min-idle-days", type=float, default=7)
    train.add_argument("--min-train", type=int, default=200)
    train.add_argument("--min-test", type=int, default=50)
    train.add_argument("--min-users", type=int, default=20)
    train.add_argument("--min-class", type=int, default=5)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--input", type=Path, required=True)
    evaluate.add_argument("--manifest", type=Path, help="default: manifest.json beside input")
    evaluate.add_argument("--as-of", required=True)
    evaluate.add_argument("--model", type=Path, required=True)
    args = parser.parse_args()
    try:
        as_of = base.timestamp(args.as_of)
        reject_future_as_of(as_of)
        manifest_path = args.manifest or args.input.with_name("manifest.json")
        if args.command == "train":
            cutoff = base.timestamp(args.cutoff)
            if cutoff > as_of or cutoff >= EVALUATION_START:
                raise ValueError("training cutoff must be observed and before December 1")
            limits = {
                name: getattr(args, name)
                for name in ("min_train", "min_test", "min_users", "min_class")
            }
            if min(limits.values()) < 1:
                raise ValueError("support limits must be positive")
            if not math.isfinite(args.min_idle_days) or not 7 <= args.min_idle_days <= 365:
                raise ValueError("pilot minimum idle days must be finite and between 7 and 365")
            receipt = verify_manifest(
                args.input,
                manifest_path,
                start=calendar_blocks(cutoff)[0][0],
                end=cutoff - HORIZON,
                label_cutoff=cutoff,
                as_of=cutoff,
                min_idle=args.min_idle_days,
            )
            rows, counts, digest = load_snapshot(args.input, cutoff, args.min_idle_days)
            if counts["input"] != receipt["eligible_rows"] or digest != receipt["data_sha256"]:
                raise ValueError("parsed snapshot differs from verified manifest")
            report, bundle = train_comparison(rows, cutoff, limits)
            if bundle:
                bundle.update(
                    data_sha256=digest, min_idle_days=args.min_idle_days, snapshot_manifest=receipt
                )
                write_private(args.model_out, bundle)
            report["bundle_written"] = bundle is not None
        else:
            bundle = json.loads(args.model.read_text())
            if as_of < EVALUATION_END + HORIZON:
                raise ValueError(
                    "December outcomes unavailable; require as-of December 16 or later"
                )
            receipt = verify_manifest(
                args.input,
                manifest_path,
                start=EVALUATION_START,
                end=EVALUATION_END,
                label_cutoff=EVALUATION_END + HORIZON,
                as_of=as_of,
                min_idle=bundle["min_idle_days"],
            )
            if receipt["sql_sha256"] != bundle["snapshot_manifest"]["sql_sha256"]:
                raise ValueError("feature SQL changed after the model was frozen")
            rows, counts, digest = load_snapshot(args.input, as_of, bundle["min_idle_days"])
            if counts["input"] != receipt["eligible_rows"] or digest != receipt["data_sha256"]:
                raise ValueError("parsed snapshot differs from verified manifest")
            report = evaluate_frozen(rows, bundle, as_of)
        report.update(
            data_sha256=digest,
            snapshot_manifest=receipt,
            input_filters=counts,
            as_of=as_of.isoformat(),
        )
        print(json.dumps(report, indent=2, allow_nan=False))
    except (ValueError, OSError, ImportError, KeyError) as error:
        parser.exit(2, f"matched comparison failed: {error}\n")


if __name__ == "__main__":
    main()
