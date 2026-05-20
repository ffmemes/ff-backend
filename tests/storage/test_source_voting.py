from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import (
    engine,
    fetch_one,
    meme_raw_telegram,
    meme_source,
    meme_source_candidate,
    meme_source_candidate_poll,
    meme_source_candidate_vote,
)
from src.storage.constants import MemeSourceStatus
from src.storage.parsers.schemas import TgChannelPostParsingResult
from src.storage.source_voting import (
    CANDIDATE_STATUS_DISCOVERED,
    POLL_STATUS_OPEN,
    POLL_STATUS_PASSED,
    POLL_STATUS_REJECTED,
    SOURCE_VOTE_EARLY_REJECT_REASON,
    VOTE_ADD_SOURCE,
    VOTE_SKIP_SOURCE,
    advance_daily_source_cycle,
    close_source_candidate_poll,
    create_source_candidate_poll,
    mark_source_candidate_poll_open,
    post_new_source_candidate_poll,
    post_source_candidate_poll_message,
    prepare_source_candidate,
    record_source_candidate_vote,
    select_daily_source_candidate,
)
from src.tgbot.constants import TELEGRAM_MODERATOR_CHAT_ID
from tests.factories import TEST_ID_START, cleanup_test_data

CANDIDATE_ID = TEST_ID_START + 2200
CANDIDATE_URL = "https://t.me/ffm_source_vote_candidate"
SECOND_CANDIDATE_ID = TEST_ID_START + 2201
SECOND_CANDIDATE_URL = "https://t.me/ffm_source_vote_candidate_next"


def _post(post_id: int, content: str = "смешной мем") -> TgChannelPostParsingResult:
    return TgChannelPostParsingResult(
        post_id=post_id,
        url=f"{CANDIDATE_URL}/{post_id}",
        content=content,
        media=[{"url": "https://example.com/meme.jpg"}],
        views=100,
        date=datetime.utcnow(),
    )


async def _create_candidate(
    conn: AsyncConnection,
    *,
    candidate_id: int = CANDIDATE_ID,
    url: str = CANDIDATE_URL,
    times_forwarded: int = 5,
) -> None:
    await conn.execute(
        insert(meme_source_candidate)
        .values(
            id=candidate_id,
            type="telegram",
            url=url,
            status="discovered",
            times_forwarded=times_forwarded,
            first_seen_at=datetime(2026, 5, 1, 10, 0, 0),
            last_seen_at=datetime(2026, 5, 2, 10, 0, 0),
        )
        .on_conflict_do_nothing()
    )


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await conn.execute(
            delete(meme_source_candidate_vote).where(
                meme_source_candidate_vote.c.user_id >= TEST_ID_START
            )
        )
        await conn.execute(
            delete(meme_source_candidate_poll).where(
                meme_source_candidate_poll.c.candidate_id.in_(
                    [CANDIDATE_ID, SECOND_CANDIDATE_ID]
                )
            )
        )
        await conn.execute(
            delete(meme_source_candidate).where(
                meme_source_candidate.c.id.in_([CANDIDATE_ID, SECOND_CANDIDATE_ID])
            )
        )
        await conn.execute(
            delete(meme_source).where(meme_source.c.url.in_([CANDIDATE_URL, SECOND_CANDIDATE_URL]))
        )
        await conn.commit()
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_prepare_source_candidate_caches_raw_posts_without_enabling_source(
    conn: AsyncConnection,
):
    await _create_candidate(conn)
    await conn.commit()

    result = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4001)])

    assert result["status"] == "prepared"
    source = result["source"]
    assert source["status"] == MemeSourceStatus.IN_MODERATION.value
    assert source["language_code"] == "ru"

    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == CANDIDATE_ID)
    )
    assert candidate["status"] == "prepared"
    assert candidate["promoted_meme_source_id"] == source["id"]

    raw = await fetch_one(
        select(meme_raw_telegram).where(meme_raw_telegram.c.meme_source_id == source["id"])
    )
    assert raw is not None
    assert raw["post_id"] == 4001


@pytest.mark.asyncio
async def test_prepare_source_candidate_dismisses_non_russian_candidate(
    conn: AsyncConnection,
):
    await _create_candidate(conn)
    await conn.commit()

    result = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4002, content="hello")])

    assert result["status"] == "non_ru_no_cyrillic"
    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == CANDIDATE_ID)
    )
    assert candidate["status"] == "dismissed"
    assert candidate["dismissed_reason"] == "non_ru_no_cyrillic"


