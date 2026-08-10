"""Shadow taste enrichment on ranker candidates."""

from unittest.mock import AsyncMock

import pytest

from src.crossposting import service as xpost


@pytest.mark.asyncio
async def test_enrich_adds_taste_counts(monkeypatch):
    monkeypatch.setattr(
        xpost,
        "load_ru_taste_cohort",
        lambda: (101, 102, 103),
    )
    monkeypatch.setattr(
        xpost,
        "cohort_meta",
        lambda: {"version": "ru_taste_cohort_v1"},
    )
    monkeypatch.setattr(
        xpost,
        "fetch_all",
        AsyncMock(return_value=[{"meme_id": 1, "n_taste": 2}]),
    )
    rows = [{"id": 1, "nlikes": 10}, {"id": 2, "nlikes": 5}]
    out = await xpost._enrich_candidates_with_taste_shadow(rows)
    assert out[0]["n_taste_likes"] == 2
    assert out[0]["taste_boost_shadow"] == pytest.approx(1.3)  # 1+0.15*2
    assert out[0]["taste_cohort_version"] == "ru_taste_cohort_v1"
    assert out[1]["n_taste_likes"] == 0
    assert out[1]["taste_boost_shadow"] == 1.0


@pytest.mark.asyncio
async def test_enrich_empty_cohort(monkeypatch):
    monkeypatch.setattr(xpost, "load_ru_taste_cohort", lambda: ())
    rows = [{"id": 9}]
    out = await xpost._enrich_candidates_with_taste_shadow(rows)
    assert out[0]["n_taste_likes"] == 0
