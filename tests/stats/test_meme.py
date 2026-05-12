from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import (
    engine,
    fetch_all,
    meme,
    meme_source,
    meme_stats,
    user,
    user_deep_link_log,
    user_language,
    user_meme_reaction,
)
from src.stats.meme import calculate_meme_invited_count, calculate_meme_reactions_and_engagement


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        await conn.execute(
            insert(user),
            [
                {"id": 1, "type": "user"},
                {"id": 2, "type": "user"},
                {"id": 3, "type": "user"},
            ],
        )
        await conn.execute(
            insert(meme_source),
            {
                "id": 1,
                "type": "telegram",
                "url": "111",
                "status": "parsing_enabled",
                "created_at": datetime(2024, 1, 1),
            },
        )

        meme_common = {
            "type": "image",
            "telegram_image_id": "111",
            "caption": "111",
            "meme_source_id": 1,
            "published_at": datetime(2024, 1, 1),
            "status": "ok",
            "language_code": "ru",
        }
        meme_ids = [1, 2, 3, 4, 5, 6]
        await conn.execute(
            insert(meme),
            [{"id": meme_id, "raw_meme_id": meme_id, **meme_common} for meme_id in meme_ids],
        )

        u_common = {"language_code": "ru", "created_at": datetime(2024, 1, 1)}
        await conn.execute(
            insert(user_language),
            [
                {"user_id": 1, **u_common},
                {"user_id": 2, **u_common},
                {"user_id": 3, **u_common},
            ],
        )
        umr_common = {
            "recommended_by": "111",
            "sent_at": datetime(2024, 1, 1),
            "reacted_at": datetime(2024, 1, 1, 0, 10),
        }
        await conn.execute(
            insert(user_meme_reaction),
            [
                {"user_id": 1, "meme_id": 1, "reaction_id": 1, **umr_common},
                {"user_id": 1, "meme_id": 2, "reaction_id": 1, **umr_common},
                {"user_id": 1, "meme_id": 3, "reaction_id": 1, **umr_common},
                {"user_id": 1, "meme_id": 4, "reaction_id": 1, **umr_common},
                {"user_id": 1, "meme_id": 5, "reaction_id": 1, **umr_common},
                {"user_id": 1, "meme_id": 6, "reaction_id": 2, **umr_common},
                {"user_id": 2, "meme_id": 1, "reaction_id": 1, **umr_common},
                {"user_id": 2, "meme_id": 2, "reaction_id": 2, **umr_common},
                {"user_id": 2, "meme_id": 3, "reaction_id": 2, **umr_common},
                {"user_id": 2, "meme_id": 4, "reaction_id": 2, **umr_common},
                {"user_id": 2, "meme_id": 5, "reaction_id": 2, **umr_common},
                {"user_id": 2, "meme_id": 6, "reaction_id": 2, **umr_common},
            ],
        )

        await conn.commit()
        yield conn

        await conn.execute(delete(meme_stats))
        await conn.execute(delete(user_deep_link_log))
        await conn.execute(delete(user_meme_reaction))
        await conn.execute(delete(user_language))
        await conn.execute(delete(meme))
        await conn.execute(delete(meme_source))
        await conn.execute(delete(user))
        await conn.commit()


@pytest.mark.asyncio
async def test_calculate_meme_reactions_stats(conn: AsyncConnection):
    await calculate_meme_reactions_and_engagement(
        min_meme_reactions=0, min_user_reactions=0, lookback_hours=999_999
    )

    res = await fetch_all(select(meme_stats))
    assert len(res) == 6

    print(res)

    eps = 1e-3
    for row in res:
        if row["meme_id"] == 1:
            assert abs(row["lr_smoothed"] - 1) < eps
        if row["meme_id"] == 2:
            assert abs(row["lr_smoothed"]) < eps


@pytest.mark.asyncio
async def test_calculate_meme_invited_count_excludes_self_clicks(conn: AsyncConnection):
    await conn.execute(
        insert(meme_stats),
        {"meme_id": 2, "invited_count": 7},
    )
    await conn.execute(
        insert(user_deep_link_log),
        [
            {"user_id": 1, "deep_link": "s_1_1"},
            {"user_id": 2, "deep_link": "s_1_1"},
            {"user_id": 2, "deep_link": "s_1_1"},
            {"user_id": 3, "deep_link": "s_1_1"},
            {"user_id": 1, "deep_link": "s_1_2"},
        ],
    )
    await conn.commit()

    await calculate_meme_invited_count()

    rows = await fetch_all(
        select(meme_stats.c.meme_id, meme_stats.c.invited_count).where(
            meme_stats.c.meme_id.in_([1, 2])
        )
    )
    invited_count_by_meme_id = {row["meme_id"]: row["invited_count"] for row in rows}

    assert invited_count_by_meme_id[1] == 2
    assert invited_count_by_meme_id[2] == 0
