"""Crosspost scoring — pure functions, no DB."""

import math

from src.crossposting import scoring
from src.crossposting.scoring import FACTORS, score
from src.crossposting.service import _build_decision_log


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
        **kw,
    }


def test_v5_ru_and_en():
    r = _cand(1, 10, theta_src=1.5, user_taste_z=0.4)
    assert math.isclose(score(r, "tgchannelru", "v5"), math.log(11) * 1.5 * math.exp(0.2))
    # EN ignores like volume, full-strength taste
    assert math.isclose(score(r, "tgchannelen", "v5"), 1.5 * math.exp(0.4))
    assert score(_cand(1, 999, theta_src=2.0), "tgchannelen", "v5") == 2.0
    assert score(_cand(1, 10), "tgchannelru", "v5") is None  # no shadow inputs


def test_content_and_src_fwd_mults():
    content, fwd = FACTORS["content_mult_v1"], FACTORS["src_fwd_mult"]
    assert content(_cand(1, 5), "tgchannelru") == 1.0
    assert math.isclose(content(_cand(1, 5, content_format="tweet_screenshot"), ""), 0.85)
    assert math.isclose(
        content(_cand(1, 5, content_format="tweet_screenshot", relatable=True), ""), 0.85**2
    )
    assert fwd(_cand(1, 5), "") == 1.0
    assert fwd(_cand(1, 5, src_fwd_pct=0.0), "") == 0.5
    assert fwd(_cand(1, 5, src_fwd_pct=1.0), "") == 1.5


def test_factors_mirror_old_sql_quirks():
    # int-typed CASE bind: the "0.8/0.5" impression penalty was always 0 in prod
    assert FACTORS["impr_factor"](_cand(1, 5, raw_impr_rank=2), "tgchannelru") == 0.0
    assert FACTORS["impr_factor"](_cand(1, 5, raw_impr_rank=1), "tgchannelen") == 1.0
    f = FACTORS["src_quality_mult"]
    assert f(_cand(1, 5, src_signal=None), "") == 0.5  # GREATEST(0.5, NULL) = 0.5
    assert f(_cand(1, 5, median_signal=0), "") == 0.5  # NULLIF(median, 0)
    assert f(_cand(1, 5, src_signal=0.0), "") == 0.5
    assert f(_cand(1, 5, src_signal=100.0), "") == 2.0
    assert f(_cand(1, 5, src_signal=15.0), "") == 1.5


def test_decision_log_ranks_picks_and_legacy_keys():
    tags = {"content_format": "tweet_screenshot", "relatable": True}
    cands = [
        _cand(101, 100, theta_src=1.0, user_taste_z=0.0, src_fwd_pct=0.1, **tags),
        _cand(102, 100, theta_src=0.9, user_taste_z=0.0, src_fwd_pct=0.9),
        _cand(103, 100, theta_src=0.8, user_taste_z=0.0),
    ]
    log = _build_decision_log("tgchannelru", cands, pool_size=50)
    a, b, c = log["candidates"]
    assert log["picked_meme_id"] == 101 and log["score_version"] == 4  # live = v4, ties → id
    assert a["picked_by"] == "v4" and a["picks"]["v5"] == 101
    assert a["picks"] == {"v2": 101, "v4": 101, "v5": 101, "v5c": 102, "v5f": 102}
    assert (a["ranks"]["v5f"], b["ranks"]["v5f"], c["ranks"]["v5f"]) == (3, 1, 2)
    # legacy flat keys used by docs/analyst readouts
    assert a["score_v5c"] == a["scores"]["v5c"] and a["final_score"] == a["scores"]["v4"]
    assert a["shadow_v5f_rank"] == 3 and a["shadow_v5c_pick_meme_id"] == 102
    assert a["lr_factor"] == a["factors"]["lr_factor"] and a["like_volume_enabled"] is True
    assert c["src_fwd_pct"] is None and c["score_v5f"] == c["score_v5"]


def test_live_shadow_falls_back_to_preselect_without_inputs(monkeypatch):
    monkeypatch.setitem(scoring.LIVE, "tgchannelen", "v5")
    log = _build_decision_log("tgchannelen", [_cand(101, 100)], pool_size=1)
    top = log["candidates"][0]
    assert top["picked_by"] == "v2" and log["score_version"] == 2
    assert top["score_v5"] is None and "shadow_v5_rank" not in top


def test_live_shadow_picks_when_promoted(monkeypatch):
    monkeypatch.setitem(scoring.LIVE, "tgchannelen", "v5")
    cands = [_cand(101, 100, theta_src=0.5), _cand(102, 20, theta_src=2.0)]
    log = _build_decision_log("tgchannelen", cands, pool_size=2)
    assert log["picked_meme_id"] == 102 and log["score_version"] == 5
    assert log["candidates"][0]["final_score"] == log["candidates"][0]["score_v5"]
