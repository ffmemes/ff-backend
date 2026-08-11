"""Shadow hybrid score — log only, pure functions."""

from src.crossposting.service import _build_decision_log
from src.crossposting.shadow_score import (
    SHADOW_VERSION,
    attach_shadow_ranks,
    hybrid_shadow_fields,
    maturity_band_mult,
    volume_factor,
)


def test_volume_and_hybrid():
    import math

    assert abs(volume_factor(0) - math.log(1)) < 1e-9
    assert abs(volume_factor(10) - math.log(11)) < 1e-9
    f = hybrid_shadow_fields(nlikes=10, src_quality_mult=1.5)
    assert f["shadow_version"] == SHADOW_VERSION
    assert abs(f["shadow_score"] - math.log(11) * 1.5) < 1e-5
    assert f["shadow_src_mult"] == 1.5


def test_maturity_band():
    assert maturity_band_mult(50) == 1.15
    assert maturity_band_mult(5) == 1.0
    assert maturity_band_mult(250) == 0.85
    f = hybrid_shadow_fields(nlikes=50, src_quality_mult=1.0)
    assert f["shadow_maturity_mult"] == 1.15
    assert f["shadow_score_maturity"] > f["shadow_score"]


def test_attach_shadow_ranks_disagree():
    cands = [
        {"rank": 1, "meme_id": 1, "shadow_score": 1.0},
        {"rank": 2, "meme_id": 2, "shadow_score": 9.0},
        {"rank": 3, "meme_id": 3, "shadow_score": 3.0},
    ]
    out = attach_shadow_ranks(cands)
    assert out[1]["shadow_rank"] == 1  # highest score
    assert out[0]["shadow_rank"] == 3
    assert out[0]["shadow_vs_prod_disagree"] is True
    assert out[0]["shadow_pick_meme_id"] == 2


def test_build_decision_log_includes_shadow():
    cands = [
        {
            "id": 101,
            "nlikes": 100,
            "ndislikes": 80,
            "nmemes_sent": 200,
            "raw_impr_rank": 1,
            "age_days": 3,
            "invited_count": 0,
            "src_signal": 20.0,
            "median_signal": 10.0,
            "caption": None,
            "meme_source_id": 1,
            "candidate_pool_size": 50,
        },
        {
            "id": 102,
            "nlikes": 20,
            "ndislikes": 10,
            "nmemes_sent": 40,
            "raw_impr_rank": 1,
            "age_days": 3,
            "invited_count": 0,
            "src_signal": 5.0,
            "median_signal": 10.0,
            "caption": None,
            "meme_source_id": 2,
            "candidate_pool_size": 50,
        },
    ]
    log = _build_decision_log("tgchannelru", 4, cands, like_volume_enabled=True)
    assert log is not None
    # Top-level keys must stay compatible with log_ranker_decision() columns only
    assert "shadow_version" not in log
    top = log["candidates"][0]
    assert top["shadow_version"] == SHADOW_VERSION
    assert "shadow_score" in top
    assert "shadow_rank" in top
    assert top["rank"] == 1  # production order preserved
    ranks = {c["meme_id"]: c["shadow_rank"] for c in log["candidates"]}
    assert set(ranks.values()) == {1, 2}
