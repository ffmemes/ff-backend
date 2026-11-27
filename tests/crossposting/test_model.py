"""Channel model loop — pure functions, no DB."""

import math
import random
from datetime import datetime, timedelta

import pytest

from src.crossposting.model import (
    FEATURES,
    Model,
    add_zf,
    features,
    fit_ridge,
    load_model,
    source_prior,
    spearman,
    walk_forward,
)
from src.crossposting.service import _build_decision_log
from src.flows.crossposting.model_loop import format_digest, should_activate

INPUTS = {"is_upload": False, "src_views_pct": 0.8, "src_prior_z": 0.1, "src_prior_n": 3}


def _cand(mid, nlikes, **kw):
    return {
        "id": mid,
        "nlikes": nlikes,
        "ndislikes": 10,
        "nmemes_sent": 40,
        "raw_impr_rank": 1,
        "age_days": 3,
        "invited_count": 0,
        "src_signal": 10.0,
        "median_signal": 10.0,
        "has_caption": False,
        "meme_source_id": 1,
        **kw,
    }


def _model(coef_ln_likes=1.0, version=7):
    """Only like volume matters: rank = nlikes order."""
    return Model(version, ["ln_likes"], [coef_ln_likes], [0.0], [1.0], 0.0)


def test_features_match_offline_definitions():
    x = features(_cand(1, 9, ndislikes=1, nmemes_sent=20, age_days=6, has_caption=True, **INPUTS))
    assert set(x) == set(FEATURES)
    assert x["ln_likes"] == math.log(10) and x["lr"] == 10 / 11
    assert x["react_rate"] == 0.5 and x["log_sent"] == math.log(21)
    assert x["src_views_pct"] == 0.8 and x["src_views_missing"] == 0.0
    assert x["has_caption"] == 1.0 and x["is_upload"] == 0.0
    assert x["log_src_prior_n"] == math.log(4) and x["log_meme_age"] == math.log(7)
    missing = features(_cand(1, 9, **{**INPUTS, "src_views_pct": None}))
    assert missing["src_views_pct"] == 0.5 and missing["src_views_missing"] == 1.0


def test_features_none_without_model_inputs():
    assert features(_cand(1, 9)) is None  # _attach_model_inputs failed
    assert features(_cand(1, 9, **{**INPUTS, "src_prior_z": None})) is None


def test_fit_ridge_recovers_coefficients_and_predicts():
    rng = random.Random(1)
    xs = [{f: rng.gauss(0, 1) for f in FEATURES} for _ in range(400)]
    y = [0.3 + 2 * x["ln_likes"] - x["lr"] for x in xs]
    fit = fit_ridge(xs, y, alpha=1e-6)
    m = load_model({**fit, "version": 1})
    assert all(abs(m.predict(x) - t) < 1e-6 for x, t in zip(xs, y))
    # stored coefficients are per standardized unit: beta * scale
    i = FEATURES.index("ln_likes")
    assert fit["coefs"][i] == pytest.approx(2 * fit["scale"][i], rel=1e-6)
    # a constant column cannot divide by zero
    const = fit_ridge([{**x, "is_upload": 0.0} for x in xs], y)
    assert const["scale"][FEATURES.index("is_upload")] == 1.0


@pytest.mark.parametrize(
    "bad",
    [
        {"features": ["ln_likes", "views_magic"], "coefs": [1, 1], "mean": [0, 0], "scale": [1, 1]},
        {"features": ["ln_likes"], "coefs": [float("nan")], "mean": [0], "scale": [1]},
        {"features": ["ln_likes"], "coefs": [1], "mean": [0], "scale": [0]},
        {"features": ["ln_likes", "lr"], "coefs": [1], "mean": [0, 0], "scale": [1, 1]},
        {"features": ["ln_likes"], "coefs": ["x"], "mean": [0], "scale": [1]},
        {"features": [], "coefs": [], "mean": [], "scale": []},
    ],
)
def test_load_model_rejects_unsafe_rows(bad):
    with pytest.raises((ValueError, TypeError)):
        load_model({"version": 1, "intercept": 0.0, **bad})


def test_decision_log_draws_uniformly_from_model_top_n():
    cands = [_cand(100 + i, 10 + i, **INPUTS) for i in range(6)]  # model order: 105, 104, ...
    drawn = set()
    for seed in range(60):
        log = _build_decision_log(
            "tgchannelru", cands, 6, "v4", "v4", model=_model(), top_n=3, rng=random.Random(seed)
        )
        drawn.add(log["picked_meme_id"])
    assert drawn == {105, 104, 103}
    by_id = {c["meme_id"]: c for c in log["candidates"]}
    assert [by_id[m]["policy_rank"] for m in (105, 104, 103, 100)] == [1, 2, 3, 6]
    assert [by_id[m]["propensity"] for m in (105, 103, 102)] == [1 / 3, 1 / 3, 0.0]
    assert sum(c["propensity"] for c in log["candidates"]) == pytest.approx(1)
    assert by_id[105]["model_pred"] == round(math.log(16), 4)
    assert (log["policy"], log["top_n"], log["model_version"], log["score_version"]) == (
        "model_topN_v1",
        3,
        7,
        10,
    )
    # the live score's legacy keys still describe the score, not the draw
    assert by_id[100]["picked_by"] == "v4" and by_id[100]["final_score"] is not None


