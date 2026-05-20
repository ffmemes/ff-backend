import logging

import pytest
import pytest_asyncio
from sqlalchemy import insert, select

from src.database import chat_meme_reaction, engine, meme, meme_stats, user_meme_reaction
from src.flows.storage import describe_memes
from src.flows.storage import memes as storage_memes
from src.storage.constants import MemeStatus
from src.storage.service import resolve_all_file_id_duplicates, resolve_meme_duplicate
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_meme_stats,
    create_reaction,
    create_user,
)


@pytest_asyncio.fixture()
async def duplicate_setup():
    async with engine.connect() as conn:
        await create_meme_source(conn, id=10001)
        for user_id in range(10001, 10006):
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
async def test_resolve_meme_duplicate_moves_reactions_and_refreshes_stats(duplicate_setup):
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

    result = await resolve_meme_duplicate(10002, 10001)

    assert result["moved"] == 2
    assert result["conflicts"] == 3

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
async def test_resolve_all_file_id_duplicates_sweeps_ok_exact_duplicates(duplicate_setup):
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

    result = await resolve_all_file_id_duplicates()

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
async def test_resolve_meme_duplicate_moves_chat_reactions(duplicate_setup):
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

    result = await resolve_meme_duplicate(10002, 10001)

    assert result["chat_moved"] == 1
    assert result["chat_deleted"] == 2

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
async def test_final_meme_pipeline_runs_file_id_duplicate_sweep(monkeypatch):
    calls = []

    class FakeLogger:
        def info(self, *args):
            calls.append(("log_info", args))

    async def fake_get_pending_memes():
        calls.append(("get_pending",))
        return []

    async def fake_update_ready():
        calls.append(("update_ready",))
        return []

    async def fake_resolve_all():
        calls.append(("resolve_all",))
        return {"resolved": 1, "reactions_moved": 2, "reactions_dropped": 0}

    monkeypatch.setattr(storage_memes, "get_run_logger", lambda: FakeLogger())
    monkeypatch.setattr(storage_memes, "get_pending_memes", fake_get_pending_memes)
    monkeypatch.setattr(storage_memes, "update_meme_status_of_ready_memes", fake_update_ready)
    monkeypatch.setattr(storage_memes, "resolve_all_file_id_duplicates", fake_resolve_all)
    monkeypatch.setattr(storage_memes, "safe_emit", lambda *args, **kwargs: None)

    await storage_memes.final_meme_pipeline.fn()

    assert ("resolve_all",) in calls
    assert calls.index(("update_ready",)) < calls.index(("resolve_all",))


@pytest.mark.asyncio
async def test_describe_single_meme_resolves_ok_ocr_duplicate(monkeypatch, duplicate_setup):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            ocr_result={"text": "same visible meme text", "calculated_at": "2026-05-20T00:00:00Z"},
        )
        await create_meme(conn, id=10002, meme_source_id=10001, status=MemeStatus.OK.value)
        await conn.commit()

    async def fake_download(_file_id):
        return b"image-bytes"

    async def fake_call(_image_b64, _log, *, deadline=None):
        return {
            "ocr_text": "same visible meme text",
            "description": "A duplicate text meme.",
            "language": "en",
            "__model": "test/free",
        }

    monkeypatch.setattr(describe_memes, "download_meme_content_from_tg", fake_download)
    monkeypatch.setattr(describe_memes, "call_openrouter_vision", fake_call)

    status = await describe_memes.describe_single_meme(
        {"id": 10002, "telegram_file_id": "file", "ocr_result": None, "status": "ok"},
        logging.getLogger(__name__),
    )

    dupe = await _row(meme, id=10002)
    assert status == "ok"
    assert dupe["status"] == MemeStatus.DUPLICATE.value
    assert dupe["duplicate_of"] == 10001


@pytest.mark.asyncio
async def test_describe_single_meme_does_not_resolve_upload_review_duplicate(
    monkeypatch, duplicate_setup
):
    async with engine.connect() as conn:
        await create_meme(
            conn,
            id=10001,
            meme_source_id=10001,
            ocr_result={"text": "same visible meme text", "calculated_at": "2026-05-20T00:00:00Z"},
        )
        await create_meme(
            conn,
            id=10002,
            meme_source_id=10001,
            status=MemeStatus.WAITING_REVIEW.value,
        )
        await conn.commit()

    async def fake_download(_file_id):
        return b"image-bytes"

    async def fake_call(_image_b64, _log, *, deadline=None):
        return {
            "ocr_text": "same visible meme text",
            "description": "A duplicate text meme.",
            "language": "en",
            "__model": "test/free",
        }

    monkeypatch.setattr(describe_memes, "download_meme_content_from_tg", fake_download)
    monkeypatch.setattr(describe_memes, "call_openrouter_vision", fake_call)

    status = await describe_memes.describe_single_meme(
        {
            "id": 10002,
            "telegram_file_id": "file",
            "ocr_result": None,
            "status": MemeStatus.WAITING_REVIEW.value,
        },
        logging.getLogger(__name__),
    )

    meme_row = await _row(meme, id=10002)
    assert status == "ok"
    assert meme_row["status"] == MemeStatus.WAITING_REVIEW.value
    assert meme_row["duplicate_of"] is None
