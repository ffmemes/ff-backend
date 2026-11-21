"""Temporal prediction check for historical dormant-user push reactions.

Reads a past-only feature CSV from push-reactivation-training.sql. No database
access. Output is aggregate JSON. numpy/sklearn are analyst-only fit dependencies.
The saved JSON bundle and score_features() use only the standard library.

Example:
    python scripts/analysis/push_reactivation_backtest.py --input private.csv \
        --as-of 2026-11-21T00:00:00Z --holdout-start 2026-11-01 \
        --model-out /private/path/frozen-push-model.json

The 14-day final calendar period must mature completely before it is scored.
--frozen-model evaluates an existing bundle without retraining any model.
The outcome is a reaction proxy on observed sends, not incremental reactivation.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "push-reactivation-logistic-v1"
REGULARIZATION_GRID = (0.03, 0.3, 1.0)
FALLBACK_C = 0.3
TUNED_MODELS = ("user_only", "user_content")
USER_FEATURES = (
    "idle_days",
    "user_push_count",
    "user_push_send_count",
    "user_push_reaction_rate",
    "user_feed_callback_count",
    "hours_since_push",
)
CONTENT_FEATURES = (
    "user_source_reaction_count",
    "user_source_like_rate",
    "meme_like_rate",
    "meme_send_count",
    "source_like_rate",
    "source_send_count",
    "meme_age_days",
    "meme_is_video",
    "meme_is_animation",
)
OPTIONAL_FEATURES = {"meme_age_days", "meme_is_video", "meme_is_animation"}
MODEL_FEATURES = {
    "intercept": (),
    "user_only": USER_FEATURES,
    "legacy_proxy": ("legacy_proxy_score",),
    "user_content": USER_FEATURES + CONTENT_FEATURES,
}
REQUIRED = {"event_id", "user_key", "sent_at", "y_24h", "path", "idle_days"}
FEATURE_NAMES = set(name for names in MODEL_FEATURES.values() for name in names)
REQUIRED.update(FEATURE_NAMES - OPTIONAL_FEATURES)


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def number(value: str | None) -> float | None:
    if value is None or value.strip() in {"", "NULL", "null"}:
        return None
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError("numeric features must be finite and nonnegative")
    return result


def read_rows(handle, as_of: datetime, min_idle: float) -> tuple[list[dict], dict]:
    reader = csv.DictReader(handle)
    missing = REQUIRED - set(reader.fieldnames or ())
    if missing:
        raise ValueError("missing CSV columns: " + ", ".join(sorted(missing)))
    rows = []
    counts = defaultdict(int)
    event_ids = set()
    for index, raw in enumerate(reader, start=2):
        try:
            counts["input"] += 1
            if not raw["event_id"] or raw["event_id"] in event_ids:
                raise ValueError("empty or duplicate event_id")
            event_ids.add(raw["event_id"])
            if not raw["user_key"]:
                raise ValueError("empty user_key")
            sent_at = timestamp(raw["sent_at"])
            if raw["y_24h"] not in {"0", "1"}:
                raise ValueError("y_24h must be 0 or 1")
            features = {name: number(raw.get(name)) for name in FEATURE_NAMES}
            if not (raw["path"] == "push" or raw["path"].startswith("broadcast")):
                counts["non_push"] += 1
                continue
            if features["idle_days"] is None:
                counts["unknown_idle"] += 1
                continue
            if features["idle_days"] < min_idle:
                counts["below_min_idle"] += 1
                continue
            if sent_at + timedelta(hours=24) > as_of:
                counts["immature"] += 1
                continue
            rows.append(
                {
                    "user": raw["user_key"],
                    "sent_at": sent_at,
                    "y": int(raw["y_24h"]),
                    "features": features,
                }
            )
        except (ValueError, TypeError) as error:
            raise ValueError(f"invalid CSV row {index}: {error}") from error
    rows.sort(key=lambda row: row["sent_at"])
    counts["eligible_mature"] = len(rows)
    return rows, dict(counts)


def transformed(features: dict, names: list | tuple) -> list[float | None]:
    values = []
    for name in names:
        value = features.get(name)
        if value is not None and (
            name.endswith("count") or name in {"idle_days", "hours_since_push", "meme_age_days"}
        ):
            value = math.log1p(value)
        values.append(value)
    return values


def score_features(model: dict, features: dict) -> float:
    """Score one candidate's past-only numeric features using a frozen JSON model."""
    values = transformed(features, model["feature_names"])
    normalized = [
        ((model["imputation"][i] if value is None else value) - model["means"][i])
        / model["scales"][i]
        for i, value in enumerate(values)
    ]
    normalized.extend(float(value is None) for value in values)
    logit = model["intercept"] + sum(
        coefficient * value
        for coefficient, value in zip(model["coefficients"], normalized, strict=True)
    )
    return 1 / (1 + math.exp(-max(-700, min(700, logit))))


