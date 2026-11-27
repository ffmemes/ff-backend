"""Channel model loop — pure functions, no DB."""

import logging
import math
import random
from datetime import datetime, timedelta

import pytest

from src.crossposting.model import (
    FEATURES,
    Model,
    add_zf,
    coefs_hash,
    compare,
    features,
    fit_ridge,
    load_model,
    source_prior,
    spearman,
    spec_hash,
    walk_forward,
)
from src.crossposting.service import _build_decision_log
from src.flows.crossposting import model_loop
from src.flows.crossposting.model_loop import format_digest, should_promote

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
    # a row's own spec (features, alpha) drives the refit
    sub = fit_ridge(xs, y, ["lr", "ln_likes"], alpha=1e-6)
    assert sub["features"] == ["lr", "ln_likes"] and sub["coefs"][1] == pytest.approx(
        fit["coefs"][i], rel=1e-3
    )
    assert spec_hash(["lr", "ln_likes"], 1e-6) != spec_hash(list(FEATURES), 1e-6)
    assert coefs_hash(sub) == coefs_hash({**sub}) != coefs_hash(fit)


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


def test_exploration_propensities_sum_to_one_and_reach_every_candidate():
    pool = [_cand(200, 5, pool_sample=True, **INPUTS)]
    cands = [_cand(100 + i, 10 + i, **INPUTS) for i in range(5)] + pool  # K = 6, N = 3
    logs = [
        _build_decision_log(
            "tgchannelru",
            cands,
            6,
            "v4",
            "v4",
            model=_model(),
            top_n=3,
            explore_eps=0.5,
            rng=random.Random(seed),
        )
        for seed in range(200)
    ]
    assert {log["picked_meme_id"] for log in logs} == {100, 101, 102, 103, 104, 200}
    by_id = {c["meme_id"]: c for c in logs[0]["candidates"]}
    assert by_id[104]["propensity"] == pytest.approx(0.5 / 3 + 0.5 / 6)
    assert by_id[100]["propensity"] == pytest.approx(0.5 / 6)
    assert sum(c["propensity"] for c in by_id.values()) == pytest.approx(1)
    assert logs[0]["explore_eps"] == 0.5
    # the pool sample is ranked by the model too, and flagged without a PRESELECT rank
    assert (by_id[200]["pool_sample"], by_id[200]["rank"], by_id[200]["policy_rank"]) == (
        True,
        None,
        6,
    )
    assert by_id[100]["pool_sample"] is False and by_id[100]["rank"] == 1


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
    at = datetime(2026, 11, 27)  # Friday
    labels = add_zf(
        [
            {"source_id": 1, "posted_at": at - timedelta(days=3), "f24": 9},
            {"source_id": 2, "posted_at": at - timedelta(days=3), "f24": 0},
            {"source_id": 1, "posted_at": at - timedelta(days=100), "f24": 4},
            {"source_id": 1, "posted_at": at - timedelta(days=181), "f24": 99},  # too old
            # after the cutoff: neither counted nor part of the week means (no look-ahead)
            {"source_id": 1, "posted_at": at - timedelta(hours=47), "f24": 99},
            {"source_id": 3, "posted_at": at + timedelta(hours=1), "f24": 99},  # the target
        ]
    )
    z_recent = math.log(10) - (math.log(10) + 0) / 2  # vs its week's posts matured by `at`
    z, n = source_prior(labels, 1, at)
    assert (z, n) == (pytest.approx((z_recent + 0.0) / 7), 2)
    assert source_prior(labels, 3, at) == (0.0, 0)


def test_spearman_handles_ties():
    assert spearman([1, 2, 3], [10, 20, 30]) == pytest.approx(1)
    assert spearman([1, 1, 1], [1, 2, 3]) == 0.0


def _wf_rows(n=500, seed=3, noise=0.5):
    rng, start = random.Random(seed), datetime(2026, 6, 1)
    rows = []
    for i in range(n):
        x = {f: rng.gauss(0, 1) for f in FEATURES}
        zf = x["ln_likes"] + rng.gauss(0, noise)
        rows.append({"posted_at": start + timedelta(hours=8 * i), "x": x, "zf": zf})
    return rows


def test_walk_forward_is_out_of_sample_and_compare_splits_thirds():
    rows = _wf_rows()
    test = walk_forward(rows)
    assert test and min(r["posted_at"] for r in test) > rows[149]["posted_at"]
    test = [{**r, "base": random.Random(i).random()} for i, r in enumerate(test)]
    m = compare(test)
    assert m["spearman_model"] > 0.5 and len(m["thirds"]) == 3 and min(m["thirds"]) > 0.3
    assert m["delta"] == pytest.approx(m["spearman_model"] - m["spearman_base"], abs=1e-4)
    assert compare(test[:20]) == {"n": 20}
    assert walk_forward(rows[:100]) == []


def test_promotion_rule():
    now = datetime(2026, 12, 10)
    better = {"delta": 0.01, "thirds": [0.02, -0.01, 0.03]}
    assert should_promote(better, None, now) == (True, "promoted")
    assert should_promote(better, now - timedelta(days=8), now) == (True, "promoted")
    assert should_promote(better, now - timedelta(days=6), now) == (False, "cooldown")
    one_third = {"delta": 0.05, "thirds": [0.2, -0.01, -0.01]}
    assert should_promote(one_third, None, now) == (False, "not_better")
    worse_overall = {"delta": -0.01, "thirds": [0.01, 0.01, -0.2]}
    assert should_promote(worse_overall, None, now) == (False, "not_better")
    assert should_promote({"n": 12}, None, now) == (False, "too_few_posts")