def test_decision_log_falls_back_to_score_when_model_cannot_score():
    cands = [_cand(101, 100), _cand(102, 20)]  # no model inputs attached
    log = _build_decision_log("tgchannelru", cands, 2, "v4", "v4", model=_model(-1.0), top_n=1)
    assert log["picked_meme_id"] == 101 and log["score_version"] == 4
    assert (log["policy"], log["top_n"], log["model_version"]) == ("score_topN_v1", 1, None)
    assert log["candidates"][0]["model_pred"] is None
    assert log["candidates"][0]["propensity"] == 1.0 and log["candidates"][1]["propensity"] == 0


def test_top_n_caps_at_pool_size():
    log = _build_decision_log("tgchannelen", [_cand(101, 10)], 1, "v2", "v2", top_n=3)
    assert log["top_n"] == 1 and log["candidates"][0]["propensity"] == 1.0


def test_zf_is_log_forwards_minus_msk_week_mean():
    mon = datetime(2026, 11, 23, 12)  # Monday
    labels = add_zf(
        [
            {"posted_at": mon, "f24": 9},
            {"posted_at": mon + timedelta(days=2), "f24": 0},
            # Sunday 22:00 UTC is Monday 01:00 MSK: next week, alone → zf 0
            {"posted_at": mon + timedelta(days=6, hours=10), "f24": 30},
        ]
    )
    mu = (math.log(10) + 0) / 2
    assert [r["zf"] for r in labels] == pytest.approx([math.log(10) - mu, -mu, 0.0])


def test_source_prior_uses_mature_posts_and_shrinks():
    at = datetime(2026, 11, 27)
    labels = [
        {"source_id": 1, "posted_at": at - timedelta(hours=47), "zf": 5.0},  # not mature
        {"source_id": 1, "posted_at": at - timedelta(days=3), "zf": 1.0},
        {"source_id": 1, "posted_at": at - timedelta(days=100), "zf": 0.5},
        {"source_id": 1, "posted_at": at - timedelta(days=181), "zf": 9.0},  # too old
        {"source_id": 2, "posted_at": at - timedelta(days=3), "zf": 9.0},
    ]
    assert source_prior(labels, 1, at) == (1.5 / 7, 2)
    assert source_prior(labels, 3, at) == (0.0, 0)


def test_spearman_handles_ties():
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1)
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0


def test_walk_forward_scores_model_against_logged_score():
    rng = random.Random(3)
    start, rows = datetime(2026, 6, 1), []
    for i in range(500):
        x = {f: rng.gauss(0, 1) for f in FEATURES}
        rows.append(
            {
                "posted_at": start + timedelta(hours=8 * i),
                "x": x,
                "zf": x["ln_likes"] + rng.gauss(0, 0.5),
                "score": rng.random(),  # a score with no signal
            }
        )
    wf = walk_forward(rows)
    assert wf["weeks"] >= 10 and wf["spearman_model"] > 0.5
    assert wf["delta"] == pytest.approx(wf["spearman_model"] - wf["spearman_score"], abs=1e-4)
    assert walk_forward(rows[:100]) == {"weeks": 0, "n": 0}


def test_en_activates_only_when_walk_forward_not_worse():
    assert should_activate("tgchannelru", {"delta": -0.2})
    assert should_activate("tgchannelen", {"delta": 0.0})
    assert not should_activate("tgchannelen", {"delta": -0.01})
    assert not should_activate("tgchannelen", {"weeks": 0, "n": 0})


def test_digest_shows_labels_draw_rank_and_health():
    now = datetime(2026, 11, 27, 6)
    post = {
        "telegram_message_id": 123,
        "posted_at": now - timedelta(hours=30),
        "f24": 12,
        "zf": 0.21,
        "top_n": 3,
        "model_version": 5,
        "cand": {"policy_rank": 2, "model_pred": 0.05},
    }
    health = {"last_snapshot": now - timedelta(minutes=14), "posts_24h": 5, "decisions_24h": 5}
    model_row = {
        "version": 5,
        "created_at": now,
        "n_train": 1043,
        "metrics": {"delta": 0.08},
        "is_active": True,
    }
    text = format_digest(
        [
            {
                "channel": "tgchannelru",
                "now": now,
                "posts": [post],
                "model": model_row,
                "health": {**health, "posts_to_label": 1},
            },
            {
                "channel": "tgchannelen",
                "now": now,
                "posts": [],
                "model": None,
                "health": {**health, "last_snapshot": None, "posts_to_label": 2},
            },
        ]
    )
    assert "https://t.me/fastfoodmemes/123" in text
    assert "f24 12 · zf +0.21 · жребий 2/3 · v5 прогноз +0.05" in text
    assert "модель v5 от 27.11, n 1043, wf Δρ +0.08, активна" in text
    assert "✅ снапшот 14 мин назад" in text
    assert "<b>EN</b> · модели нет" in text and "⚠️ снапшот нет" in text