@pytest.mark.asyncio
async def test_prepare_source_candidate_handles_scrape_failure_without_stranding_candidate(
    conn: AsyncConnection,
):
    await _create_candidate(conn)
    await conn.commit()

    with patch(
        "src.storage.source_voting.fetch_telegram_candidate_posts",
        new=AsyncMock(side_effect=RuntimeError("scrape failed")),
    ):
        result = await prepare_source_candidate(CANDIDATE_ID)

    assert result["status"] == "prepare_failed"

    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == CANDIDATE_ID)
    )
    assert candidate["status"] == CANDIDATE_STATUS_DISCOVERED
    assert candidate["promoted_meme_source_id"] is None

    picked = await select_daily_source_candidate()
    assert picked is not None
    assert picked["id"] == CANDIDATE_ID


@pytest.mark.asyncio
async def test_source_candidate_vote_is_unique_and_mutable(conn: AsyncConnection):
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4003)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=datetime.utcnow(),
    )
    await conn.execute(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll["id"])
        .values(status=POLL_STATUS_OPEN, message_id=123, opened_at=datetime.utcnow())
    )
    await conn.commit()

    first = await record_source_candidate_vote(
        poll_id=poll["id"],
        user_id=TEST_ID_START + 1,
        vote=VOTE_ADD_SOURCE,
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
    )
    second = await record_source_candidate_vote(
        poll_id=poll["id"],
        user_id=TEST_ID_START + 2,
        vote=VOTE_SKIP_SOURCE,
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
    )
    changed = await record_source_candidate_vote(
        poll_id=poll["id"],
        user_id=TEST_ID_START + 1,
        vote=VOTE_SKIP_SOURCE,
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
    )

    assert first["counts"] == {"yes": 1, "no": 0, "total": 1}
    assert second["counts"] == {"yes": 1, "no": 1, "total": 2}
    assert changed["status"] == "changed"
    assert changed["counts"] == {"yes": 0, "no": 2, "total": 2}


@pytest.mark.asyncio
async def test_source_candidate_vote_rejects_poll_outside_moderator_chat(
    conn: AsyncConnection,
):
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4010)])
    wrong_chat_id = TELEGRAM_MODERATOR_CHAT_ID + 99
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=wrong_chat_id,
        now=datetime.utcnow(),
    )
    await conn.execute(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll["id"])
        .values(status=POLL_STATUS_OPEN, message_id=130, opened_at=datetime.utcnow())
    )
    await conn.commit()

    result = await record_source_candidate_vote(
        poll_id=poll["id"],
        user_id=TEST_ID_START + 10,
        vote=VOTE_ADD_SOURCE,
        chat_id=wrong_chat_id,
    )
    assert result["status"] == "wrong_chat"


@pytest.mark.asyncio
async def test_source_candidate_vote_early_rejects_clear_negative_poll(
    conn: AsyncConnection,
):
    now = datetime.utcnow()
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4013)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=now,
    )
    await conn.execute(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll["id"])
        .values(
            status=POLL_STATUS_OPEN,
            message_id=131,
            opened_at=now - timedelta(hours=2),
            closes_at=now + timedelta(hours=22),
        )
    )
    await conn.commit()

    result = None
    for offset in range(1, 7):
        result = await record_source_candidate_vote(
            poll_id=poll["id"],
            user_id=TEST_ID_START + 20 + offset,
            vote=VOTE_SKIP_SOURCE,
            chat_id=TELEGRAM_MODERATOR_CHAT_ID,
            now=now,
        )

    assert result is not None
    assert result["status"] == "early_rejected"
    assert result["counts"] == {"yes": 0, "no": 6, "total": 6}

    closed_poll = await fetch_one(
        select(meme_source_candidate_poll).where(meme_source_candidate_poll.c.id == poll["id"])
    )
    assert closed_poll["status"] == POLL_STATUS_REJECTED
    assert closed_poll["data"]["close_reason"] == SOURCE_VOTE_EARLY_REJECT_REASON

    source = await fetch_one(
        select(meme_source).where(meme_source.c.id == prepared["source"]["id"])
    )
    assert source["status"] == MemeSourceStatus.PARSING_DISABLED.value
    assert source["data"]["source_vote_rejection"]["reason"] == SOURCE_VOTE_EARLY_REJECT_REASON
    assert source["data"]["source_vote_rejection"]["no"] == 6

    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == CANDIDATE_ID)
    )
    assert candidate["status"] == "dismissed"
    assert candidate["dismissed_reason"] == (
        f"source_vote:{poll['id']}:{SOURCE_VOTE_EARLY_REJECT_REASON}"
    )


