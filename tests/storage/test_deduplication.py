import pytest
import pytest_asyncio
from sqlalchemy import insert, select

from src.database import chat_meme_reaction, engine, meme, meme_stats, user_meme_reaction
from src.storage.constants import MemeStatus
from src.storage.deduplication import (
    deduplicate_described_meme,
    deduplicate_pending_meme,
    find_duplicate_by_file_id,
    find_duplicate_by_ocr_text,
    resolve_duplicate,
    sweep_file_id_duplicates,
)
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
    create_reaction,
    create_user,
)


@pytest_asyncio.fixture()
async def dedup_setup():
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10001)
        for user_id in range(10001, 10008):
            await create_user(conn, id=user_id)
        await conn.commit()

    yield

    async with engine.connect() as conn:
        await cleanup_test_data(conn)


async def _row(table, **where):
    async with engine.connect() as conn:
        query = select(table)
        for column, value in where.items():
            query = query.where(getattr(table.c, column) == value)
        result = await conn.execute(query)
        row = result.first()
        return row._asdict() if row else None


@pytest.mark.asyncio
async def test_find_duplicate_by_file_id_uses_older_ok_or_created_memes(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            status=MemeStatus.OK.value,
            telegram_file_id="same-file-id",
        )
        await create_meme(
            conn,
            id=10002,
            meme_source_id=10001,
            status=MemeStatus.CREATED.value,
            telegram_file_id="same-file-id",
        )
        await conn.commit()

    assert await find_duplicate_by_file_id(10002, "same-file-id") == 10001
    assert await find_duplicate_by_file_id(10001, "same-file-id") is None


@pytest.mark.asyncio
async def test_find_duplicate_by_file_id_prefers_published_original(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            status=MemeStatus.OK.value,
            telegram_file_id="same-file-id",
        )
        await create_meme(
            conn,
            id=10002,
            meme_source_id=10001,
            status=MemeStatus.PUBLISHED.value,
            telegram_file_id="same-file-id",
        )
        await conn.commit()

    assert await find_duplicate_by_file_id(10003, "same-file-id") == 10002


@pytest.mark.asyncio
async def test_find_duplicate_by_ocr_text_skips_short_text(dedup_setup):
    assert await find_duplicate_by_ocr_text(10001, "too short") is None