def fit_models(rows: list[dict], regularization: dict | None = None) -> dict:
    import numpy as np
    from sklearn.linear_model import LogisticRegression

    labels = np.array([row["y"] for row in rows])
    models = {}
    for name, features in MODEL_FEATURES.items():
        model = {
            "feature_names": list(features),
            "imputation": [],
            "means": [],
            "scales": [],
            "coefficients": [],
        }
        if not features:
            probability = (sum(labels) + 0.5) / (len(labels) + 1)
            model["intercept"] = math.log(probability / (1 - probability))
            models[name] = model
            continue
        raw = [transformed(row["features"], features) for row in rows]
        for column in zip(*raw, strict=True):
            available = [value for value in column if value is not None]
            model["imputation"].append(statistics.median(available) if available else 0.0)
        imputed = np.array(
            [
                [
                    model["imputation"][i] if value is None else value
                    for i, value in enumerate(values)
                ]
                for values in raw
            ]
        )
        means, scales = imputed.mean(axis=0), imputed.std(axis=0)
        scales[scales == 0] = 1
        missing = np.array([[float(value is None) for value in values] for values in raw])
        matrix = np.concatenate(((imputed - means) / scales, missing), axis=1)
        strength = (regularization or {}).get(name, 1.0)
        estimator = LogisticRegression(C=strength, max_iter=1000, solver="lbfgs")
        estimator.fit(matrix, labels)
        model.update(
            means=means.tolist(),
            scales=scales.tolist(),
            coefficients=estimator.coef_[0].tolist(),
            intercept=float(estimator.intercept_[0]),
        )
        models[name] = model
    return models


def auc(labels: list[int], probabilities: list[float]) -> float | None:
    positives = sum(labels)
    negatives = len(labels) - positives
    if not positives or not negatives:
        return None
    ordered = sorted(zip(probabilities, labels, strict=True))
    wins = 0.0
    negatives_before = 0
    index = 0
    while index < len(ordered):
        end = index + 1
        while end < len(ordered) and ordered[end][0] == ordered[index][0]:
            end += 1
        positive_ties = sum(label for _, label in ordered[index:end])
        negative_ties = end - index - positive_ties
        wins += positive_ties * (negatives_before + negative_ties / 2)
        negatives_before += negative_ties
        index = end
    return wins / (positives * negatives)


def losses(rows: list[dict], probabilities: list[float]) -> list[float]:
    result = []
    for row, probability in zip(rows, probabilities, strict=True):
        probability = max(1e-12, min(1 - 1e-12, probability))
        result.append(-math.log(probability if row["y"] else 1 - probability))
    return result


def user_mean_loss(rows: list[dict], probabilities: list[float]) -> float:
    by_user = defaultdict(list)
    for row, loss in zip(rows, losses(rows, probabilities), strict=True):
        by_user[row["user"]].append(loss)
    return statistics.mean(statistics.mean(values) for values in by_user.values())


def metrics(rows: list[dict], probabilities: list[float]) -> dict:
    labels = [row["y"] for row in rows]
    by_user = defaultdict(list)
    for row, probability in zip(rows, probabilities, strict=True):
        by_user[row["user"]].append((row["y"], probability))
    conditional = []
    for observations in by_user.values():
        user_auc = auc([y for y, _ in observations], [p for _, p in observations])
        if user_auc is not None:
            conditional.append(user_auc)
    return {
        "log_loss": statistics.mean(losses(rows, probabilities)),
        "brier": statistics.mean((y - p) ** 2 for y, p in zip(labels, probabilities)),
        "auc": auc(labels, probabilities),
        "mean_predicted": statistics.mean(probabilities),
        "conditional_user_auc": statistics.mean(conditional) if conditional else None,
        "conditional_user_auc_users": len(conditional),
    }