@pytest.mark.asyncio
async def test_source_candidate_vote_does_not_early_reject_before_min_open_time(
    conn: AsyncConnection,
):
    now = datetime.utcnow()
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4014)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=now,
    )
    await conn.execute(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll["id"])
        .values(
            status=POLL_STATUS_OPEN,
            message_id=132,
            opened_at=now - timedelta(minutes=89),
            closes_at=now + timedelta(hours=22),
        )
    )
    await conn.commit()

    result = None
    for offset in range(1, 7):
        result = await record_source_candidate_vote(
            poll_id=poll["id"],
            user_id=TEST_ID_START + 40 + offset,
            vote=VOTE_SKIP_SOURCE,
            chat_id=TELEGRAM_MODERATOR_CHAT_ID,
            now=now,
        )

    assert result is not None
    assert result["status"] == "recorded"
    assert result["counts"] == {"yes": 0, "no": 6, "total": 6}

    open_poll = await fetch_one(
        select(meme_source_candidate_poll).where(meme_source_candidate_poll.c.id == poll["id"])
    )
    assert open_poll["status"] == POLL_STATUS_OPEN


@pytest.mark.asyncio
async def test_close_passed_poll_enables_prepared_source_without_reparsing(
    conn: AsyncConnection,
):
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4004)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=datetime.utcnow() - timedelta(hours=25),
    )
    await conn.execute(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll["id"])
        .values(
            status=POLL_STATUS_OPEN,
            message_id=124,
            opened_at=datetime.utcnow() - timedelta(hours=25),
            closes_at=datetime.utcnow() - timedelta(hours=1),
        )
    )
    await conn.commit()

    for offset, vote in enumerate([VOTE_ADD_SOURCE, VOTE_ADD_SOURCE, VOTE_SKIP_SOURCE], start=1):
        await record_source_candidate_vote(
            poll_id=poll["id"],
            user_id=TEST_ID_START + offset,
            vote=vote,
            chat_id=TELEGRAM_MODERATOR_CHAT_ID,
            now=datetime.utcnow() - timedelta(hours=2),
        )

    with patch(
        "src.flows.storage.memes.process_cached_telegram_source",
        new=AsyncMock(),
    ) as process_cached:
        result = await close_source_candidate_poll(poll["id"], now=datetime.utcnow())

    assert result["status"] == POLL_STATUS_PASSED
    assert result["counts"] == {"yes": 2, "no": 1, "total": 3}
    process_cached.assert_awaited_once_with(prepared["source"]["id"])

    source = await fetch_one(
        select(meme_source).where(meme_source.c.id == prepared["source"]["id"])
    )
    assert source["status"] == MemeSourceStatus.PARSING_ENABLED.value
    assert source["data"]["source_vote"]["poll_id"] == poll["id"]

    candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == CANDIDATE_ID)
    )
    assert candidate["status"] == "promoted"


