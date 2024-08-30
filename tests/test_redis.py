from datetime import datetime

import asyncio

import pytest
import pytest_asyncio

from src import redis


@pytest.mark.asyncio
async def test_add_memes_to_queue_by_key_ok():
    user_id = 999
    queue_key = redis.get_meme_queue_key(user_id)

    memes = [
        {'id': 1, 'recommended_by': 'best_algo'},
        {'id': 2, 'recommended_by': 'best_algo'},
    ]

    await redis.add_memes_to_queue_by_key(queue_key, memes, expire=1)

    stored = await redis.redis_client.smembers(queue_key)
    assert len(stored) == 2
    
    await asyncio.sleep(3)

    stored = await redis.redis_client.smembers(queue_key)
    assert len(stored) == 0