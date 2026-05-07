"""Integration tests for maybe_auto_snooze_source."""

from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import engine, fetch_one, meme, meme_raw_telegram, meme_source
from src.storage.constants import MemeSourceStatus, MemeSourceType, MemeStatus
from src.storage.service import auto_snooze_stale_sources, maybe_auto_snooze_source
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
STALE_INSTAGRAM_SOURCE_ID = TEST_ID_START + 501
RECENT_TELEGRAM_SOURCE_ID = TEST_ID_START + 502
RAW_ACTIVE_SOURCE_ID = TEST_ID_START + 503
STALE_SOURCE_MEME_ID = TEST_ID_START + 1501

# Recent timestamp inside the 7d rolling window. Factory default FIXED_DT (2024-06-01)
# is outside the window, so tests for time-based criteria must pass an explicit recent
# created_at/parsed_at.
RECENT = datetime.utcnow() - timedelta(hours=1)


async def _insert_recent_raw_telegram(conn: AsyncConnection, source_id: int) -> None:
    await conn.execute(
        insert(meme_raw_telegram).values(
            {
                "meme_source_id": source_id,
                "post_id": source_id,
                "url": f"https://t.me/test_source_{source_id}/{source_id}",
                "date": RECENT,
                "content": "recent raw post",
                "media": [],
                "views": 1,
                "created_at": RECENT,
            }
        )
    )


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


@pytest.mark.asyncio
async def test_auto_snooze_stale_source_without_recent_raw_posts(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=STALE_INSTAGRAM_SOURCE_ID,
        type=MemeSourceType.INSTAGRAM.value,
        status="parsing_enabled",
    )
    await conn.commit()

    result = await auto_snooze_stale_sources(meme_source_ids=[STALE_INSTAGRAM_SOURCE_ID])

    assert [source["id"] for source in result] == [STALE_INSTAGRAM_SOURCE_ID]
    source = await fetch_one(
        meme_source.select().where(meme_source.c.id == STALE_INSTAGRAM_SOURCE_ID)
    )
    assert source["status"] == MemeSourceStatus.SNOOZED.value
    assert source["data"]["snoozed_reason"] == "stale_no_raw_posts_7d"
    assert source["data"]["stale_after_days"] == 7
    assert "snoozed_at" in source["data"]


@pytest.mark.asyncio
async def test_auto_snooze_stale_source_snoozes_existing_ok_memes(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=STALE_INSTAGRAM_SOURCE_ID,
        type=MemeSourceType.INSTAGRAM.value,
        status="parsing_enabled",
    )
    await create_meme(
        conn,
        id=STALE_SOURCE_MEME_ID,
        meme_source_id=STALE_INSTAGRAM_SOURCE_ID,
        status=MemeStatus.OK.value,
    )
    await conn.commit()

    result = await auto_snooze_stale_sources(meme_source_ids=[STALE_INSTAGRAM_SOURCE_ID])

    assert [source["id"] for source in result] == [STALE_INSTAGRAM_SOURCE_ID]
    stored_meme = await fetch_one(meme.select().where(meme.c.id == STALE_SOURCE_MEME_ID))
    assert stored_meme["status"] == MemeStatus.SNOOZED.value


@pytest.mark.asyncio
async def test_no_stale_snooze_for_recently_parsed_source(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=RECENT_TELEGRAM_SOURCE_ID,
        type=MemeSourceType.TELEGRAM.value,
        status="parsing_enabled",
    )
    await conn.execute(
        meme_source.update()
        .where(meme_source.c.id == RECENT_TELEGRAM_SOURCE_ID)
        .values(parsed_at=RECENT)
    )
    await conn.commit()

    result = await auto_snooze_stale_sources(meme_source_ids=[RECENT_TELEGRAM_SOURCE_ID])

    assert result == []
    source = await fetch_one(
        meme_source.select().where(meme_source.c.id == RECENT_TELEGRAM_SOURCE_ID)
    )
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


@pytest.mark.asyncio
async def test_no_stale_snooze_when_source_has_recent_raw_posts(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=RAW_ACTIVE_SOURCE_ID,
        type=MemeSourceType.TELEGRAM.value,
        status="parsing_enabled",
    )
    await _insert_recent_raw_telegram(conn, RAW_ACTIVE_SOURCE_ID)
    await conn.commit()

    result = await auto_snooze_stale_sources(meme_source_ids=[RAW_ACTIVE_SOURCE_ID])

    assert result == []
    source = await fetch_one(meme_source.select().where(meme_source.c.id == RAW_ACTIVE_SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


# Criterion 3: rolling 7d ad_rate > 30% with min 30 processed memes (FFM-847).


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


# Criterion 3a: extreme_ad_rate early-kill (FFM-847 follow-up).
# Pure-pumper sources that post few but ~100% ad memes never reach the 30-meme
# sample threshold on volume alone. Catch them at >=80% ad_rate with >=10 processed.


@pytest.mark.asyncio
async def test_snooze_on_extreme_ad_rate_below_standard_sample(conn: AsyncConnection):
    """100% ad_rate with 12 processed memes (below the 30-meme standard threshold)
    must early-kill via 'extreme_ad_rate'."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=12, n_ok=0)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result == "extreme_ad_rate"
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.SNOOZED.value
    assert source["data"]["snoozed_reason"] == "extreme_ad_rate"


@pytest.mark.asyncio
async def test_snooze_on_extreme_ad_rate_at_80_pct_boundary(conn: AsyncConnection):
    """Threshold is `>= 0.80`. Exactly 80% (8 ad / 10 processed) must snooze."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=8, n_ok=2)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result == "extreme_ad_rate"


@pytest.mark.asyncio
async def test_no_snooze_on_extreme_ad_rate_below_min_sample(conn: AsyncConnection):
    """9 processed memes (9 ad = 100% ad_rate) is below the 10-meme minimum sample
    for the early-kill. Don't snooze — wait for one more meme."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=9, n_ok=0)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result is None
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value


@pytest.mark.asyncio
async def test_no_snooze_just_below_extreme_threshold(conn: AsyncConnection):
    """79% ad_rate (mid-band: too high to be healthy, too low for early-kill, sample
    too small for standard gate) must NOT snooze. Wait for the standard gate to
    kick in once n_processed >= 30."""
    await create_meme_source(conn, id=SOURCE_ID, status="parsing_enabled")
    # 11 ad + 3 ok = 14 processed, ad_rate ≈ 78.6% — under 80%, under 30 sample
    await _seed_memes(conn, source_id=SOURCE_ID, n_ad=11, n_ok=3)
    await conn.commit()

    result = await maybe_auto_snooze_source(SOURCE_ID, new_posts_count=5)

    assert result is None
    source = await fetch_one(meme_source.select().where(meme_source.c.id == SOURCE_ID))
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
