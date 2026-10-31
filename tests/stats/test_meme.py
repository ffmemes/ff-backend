from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select, text
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import (
    engine,
    fetch_all,
    meme,
    meme_raw_telegram,
    meme_source,
    meme_stats,
    user,
    user_deep_link_log,
    user_language,
    user_meme_reaction,
)
from src.stats.meme import (
    calculate_meme_invited_count,
    calculate_meme_raw_impressions_stats,
    calculate_meme_reactions_and_engagement,
)


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
        await conn.execute(delete(meme_raw_telegram))
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
async def test_meme_stats_exclude_friend_challenge_answers(conn: AsyncConnection):
    await conn.execute(
        insert(user_meme_reaction),
        {
            "user_id": 3,
            "meme_id": 1,
            "reaction_id": 2,
            "recommended_by": "friend_challenge",
            "sent_at": datetime(2024, 1, 1),
            "reacted_at": datetime(2024, 1, 1, 0, 10),
        },
    )
    await conn.commit()

    await calculate_meme_reactions_and_engagement(
        min_meme_reactions=0, min_user_reactions=0, lookback_hours=999_999
    )

    row = (await fetch_all(select(meme_stats).where(meme_stats.c.meme_id == 1)))[0]
    assert (row["nlikes"], row["ndislikes"], row["nmemes_sent"]) == (2, 0, 2)
    assert abs(row["lr_smoothed"] - 1) < 1e-3


@pytest.mark.asyncio
async def test_incremental_stats_target_originals_of_recent_duplicates(conn: AsyncConnection):
    # Every reaction in the fixture is from 2024, so nothing is inside the
    # lookback window. A recently marked duplicate must still pull its
    # original into the recompute, and nothing else.
    await conn.execute(
        text(
            """
            UPDATE meme
            SET status = 'duplicate', duplicate_of = 1, updated_at = NOW()
            WHERE id = 2
            """
        )
    )
    await conn.execute(
        text(
            """
            UPDATE meme
            SET status = 'duplicate', duplicate_of = 3,
                updated_at = NOW() - INTERVAL '2 days'
            WHERE id = 4
            """
        )
    )
    await conn.commit()

    await calculate_meme_reactions_and_engagement(lookback_hours=3)

    rows = await fetch_all(
        select(meme_stats.c.meme_id, meme_stats.c.nlikes, meme_stats.c.ndislikes)
    )
    assert [(row["meme_id"], row["nlikes"], row["ndislikes"]) for row in rows] == [(1, 2, 0)]


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
            {"user_id": 2, "deep_link": "m_1_1"},
            {"user_id": 2, "deep_link": "s_1_1"},
            {"user_id": 3, "deep_link": "s_1_1"},
            {"user_id": 1, "deep_link": "m_1_2"},
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


@pytest.mark.asyncio
async def test_raw_impr_rank_by_reaction_rate_within_source_and_type(conn: AsyncConnection):
    # (meme_id, views, reactions): images 1-4, videos 5-6 ranked separately.
    raws = [(1, 1000, 10), (2, 100, 20), (3, 5000, None), (4, 50, None), (5, 10, 5), (6, 1000, 100)]
    await conn.execute(
        insert(meme_raw_telegram),
        [
            {
                "id": i,
                "meme_source_id": 1,
                "post_id": i,
                "url": f"https://t.me/s/x/{i}",
                "date": datetime(2024, 1, 1),
                "views": views,
                "reactions": reactions,
            }
            for i, views, reactions in raws
        ],
    )
    await conn.execute(text("UPDATE meme SET type = 'video' WHERE id IN (5, 6)"))
    await conn.commit()

    await calculate_meme_raw_impressions_stats()

    rows = await fetch_all(select(meme_stats.c.meme_id, meme_stats.c.raw_impr_rank))
    ranks = {r["meme_id"]: r["raw_impr_rank"] for r in rows}
    # Images: 20% rate > 1% rate > NULL reactions by views (5000 > 50).
    assert [ranks[i] for i in (2, 1, 3, 4)] == [0, 1, 2, 3]
    # Videos: 50% rate beats 10% despite 100x fewer views.
    assert (ranks[5], ranks[6]) == (0, 2)
