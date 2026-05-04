"""Tests for promote_source_candidate idempotency + TOCTOU guard (FFM-940)."""

from datetime import datetime
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.factories import TEST_ID_START, cleanup_test_data, create_user

from src.database import engine, fetch_one, meme_source, meme_source_candidate
from src.tgbot.service import promote_source_candidate

TOCTOU_URL = "https://t.me/ffm940_toctou_candidate"
ALREADY_DISMISSED_URL = "https://t.me/ffm940_dismissed_candidate"
PROMOTING_USER_ID = TEST_ID_START + 940


async def _create_discovered_candidate(conn: AsyncConnection, url: str) -> int:
    await conn.execute(
        insert(meme_source_candidate)
        .values(
            type="telegram",
            url=url,
            status="discovered",
            times_forwarded=3,
            created_at=datetime(2024, 6, 1, 12, 0, 0),
            updated_at=datetime(2024, 6, 1, 12, 0, 0),
        )
        .on_conflict_do_nothing()
    )
    row = (
        await conn.execute(
            select(meme_source_candidate.c.id).where(meme_source_candidate.c.url == url)
        )
    ).one()
    return int(row.id)


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        await create_user(conn, id=PROMOTING_USER_ID, type="moderator")
        await conn.commit()
        yield conn
        await conn.execute(
            delete(meme_source_candidate).where(
                meme_source_candidate.c.url.in_([TOCTOU_URL, ALREADY_DISMISSED_URL])
            )
        )
        await conn.execute(
            delete(meme_source).where(meme_source.c.url.in_([TOCTOU_URL, ALREADY_DISMISSED_URL]))
        )
        await conn.commit()
        await cleanup_test_data(conn)


@pytest.mark.asyncio
async def test_promote_skips_already_dismissed_candidate(conn: AsyncConnection):
    """Early-check path: a dismissed candidate is never promoted."""
    candidate_id = await _create_discovered_candidate(conn, ALREADY_DISMISSED_URL)
    await conn.execute(
        meme_source_candidate.update()
        .where(meme_source_candidate.c.id == candidate_id)
        .values(status="dismissed", dismissed_reason="moderator")
    )
    await conn.commit()

    result = await promote_source_candidate(candidate_id, added_by_user_id=PROMOTING_USER_ID)
    assert result is None

    final_row = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == candidate_id)
    )
    assert final_row["status"] == "dismissed"


@pytest.mark.asyncio
async def test_promote_does_not_clobber_concurrent_dismiss(conn: AsyncConnection):
    """TOCTOU guard: simulate the candidate being dismissed AFTER the existence
    check but BEFORE the trailing UPDATE. Without the `WHERE status='discovered'`
    guard on that UPDATE, the dismiss would be silently overwritten with
    'promoted'. With the guard, the trailing UPDATE is a no-op.
    """
    candidate_id = await _create_discovered_candidate(conn, TOCTOU_URL)
    await conn.commit()

    real_candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == candidate_id)
    )

    async def get_then_dismiss(cand_id: int):
        # Return the still-discovered snapshot the caller saw, then flip the
        # real DB row to 'dismissed' as if a concurrent moderator clicked
        # dismiss in the gap.
        snapshot = dict(real_candidate)
        async with engine.begin() as race_conn:
            await race_conn.execute(
                meme_source_candidate.update()
                .where(meme_source_candidate.c.id == cand_id)
                .values(status="dismissed", dismissed_reason="moderator-race")
            )
        return snapshot

    with patch(
        "src.tgbot.service.get_source_candidate_by_id",
        side_effect=get_then_dismiss,
    ):
        promoted = await promote_source_candidate(candidate_id, added_by_user_id=PROMOTING_USER_ID)

    # The meme_source insert still ran (it is idempotent + reflects moderator
    # intent at the moment of click), but the candidate row must retain the
    # 'dismissed' status set by the concurrent moderator.
    assert promoted is not None
    assert promoted["url"] == TOCTOU_URL

    final_candidate = await fetch_one(
        select(meme_source_candidate).where(meme_source_candidate.c.id == candidate_id)
    )
    assert final_candidate["status"] == "dismissed"
    assert final_candidate["dismissed_reason"] == "moderator-race"
