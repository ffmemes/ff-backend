"""Measure a frozen dormant-push scorer locally, without database or Telegram calls.

The synthetic workload includes input validation, scoring, and stable sorting.
Artifact read/validation and synthetic input creation run outside ranking timers.
This analyst prototype does not select or send production memes.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import platform
import random
import statistics
import sys
import time
import tracemalloc
from datetime import datetime, timezone
from pathlib import Path

from push_reactivation_backtest import score_features

VERSION = "push-reactivation-logistic-v2"
FEATURES = (
    "idle_days",
    "user_push_count",
    "user_push_send_count",
    "user_push_reaction_rate",
    "user_feed_callback_count",
    "hours_since_push",
    "taste_feed_count",
    "taste_feed_like_rate",
    "user_source_reaction_count",
    "user_source_like_rate",
    "meme_like_rate",
    "meme_send_count",
    "source_like_rate",
    "source_send_count",
    "meme_age_days",
    "meme_is_video",
    "meme_is_animation",
    "taste_source_count",
    "taste_source_like_rate",
)
USER_FIELDS = FEATURES[:8]
RATE_FIELDS = {name for name in FEATURES if name.endswith("rate")}
FLAG_FIELDS = {"meme_is_video", "meme_is_animation"}
MAX_CANDIDATES = 64


def finite_number(value):
    return type(value) in (int, float) and math.isfinite(value)


def validate_artifact(bundle):
    """Reject unknown schemas and unsafe numeric parameters before any scoring."""
    if not isinstance(bundle, dict) or bundle.get("version") != VERSION:
        raise ValueError("unsupported artifact version")
    if bundle.get("horizon_hours") != 24 or bundle.get("min_idle_days") != 7:
        raise ValueError("unexpected outcome horizon or dormant audience")
    cutoff = datetime.fromisoformat(bundle["training_cutoff"])
    if cutoff.tzinfo is None:
        raise ValueError("artifact cutoff must include a timezone")
    model = bundle["models"]["user_content"]
    if model.get("feature_names") != list(FEATURES):
        raise ValueError("unexpected feature names or order")
    n = len(FEATURES)
    lengths = {"imputation": n, "means": n, "scales": n, "coefficients": 2 * n}
    for name, length in lengths.items():
        values = model.get(name)
        if not isinstance(values, list) or len(values) != length:
            raise ValueError(f"unexpected {name} length")
        if not all(finite_number(value) for value in values):
            raise ValueError(f"non-finite or invalid {name}")
    if not all(value > 0 for value in model["scales"]):
        raise ValueError("scales must be positive")
    if not finite_number(model.get("intercept")):
        raise ValueError("non-finite or invalid intercept")
    return model


def load_artifact(path):
    bundle = json.loads(path.read_bytes())
    return validate_artifact(bundle)


def validate_features(features):
    for name in FEATURES:
        value = features.get(name)
        if value is None:
            continue
        if not finite_number(value) or value < 0:
            raise ValueError(f"invalid feature {name}")
        if name in RATE_FIELDS and value > 1:
            raise ValueError(f"invalid probability feature {name}")
        if name in FLAG_FIELDS and value not in (0, 1):
            raise ValueError(f"invalid media flag {name}")


def rank_candidates(model, candidates):
    """Return stable input indices and scores for one bounded candidate shortlist."""
    if not 1 <= len(candidates) <= MAX_CANDIDATES:
        raise ValueError("candidate count must be in 1..64")
    scored = []
    for index, features in enumerate(candidates):
        validate_features(features)
        probability = score_features(model, features)
        if not math.isfinite(probability) or not 0 <= probability <= 1:
            raise ValueError("invalid score")
        scored.append((index, probability))
    return sorted(scored, key=lambda item: (-item[1], item[0]))


def synthetic_users(count):
    """Build deterministic, non-personal rows with candidate-specific source tastes."""
    generator = random.Random(20261121)

    def value(name):
        if generator.random() < 0.07:
            return None
        if name in RATE_FIELDS:
            return generator.random()
        if name in FLAG_FIELDS:
            return generator.randrange(2)
        if name == "idle_days":
            return generator.uniform(7, 365)
        return generator.randrange(200)

    rows = []
    for _ in range(count):
        user = {name: value(name) for name in USER_FIELDS}
        candidates = []
        for _ in range(MAX_CANDIDATES):
            features = {name: value(name) for name in FEATURES}
            features.update(user)
            # Each candidate may belong to a different source with different taste.
            candidates.append(features)
        rows.append(candidates)
    return rows


def verify(model, users):
    """Compare ordering and probabilities and check an independently calculated logit."""
    comparisons = 0
    for candidates in users[:16]:
        for k in (1, 16, 32, 64):
            expected = sorted(
                enumerate(score_features(model, row) for row in candidates[:k]),
                key=lambda item: (-item[1], item[0]),
            )
            if rank_candidates(model, candidates[:k]) != expected:
                raise AssertionError("reference score/order mismatch")
            comparisons += k
    # An explicit golden vector checks log1p, scaling, missing imputation and
    # appended indicators independently from score_features' implementation.
    n = len(FEATURES)
    golden = {
        "feature_names": list(FEATURES),
        "imputation": [0.5] * n,
        "means": [1.0] * n,
        "scales": [2.0] * n,
        "coefficients": [0.0] * (2 * n),
        "intercept": 0.2,
    }
    golden["coefficients"][0] = 0.4
    golden["coefficients"][3] = -0.6
    golden["coefficients"][1] = 0.3
    golden["coefficients"][n + 1] = 0.8
    features = dict.fromkeys(FEATURES, 0.0)
    features.update(idle_days=9, user_push_count=None, user_push_reaction_rate=0.25)
    logit = 0.2 + 0.4 * (math.log(10) - 1) / 2 - 0.6 * (0.25 - 1) / 2
    logit += 0.3 * (0.5 - 1) / 2 + 0.8
    expected = 1 / (1 + math.exp(-logit))
    if not math.isclose(score_features(golden, features), expected, abs_tol=1e-14):
        raise AssertionError("independent golden logistic check failed")
    tied = [features, dict(features)]
    if [index for index, _ in rank_candidates(golden, tied)] != [0, 1]:
        raise AssertionError("unstable equal-score ordering")
    return {"reference_comparisons": comparisons, "independent_golden_vector": "passed"}


def verify_rejections(bundle):
    mutations = (
        lambda b: b.update(version="unknown"),
        lambda b: b.update(horizon_hours=1),
        lambda b: b["models"]["user_content"]["scales"].__setitem__(0, 0),
        lambda b: b["models"]["user_content"]["scales"].__setitem__(0, -1),
        lambda b: b["models"]["user_content"]["means"].__setitem__(0, float("nan")),
        lambda b: b["models"]["user_content"]["coefficients"].__setitem__(0, float("inf")),
        lambda b: b["models"]["user_content"]["coefficients"].pop(),
        lambda b: b["models"]["user_content"]["feature_names"].reverse(),
        lambda b: b["models"]["user_content"].update(intercept=True),
    )
    for mutate in mutations:
        changed = copy.deepcopy(bundle)
        mutate(changed)
        try:
            validate_artifact(changed)
        except ValueError:
            continue
        raise AssertionError("invalid artifact accepted")
    return len(mutations)


def percentile(values, probability):
    return sorted(values)[math.ceil(probability * len(values)) - 1]


def benchmark(path, count, repeats):
    model = load_artifact(path)
    bundle = json.loads(path.read_bytes())
    users = synthetic_users(count)
    checks = verify(model, users)
    checks["rejected_invalid_artifacts"] = verify_rejections(bundle)
    load_ns = []
    for _ in range(50):
        start = time.perf_counter_ns()
        load_artifact(path)
        load_ns.append(time.perf_counter_ns() - start)
    timings = []
    for k in (1, 16, 32, 64):
        # Allocate shortlist views outside timers; candidate features are ready.
        shortlisted = [candidates[:k] for candidates in users]
        for candidates in shortlisted[:8]:
            rank_candidates(model, candidates)
        samples = []
        for _ in range(repeats):
            for candidates in shortlisted:
                start = time.perf_counter_ns()
                rank_candidates(model, candidates)
                samples.append(time.perf_counter_ns() - start)
        timings.append(
            {
                "candidates_per_user": k,
                "timed_user_batches": len(samples),
                "p50_ms": statistics.median(samples) / 1e6,
                "p95_ms": percentile(samples, 0.95) / 1e6,
                "mean_ms": statistics.mean(samples) / 1e6,
                "users_per_second_serial": len(samples) * 1e9 / sum(samples),
                "candidates_per_second_serial": len(samples) * k * 1e9 / sum(samples),
            }
        )
    # Python allocations for one ranking call; excludes resident inputs/model,
    # C/native allocator overhead and process RSS. Timings exclude tracemalloc.
    tracemalloc.start()
    tracemalloc.reset_peak()
    ranked = rank_candidates(model, users[0])
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(ranked) == MAX_CANDIDATES
    return {
        "measured_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifact_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "benchmark_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reference_module_sha256": hashlib.sha256(
            Path(sys.modules[score_features.__module__].__file__).read_bytes()
        ).hexdigest(),
        "machine": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
            "processor": platform.processor(),
        },
        "dataset": {
            "kind": "synthetic",
            "seed": 20261121,
            "users": count,
            "max_candidates": MAX_CANDIDATES,
            "repeats": repeats,
        },
        "checks": checks,
        "ranking": timings,
        "artifact_load": {
            "reads": len(load_ns),
            "bytes": path.stat().st_size,
            "p50_ms": statistics.median(load_ns) / 1e6,
            "p95_ms": percentile(load_ns, 0.95) / 1e6,
            "scope": "local filesystem, JSON parse and schema validation; warm OS cache",
        },
        "memory": {
            "ranking_k64_python_peak_allocated_bytes": peak,
            "scope": "one call only, excludes resident inputs/model and process RSS",
        },
        "measured_scope": "local Python input validation, ready-feature scoring and sorting",
        "unmeasured": [
            "database features and candidate selection",
            "cache reads and writes",
            "network and Telegram delivery",
            "concurrency",
            "production hardware",
        ],
        "interpretation": "Scoring cost alone can guide a bounded prototype. HQ fallback cost and "
        "database work require separate measurement before production activation.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--users", type=int, default=256)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 16 <= args.users <= 10000 or not 1 <= args.repeats <= 100:
        parser.error("users must be 16..10000 and repeats 1..100")
    result = benchmark(args.model, args.users, args.repeats)
    with args.output.open("x") as handle:
        args.output.chmod(0o600)
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