@pytest.mark.asyncio
async def test_refit_keeps_active_spec_and_stores_inactive_unless_better(monkeypatch):
    now = datetime(2026, 12, 10)
    rows = [{**r, "score": random.Random(i).random()} for i, r in enumerate(_wf_rows(noise=0))]
    active = {
        "version": 4,
        "features": ["ln_likes", "lr"],  # an agent's spec: the refit must keep it
        "coefs": [1.0, 0.0],  # frozen and perfect on these rows: nothing beats it
        "mean": [0.0, 0.0],
        "scale": [1.0, 1.0],
        "intercept": 0.0,
        "alpha": 3.0,
        "train_to": rows[200]["posted_at"],
        "activated_at": now - timedelta(days=30),
        "created_at": now - timedelta(days=30),
    }
    saved = {}

    async def fake_active(channel):
        return active

    async def fake_rows(channel):
        return rows

    async def fake_save(channel, fit, alpha, rows_, metrics, promote):
        saved.update(fit=fit, alpha=alpha, metrics=metrics, promote=promote)
        return 5

    monkeypatch.setattr(model_loop, "_active_row", fake_active)
    monkeypatch.setattr(model_loop, "training_rows", fake_rows)
    monkeypatch.setattr(model_loop, "_save_model", fake_save)
    monkeypatch.setattr(model_loop, "_now", lambda: now)
    await model_loop.retrain_channel("tgchannelru")
    assert saved["fit"]["features"] == ["ln_likes", "lr"] and saved["alpha"] == 3.0
    assert saved["metrics"]["baseline"] == "v4" and saved["promote"] is False
    assert saved["metrics"]["decision"] == "not_better"
    assert saved["metrics"]["since"] > str(active["train_to"])  # out of sample for v4 only

    # no active model: default spec, judged against the logged live score (random here)
    active = None
    await model_loop.retrain_channel("tgchannelru")
    assert saved["fit"]["features"] == list(FEATURES) and saved["metrics"]["baseline"] == "score"
    assert saved["promote"] is True


@pytest.mark.asyncio
async def test_training_rows_prefer_logged_inputs_unless_they_failed(monkeypatch):
    t = datetime(2026, 11, 20, 10)
    labels = add_zf([{"meme_id": m, "source_id": 1, "posted_at": t, "f24": 5} for m in (1, 2, 3)])
    base = {"nlikes": 9, "ndislikes": 1, "nmemes_sent": 20, "age_days": 3, "final_score": 1.0}
    cands = {
        1: {**base, "is_upload": False, "src_views_pct": 0.7},  # logged at decision
        2: {**base, "is_upload": None, "src_views_pct": None},  # inputs failed then
        3: base,  # logged before the model inputs existed
    }

    async def fake_labels(channel, until):
        return labels

    async def fake_picked(channel, labels_, since):
        return [{**r, "decided_at": t, "cand": cands[r["meme_id"]]} for r in labels_]

    async def fake_static(meme_ids):
        return {m: {"is_upload": True, "src_views_pct": 0.2} for m in meme_ids}

    monkeypatch.setattr(model_loop, "fetch_labels", fake_labels)
    monkeypatch.setattr(model_loop, "_picked", fake_picked)
    monkeypatch.setattr(model_loop, "fetch_model_static_inputs", fake_static)
    xs = [r["x"] for r in await model_loop.training_rows("tgchannelru")]
    assert [(x["is_upload"], x["src_views_pct"]) for x in xs] == [
        (0.0, 0.7),
        (1.0, 0.2),
        (1.0, 0.2),
    ]


@pytest.mark.asyncio
async def test_refit_failure_on_one_channel_does_not_stop_the_other(monkeypatch):
    calls = []

    async def fake_retrain(channel):
        calls.append(channel)
        if channel == "tgchannelru":
            raise RuntimeError("boom")
        return "ok"

    monkeypatch.setattr(model_loop, "retrain_channel", fake_retrain)
    monkeypatch.setattr(model_loop, "get_run_logger", lambda: logging.getLogger("test"))
    with pytest.raises(RuntimeError, match="tgchannelru"):
        await model_loop.retrain_channel_models.fn()
    assert calls == ["tgchannelru", "tgchannelen"]


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
    explored = {**post, "telegram_message_id": 124, "cand": {"policy_rank": 9}}
    health = {"last_snapshot": now - timedelta(minutes=14), "posts_24h": 5, "decisions_24h": 5}
    active = {"version": 5, "created_at": now, "activated_at": now, "is_active": True}
    nightly = {
        "version": 6,
        "n_train": 1043,
        "metrics": {"baseline": "v5", "delta": 0.01, "thirds": [0.1, -0.1, 0.0]},
        "is_active": False,
    }
    nightly["metrics"]["decision"] = "not_better"
    text = format_digest(
        [
            {
                "channel": "tgchannelru",
                "now": now,
                "posts": [post, explored],
                "models": [active, nightly],
                "health": {**health, "posts_to_label": 2},
            },
            {
                "channel": "tgchannelen",
                "now": now,
                "posts": [],
                "models": [],
                "health": {**health, "last_snapshot": None, "posts_to_label": 2},
            },
        ]
    )
    assert "https://t.me/fastfoodmemes/123" in text
    assert "f24 12 · zf +0.21 · жребий 2/3 · v5 прогноз +0.05" in text
    assert "модель v5 активна с 27.11; ночная v6 (n 1043) против v5: Δρ +0.01, лучше в 1/3" in text
    assert "не продвинута: не лучше" in text
    assert "жребий 9/3 (исследование)" in text
    assert "✅ снапшот 14 мин назад" in text
    assert "<b>EN</b> · модели нет" in text and "⚠️ снапшот нет" in text
