"""Integration tests for `src.storage.moderation.advance_meme_source`.

Covers the shared moderation transition used by both the Telegram
moderator UI and the admin CLI (FFM-1154).
"""

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import engine, fetch_one, meme
from src.storage.constants import MemeSourceStatus, MemeStatus
from src.storage.moderation import (
    MemeSourceNotFoundError,
    advance_meme_source,
)
from tests.factories import (
    TEST_ID_START,
    cleanup_test_data,
    create_meme,
    create_meme_source,
)

SOURCE_ID = TEST_ID_START + 700
MEME_ID_OK = TEST_ID_START + 1700
MEME_ID_SNOOZED = TEST_ID_START + 1701


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        yield conn
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_set_language_records_audit_trail(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=SOURCE_ID,
        status=MemeSourceStatus.IN_MODERATION.value,
        language_code=None,
    )
    await conn.commit()

    result = await advance_meme_source(
        SOURCE_ID,
        moderator_id="agent:cto",
        language_code="ru",
        trigger_parse=False,
    )

    assert result["before_language_code"] is None
    assert result["source"]["language_code"] == "ru"
    assert result["source"]["status"] == MemeSourceStatus.IN_MODERATION.value
    assert result["snoozed_count"] == 0
    assert result["unsnoozed_count"] == 0
    assert result["parsed"] is False

    log = result["source"]["data"]["moderation_log"]
    assert len(log) == 1
    assert log[0]["moderator"] == "agent:cto"
    assert log[0]["changed"]["language_code"] == {"from": None, "to": "ru"}
    assert result["source"]["data"]["last_moderated_by"] == "agent:cto"


@pytest.mark.asyncio
async def test_advance_to_parsing_enabled_logs_status(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=SOURCE_ID,
        status=MemeSourceStatus.IN_MODERATION.value,
        language_code="ru",
    )
    await conn.commit()

    result = await advance_meme_source(
        SOURCE_ID,
        moderator_id="agent:cto",
        status=MemeSourceStatus.PARSING_ENABLED.value,
        trigger_parse=False,
    )

    assert result["before_status"] == MemeSourceStatus.IN_MODERATION.value
    assert result["source"]["status"] == MemeSourceStatus.PARSING_ENABLED.value

    log = result["source"]["data"]["moderation_log"]
    assert len(log) == 1
    assert log[0]["changed"]["status"] == {
        "from": MemeSourceStatus.IN_MODERATION.value,
        "to": MemeSourceStatus.PARSING_ENABLED.value,
    }


@pytest.mark.asyncio
async def test_unsnooze_on_snoozed_to_parsing_enabled(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=SOURCE_ID,
        status=MemeSourceStatus.SNOOZED.value,
        language_code="ru",
    )
    # One snoozed meme (will be unsnoozed) + one OK meme (must stay OK so
    # we know the cascade only touches snoozed rows for this source).
    await create_meme(
        conn,
        id=MEME_ID_SNOOZED,
        meme_source_id=SOURCE_ID,
        status=MemeStatus.SNOOZED.value,
    )
    await create_meme(
        conn,
        id=MEME_ID_OK,
        meme_source_id=SOURCE_ID,
        status=MemeStatus.OK.value,
    )
    await conn.commit()

    result = await advance_meme_source(
        SOURCE_ID,
        moderator_id="agent:cto",
        status=MemeSourceStatus.PARSING_ENABLED.value,
        trigger_parse=False,
    )

    assert result["unsnoozed_count"] == 1
    assert result["snoozed_count"] == 0

    snoozed_row = await fetch_one(meme.select().where(meme.c.id == MEME_ID_SNOOZED))
    ok_row = await fetch_one(meme.select().where(meme.c.id == MEME_ID_OK))
    assert snoozed_row["status"] == MemeStatus.OK.value
    assert ok_row["status"] == MemeStatus.OK.value


@pytest.mark.asyncio
async def test_snooze_cascades_ok_memes_to_snoozed(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=SOURCE_ID,
        status=MemeSourceStatus.PARSING_ENABLED.value,
        language_code="ru",
    )
    await create_meme(
        conn,
        id=MEME_ID_OK,
        meme_source_id=SOURCE_ID,
        status=MemeStatus.OK.value,
    )
    await conn.commit()

    result = await advance_meme_source(
        SOURCE_ID,
        moderator_id="42",
        status=MemeSourceStatus.SNOOZED.value,
        trigger_parse=False,
    )

    assert result["snoozed_count"] == 1
    assert result["unsnoozed_count"] == 0

    row = await fetch_one(meme.select().where(meme.c.id == MEME_ID_OK))
    assert row["status"] == MemeStatus.SNOOZED.value


@pytest.mark.asyncio
async def test_audit_log_appends_across_calls(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=SOURCE_ID,
        status=MemeSourceStatus.IN_MODERATION.value,
        language_code=None,
    )
    await conn.commit()

    await advance_meme_source(
        SOURCE_ID,
        moderator_id="agent:qa",
        language_code="ru",
        trigger_parse=False,
    )
    second = await advance_meme_source(
        SOURCE_ID,
        moderator_id="agent:cto",
        status=MemeSourceStatus.PARSING_ENABLED.value,
        trigger_parse=False,
    )

    log = second["source"]["data"]["moderation_log"]
    assert len(log) == 2
    assert log[0]["moderator"] == "agent:qa"
    assert log[1]["moderator"] == "agent:cto"
    assert second["source"]["data"]["last_moderated_by"] == "agent:cto"


@pytest.mark.asyncio
async def test_no_op_change_does_not_append_log(conn: AsyncConnection):
    """If the requested values match current state, no audit entry is added."""
    await create_meme_source(
        conn,
        id=SOURCE_ID,
        status=MemeSourceStatus.PARSING_ENABLED.value,
        language_code="ru",
    )
    await conn.commit()

    result = await advance_meme_source(
        SOURCE_ID,
        moderator_id="agent:cto",
        language_code="ru",
        status=MemeSourceStatus.PARSING_ENABLED.value,
        trigger_parse=False,
    )

    data = result["source"]["data"] or {}
    assert data.get("moderation_log") is None or data.get("moderation_log") == []


@pytest.mark.asyncio
async def test_missing_source_raises(conn: AsyncConnection):
    # No row was created for this id; cleanup fixture doesn't matter.
    await conn.commit()
    with pytest.raises(MemeSourceNotFoundError):
        await advance_meme_source(
            TEST_ID_START + 9999,
            moderator_id="agent:cto",
            status=MemeSourceStatus.PARSING_ENABLED.value,
            trigger_parse=False,
        )


@pytest.mark.asyncio
async def test_invalid_status_raises_value_error(conn: AsyncConnection):
    await create_meme_source(
        conn,
        id=SOURCE_ID,
        status=MemeSourceStatus.IN_MODERATION.value,
    )
    await conn.commit()
    with pytest.raises(ValueError):
        await advance_meme_source(
            SOURCE_ID,
            moderator_id="agent:cto",
            status="not_a_real_status",
            trigger_parse=False,
        )


@pytest.mark.asyncio
async def test_no_fields_raises_value_error(conn: AsyncConnection):
    await create_meme_source(conn, id=SOURCE_ID)
    await conn.commit()
    with pytest.raises(ValueError):
        await advance_meme_source(
            SOURCE_ID,
            moderator_id="agent:cto",
            trigger_parse=False,
        )
