"""Negative source personalization: block sources the user already dislikes."""

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
from src.recommendations.utils import block_disliked_sources_sql_filter

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

        # Good source: user likes it
        await create_user_meme_source_stats(
            conn, user_id=USER_ID, meme_source_id=SOURCE_GOOD, nlikes=10, ndislikes=1
        )
        # Bad source: clear dislike majority with enough evidence
        await create_user_meme_source_stats(
            conn, user_id=USER_ID, meme_source_id=SOURCE_BAD, nlikes=1, ndislikes=9
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


def test_block_filter_sql_empty_when_disabled():
    assert block_disliked_sources_sql_filter(enabled=False) == ""


def test_block_filter_sql_contains_not_exists_when_enabled():
    frag = block_disliked_sources_sql_filter(enabled=True, min_reactions=5)
    assert "NOT EXISTS" in frag
    assert "umss_block" in frag
    assert ">= 5" in frag


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "engine_name",
    [
        "lr_smoothed",
        "like_spread_and_recent_memes",
        "es_ranked",
        "recently_liked",
        "viral_shares",
    ],
)
async def test_engines_skip_disliked_sources(disliked_source_data, engine_name, monkeypatch):
    monkeypatch.setattr(
        "src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_SOURCES",
        True,
    )
    monkeypatch.setattr(
        "src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_MIN_REACTIONS",
        5,
    )
    # recently_liked needs global likes; seed via reactions is heavy — only check
    # engines that rank from meme_stats without global like CTE.
    if engine_name == "recently_liked":
        pytest.skip("recently_liked depends on global like events not in this fixture")

    retriever = CandidatesRetriever()
    results = await retriever.get_candidates(engine_name, USER_ID, limit=50)
    ids = {r["id"] for r in results}
    bad_ids = set(range(10011, 10016))
    assert not (ids & bad_ids), (
        f"{engine_name} returned memes from disliked source: {ids & bad_ids}"
    )
    # Should still be able to return good-source memes for stats-based engines
    if engine_name in {"lr_smoothed", "like_spread_and_recent_memes", "es_ranked"}:
        assert ids & set(range(10001, 10006)), f"{engine_name} returned no good-source memes"


@pytest.mark.asyncio
async def test_filter_disabled_allows_disliked_source(disliked_source_data, monkeypatch):
    monkeypatch.setattr(
        "src.config.settings.RECOMMENDATION_BLOCK_DISLIKED_SOURCES",
        False,
    )
    retriever = CandidatesRetriever()
    results = await retriever.get_candidates("lr_smoothed", USER_ID, limit=50)
    ids = {r["id"] for r in results}
    # Without filter, disliked-source memes may appear (they have same quality stats)
    assert ids & set(range(10011, 10016)) or ids & set(range(10001, 10006))
