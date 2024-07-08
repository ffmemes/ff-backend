from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncConnection

from src.database import (engine, fetch_all, meme, meme_source, meme_stats, user,
                          user_language, user_meme_reaction)
from src.stats.meme import calculate_meme_reactions_stats


@pytest_asyncio.fixture()
async def conn():
    async with engine.connect() as conn:

        await conn.execute(
            insert(user),
            [{'id': 1, 'type': "user"}, {'id': 2, 'type': "user"}]
        )
        await conn.execute(
            insert(meme_source),
            {'id': 1, 'type': 'telegram', 'url': '111', 'status': 'parsing_enabled', 'created_at': datetime(2024, 1, 1)}
        )

        meme_common = {
            'type': 'image', 'telegram_image_id': '111', 'caption': '111', 'meme_source_id': 1,
            'published_at': datetime(2024, 1, 1), 'status': 'ok', 'language_code': 'ru',
        }
        meme_ids = [1, 2, 3, 4, 5]
        await conn.execute(
            insert(meme),
            [{'id': meme_id, 'raw_meme_id': meme_id, **meme_common} for meme_id in meme_ids]
        )

        u_common = {'language_code': 'ru', 'created_at': datetime(2024, 1, 1)}
        await conn.execute(
            insert(user_language),
            [
                {'user_id': 1, **u_common},
                {'user_id': 2, **u_common},
            ]
        )
        umr_common = {'recommended_by': '111', 'sent_at': datetime(2024, 1, 1), 'reacted_at': datetime(2024, 1, 1, 0, 10)}
        await conn.execute(
            insert(user_meme_reaction),
            [
                {'user_id': 1, 'meme_id': 1, 'reaction_id': 1, **umr_common},
                {'user_id': 1, 'meme_id': 2, 'reaction_id': 1, **umr_common},
                {'user_id': 1, 'meme_id': 3, 'reaction_id': 1, **umr_common},
                {'user_id': 1, 'meme_id': 4, 'reaction_id': 1, **umr_common},
                {'user_id': 1, 'meme_id': 5, 'reaction_id': 2, **umr_common},
                {'user_id': 2, 'meme_id': 1, 'reaction_id': 1, **umr_common},
                {'user_id': 2, 'meme_id': 2, 'reaction_id': 2, **umr_common},
                {'user_id': 2, 'meme_id': 3, 'reaction_id': 2, **umr_common},
                {'user_id': 2, 'meme_id': 4, 'reaction_id': 2, **umr_common},
                {'user_id': 2, 'meme_id': 5, 'reaction_id': 2, **umr_common},
            ]
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



@pytest.mark.asyncio
async def test_calculate_meme_reactions_stats(conn: AsyncConnection):
    await calculate_meme_reactions_stats()

    res = await fetch_all(select(meme_stats))
    print(res)
    assert len(res) == 5