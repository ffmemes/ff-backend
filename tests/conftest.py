import asyncio
from typing import Generator

import pytest


@pytest.fixture(autouse=True, scope="session")
def run_migrations() -> None:
    import os

    print("running migrations..")
    os.system("alembic upgrade head")
    yield
    os.system("alembic downgrade base")


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    from src.database import engine

    loop = asyncio.get_event_loop_policy().new_event_loop()
    # Dispose stale pool connections so new ones bind to this loop
    loop.run_until_complete(engine.dispose())
    yield loop
    loop.run_until_complete(engine.dispose())
    loop.close()