@pytest.mark.asyncio
async def test_post_new_source_candidate_poll_retries_prepared_candidate_after_send_failure(
    conn: AsyncConnection,
):
    await _create_candidate(conn)
    await conn.commit()
    bot = SimpleNamespace(
        send_message=AsyncMock(
            side_effect=[
                RuntimeError("telegram is temporarily unavailable"),
                SimpleNamespace(message_id=555),
            ]
        )
    )

    with patch(
        "src.storage.source_voting.fetch_telegram_candidate_posts",
        new=AsyncMock(return_value=[_post(4005)]),
    ) as fetch_posts:
        with pytest.raises(RuntimeError):
            await post_new_source_candidate_poll(bot, now=datetime.utcnow())

        result = await post_new_source_candidate_poll(bot, now=datetime.utcnow())

    assert result["status"] == "posted"
    assert result["poll"]["message_id"] == 555
    assert result["poll"]["status"] == POLL_STATUS_OPEN
    assert bot.send_message.await_count == 2
    fetch_posts.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_source_cycle_resumes_existing_draft_poll(conn: AsyncConnection):
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4006)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=datetime.utcnow(),
    )
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=556)))

    result = await advance_daily_source_cycle(bot, now=datetime.utcnow())

    assert result["new_poll"]["status"] == "posted"
    assert result["new_poll"]["poll"]["id"] == poll["id"]
    assert result["new_poll"]["poll"]["message_id"] == 556
    assert result["new_poll"]["poll"]["status"] == POLL_STATUS_OPEN
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_daily_source_cycle_early_rejects_negative_poll_and_posts_next_candidate(
    conn: AsyncConnection,
):
    now = datetime.utcnow()
    await _create_candidate(conn)
    await _create_candidate(
        conn,
        candidate_id=SECOND_CANDIDATE_ID,
        url=SECOND_CANDIDATE_URL,
        times_forwarded=4,
    )
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4015)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=now,
    )
    await conn.execute(
        meme_source_candidate_poll.update()
        .where(meme_source_candidate_poll.c.id == poll["id"])
        .values(
            status=POLL_STATUS_OPEN,
            message_id=558,
            opened_at=now - timedelta(hours=2),
            closes_at=now + timedelta(hours=22),
        )
    )
    await conn.commit()

    for offset in range(1, 7):
        await record_source_candidate_vote(
            poll_id=poll["id"],
            user_id=TEST_ID_START + 60 + offset,
            vote=VOTE_SKIP_SOURCE,
            chat_id=TELEGRAM_MODERATOR_CHAT_ID,
            now=now - timedelta(minutes=31),
        )

    bot = SimpleNamespace(
        edit_message_text=AsyncMock(),
        unpin_chat_message=AsyncMock(),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=559)),
    )
    with patch(
        "src.storage.source_voting.fetch_telegram_candidate_posts",
        new=AsyncMock(return_value=[_post(4016)]),
    ):
        result = await advance_daily_source_cycle(bot, now=now)

    assert result["closed_poll"]["status"] == POLL_STATUS_REJECTED
    assert (
        result["closed_poll"]["poll"]["data"]["close_reason"]
        == SOURCE_VOTE_EARLY_REJECT_REASON
    )
    assert result["new_poll"]["status"] == "posted"
    assert result["new_poll"]["candidate"]["id"] == SECOND_CANDIDATE_ID
    bot.edit_message_text.assert_awaited_once()
    edited_text = bot.edit_message_text.await_args.kwargs["text"]
    assert CANDIDATE_URL in edited_text
    assert "Голосование завершено: мем-источник отклонён." in edited_text
    bot.unpin_chat_message.assert_awaited_once_with(
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        message_id=558,
    )
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_opening_draft_poll_refreshes_vote_window(conn: AsyncConnection):
    now = datetime.utcnow()
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4007)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=now - timedelta(days=1),
    )
    await conn.commit()

    opened = await mark_source_candidate_poll_open(
        poll["id"],
        message_id=555,
        opened_at=now,
    )

    assert opened is not None
    assert opened["status"] == POLL_STATUS_OPEN
    assert opened["opened_at"] == now
    assert opened["closes_at"] == now + timedelta(hours=24)
    assert opened["message_id"] == 555


@pytest.mark.asyncio
async def test_post_source_candidate_poll_message_cancels_non_moderator_poll(
    conn: AsyncConnection,
):
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4011)])
    custom_chat_id = TELEGRAM_MODERATOR_CHAT_ID + 77
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=custom_chat_id,
        now=datetime.utcnow(),
    )
    bot = SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=777)))

    result = await post_source_candidate_poll_message(bot, poll, now=datetime.utcnow())

    assert result["status"] == "wrong_chat_target"
    bot.send_message.assert_not_awaited()
    assert result["poll"]["status"] == "cancelled"


@pytest.mark.asyncio
async def test_post_source_candidate_poll_message_pins_silently(conn: AsyncConnection):
    await _create_candidate(conn)
    await conn.commit()
    prepared = await prepare_source_candidate(CANDIDATE_ID, posts=[_post(4012)])
    poll = await create_source_candidate_poll(
        CANDIDATE_ID,
        prepared_meme_source_id=prepared["source"]["id"],
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        now=datetime.utcnow(),
    )
    message = SimpleNamespace(message_id=778)
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=message),
        pin_chat_message=AsyncMock(),
    )

    result = await post_source_candidate_poll_message(bot, poll, now=datetime.utcnow())

    assert result["status"] == "posted"
    sent_text = bot.send_message.await_args.kwargs["text"]
    assert sent_text == (
        "Добавляем новый источник мемов?\n\n"
        f"🔗 {CANDIDATE_URL}\n\n"
        "Наши паблики пересылали мемы оттуда 5 раз.\n"
        "Откройте ссылку и проголосуйте ниже.\n"
        "Голосование решит, начнем ли брать оттуда мемы на постоянке."
    )
    bot.pin_chat_message.assert_awaited_once_with(
        chat_id=TELEGRAM_MODERATOR_CHAT_ID,
        message_id=778,
        disable_notification=True,
    )
