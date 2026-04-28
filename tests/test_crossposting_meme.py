import pytest
import pytest_asyncio
from sqlalchemy import delete, text

from src.crossposting.service import get_next_meme_for_tgchannelru
from src.database import crossposting, engine
from src.flows.crossposting.meme import _clean_caption
from tests.factories import (
    TEST_ID_START,
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
)


def test_strips_reddit_url():
    assert _clean_caption("https://redd.it/1rzi593") == ""


def test_strips_reddit_com_url():
    assert _clean_caption("https://www.reddit.com/r/me_irl/comments/abc") == ""


def test_strips_tg_handle():
    assert _clean_caption("@r_me_irl") == ""


def test_strips_subreddit_name():
    assert _clean_caption("me_irl") == ""


def test_strips_all_attribution_lines():
    caption = "me_irl\nhttps://redd.it/1rzi593\n@r_me_irl"
    assert _clean_caption(caption) == ""


def test_preserves_real_caption():
    caption = "When you finally fix the bug after 3 hours"
    assert _clean_caption(caption) == caption


def test_strips_attribution_preserves_real_content():
    caption = "me_irl\nhttps://redd.it/abc\n@r_me_irl\nThis is a real caption with multiple words"
    assert _clean_caption(caption) == "This is a real caption with multiple words"


def test_empty_string():
    assert _clean_caption("") == ""


def test_whitespace_only():
    assert _clean_caption("  \n  ") == ""


# ── Integration tests for get_next_meme_for_tgchannelru ranker ───────────


async def _wipe(conn):
    await conn.execute(delete(crossposting).where(crossposting.c.meme_id >= TEST_ID_START))
    await cleanup_test_data(conn)
    await conn.commit()


async def _insert_crossposting(
    conn,
    channel: str,
    meme_id: int,
    hours_ago: int,
    views: int = 0,
    forwards: int = 0,
    telegram_message_id: int | None = None,
) -> None:
    await conn.execute(
        text(
            "INSERT INTO crossposting "
            "(channel, meme_id, created_at, views, forwards, telegram_message_id) "
            f"VALUES (:channel, :meme_id, NOW() - INTERVAL '{hours_ago} hours', "
            ":views, :forwards, :tmid) "
            "ON CONFLICT DO NOTHING"
        ),
        {
            "channel": channel,
            "meme_id": meme_id,
            "views": views,
            "forwards": forwards,
            "tmid": telegram_message_id,
        },
    )


@pytest_asyncio.fixture()
async def clean_xpost():
    async with engine.connect() as conn:
        await _wipe(conn)
    yield
    async with engine.connect() as conn:
        await _wipe(conn)


@pytest.mark.asyncio
async def test_select_excludes_source_posted_within_24h(clean_xpost):
    async with engine.connect() as conn:
        # Source A: posted within 24h → must be excluded by diversity cap
        await create_meme_source(conn, id=10001, language_code="ru")
        await create_meme(
            conn, id=10001, meme_source_id=10001, language_code="ru", type="image", status="ok"
        )
        await create_meme(
            conn, id=10002, meme_source_id=10001, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10001, nlikes=10, ndislikes=2)
        await create_meme_stats(conn, meme_id=10002, nlikes=10, ndislikes=2)
        await _insert_crossposting(
            conn,
            "tgchannelru",
            10001,
            hours_ago=1,
            views=200,
            forwards=20,
            telegram_message_id=999001,
        )

        # Source B: not posted recently → must be selected over Source A
        await create_meme_source(conn, id=10003, language_code="ru")
        await create_meme(
            conn, id=10004, meme_source_id=10003, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10004, nlikes=10, ndislikes=2)
        await conn.commit()

    result = await get_next_meme_for_tgchannelru()
    assert result is not None, "Source B candidate should remain selectable"
    assert result["id"] == 10004, (
        "diversity cap must exclude source 10001 and prefer source 10003 candidate"
    )


@pytest.mark.asyncio
async def test_select_returns_none_when_all_filtered(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10010, language_code="ru")
        # Below nlikes threshold
        await create_meme(
            conn, id=10011, meme_source_id=10010, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10011, nlikes=2, ndislikes=0)
        # Wrong type (video filtered out)
        await create_meme(
            conn, id=10012, meme_source_id=10010, language_code="ru", type="video", status="ok"
        )
        await create_meme_stats(conn, meme_id=10012, nlikes=10, ndislikes=0)
        # Already in crossposting (CP.meme_id IS NULL filter excludes it)
        await create_meme(
            conn, id=10013, meme_source_id=10010, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10013, nlikes=10, ndislikes=0)
        await _insert_crossposting(conn, "tgchannelru", 10013, hours_ago=72, views=100, forwards=5)
        await conn.commit()

    result = await get_next_meme_for_tgchannelru()
    assert result is None


@pytest.mark.asyncio
async def test_source_quality_applied_when_n_above_threshold(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10100, language_code="ru", url="https://t.me/good_src")
        await create_meme_source(conn, id=10200, language_code="ru", url="https://t.me/bad_src")

        # 5 mature posts per source (>48h, <30d, image, views>0) so src_quality CTE picks them up
        for i in range(5):
            good_id = 10101 + i
            await create_meme(
                conn,
                id=good_id,
                meme_source_id=10100,
                language_code="ru",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=good_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelru", good_id, hours_ago=24 * 5, views=200, forwards=20
            )

            bad_id = 10201 + i
            await create_meme(
                conn,
                id=bad_id,
                meme_source_id=10200,
                language_code="ru",
                type="image",
                status="ok",
            )
            await create_meme_stats(conn, meme_id=bad_id, nlikes=5, ndislikes=0)
            await _insert_crossposting(
                conn, "tgchannelru", bad_id, hours_ago=24 * 5, views=50, forwards=2
            )

        # Fresh candidates not in crossposting — one per source
        await create_meme(
            conn, id=10150, meme_source_id=10100, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10150, nlikes=10, ndislikes=2)
        await create_meme(
            conn, id=10250, meme_source_id=10200, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10250, nlikes=10, ndislikes=2)
        await conn.commit()

    result = await get_next_meme_for_tgchannelru()
    assert result is not None
    assert result["id"] == 10150, (
        "good_source candidate should outrank bad_source via SQ multiplier"
    )


@pytest.mark.asyncio
async def test_source_quality_neutral_when_no_snapshots(clean_xpost):
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10300, language_code="ru")
        await create_meme(
            conn, id=10301, meme_source_id=10300, language_code="ru", type="image", status="ok"
        )
        await create_meme_stats(conn, meme_id=10301, nlikes=10, ndislikes=2)
        await conn.commit()

    result = await get_next_meme_for_tgchannelru()
    assert result is not None
    assert result["id"] == 10301