def content_gain(rows: list[dict], predictions: dict) -> dict:
    user_loss = losses(rows, predictions["user_only"])
    content_loss = losses(rows, predictions["user_content"])
    by_user = defaultdict(list)
    for row, before, after in zip(rows, user_loss, content_loss, strict=True):
        by_user[row["user"]].append(before - after)
    user_gains = [statistics.mean(values) for values in by_user.values()]
    generator = random.Random(20261121)
    samples = sorted(
        statistics.mean(generator.choices(user_gains, k=len(user_gains))) for _ in range(1000)
    )
    return {
        "log_loss_gain_per_send": statistics.mean(user_loss) - statistics.mean(content_loss),
        "log_loss_gain_per_user": statistics.mean(user_gains),
        "user_cluster_bootstrap_95pct": [samples[24], samples[974]],
        "positive_means_content_improves": True,
    }


def support(rows: list[dict]) -> dict:
    positives = sum(row["y"] for row in rows)
    return {
        "sends": len(rows),
        "users": len({row["user"] for row in rows}),
        "positive": positives,
        "negative": len(rows) - positives,
    }


def training_user_digest(rows: list[dict]) -> str:
    return hashlib.sha256("\n".join(sorted({row["user"] for row in rows})).encode()).hexdigest()


def dormancy_diagnostics(rows: list, models: dict, args) -> list:
    result = []
    for label, lower, upper in (
        ("7_to_29", 7, 29),
        ("29_to_90", 29, 90),
        ("90_to_365", 90, 365.000001),
    ):
        group = [row for row in rows if lower <= row["features"]["idle_days"] < upper]
        diagnostic = {
            "cohort": label,
            **support(group),
            "observed_rate": None,
            "mean_predicted": None,
            "log_loss": None,
        }
        if group:
            predictions = {
                name: [score_features(models[name], row["features"]) for row in group]
                for name in TUNED_MODELS
            }
            diagnostic["observed_rate"] = sum(row["y"] for row in group) / len(group)
            diagnostic["mean_predicted"] = {
                name: statistics.mean(values) for name, values in predictions.items()
            }
            if enough(group, args.min_test, args.min_users, args.min_class):
                diagnostic["log_loss"] = {
                    name: statistics.mean(losses(group, values))
                    for name, values in predictions.items()
                }
        result.append(diagnostic)
    return result


def temporal_split(rows: list[dict], start: datetime, end: datetime) -> tuple[list, list]:
    train = [row for row in rows if row["sent_at"] + timedelta(hours=24) <= start]
    test = [row for row in rows if start <= row["sent_at"] < end]
    return train, test


def evaluate(train: list, test: list, models: dict, known_training_users: bool = True) -> dict:
    predictions = {
        name: [score_features(model, row["features"]) for row in test]
        for name, model in models.items()
    }
    train_users = {row["user"] for row in train}
    return {
        "status": "evaluated",
        "train": support(train),
        "test": support(test),
        "seen_user_send_fraction": (
            statistics.mean(row["user"] in train_users for row in test)
            if known_training_users
            else None
        ),
        "models": {name: metrics(test, values) for name, values in predictions.items()},
        "content_beyond_user": content_gain(test, predictions),
    }


def enough(rows: list, minimum_rows: int, minimum_users: int, minimum_class: int) -> bool:
    counts = support(rows)
    return (
        counts["sends"] >= minimum_rows
        and counts["users"] >= minimum_users
        and min(counts["positive"], counts["negative"]) >= minimum_class
    )


