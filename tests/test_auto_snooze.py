"""Integration tests for maybe_auto_snooze_source."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import engine, fetch_one, meme_source
from src.storage.constants import MemeSourceStatus
from src.storage.service import maybe_auto_snooze_source
from tests.factories import (
    TEST_ID_START,
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_source_stats,
)


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await cleanup_test_data(conn)


SOURCE_ID = TEST_ID_START + 500


@pytest.mark.asyncio
async def test_no_snooze_on_first_empty_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
    assert source["data"]["consecutive_empty_parses"] == 1


@pytest.mark.asyncio
async def test_no_snooze_on_second_empty_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
    assert source["data"]["consecutive_empty_parses"] == 2


@pytest.mark.asyncio
async def test_snooze_on_third_consecutive_empty_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)

    assert result == "no_posts_3x"
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.SNOOZED.value
    assert source["data"]["snoozed_reason"] == "no_posts_3x"
    assert "snoozed_at" in source["data"]


@pytest.mark.asyncio
async def test_counter_resets_after_successful_parse(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await conn.commit()

    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    # successful parse resets counter
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
    assert source["data"]["consecutive_empty_parses"] == 0

    # subsequent empty parses start from 1 again
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result == "no_posts_3x"


@pytest.mark.asyncio
async def test_snooze_on_low_like_rate(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    # 5% like rate with 200 total reactions → should snooze
    await create_meme_source_stats(
        conn,
        meme_source_id=SOURCE_ID,
        nlikes=10,
        ndislikes=190,
        nmemes_sent=200,
    )
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result == "low_like_rate"
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.SNOOZED.value
    assert source["data"]["snoozed_reason"] == "low_like_rate"


@pytest.mark.asyncio
async def test_no_snooze_on_acceptable_like_rate(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    # 50% like rate → healthy, no snooze
    await create_meme_source_stats(
        conn,
        meme_source_id=SOURCE_ID,
        nlikes=100,
        ndislikes=100,
        nmemes_sent=200,
    )
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)
    assert result is None

    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


@pytest.mark.asyncio
async def test_no_snooze_when_below_min_reactions(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    # 5% like rate but only 40 reactions → not enough data, no snooze
    await create_meme_source_stats(
        conn,
        meme_source_id=SOURCE_ID,
        nlikes=2,
        ndislikes=38,
        nmemes_sent=40,
    )
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)
    assert result is None


@pytest.mark.asyncio
async def test_already_snoozed_source_skipped(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID, status="snoozed")
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=0)
    assert result is None


# Criterion 3: rolling 7d ad_rate > 30% with min 30 processed memes (FFM-847).

# Recent timestamp inside the 7d rolling window. Factory default FIXED_DT (2024-06-01)
# is outside the window, so tests for criterion 3 must pass an explicit recent created_at.
RECENT = datetime.utcnow() - timedelta(hours=1)


async def _seed_memes(
    conn: AsyncConnection,
    *,
    source_id: int,
    n_ad: int,
    n_ok: int,
    n_published: int = 0,
    n_duplicate: int = 0,
    n_failed: int = 0,
) -> None:
    """Create memes with the given status mix, all timestamped inside the 7d window."""
    next_id = TEST_ID_START + 1000
    for _ in range(n_ad):
        await create_meme(
            conn, id=next_id, meme_source_id=source_id, status="ad", created_at=RECENT
        )
        next_id += 1
    for _ in range(n_ok):
        await create_meme(
            conn, id=next_id, meme_source_id=source_id, status="ok", created_at=RECENT
        )
        next_id += 1
    for _ in range(n_published):
        await create_meme(
            conn, id=next_id, meme_source_id=source_id, status="published", created_at=RECENT
        )
        next_id += 1
    for _ in range(n_duplicate):
        await create_meme(
            conn, id=next_id, meme_source_id=source_id, status="duplicate", created_at=RECENT
        )
        next_id += 1
    for _ in range(n_failed):
        await create_meme(
            conn,
            id=next_id,
            meme_source_id=source_id,
            status="broken_content_link",
            created_at=RECENT,
        )
        next_id += 1


@pytest.mark.asyncio
async def test_snooze_on_high_ad_rate(conn: AsyncConnection):
    """Source with 50% ad_rate over 30 processed memes (15 ad + 15 ok) -> snooze."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=15, n_ok=15)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result == "high_ad_rate"
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.SNOOZED.value
    assert source["data"]["snoozed_reason"] == "high_ad_rate"


@pytest.mark.asyncio
async def test_no_snooze_when_published_inflates_denominator(conn: AsyncConnection):
    """SE catch (PR #214 review): healthy source whose ok memes get cross-posted to
    'published' must still count as processed, otherwise the denominator shrinks and
    a 10%-real-ad-rate source false-positive-snoozes at 33%.

    Setup: 10 ad + 20 ok + 70 published = 100 processed, real ad_rate = 10%.
    Without 'published' in the denominator, n_processed would be 30 and ad_rate = 33%.
    """
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=10, n_ok=20, n_published=70)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result is None, "healthy source with cross-posted memes must not snooze"
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


@pytest.mark.asyncio
async def test_no_snooze_when_below_min_processed(conn: AsyncConnection):
    """29 processed memes (15 ad + 14 ok = 51% ad_rate) is below the 30-meme minimum
    sample. Don't snooze — wait for more data."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=15, n_ok=14)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result is None
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


@pytest.mark.asyncio
async def test_no_snooze_at_exactly_30_pct_ad_rate(conn: AsyncConnection):
    """Threshold is strict `> 0.30`. Exactly 30% (9 ad / 30 processed) must NOT snooze."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=9, n_ok=21)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result is None
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


@pytest.mark.asyncio
async def test_failed_pipeline_memes_excluded_from_denominator(conn: AsyncConnection):
    """Pipeline failures (broken_content_link etc.) are not source-quality signal —
    they shouldn't pad the denominator. Setup: 15 ad + 15 ok + 50 broken_content_link.
    Real ad_rate over delivered memes = 50%, must snooze."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=15, n_ok=15, n_failed=50)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result == "high_ad_rate"
