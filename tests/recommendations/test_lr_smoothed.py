from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncConnection

from src import redis
from src.database import (
    engine,
    meme,
    meme_source,
    meme_stats,
    user,
    user_language,
    user_meme_reaction,
    user_meme_source_stats,
)
from src.recommendations.candidates import get_lr_smoothed


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:
        await conn.execute(
            insert(user), [{"id": 1, "type": "user"}, {"id": 2, "type": "user"}]
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
        meme_ids = [1, 2, 3, 4, 5]
        await conn.execute(
            insert(meme),
            [
                {"id": meme_id, "raw_meme_id": meme_id, **meme_common}
                for meme_id in meme_ids
            ],
        )

        u_common = {"language_code": "ru", "created_at": datetime(2024, 1, 1)}
        await conn.execute(
            insert(user_language),
            [
                {"user_id": 1, **u_common},
                {"user_id": 2, **u_common},
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
            ],
        )

        await conn.execute(
            insert(user_meme_source_stats),
            [
                {
                    "user_id": 1,
                    "meme_source_id": 1,
                    "nlikes": 10,
                    "ndislikes": 10,
                    "updated_at": datetime(2024, 1, 1, 0, 0),
                },
            ],
        )

        meme_stats_common = {
            "nlikes": 10,
            "ndislikes": 10,
            "age_days": 10,
            "raw_impr_rank": 9999,
            "sec_to_react": 10,
            "invited_count": 0,
            "updated_at": datetime(2024, 1, 1, 0, 0),
        }
        await conn.execute(
            insert(meme_stats),
            [
                {
                    "meme_id": meme_id,
                    "lr_smoothed": -0.2 + 0.1 * meme_id,
                    **meme_stats_common,
                }
                for meme_id in [2, 3, 4, 5]
            ],
        )

        await conn.commit()
        yield conn

        await conn.execute(delete(meme_stats))
        await conn.execute(delete(user_meme_reaction))
        await conn.execute(delete(user_language))
        await conn.execute(delete(meme))
        await conn.execute(delete(meme_source))
        await conn.execute(delete(user))
        await conn.commit()

        queue_key = redis.get_meme_queue_key(1)
        await redis.delete_by_key(queue_key)
        queue_key = redis.get_meme_queue_key(51)
        await redis.delete_by_key(queue_key)


@pytest.mark.asyncio
async def test_calculate_meme_reactions_stats(conn: AsyncConnection):
    res = await get_lr_smoothed(1)

    assert len(res) == 4