@pytest.mark.asyncio
async def test_resolve_duplicate_moves_reactions_and_refreshes_stats(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(conn, id=10001, meme_source_id=10001)
        await create_meme(conn, id=10002, meme_source_id=10001)
        await create_meme_stats(conn, meme_id=10001, nlikes=1, ndislikes=1, nmemes_sent=2)
        await create_meme_stats(conn, meme_id=10002, nlikes=2, ndislikes=1, nmemes_sent=3)
        await create_reaction(conn, user_id=10001, meme_id=10001, reaction_id=1)
        await create_reaction(conn, user_id=10002, meme_id=10001, reaction_id=2)
        await create_reaction(conn, user_id=10002, meme_id=10002, reaction_id=1)
        await create_reaction(conn, user_id=10003, meme_id=10002, reaction_id=1)
        await create_reaction(conn, user_id=10004, meme_id=10002, reaction_id=2)
        await conn.commit()

    result = await resolve_duplicate(10002, 10001, reason="test")

    assert result.reactions_moved == 2
    assert result.reactions_dropped == 3

    original_stats = await _row(meme_stats, meme_id=10001)
    assert original_stats["nlikes"] == 2
    assert original_stats["ndislikes"] == 2
    assert original_stats["nmemes_sent"] == 4

    dupe = await _row(meme, id=10002)
    assert dupe["status"] == MemeStatus.DUPLICATE.value
    assert dupe["duplicate_of"] == 10001
    assert await _row(meme_stats, meme_id=10002) is None

    async with engine.connect() as conn:
        reaction_rows = await conn.execute(
            select(user_meme_reaction).where(user_meme_reaction.c.meme_id == 10002)
        )
        assert reaction_rows.all() == []


@pytest.mark.asyncio
async def test_resolve_duplicate_reparents_existing_duplicate_children(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(conn, id=10001, meme_source_id=10001)
        await create_meme(conn, id=10002, meme_source_id=10001)
        await create_meme(conn, id=10003, meme_source_id=10001, status=MemeStatus.DUPLICATE.value)
        await conn.execute(meme.update().where(meme.c.id == 10003).values(duplicate_of=10002))
        await create_reaction(conn, user_id=10001, meme_id=10002, reaction_id=1)
        await conn.commit()

    await resolve_duplicate(10002, 10001, reason="test")

    dupe = await _row(meme, id=10002)
    child = await _row(meme, id=10003)
    assert dupe["duplicate_of"] == 10001
    assert child["duplicate_of"] == 10001


@pytest.mark.asyncio
async def test_resolve_duplicate_moves_chat_reactions(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(conn, id=10001, meme_source_id=10001)
        await create_meme(conn, id=10002, meme_source_id=10001)
        await conn.execute(
            insert(chat_meme_reaction),
            [
                {"chat_id": 1, "meme_id": 10001, "user_id": 10001, "reaction": 1},
                {"chat_id": 1, "meme_id": 10002, "user_id": 10001, "reaction": 2},
                {"chat_id": 1, "meme_id": 10002, "user_id": 10002, "reaction": 1},
            ],
        )
        await conn.commit()

    result = await resolve_duplicate(10002, 10001, reason="test")

    assert result.chat_reactions_moved == 1
    assert result.chat_reactions_dropped == 2

    async with engine.connect() as conn:
        original_rows = await conn.execute(
            select(chat_meme_reaction)
            .where(chat_meme_reaction.c.meme_id == 10001)
            .order_by(chat_meme_reaction.c.user_id)
        )
        dupe_rows = await conn.execute(
            select(chat_meme_reaction).where(chat_meme_reaction.c.meme_id == 10002)
        )

    assert [row._asdict()["user_id"] for row in original_rows.all()] == [10001, 10002]
    assert dupe_rows.all() == []


@pytest.mark.asyncio
async def test_deduplicate_pending_meme_resolves_file_id_before_ok_promotion(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            status=MemeStatus.OK.value,
            telegram_file_id="same-file-id",
        )
        pending = await create_meme(
            conn,
            id=10002,
            meme_source_id=10001,
            status=MemeStatus.CREATED.value,
            telegram_file_id="same-file-id",
        )
        await conn.commit()

    result = await deduplicate_pending_meme(pending)

    assert result.duplicate_found is True
    assert result.duplicate_of == 10001
    assert result.reason == "telegram_file_id"
    dupe = await _row(meme, id=10002)
    assert dupe["status"] == MemeStatus.DUPLICATE.value


@pytest.mark.asyncio
async def test_deduplicate_described_meme_resolves_only_ok_memes(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            ocr_result={"text": "same visible meme text", "calculated_at": "2026-05-20T00:00:00Z"},
        )
        await create_meme(conn, id=10002, meme_source_id=10001, status=MemeStatus.OK.value)
        await create_meme(
            conn,
            id=10003,
            meme_source_id=10001,
            status=MemeStatus.WAITING_REVIEW.value,
        )
        await conn.commit()

    ok_result = await deduplicate_described_meme(
        10002,
        "same visible meme text",
        status=MemeStatus.OK.value,
    )
    review_result = await deduplicate_described_meme(
        10003,
        "same visible meme text",
        status=MemeStatus.WAITING_REVIEW.value,
    )

    assert ok_result.duplicate_found is True
    assert ok_result.duplicate_of == 10001
    assert review_result.duplicate_found is False
    review_meme = await _row(meme, id=10003)
    assert review_meme["status"] == MemeStatus.WAITING_REVIEW.value


@pytest.mark.asyncio
async def test_sweep_file_id_duplicates_resolves_ok_exact_duplicates(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            telegram_file_id="same-file-id",
        )
        await create_meme(
            conn,
            id=10002,
            meme_source_id=10001,
            telegram_file_id="same-file-id",
        )
        await create_reaction(conn, user_id=10001, meme_id=10001, reaction_id=1)
        await create_reaction(conn, user_id=10002, meme_id=10002, reaction_id=2)
        await conn.commit()

    result = await sweep_file_id_duplicates()

    assert result["resolved"] == 1
    assert result["reactions_moved"] == 1

    original_stats = await _row(meme_stats, meme_id=10001)
    assert original_stats["nlikes"] == 1
    assert original_stats["ndislikes"] == 1
    assert original_stats["nmemes_sent"] == 2

    dupe = await _row(meme, id=10002)
    assert dupe["status"] == MemeStatus.DUPLICATE.value
    assert dupe["duplicate_of"] == 10001


@pytest.mark.asyncio
async def test_sweep_file_id_duplicates_resolves_ok_meme_to_published_original(dedup_setup):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            telegram_file_id="same-file-id",
        )
        await create_meme(
            conn,
            id=10002,
            meme_source_id=10001,
            status=MemeStatus.PUBLISHED.value,
            telegram_file_id="same-file-id",
        )
        await create_reaction(conn, user_id=10001, meme_id=10001, reaction_id=1)
        await conn.commit()

    result = await sweep_file_id_duplicates()

    assert result["resolved"] == 1
    dupe = await _row(meme, id=10001)
    assert dupe["status"] == MemeStatus.DUPLICATE.value
    assert dupe["duplicate_of"] == 10002

    published_stats = await _row(meme_stats, meme_id=10002)
    assert published_stats["nlikes"] == 1
    assert published_stats["nmemes_sent"] == 1
