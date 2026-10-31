"""v5 shadow score — log only, pure functions."""

import math

from src.crossposting.service import _build_decision_log
from src.crossposting.shadow_score import (
    SHADOW_V5_VERSION,
    attach_v5_ranks,
    content_mult_v1,
    score_v5,
)


def test_score_v5_ru_and_en():
    assert math.isclose(score_v5("tgchannelru", 10, 1.5, 0.4), math.log(11) * 1.5 * math.exp(0.2))
    # EN ignores like volume, full-strength taste
    assert math.isclose(score_v5("tgchannelen", 10, 1.5, 0.4), 1.5 * math.exp(0.4))
    assert math.isclose(score_v5("tgchannelen", 999, 2.0, None), 2.0)


def test_attach_v5_ranks_keeps_order_and_picks_best():
    cands = [
        {"rank": 1, "meme_id": 1, "score_v5": 1.0},
        {"rank": 2, "meme_id": 2, "score_v5": 9.0},
        {"rank": 3, "meme_id": 3, "score_v5": 3.0},
    ]
    out = attach_v5_ranks(cands)
    assert [c["meme_id"] for c in out] == [1, 2, 3]
    assert [c["shadow_v5_rank"] for c in out] == [3, 1, 2]
    assert {c["shadow_v5_pick_meme_id"] for c in out} == {2}


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
        "caption": None,
        "meme_source_id": 1,
        "candidate_pool_size": 50,
        **kw,
    }


def test_build_decision_log_v5_fields():
    cands = [
        _cand(101, 100, theta_src=0.5, user_taste_z=-1.0),
        _cand(102, 20, theta_src=2.0, user_taste_z=1.0),
    ]
    log = _build_decision_log("tgchannelen", 2, cands)
    top = log["candidates"][0]
    assert top["rank"] == 1 and top["meme_id"] == 101  # production order preserved
    assert top["shadow_version"] == SHADOW_V5_VERSION
    assert top["shadow_v5_pick_meme_id"] == 102
    assert "taste_boost_shadow" not in top


def test_build_decision_log_without_v5_inputs_logs_none():
    log = _build_decision_log("tgchannelru", 4, [_cand(101, 100)], like_volume_enabled=True)
    top = log["candidates"][0]
    assert top["score_v5"] is None
    assert "shadow_v5_rank" not in top


def test_content_mult_v1():
    assert content_mult_v1(None, None) == 1.0
    assert content_mult_v1("single_caption", False) == 1.0
    assert math.isclose(content_mult_v1("tweet_screenshot", None), 0.85)
    assert math.isclose(content_mult_v1("single_caption", True), 0.85)
    assert math.isclose(content_mult_v1("tweet_screenshot", True), 0.85**2)


def test_build_decision_log_v5c_shadow():
    tags = {"content_format": "tweet_screenshot", "relatable": True, "politics_news": False}
    cands = [
        _cand(101, 100, theta_src=1.0, user_taste_z=0.0, **tags),
        _cand(102, 100, theta_src=0.9, user_taste_z=0.0),
    ]
    log = _build_decision_log("tgchannelru", 4, cands, like_volume_enabled=True)
    top, second = log["candidates"]
    assert log["picked_meme_id"] == 101 and top["meme_id"] == 101  # pick unchanged
    assert {k: top[k] for k in tags} == tags
    assert math.isclose(top["score_v5c"], top["score_v5"] * 0.85**2, rel_tol=1e-5)
    assert second["content_mult_v1"] == 1.0 and second["score_v5c"] == second["score_v5"]
    assert top["shadow_v5_pick_meme_id"] == 101  # theta 1.0 > 0.9
    assert top["shadow_v5c_pick_meme_id"] == 102  # tags flip the shadow pick
    assert (top["shadow_v5c_rank"], second["shadow_v5c_rank"]) == (2, 1)


def test_build_decision_log_v5c_none_without_v5():
    top = _build_decision_log("tgchannelru", 4, [_cand(101, 100)])["candidates"][0]
    assert top["content_mult_v1"] == 1.0 and top["score_v5c"] is None
    assert "shadow_v5c_rank" not in top
