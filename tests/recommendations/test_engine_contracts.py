"""Contract tests for recommendation engine SQL queries against real Postgres."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from tests.factories import (
    FIXED_DT,
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_source_stats,
    create_meme_stats,
    create_reaction,
    create_user,
    create_user_language,
    create_user_meme_source_stats,
)

from src.database import engine
from src.recommendations.candidates import CandidatesRetriever

USER_ID = 10001
SOURCE_TELEGRAM = 10001
SOURCE_USER_UPLOAD = 10002


@pytest_asyncio.fixture(loop_scope="session")
async def base_data():
    """Shared base fixture: users, sources, memes, stats."""
    async with engine.connect() as conn:
        # 4 users
        for uid in (10001, 10002, 10003, 10004):
            await create_user(conn, id=uid)
            await create_user_language(conn, user_id=uid, language_code="ru")

        # 2 sources
        await create_meme_source(conn, id=SOURCE_TELEGRAM, type="telegram")
        await create_meme_source(
            conn, id=SOURCE_USER_UPLOAD, type="user upload", url="https://t.me/test_upload_10002"
        )

        # 8 ok memes from telegram source
        for mid in range(10001, 10006):
            await create_meme(conn, id=mid, meme_source_id=SOURCE_TELEGRAM)

        # 3 ok memes from user upload source
        for mid in range(10006, 10009):
            await create_meme(conn, id=mid, meme_source_id=SOURCE_USER_UPLOAD)

        # 1 duplicate meme (should be excluded)
        await create_meme(conn, id=10009, meme_source_id=SOURCE_TELEGRAM, status="duplicate")

        # 1 wrong-language meme (should be excluded for ru users)
        await create_meme(conn, id=10010, meme_source_id=SOURCE_TELEGRAM, language_code="en")

        # 1 already-reacted meme for user 10001 (recent, within 30-day window)
        await create_meme(conn, id=10011, meme_source_id=SOURCE_TELEGRAM)
        recent = datetime.utcnow() - timedelta(days=1)
        await create_reaction(
            conn, user_id=10001, meme_id=10011, reaction_id=1, sent_at=recent, reacted_at=recent
        )

        # meme_stats for all ok memes (10001-10008, 10011)
        stats_defaults = dict(
            nlikes=15,
            ndislikes=5,
            nmemes_sent=30,
            raw_impr_rank=0,
            age_days=10,
            lr_smoothed=0.6,
            invited_count=3,
            sec_to_react=6.0,
        )
        for mid in list(range(10001, 10009)) + [10011]:
            await create_meme_stats(conn, meme_id=mid, **stats_defaults)

        # meme_source_stats
        await create_meme_source_stats(conn, meme_source_id=SOURCE_TELEGRAM)
        await create_meme_source_stats(conn, meme_source_id=SOURCE_USER_UPLOAD)

        # user_meme_source_stats for user 10001
        await create_user_meme_source_stats(
            conn, user_id=10001, meme_source_id=SOURCE_TELEGRAM, nlikes=8, ndislikes=3
        )
        await create_user_meme_source_stats(
            conn, user_id=10001, meme_source_id=SOURCE_USER_UPLOAD, nlikes=8, ndislikes=3
        )

        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


# Engines that use LEFT JOIN on user_meme_source_stats (work without it)
ENGINES_LEFT_JOIN_UMSS = [
    "best_uploaded_memes",
    "lr_smoothed",
    "like_spread_and_recent_memes",
    "es_ranked",
]

# Engines that require user_meme_source_stats via INNER JOIN
ENGINES_INNER_JOIN_UMSS = [
    "goat",
]

ALL_TESTABLE_ENGINES = ENGINES_LEFT_JOIN_UMSS + ENGINES_INNER_JOIN_UMSS


retriever = CandidatesRetriever()


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_name", ALL_TESTABLE_ENGINES)
async def test_returns_only_ok_status(base_data, engine_name):
    results = await retriever.get_candidates(engine_name, USER_ID, limit=50)
    result_ids = {r["id"] for r in results}
    assert 10009 not in result_ids, f"{engine_name} returned duplicate meme"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_name", ALL_TESTABLE_ENGINES)
async def test_respects_user_language(base_data, engine_name):
    results = await retriever.get_candidates(engine_name, USER_ID, limit=50)
    result_ids = {r["id"] for r in results}
    assert 10010 not in result_ids, f"{engine_name} returned wrong-language meme"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_name", ALL_TESTABLE_ENGINES)
async def test_excludes_reacted_memes(base_data, engine_name):
    results = await retriever.get_candidates(engine_name, USER_ID, limit=50)
    result_ids = {r["id"] for r in results}
    assert 10011 not in result_ids, f"{engine_name} returned already-reacted meme"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_name", ALL_TESTABLE_ENGINES)
async def test_has_correct_recommended_by(base_data, engine_name):
    results = await retriever.get_candidates(engine_name, USER_ID, limit=50)
    if len(results) == 0:
        pytest.skip(f"{engine_name} returned no results (expected for some engines)")
    for r in results:
        assert "recommended_by" in r, f"{engine_name} missing recommended_by"
        assert r["recommended_by"] is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_name", ALL_TESTABLE_ENGINES)
async def test_respects_exclude_meme_ids(base_data, engine_name):
    results = await retriever.get_candidates(
        engine_name, USER_ID, limit=50, exclude_mem_ids=[10001]
    )
    result_ids = {r["id"] for r in results}
    assert 10001 not in result_ids, f"{engine_name} did not respect exclude_meme_ids"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_name", ALL_TESTABLE_ENGINES)
async def test_respects_limit(base_data, engine_name):
    results = await retriever.get_candidates(engine_name, USER_ID, limit=1)
    assert len(results) <= 1, f"{engine_name} returned more than limit"


@pytest.mark.asyncio
@pytest.mark.parametrize("engine_name", ALL_TESTABLE_ENGINES)
async def test_returns_required_fields(base_data, engine_name):
    results = await retriever.get_candidates(engine_name, USER_ID, limit=50)
    if len(results) == 0:
        pytest.skip(f"{engine_name} returned no results")
    required = {"id", "type", "telegram_file_id", "recommended_by"}
    for r in results:
        missing = required - set(r.keys())
        assert not missing, f"{engine_name} missing fields: {missing}"


# --- Individual engine tests ---


@pytest.mark.asyncio
async def test_best_uploaded_memes_only_from_user_upload_source(base_data):
    results = await retriever.get_candidates("best_uploaded_memes", USER_ID, limit=50)
    assert len(results) > 0
    for r in results:
        assert r["id"] in range(
            10006, 10009
        ), f"best_uploaded_memes returned meme {r['id']} not from user upload source"


@pytest.mark.asyncio
async def test_goat_empty_without_user_source_stats(base_data):
    """User 10004 has no user_meme_source_stats -> goat uses INNER JOIN -> empty."""
    results = await retriever.get_candidates("goat", 10004, limit=50)
    assert len(results) == 0


@pytest.mark.asyncio
async def test_recently_liked_with_likes(base_data):
    """recently_liked needs > 1 like (reaction_id=1) with recent sent_at."""
    recent = datetime.utcnow() - timedelta(hours=1)
    async with engine.connect() as conn:
        for uid in (10002, 10003):
            await create_reaction(
                conn,
                user_id=uid,
                meme_id=10002,
                reaction_id=1,
                sent_at=recent,
                reacted_at=recent + timedelta(seconds=3),
            )
        await conn.commit()

    results = await retriever.get_candidates("recently_liked", USER_ID, limit=50)
    assert len(results) > 0
    assert any(r["id"] == 10002 for r in results)


@pytest.mark.asyncio
async def test_engine_with_no_matching_language(base_data):
    """User with only 'en' language shouldn't see 'ru' memes from most engines."""
    async with engine.connect() as conn:
        await create_user(conn, id=10005)
        await create_user_language(conn, user_id=10005, language_code="en")
        await conn.commit()

    # All our test memes are 'ru' (except 10010 which is 'en' but is from telegram source)
    results = await retriever.get_candidates("lr_smoothed", 10005, limit=50)
    ru_memes = {r["id"] for r in results if r["id"] in range(10001, 10009)}
    assert len(ru_memes) == 0


@pytest.mark.asyncio
async def test_engine_with_all_memes_seen(base_data):
    """If user reacted to all memes, engine should return empty."""
    async with engine.connect() as conn:
        for mid in range(10001, 10009):
            await create_reaction(
                conn,
                user_id=10001,
                meme_id=mid,
                reaction_id=1,
                reacted_at=FIXED_DT,
            )
        await conn.commit()

    results = await retriever.get_candidates("lr_smoothed", USER_ID, limit=50)
    # All ok memes (10001-10008) are now reacted, only meme 10010 (wrong lang) left
    ok_meme_ids = set(range(10001, 10009))
    returned_ok = {r["id"] for r in results} & ok_meme_ids
    assert len(returned_ok) == 0