def tune_development(rows: list, cutoff: datetime, as_of: datetime, args) -> tuple[list, dict]:
    """Choose C independently for user/content models, using only earlier calendar blocks."""
    folds = []
    supported = []
    scores = {name: {strength: [] for strength in REGULARIZATION_GRID} for name in TUNED_MODELS}
    development_end = cutoff - timedelta(hours=24)
    for index in range(args.dev_folds, 0, -1):
        start = development_end - timedelta(days=args.fold_days * index)
        end = start + timedelta(days=args.fold_days)
        train, test = temporal_split(rows, start, end)
        fold = {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "train": support(train),
            "test": support(test),
            "status": "insufficient_support",
        }
        folds.append(fold)
        if not (
            end + timedelta(hours=24) <= min(as_of, cutoff)
            and enough(train, args.min_train, args.min_users, args.min_class)
            and enough(test, args.min_test, args.min_users, args.min_class)
        ):
            continue
        candidates = {}
        fold["tuning_scores"] = []
        for strength in REGULARIZATION_GRID:
            models = fit_models(train, dict.fromkeys(TUNED_MODELS, strength))
            candidates[strength] = models
            observed = {"C": strength}
            for name in TUNED_MODELS:
                probabilities = [score_features(models[name], row["features"]) for row in test]
                score = user_mean_loss(test, probabilities)
                scores[name][strength].append(score)
                observed[name] = score
            fold["tuning_scores"].append(observed)
        supported.append((fold, train, test, candidates))
    sufficient = len(supported) >= 2
    selected = {}
    for name in TUNED_MODELS:
        selected[name] = (
            min(
                REGULARIZATION_GRID,
                key=lambda strength: (round(statistics.mean(scores[name][strength]), 12), strength),
            )
            if sufficient
            else FALLBACK_C
        )
    for fold, train, test, candidates in supported:
        models = dict(candidates[1.0])
        for name in TUNED_MODELS:
            models[name] = candidates[selected[name]][name]
        fold.update(evaluate(train, test, models))
    tuning = {
        "kind": "L2",
        "candidate_C": list(REGULARIZATION_GRID),
        "selected_C": selected,
        "fallback_C": FALLBACK_C,
        "minimum_supported_folds": 2,
        "supported_folds": len(supported),
        "selection": "independent per model, mean of fold user-averaged log losses; "
        "ties at 12 decimals choose smaller C; fewer than 2 folds use fallback",
        "development_scores": {
            name: [
                {
                    "C": strength,
                    "mean_user_log_loss": statistics.mean(values) if values else None,
                    "folds": len(values),
                }
                for strength, values in candidates.items()
            ]
            for name, candidates in scores.items()
        },
    }
    return folds, tuning


