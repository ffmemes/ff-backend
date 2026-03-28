import asyncio
from typing import Generator

import pytest

from src.database import engine
from src.redis import pool as redis_pool


@pytest.fixture(autouse=True, scope="session")
def run_migrations() -> None:
    import os

    print("running migrations..")
    os.system("alembic upgrade head")
    yield
    os.system("alembic downgrade base")


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    # Dispose stale pool connections so new ones bind to this loop
    loop.run_until_complete(engine.dispose())
    loop.run_until_complete(redis_pool.disconnect())
    yield loop
    loop.run_until_complete(engine.dispose())
    loop.run_until_complete(redis_pool.disconnect())
    loop.close()
