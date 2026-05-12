from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection
from tests.factories import (
    cleanup_test_data,
    create_meme,
    create_meme_source,
    create_reaction,
    create_user,
)

from src.database import engine
from src.flows.stats.meme import _format_low_sent_pool_skip_rate_alert
from src.stats.meme import get_low_sent_pool_skip_rate_alerts


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        await cleanup_test_data(conn)
        yield conn
        await cleanup_test_data(conn)


async def _create_low_sent_reactions(
    conn: AsyncConnection,
    meme_id: int,
    reaction_ids: list[int | None],
    *,
    user_id_start: int,
    recommended_by: str = "low_sent_pool",
) -> None:
    sent_at = datetime.utcnow() - timedelta(hours=1)
    for idx, reaction_id in enumerate(reaction_ids):
        user_id = user_id_start + idx
        await create_user(conn, id=user_id)
        await create_reaction(
            conn,
            user_id=user_id,
            meme_id=meme_id,
            reaction_id=reaction_id,
            recommended_by=recommended_by,
            sent_at=sent_at + timedelta(seconds=idx),
            reacted_at=(sent_at + timedelta(seconds=idx + 5) if reaction_id is not None else None),
        )
    await conn.commit()


@pytest.mark.asyncio
async def test_low_sent_skip_alert_flags_only_strictly_above_threshold(
    conn: AsyncConnection,
) -> None:
    await create_meme_source(conn, id=10001)
    await create_meme(conn, id=10001, meme_source_id=10001)
    await create_meme(conn, id=10002, meme_source_id=10001)
    await create_meme(conn, id=10003, meme_source_id=10001)
    await conn.commit()

    await _create_low_sent_reactions(
        conn,
        10001,
        [2, 2, 2, 2, 2, 2, 1, 1, 1, 1],
        user_id_start=11000,
    )
    await _create_low_sent_reactions(
        conn,
        10002,
        [2, 2, 2, 2, 2, 1, 1, 1, 1, 1],
        user_id_start=11100,
    )
    await _create_low_sent_reactions(
        conn,
        10003,
        [2, 2, 2, 2, 2, 2, 1, 1, 1, 1],
        user_id_start=11200,
        recommended_by="goat",
    )

    rows = await get_low_sent_pool_skip_rate_alerts(
        skip_rate_threshold=0.5,
        min_sends=10,
        lookback_days=7,
        limit=10,
    )

    assert [row["meme_id"] for row in rows] == [10001]
    row = rows[0]
    assert row["sends"] == 10
    assert row["explicit_reactions"] == 10
    assert row["likes"] == 4
    assert row["skips"] == 6
    assert row["like_rate"] == pytest.approx(0.4)
    assert row["skip_rate"] == pytest.approx(0.6)
    assert row["already_rejected_or_snoozed"] is False


@pytest.mark.asyncio
async def test_low_sent_skip_alert_includes_already_actioned_metadata(
    conn: AsyncConnection,
) -> None:
    await create_meme_source(conn, id=10011, status="snoozed")
    await create_meme(conn, id=10011, meme_source_id=10011, status="rejected")
    await conn.commit()

    await _create_low_sent_reactions(
        conn,
        10011,
        [2, 2, 1],
        user_id_start=11300,
    )

    rows = await get_low_sent_pool_skip_rate_alerts(
        skip_rate_threshold=0.5,
        min_sends=3,
        lookback_days=7,
        limit=10,
    )

    assert [row["meme_id"] for row in rows] == [10011]
    assert rows[0]["meme_status"] == "rejected"
    assert rows[0]["source_status"] == "snoozed"
    assert rows[0]["already_rejected_or_snoozed"] is True


def test_low_sent_alert_message_points_moderators_to_manual_review() -> None:
    message = _format_low_sent_pool_skip_rate_alert(
        [
            {
                "meme_id": 10001,
                "meme_source_id": 10002,
                "source_type": "telegram",
                "meme_status": "ok",
                "source_status": "parsing_enabled",
                "already_rejected_or_snoozed": False,
                "sends": 10,
                "explicit_reactions": 10,
                "likes": 4,
                "skips": 6,
                "like_rate": 0.4,
                "skip_rate": 0.6,
                "published_age_days": 3.5,
                "last_sent_at": "2026-05-12 07:00:00",
                "source_url": "https://t.me/source/123",
            }
        ],
        skip_rate_threshold=0.5,
        min_sends=10,
        lookback_days=7,
    )

    assert "<code>/meme 10001</code>" in message
    assert "action=needs_review" in message
    assert "No recommendation traffic changed" in message