def run(args) -> tuple[dict, dict | None]:
    as_of = timestamp(args.as_of)
    frozen = json.loads(Path(args.frozen_model).read_text()) if args.frozen_model else None
    if frozen and frozen.get("version") != VERSION:
        raise ValueError("unsupported frozen model version")
    cutoff = timestamp(frozen["training_cutoff"] if frozen else args.holdout_start)
    if cutoff > as_of:
        raise ValueError("training cutoff must not be later than --as-of")
    if frozen:
        first_send = timestamp(frozen["training_first_send"])
        last_send = timestamp(frozen["training_last_send"])
        if first_send > last_send or last_send + timedelta(hours=24) > cutoff:
            raise ValueError("frozen artifact training outcomes extend beyond its training cutoff")
    evaluation_start = cutoff
    if getattr(args, "evaluation_start", None):
        evaluation_start = timestamp(args.evaluation_start)
        if not frozen or evaluation_start < cutoff:
            raise ValueError("--evaluation-start requires a frozen model and a date >= its cutoff")
    min_idle = frozen["min_idle_days"] if frozen else args.min_idle_days
    fold_days = frozen["final_days"] if frozen else args.fold_days
    if args.input == "-":
        rows, filters = read_rows(sys.stdin, as_of, min_idle)
    else:
        with Path(args.input).open(newline="") as handle:
            rows, filters = read_rows(handle, as_of, min_idle)
    report = {
        "version": VERSION,
        "as_of": as_of.isoformat(),
        "filters": filters,
        "target": "observed push stored-reaction proxy within 24h",
        "min_idle_days": min_idle,
        "training_cutoff": cutoff.isoformat(),
        "evaluation_start": evaluation_start.isoformat(),
        "development": [],
        "limitations": [
            "Stored reaction timestamps can be overwritten by later corrections.",
            "Labels and reconstructable features omit deleted or unavailable history.",
            "Prediction on selected delivered pushes cannot establish causal lift or ranking lift.",
            "Legacy proxy is reconstructed affinity times meme rate, not historical HQ replay.",
            "No candidate-set hit rate is identifiable from delivered-only rows.",
            "Block, latency and incremental-return guardrails need prospective evaluation.",
        ],
    }
    if frozen:
        tuning = frozen["regularization"]
    else:
        report["development"], tuning = tune_development(rows, cutoff, as_of, args)
    report["regularization"] = tuning
    end = evaluation_start + timedelta(days=fold_days)
    train, _ = temporal_split(rows, cutoff, cutoff)
    test = [row for row in rows if evaluation_start <= row["sent_at"] < end]
    final = {
        "start": evaluation_start.isoformat(),
        "end": end.isoformat(),
        "train": support(train),
        "test": support(test),
        "status": "insufficient_support",
    }
    bundle = frozen
    development = report["development"]
    development_pass = bool(development) and all(
        fold["status"] == "evaluated" and fold["content_beyond_user"]["log_loss_gain_per_user"] > 0
        for fold in development
    )
    if frozen is None and enough(train, args.min_train, args.min_users, args.min_class):
        bundle = {
            "version": VERSION,
            "training_cutoff": cutoff.isoformat(),
            "training_first_send": train[0]["sent_at"].isoformat(),
            "training_last_send": train[-1]["sent_at"].isoformat(),
            "training_support": support(train),
            "training_user_set_sha256": training_user_digest(train),
            "min_idle_days": min_idle,
            "final_days": fold_days,
            "horizon_hours": 24,
            "transforms": "log1p for counts, idle_days, hours_since_push; median imputation; "
            "training mean/std scaling; appended missing indicators in feature order",
            "regularization": tuning,
            "models": fit_models(train, tuning["selected_C"]),
            "development_positive_every_fold": development_pass,
            "reproducibility": {
                "driver_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "python": sys.version.split()[0],
                "numpy": importlib.metadata.version("numpy"),
                "scikit_learn": importlib.metadata.version("scikit-learn"),
            },
        }
    if end + timedelta(hours=24) > as_of:
        final["status"] = "pending_complete_outcome_window"
    elif bundle and enough(test, args.min_test, args.min_users, args.min_class):
        known_users = not frozen or (
            training_user_digest(train) == frozen.get("training_user_set_sha256")
        )
        final.update(evaluate(train, test, bundle["models"], known_users))
        final["dormancy_diagnostics"] = dormancy_diagnostics(test, bundle["models"], args)
        final["subgroup_rule"] = "Descriptive only; subgroup results never change candidate gate."
    report["final"] = final
    if frozen:
        development_pass = frozen.get("development_positive_every_fold", False)
    final_pass = (
        final["status"] == "evaluated"
        and final["content_beyond_user"]["user_cluster_bootstrap_95pct"][0] > 0
    )
    report["candidate_gate"] = {
        "development_positive_every_fold": development_pass,
        "final_user_cluster_interval_positive": final_pass,
        "next_action": "prospective_shadow_only"
        if final_pass and development_pass
        else "collect_more_data_or_reject_current_candidate",
        "production_authorized": False,
        "holdout_rule": "No tuning on final period; changed candidates need a new future period.",
    }
    return report, bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="past-only feature CSV, or - for stdin")
    parser.add_argument("--as-of", required=True, help="label observation cutoff, UTC ISO time")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--holdout-start", help="frozen training cutoff, UTC ISO date/timestamp")
    source.add_argument("--frozen-model", help="evaluate an existing JSON bundle without refitting")
    parser.add_argument("--evaluation-start", help="later evaluation window for frozen models only")
    parser.add_argument("--model-out", help="private JSON bundle destination; no individual rows")
    parser.add_argument("--min-idle-days", type=float, default=7)
    parser.add_argument("--fold-days", type=int, default=14)
    parser.add_argument("--dev-folds", type=int, default=3)
    parser.add_argument("--min-train", type=int, default=200)
    parser.add_argument("--min-test", type=int, default=50)
    parser.add_argument("--min-users", type=int, default=20)
    parser.add_argument("--min-class", type=int, default=5)
    args = parser.parse_args()
    if (
        min(
            args.fold_days,
            args.dev_folds,
            args.min_train,
            args.min_test,
            args.min_users,
            args.min_class,
        )
        < 1
        or args.min_idle_days < 0
    ):
        parser.error("support and window limits must be positive; idle days must be nonnegative")
    try:
        report, bundle = run(args)
        if args.model_out and bundle:
            path = Path(args.model_out)
            if path.exists():
                raise ValueError("model destination exists; use a new versioned private path")
            with path.open("x") as handle:
                path.chmod(0o600)
                json.dump(bundle, handle, indent=2, allow_nan=False)
                handle.write("\n")
        report["model_artifact_written"] = bool(args.model_out and bundle)
        print(json.dumps(report, indent=2, allow_nan=False))
    except (ValueError, OSError, ImportError) as error:
        parser.exit(2, f"backtest failed: {error}\n")


if __name__ == "__main__":
    main()
