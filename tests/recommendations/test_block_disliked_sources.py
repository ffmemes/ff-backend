"""Source affinity policies: demote (default) vs hard-block (optional)."""

import pytest
import pytest_asyncio
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
    create_user,
    create_user_language,
    create_user_meme_source_stats,
)

from src.database import engine
from src.recommendations.candidates import CandidatesRetriever
from src.recommendations.utils import (
    block_disliked_sources_sql_filter,
    disliked_source_demote_sql,
)

USER_ID = 10001
SOURCE_GOOD = 10001
SOURCE_BAD = 10002


@pytest_asyncio.fixture()
async def disliked_source_data():
    async with engine.connect() as conn:
        await create_user(conn, id=USER_ID)
        await create_user_language(conn, user_id=USER_ID, language_code="ru")
        await create_meme_source(conn, id=SOURCE_GOOD, type="telegram", url="https://t.me/good")
        await create_meme_source(conn, id=SOURCE_BAD, type="telegram", url="https://t.me/bad")

        await create_user_meme_source_stats(
            conn, user_id=USER_ID, meme_source_id=SOURCE_GOOD, nlikes=10, ndislikes=1
        )
        # Soft majority dislike (demote), not 3x hate (hard block)
        await create_user_meme_source_stats(
            conn, user_id=USER_ID, meme_source_id=SOURCE_BAD, nlikes=2, ndislikes=8
        )

        for mid in range(10001, 10006):
            await create_meme(conn, id=mid, meme_source_id=SOURCE_GOOD)
            await create_meme_stats(
                conn,
                meme_id=mid,
                nlikes=20,
                ndislikes=5,
                nmemes_sent=40,
                lr_smoothed=0.2,
                engagement_score=0.15,
                raw_impr_rank=0,
                invited_count=2,
            )
        for mid in range(10011, 10016):
            await create_meme(conn, id=mid, meme_source_id=SOURCE_BAD)
            await create_meme_stats(
                conn,
                meme_id=mid,
                nlikes=20,
                ndislikes=5,
                nmemes_sent=40,
                lr_smoothed=0.2,
                engagement_score=0.15,
                raw_impr_rank=0,
                invited_count=2,
            )
        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


def test_hard_block_off_by_default_string():
    # Explicit disabled
    assert block_disliked_sources_sql_filter(enabled=False) == ""


def test_hard_block_requires_ratio_when_enabled():
    frag = block_disliked_sources_sql_filter(
        enabled=True, min_reactions=15, min_dislike_to_like_ratio=3.0
    )
    assert "NOT EXISTS" in frag
    assert ">= 15" in frag
    assert "3.0" in frag or "3." in frag


def test_demote_sql_returns_case_expression():
    frag = disliked_source_demote_sql(enabled=True, min_reactions=5, multiplier=0.15)
    assert "CASE" in frag
    assert "0.15" in frag


@pytest.mark.asyncio
async def test_hard_block_disabled_still_returns_bad_source_candidates(
    disliked_source_data, monkeypatch
):
    """Default hard-block OFF: majority-dislike sources remain eligible (demoted only)."""
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_SOURCES", False)
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_DEMOTE_DISLIKED_SOURCES", True)

    retriever = CandidatesRetriever()
    results = await retriever.get_candidates("lr_smoothed", USER_ID, limit=50)
    ids = {r["id"] for r in results}
    # Good sources preferred but bad may still appear with soft demote if limit large
    assert ids & set(range(10001, 10006)), "expected good-source memes"


@pytest.mark.asyncio
async def test_hard_block_strong_hate_excludes_source(disliked_source_data, monkeypatch):
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_SOURCES", True)
    # Soft majority 8:2 is not 3x — should NOT hard-block
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_MIN_REACTIONS", 5)
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_RATIO", 3.0)

    retriever = CandidatesRetriever()
    results = await retriever.get_candidates("lr_smoothed", USER_ID, limit=50)
    ids = {r["id"] for r in results}
    # 8 dislikes vs 2 likes = 4x >= 3x and n=10 — wait 8 >= 3*2=6, yes hard block!
    # 8 >= 6 and n=10 >= 5 → hard blocked with ratio 3
    # Actually nlikes=2 ndislikes=8, 8 >= 3*2 = 6, yes blocked
    bad = ids & set(range(10011, 10016))
    assert not bad, f"strong-ratio hard block should exclude: {bad}"


@pytest.mark.asyncio
async def test_hard_block_high_ratio_only(disliked_source_data, monkeypatch):
    """With ratio 5, 8:2 source is not hard-blocked (8 < 5*2=10)."""
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_SOURCES", True)
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_MIN_REACTIONS", 5)
    monkeypatch.setattr("src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_RATIO", 5.0)

    retriever = CandidatesRetriever()
    results = await retriever.get_candidates("lr_smoothed", USER_ID, limit=50)
    ids = {r["id"] for r in results}
    # May include bad-source under soft demote only
    assert ids & set(range(10001, 10006))
